"""``omgkg``: run Query -> RAG -> KG -> LLM -> Answer, and set up its data.

    omgkg import-snapshot FILE    load the OmgevingsChat Qdrant index (RAG)
    omgkg build-graph             build the knowledge graph in Neo4j (KG)
    omgkg ask "QUESTION"          answer a question through the whole pipeline
    omgkg serve-kg                our KG as OmgevingsChat's KG endpoint
    omgkg overlap                 how many of their wIds our graph knows

Settings come from the environment, then from ``.env`` (see ``.env.example``).
"""

import argparse
import os
import sys
from pathlib import Path

from neo4j import Driver, GraphDatabase
from openai import OpenAI

from omgkg.generation.answer import Answer, OpenAIModel
from omgkg.graph import build, kg_service
from omgkg.graph.knowledge_graph import KnowledgeGraph, Neo4jGraph
from omgkg.ingest.dso.stop_tpod import read_regeling
from omgkg.models import TextComponent
from omgkg.pipeline import ask
from omgkg.retrieval import qdrant
from omgkg.retrieval.omgevingschat import OmgevingsChatRetriever, bridge_transport

ROOT = Path(__file__).parents[2]
DSO_SNAPSHOT_ID = "maastricht-dso-2026-10-02"  # data/manifests/<id>.json


def load_dotenv(path: Path) -> None:
    """``KEY=value`` lines; variables already set in the environment win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        value = value.strip().strip("'\"")
        if sep and key and not key.startswith("#") and value:
            os.environ.setdefault(key.strip(), value)


def setting(name: str, default: str | None = None) -> str:
    value = os.environ.get(name) or default
    if value is None:
        sys.exit(f"Set {name} in .env (see .env.example).")
    return value


def neo4j_driver() -> Driver:
    return GraphDatabase.driver(
        setting("NEO4J_URI", "bolt://localhost:7687"),
        auth=(
            setting("NEO4J_USER", "neo4j"),
            setting("NEO4J_PASSWORD", "testpassword"),
        ),
        notifications_min_severity="OFF",
    )


def articles(snapshot: Path) -> dict[str, TextComponent]:
    return {
        c.provenance.text_component_id or c.id: c
        for c in read_regeling(snapshot, DSO_SNAPSHOT_ID)
        if c.kind == "article"
    }


def knowledge_graph(driver: Driver, limit: int) -> KnowledgeGraph:
    return KnowledgeGraph(Neo4jGraph(driver), articles(build.SNAPSHOT), limit=limit)


def rag() -> OmgevingsChatRetriever:
    platform = Path(
        setting("OMGKG_PLATFORM_DIR", str(ROOT.parent / "omgevingschat-platform"))
    )
    if not (platform / "apps" / "benchmark-service").is_dir():
        sys.exit(
            f"No OmgevingsChat checkout at {platform}: clone and install it "
            "(bridge/omgevingschat/README.md) or set OMGKG_PLATFORM_DIR in .env."
        )
    collection = setting("OMGKG_QDRANT_COLLECTION")
    env_file = setting(
        "OMGKG_PLATFORM_ENV", str(platform / "apps" / "web" / ".env.local")
    )
    return OmgevingsChatRetriever(
        bridge_transport(
            platform,
            collection=collection,
            source_id=setting(
                "OMGKG_SOURCE_ID", "/akn/nl/act/gm0935/2020/omgevingsplan"
            ),
            env_file=Path(env_file),
            metadata_schema=setting("OMGKG_METADATA_SCHEMA", "v2"),
            qdrant_url=setting("OMGKG_QDRANT_URL", "http://localhost:6333"),
        ),
        snapshot_id=f"qdrant:{collection}",
    )


def print_answer(result: Answer) -> None:
    print(result.text, "\n\nBronnen:")
    cited = {e.text_component_id for e in result.citations}
    for i, e in enumerate(result.evidence, start=1):
        via = " [via kennisgraaf]" if e.graph_paths else ""
        mark = "*" if e.text_component_id in cited else " "
        title = e.provenance.structural_path.split(" > ")[-1] or e.text_component_id
        print(f"{mark}[{i}] {title}{via}")
    print("\n* = geciteerd in het antwoord")


def cmd_import_snapshot(args: argparse.Namespace) -> None:
    collection = args.collection or setting("OMGKG_QDRANT_COLLECTION")
    count = qdrant.import_snapshot(
        args.file,
        collection,
        setting("OMGKG_QDRANT_URL", "http://localhost:6333"),
        os.environ.get("QDRANT_API_KEY"),
    )
    print(f"Collection {collection!r} restored: {count} points.")
    if os.environ.get("OMGKG_QDRANT_COLLECTION") != collection:
        print(f"Set OMGKG_QDRANT_COLLECTION={collection} in .env for `omgkg ask`.")


def cmd_build_graph(args: argparse.Namespace) -> None:
    with neo4j_driver() as driver:
        driver.verify_connectivity()
        counts = build.build_graph(driver, args.snapshot)
    print(", ".join(f"{n} {name}" for name, n in counts.items()))


def cmd_ask(args: argparse.Namespace) -> None:
    # Check every setting before the first slow or paid call.
    retriever = rag()
    llm = OpenAIModel(
        setting("OMGKG_LLM_MODEL", "gpt-4o"),
        OpenAI(api_key=setting("OPENAI_API_KEY")),
    )
    if args.no_kg:
        return print_answer(ask(args.question, retriever, None, llm, k=args.k))
    with neo4j_driver() as driver:
        kg = knowledge_graph(driver, args.kg_limit)
        print_answer(ask(args.question, retriever, kg, llm, k=args.k))


def cmd_serve_kg(args: argparse.Namespace) -> None:
    with neo4j_driver() as driver:
        driver.verify_connectivity()
        kg = knowledge_graph(driver, args.kg_limit)
        kg_service.serve(kg, setting("OMGKG_KG_API_KEY"), args.host, args.port)


def cmd_overlap(args: argparse.Namespace) -> None:
    theirs = qdrant.collection_wids(
        setting("OMGKG_QDRANT_COLLECTION"),
        setting("OMGKG_QDRANT_URL", "http://localhost:6333"),
        os.environ.get("QDRANT_API_KEY"),
    )
    ours = set()
    for wid, article in articles(build.SNAPSHOT).items():
        ours |= {wid, *(p.w_id for p in article.paragraphs)}
    shared = theirs & ours
    print(f"wIds in their index: {len(theirs)}; articles and lids in ours: {len(ours)}")
    print(f"shared: {len(shared)} ({len(shared) / max(len(theirs), 1):.1%} of theirs)")
    for wid in sorted(theirs - ours)[:20]:
        print(f"  only theirs: {wid}")


def main(argv: list[str] | None = None) -> None:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(prog="omgkg", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(required=True, metavar="COMMAND")

    command = commands.add_parser("import-snapshot", help="load a Qdrant snapshot")
    command.add_argument("file", type=Path)
    command.add_argument("--collection", help="default: OMGKG_QDRANT_COLLECTION")
    command.set_defaults(run=cmd_import_snapshot)

    command = commands.add_parser("build-graph", help="build the KG in Neo4j")
    command.add_argument("--snapshot", type=Path, default=build.SNAPSHOT)
    command.set_defaults(run=cmd_build_graph)

    command = commands.add_parser("ask", help="Query -> RAG -> KG -> LLM -> Answer")
    command.add_argument("question")
    command.add_argument("--k", type=int, default=5, help="passages from RAG")
    command.add_argument("--kg-limit", type=int, default=5, help="articles from KG")
    command.add_argument("--no-kg", action="store_true", help="skip the graph")
    command.set_defaults(run=cmd_ask)

    command = commands.add_parser("serve-kg", help="OmgevingsChat KG endpoint")
    command.add_argument("--host", default="127.0.0.1")
    command.add_argument("--port", type=int, default=8765)
    command.add_argument("--kg-limit", type=int, default=5)
    command.set_defaults(run=cmd_serve_kg)

    command = commands.add_parser("overlap", help="their wIds known to our graph")
    command.set_defaults(run=cmd_overlap)

    args = parser.parse_args(argv)
    args.run(args)


if __name__ == "__main__":
    main()
