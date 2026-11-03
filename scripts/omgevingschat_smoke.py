"""Snapshot-day checks for the OmgevingsChat baseline (configuration A).

  ask      run one question through their retrieval via the bridge and show which
           evidence links to an article or lid in our corpus
  overlap  count how many wIds in their Qdrant collection exist in our snapshot
           (their index is "the latest version", ours is 2026-10-02)

Run from the repository root, with their checkout installed (pnpm install) and
Qdrant running:

  uv run python scripts/omgevingschat_smoke.py ask "mag ik een dakkapel bouwen?" \\
      --collection <name>
  uv run python scripts/omgevingschat_smoke.py overlap --collection <name>
"""

import argparse
import json
import re
import urllib.request
from pathlib import Path

from omgkg.retrieval.omgevingschat import OmgevingsChatRetriever, bridge_transport

ROOT = Path(__file__).parents[1]
CORPUS = ROOT / "source_data" / "Maastricht-DSO-production-2026-10-02"
PLATFORM = ROOT.parent / "omgevingschat-platform"
SOURCE_ID = "/akn/nl/act/gm0935/2020/omgevingsplan"


def corpus_wids() -> set[str]:
    wids: set[str] = set()
    for xml in CORPUS.rglob("*.xml"):
        wids.update(re.findall(r'wId="(gm0935[^"]+)"', xml.read_text(encoding="utf-8")))
    return wids


def collection_wids(qdrant_url: str, collection: str) -> set[str]:
    wids: set[str] = set()
    offset = None
    while True:
        body = {"limit": 256, "with_payload": True, "with_vector": False}
        if offset is not None:
            body["offset"] = offset
        request = urllib.request.Request(
            f"{qdrant_url}/collections/{collection}/points/scroll",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request) as response:
            result = json.load(response)["result"]
        for point in result["points"]:
            payload = point.get("payload") or {}
            meta = payload.get("metadata") or payload
            wid = meta.get("component_id") or meta.get("doc_componentId")
            if isinstance(wid, str) and wid.startswith("gm0935"):
                wids.add(wid)
        offset = result.get("next_page_offset")
        if offset is None:
            return wids


def ask(args: argparse.Namespace) -> None:
    retriever = OmgevingsChatRetriever(
        bridge_transport(
            args.platform,
            collection=args.collection,
            source_id=args.source_id,
            env_file=args.env_file,
            metadata_schema=args.schema,
        ),
        snapshot_id=f"qdrant:{args.collection}",
    )
    known = corpus_wids()
    result = retriever.search(args.question)
    print(f"their retrieval: {result.latency_ms:.0f} ms, {len(result.sources)} sources")
    for evidence in retriever.retrieve(args.question, k=args.k):
        mark = "in graph" if evidence.text_component_id in known else "NOT in graph"
        print(f"{evidence.rank:>2}. [{mark}] {evidence.provenance.structural_path}")
        print(f"    {evidence.text_component_id}")


def overlap(args: argparse.Namespace) -> None:
    theirs = collection_wids(args.qdrant_url, args.collection)
    ours = corpus_wids()
    shared = theirs & ours
    print(f"wIds in their collection: {len(theirs)}")
    print(f"wIds in our 2026-10-02 snapshot: {len(ours)}")
    print(f"shared: {len(shared)} ({len(shared) / max(len(theirs), 1):.1%} of theirs)")
    for wid in sorted(theirs - ours)[:20]:
        print(f"  only theirs: {wid}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(required=True)

    ask_cmd = commands.add_parser("ask")
    ask_cmd.add_argument("question")
    ask_cmd.add_argument("--k", type=int, default=5)
    ask_cmd.add_argument("--source-id", default=SOURCE_ID)
    ask_cmd.add_argument("--schema", choices=["v1", "v2"], default="v2")
    ask_cmd.add_argument("--platform", type=Path, default=PLATFORM)
    ask_cmd.add_argument(
        "--env-file", type=Path, default=PLATFORM / "apps" / "web" / ".env.local"
    )
    ask_cmd.set_defaults(run=ask)

    overlap_cmd = commands.add_parser("overlap")
    overlap_cmd.add_argument("--qdrant-url", default="http://localhost:6333")
    overlap_cmd.set_defaults(run=overlap)

    for command in (ask_cmd, overlap_cmd):
        command.add_argument("--collection", required=True)

    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
