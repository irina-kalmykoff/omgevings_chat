"""Query -> RAG -> KG -> LLM -> Answer, with a canned bridge, fake graph and LLM."""

import os
from pathlib import Path

import pytest

from omgkg.cli import load_dotenv
from omgkg.generation.answer import answer, build_prompt
from omgkg.pipeline import ask
from omgkg.retrieval.omgevingschat import OmgevingsChatRetriever
from tests.test_knowledge_graph import ART, evidence, kg

BRIDGE_OUTPUT = Path(__file__).parent / "fixtures" / "omgevingschat_bridge_output.json"
# The canned bridge response retrieves 22.27 and 22.28 from the real snapshot.
REAL_27 = "gm0935_34__chp_22__subchp_22.2__subsec_22.2.7__subsec_22.2.7.2__art_22.27"


class FakeLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    def complete(self, instructions: str, prompt: str) -> str:
        assert "vierkante haken" in instructions  # the shared answer prompt
        self.prompts.append(prompt)
        return self.reply


def test_graph_sources_are_labelled_with_their_relation() -> None:
    prompt = build_prompt(
        "Mag ik een dakkapel bouwen?", kg().expand([evidence(ART.format(27))])
    )
    assert "Vraag: Mag ik een dakkapel bouwen?" in prompt
    assert (
        "[2] Hoofdstuk 22 > Artikel 22.28 (via kennisgraaf: maakt een inperking op [1];"
        " netto effect: verbod)" in prompt
    )
    assert (
        "[3] Hoofdstuk 22 > Artikel 22.26"
        " (via kennisgraaf: [1] maakt hierop een uitzondering)" in prompt
    )
    assert "(via kennisgraaf: waarnaar [1] verwijst)" in prompt


def test_citations_resolve_to_evidence_and_ignore_unknown_numbers() -> None:
    items = [evidence(ART.format(27)), evidence(ART.format(28), rank=2)]
    result = answer("vraag", items, FakeLLM("Ja [2], maar zie [1] en [2][9]."))
    assert [e.text_component_id for e in result.citations] == [
        ART.format(28),
        ART.format(27),
    ]


def test_ask_runs_rag_then_kg_then_llm() -> None:
    rag = OmgevingsChatRetriever(
        transport=lambda _: BRIDGE_OUTPUT.read_text(encoding="utf-8"), snapshot_id="q"
    )
    graph = kg(art27=REAL_27)
    llm = FakeLLM("Nee, een vergunning is nodig [1][2].")

    result = ask("Mag ik een dakkapel bouwen?", rag, graph, llm, k=3)

    # Graph articles follow the RAG hit that pulled them in; the other two RAG
    # hits (a Bbl chunk, and a 22.28 wId this fake graph lacks) come after.
    assert [e.text_component_id for e in result.evidence[:4]] == [
        REAL_27,
        ART.format(28),
        ART.format(26),
        ART.format(30),
    ]
    assert len(result.evidence) == 6
    assert "(via kennisgraaf:" in llm.prompts[0]
    assert [e.text_component_id for e in result.citations] == [REAL_27, ART.format(28)]


def test_ask_without_kg_is_the_text_baseline() -> None:
    rag = OmgevingsChatRetriever(
        transport=lambda _: BRIDGE_OUTPUT.read_text(encoding="utf-8"), snapshot_id="q"
    )
    result = ask("vraag", rag, None, FakeLLM("antwoord"), k=3)
    assert len(result.evidence) == 3
    assert all(not e.graph_paths for e in result.evidence)


def test_dotenv_skips_comments_and_empty_values_and_keeps_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = tmp_path / ".env"
    env.write_text("# c\nOMGKG_T1=from_file\nOMGKG_T2=\nOMGKG_T3='quoted'\n")
    monkeypatch.setenv("OMGKG_T1", "preset")
    for name in ("OMGKG_T2", "OMGKG_T3"):
        monkeypatch.delenv(name, raising=False)
    load_dotenv(env)
    assert os.environ["OMGKG_T1"] == "preset"
    assert "OMGKG_T2" not in os.environ
    assert os.environ["OMGKG_T3"] == "quoted"
    monkeypatch.delenv("OMGKG_T3")
