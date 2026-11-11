"""Configuration A: OmgevingsChat's own retrieval pipeline as the baseline.

Their pipeline is TypeScript (``packages/retrieval`` in omgevingschat-platform),
so it runs behind a bridge process. The contract:

- stdin: ``{"query": "..."}``
- stdout: ``{"latencyMs": 812, "sources": [RetrievedSource, ...]}``, where each
  source is their ``RetrievedSource`` type unchanged, ranked by ``order``.

Their ``documentComponentId`` is the STOP wId of the article or lid, the same ID
our ``Artikel``/``Lid`` nodes carry, so evidence links straight into the graph.

The bridge script is ``bridge/omgevingschat/omgkg-bridge.ts``; it runs
source-bound, pinned to one document, so it makes no location or DSO API calls.
"""

import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from omgkg.models import Evidence, Provenance

# Sends one request JSON to the bridge and returns its stdout.
Transport = Callable[[str], str]


class BridgeError(RuntimeError):
    """The bridge process failed or returned output outside the contract."""


class BridgeRequest(BaseModel):
    query: str = Field(min_length=1)


class BridgeSource(BaseModel):
    """The fields we use from their ``RetrievedSource`` (other fields ignored)."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    type: str
    id: str
    text: str
    order: int
    identifier: str | None = None
    document_component_id: str | None = Field(None, alias="documentComponentId")
    document_kop: str | None = Field(None, alias="documentKop")
    url: str | None = None
    score: float | None = None
    retrieval_stage: str | None = Field(None, alias="retrievalStage")


class BridgeResult(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    latency_ms: float = Field(alias="latencyMs", ge=0)
    sources: list[BridgeSource]


BRIDGE_SCRIPT = (
    Path(__file__).parents[3] / "bridge" / "omgevingschat" / "omgkg-bridge.ts"
)


def subprocess_transport(
    command: Sequence[str],
    env: Mapping[str, str] | None = None,
    timeout_s: float = 120,
) -> Transport:
    def run(request: str) -> str:
        done = subprocess.run(
            list(command),
            input=request,
            capture_output=True,
            text=True,
            env={**os.environ, **env} if env else None,
            timeout=timeout_s,
            check=False,
        )
        if done.returncode != 0:
            raise BridgeError(
                f"bridge exited with {done.returncode}: {done.stderr.strip()}"
            )
        return done.stdout

    return run


def bridge_transport(
    platform_dir: Path,
    collection: str,
    source_id: str,
    env_file: Path | None = None,
    metadata_schema: str = "v2",
    qdrant_url: str | None = None,
) -> Transport:
    """Run the bridge inside a local omgevingschat-platform checkout.

    The script is copied into their benchmark service so its imports resolve
    against their installed workspace (``pnpm install`` first).
    """
    service = platform_dir / "apps" / "benchmark-service"
    shutil.copyfile(BRIDGE_SCRIPT, service / "src" / "omgkg-bridge.ts")
    env = {
        "OMGKG_QDRANT_COLLECTION": collection,
        "OMGKG_SOURCE_ID": source_id,
        "OMGKG_METADATA_SCHEMA": metadata_schema,
    }
    if env_file is not None:
        env["OMGKG_ENV_FILE"] = str(env_file.resolve())
    if qdrant_url is not None:
        # Wins over their .env file: the bridge reads the Qdrant we imported into.
        env["QDRANT_URL"] = qdrant_url
    return subprocess_transport(
        ["pnpm", "--dir", str(service), "exec", "tsx", "src/omgkg-bridge.ts"], env=env
    )


# STOP wIds: "...__art_22.28__para_2" is lid 2 of article 22.28; "__artrecital__"
# (per article) and "__genrecital__" (general) mark the explanatory notes.
LID = re.compile(r"__art_([^_]+)__para_(\d+)$")
NOTE = re.compile(r"__(?:art|gen)recital__")


def label(source: BridgeSource) -> str:
    """What the passage is. Their ``documentKop`` names a lid "2." and gives a
    note the heading of the article it explains, so neither says what it is."""
    kop = source.document_kop or ""
    wid = source.document_component_id or ""
    if NOTE.search(wid):
        return f"Toelichting bij {kop}" if kop else "Toelichting"
    if lid := LID.search(wid):
        return f"Artikel {lid[1]}, lid {lid[2]}"
    return kop


def select_sources(sources: list[BridgeSource], k: int) -> list[BridgeSource]:
    """Choose which of their sources become our top-k evidence, in rank order.

    Their pipeline returns more than k: up to 18 reranked sources plus
    structural-expansion context.
    """
    # Baseline = their pipeline unchanged: their own ranking. The bridge pins
    # retrieval to the Maastricht omgevingsplan, so every source is that DSO
    # document, the same one our graph covers.
    return sorted(sources, key=lambda source: source.order)[:k]


class OmgevingsChatRetriever:
    def __init__(self, transport: Transport, snapshot_id: str) -> None:
        self._transport = transport
        self._snapshot_id = snapshot_id

    def search(self, query: str) -> BridgeResult:
        """One bridge call, with their own retrieval latency."""
        stdout = self._transport(BridgeRequest(query=query).model_dump_json())
        try:
            return BridgeResult.model_validate_json(stdout)
        except ValueError as error:
            raise BridgeError(f"bridge output breaks the contract: {error}") from error

    def retrieve(self, query: str, k: int) -> list[Evidence]:
        chosen = select_sources(self.search(query).sources, k)
        return [
            self._to_evidence(source, rank)
            for rank, source in enumerate(chosen, start=1)
        ]

    def _to_evidence(self, source: BridgeSource, rank: int) -> Evidence:
        return Evidence(
            text_component_id=source.document_component_id or source.id,
            text=source.text,
            score=source.score,
            rank=rank,
            provenance=Provenance(
                source_type="dso_resource",
                document_id=source.identifier or source.id,
                text_component_id=source.document_component_id,
                structural_path=label(source),
                source_uri=source.url,
                snapshot_id=self._snapshot_id,
            ),
        )
