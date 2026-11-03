"""The OmgevingsChat baseline retriever, against a canned bridge response."""

import sys
from pathlib import Path

import pytest

from omgkg.retrieval.base import Retriever
from omgkg.retrieval.omgevingschat import (
    BRIDGE_SCRIPT,
    BridgeError,
    OmgevingsChatRetriever,
    bridge_transport,
    select_sources,
    subprocess_transport,
)

FIXTURE = Path(__file__).parent / "fixtures" / "omgevingschat_bridge_output.json"


def canned(request: str) -> str:
    return FIXTURE.read_text(encoding="utf-8")


def make_retriever() -> OmgevingsChatRetriever:
    return OmgevingsChatRetriever(transport=canned, snapshot_id="qdrant-maastricht")


def test_is_a_retriever() -> None:
    retriever: Retriever = make_retriever()
    assert retriever is not None


def test_search_keeps_their_latency_and_all_sources() -> None:
    result = make_retriever().search("mag ik een dakkapel bouwen?")
    assert result.latency_ms == 812.5
    assert [s.order for s in result.sources] == [1, 2, 3]


def test_evidence_links_to_graph_wid_with_provenance() -> None:
    evidence = make_retriever().retrieve("mag ik een dakkapel bouwen?", k=5)
    first = evidence[0]
    assert first.rank == 1
    assert first.text_component_id.endswith("__art_22.27")
    assert first.provenance.document_id == "/akn/nl/act/gm0935/2020/omgevingsplan"
    assert first.provenance.snapshot_id == "qdrant-maastricht"
    assert first.graph_paths == []


def test_select_sources_returns_at_most_k_in_rank_order() -> None:
    sources = make_retriever().search("q").sources
    chosen = select_sources(sources, k=2)
    assert len(chosen) <= 2
    assert [s.order for s in chosen] == sorted(s.order for s in chosen)


def test_contract_violation_is_a_bridge_error() -> None:
    retriever = OmgevingsChatRetriever(
        transport=lambda request: '{"sources": []}', snapshot_id="s"
    )
    with pytest.raises(BridgeError, match="contract"):
        retriever.search("q")


def test_subprocess_transport_round_trip_and_failure() -> None:
    echo = subprocess_transport(
        [sys.executable, "-c", "import sys; print(sys.stdin.read())"]
    )
    assert echo('{"query": "q"}').strip() == '{"query": "q"}'

    failing = subprocess_transport(
        [sys.executable, "-c", "import sys; sys.exit('no qdrant')"]
    )
    with pytest.raises(BridgeError, match="no qdrant"):
        failing("{}")


def test_subprocess_transport_passes_env() -> None:
    show = subprocess_transport(
        [sys.executable, "-c", "import os; print(os.environ['OMGKG_PROBE'])"],
        env={"OMGKG_PROBE": "maastricht"},
    )
    assert show("{}").strip() == "maastricht"


def test_bridge_transport_installs_script_into_checkout(tmp_path: Path) -> None:
    service_src = tmp_path / "apps" / "benchmark-service" / "src"
    service_src.mkdir(parents=True)
    bridge_transport(tmp_path, collection="c", source_id="s")
    installed = service_src / "omgkg-bridge.ts"
    assert installed.read_text(encoding="utf-8") == BRIDGE_SCRIPT.read_text(
        encoding="utf-8"
    )
