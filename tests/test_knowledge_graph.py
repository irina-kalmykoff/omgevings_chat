"""The KG step and its OmgevingsChat endpoint, against a fake graph."""

import importlib.util
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

from omgkg.generation.answer import build_prompt
from omgkg.graph.build import DERIVE, PROTOTYPE, SNAPSHOT, TAGS, cypher_statements, read_tags
from omgkg.graph.kg_service import respond
from omgkg.graph.knowledge_graph import KnowledgeGraph, Link, Neo4jGraph, _describe
from omgkg.models import Evidence, Provenance, TextComponent

ART = "gm0935_34__chp_22__art_22.{}"


def component(number: str, wid: str | None = None) -> TextComponent:
    wid = wid or ART.format(number)
    return TextComponent(
        id=f"/akn/nl/act/gm0935/2020/omgevingsplan/nld@34#{wid}",
        kind="article",
        number=f"22.{number}",
        heading=f"Artikel 22.{number}",
        context=[],
        text=f"Tekst van artikel 22.{number}.",
        provenance=Provenance(
            source_type="legal_text_passage",
            document_id="/akn/nl/act/gm0935/2020/omgevingsplan",
            text_component_id=wid,
            structural_path=f"Hoofdstuk 22 > Artikel 22.{number}",
            snapshot_id="test",
        ),
    )


class FakeGraph:
    """22.28 restricts 22.27, 22.27 makes an exception to 22.26, 22.27 cites 22.30."""

    def __init__(self, art27: str) -> None:
        self.links_by_source = {
            ART.format(28): [
                Link(ART.format(28), art27, "overrides", "restriction", "prohibition")
            ],
            art27: [
                Link(art27, ART.format(30), "refers_to"),
                Link(art27, ART.format(26), "overrides", "exception"),
                Link(
                    art27,
                    ART.format(28),
                    "overridden_by",
                    "restriction",
                    "prohibition",
                ),
            ],
        }

    def links(self, wids: Sequence[str]) -> list[Link]:
        assert all("__para_" not in w for w in wids), "the graph gets article wIds"
        return [
            replace(link, source=wid)
            for wid in wids
            for link in self.links_by_source.get(wid, [])
        ]


# The explanatory notes (toelichting) on articles 22.26 and 22.27.
NOTE = "gm0935_34__artrecital__content_9"
NOTE_27 = "gm0935_34__artrecital__content_10"


def kg(limit: int = 5, art27: str = ART.format(27)) -> KnowledgeGraph:
    """``art27`` is the wId standing for article 22.27."""
    texts = {ART.format(n): component(str(n)) for n in (26, 28, 30)}
    texts[art27] = component("27", art27)
    return KnowledgeGraph(
        FakeGraph(art27),
        texts,
        explains={NOTE: ART.format(26), NOTE_27: art27},
        limit=limit,
    )


def evidence(wid: str, rank: int = 1) -> Evidence:
    return Evidence(
        text_component_id=wid,
        text="RAG-tekst",
        rank=rank,
        provenance=Provenance(
            source_type="dso_resource", document_id="d", snapshot_id="qdrant:x"
        ),
    )


def test_exceptions_come_before_references() -> None:
    related = kg().related([ART.format(27)])
    assert [link.target for link in related] == [
        ART.format(28),  # overrides the retrieved rule: changes its answer
        ART.format(26),
        ART.format(30),
    ]


def test_already_retrieved_articles_and_the_limit_are_respected() -> None:
    related = kg(limit=1).related([ART.format(27), ART.format(28)])
    assert [link.target for link in related] == [ART.format(26)]


def test_a_lid_is_resolved_to_its_article_but_stays_the_source() -> None:
    lid = ART.format(27) + "__para_2"
    related = kg().related([lid])
    assert related[0].target == ART.format(28)
    assert related[0].source == lid


def test_a_second_override_hop_completes_the_chain() -> None:
    # RAG finds 22.28; it restricts 22.27, which is an exception to 22.26.
    related = kg().related([ART.format(28)])
    assert [(link.source, link.target) for link in related] == [
        (ART.format(28), ART.format(27)),
        (ART.format(27), ART.format(26)),  # reported from 22.27, the hop it took
    ]  # 22.30, which 22.27 only refers to, is not followed on the second hop


def test_a_note_brings_in_the_article_it_explains_outside_the_limit() -> None:
    related = kg(limit=0).related([NOTE])
    assert [(link.relation, link.target) for link in related] == [
        ("explains", ART.format(26))
    ]
    assert kg().article_of(NOTE) == ART.format(26)
    # The article itself was retrieved too: nothing to bring in.
    assert kg().related([NOTE, ART.format(26)]) == []


def test_expand_puts_each_article_right_after_what_pulled_it_in() -> None:
    expanded = kg().expand([evidence(ART.format(28)), evidence("chunk-bbl", rank=2)])
    assert [e.text_component_id for e in expanded] == [
        ART.format(28),
        ART.format(27),
        ART.format(26),
        "chunk-bbl",
    ]
    assert [e.rank for e in expanded] == [1, 3, 4, 2]  # rank: retrieval, then added


def test_expand_appends_graph_evidence_with_its_path() -> None:
    expanded = kg().expand([evidence(ART.format(27))])
    assert [e.rank for e in expanded] == [1, 2, 3, 4]
    added = expanded[1]
    assert added.text == "Tekst van artikel 22.28."
    assert added.graph_paths[0].node_ids == [ART.format(27), ART.format(28)]
    assert added.graph_paths[0].relations == ["overridden_by:restriction:prohibition"]
    assert added.provenance.source_type == "legal_text_passage"


def test_endpoint_promotes_force_bearing_candidates_and_adds_graph_sources() -> None:
    body = {
        "query": "dakkapel",
        "background_documents": [
            {
                "id": "q-1",
                "content": "...",
                "meta": {"documentComponentId": ART.format(27)},
            },
            {"id": "q-2", "content": "...", "meta": {"documentComponentId": ""}},
            {"id": "q-3", "content": "..."},
            "not a document",
        ],
    }
    answers = respond(body, kg())["answer"]
    assert answers[0] == {"id": "q-1"}  # their id: bypasses the rerank
    first_added = answers[1]
    assert first_added["id"] == f"omgkg:{ART.format(28)}"
    assert first_added["content"] == "Tekst van artikel 22.28."
    assert first_added["title"] == (
        "Artikel 22.28 (kennisgraaf: maakt een inperking op Artikel 22.27)"
    )
    assert first_added["componentId"] == ART.format(28)


def test_endpoint_adds_the_article_of_a_retrieved_note() -> None:
    body = {
        "background_documents": [{"id": "q-9", "meta": {"documentComponentId": NOTE}}]
    }
    (added,) = respond(body, kg())["answer"]
    assert added["id"] == f"omgkg:{ART.format(26)}"
    assert added["title"] == (
        "Artikel 22.26 (kennisgraaf: het artikel bij een gevonden toelichting)"
    )


def test_endpoint_does_not_promote_a_note_but_adds_its_article() -> None:
    body = {
        "background_documents": [
            {"id": "q-n", "meta": {"documentComponentId": NOTE_27}}
        ]
    }
    answers = respond(body, kg())["answer"]
    assert {"id": "q-n"} not in answers  # a note is not a rule: no rerank bypass
    assert [a["id"] for a in answers][:3] == [
        f"omgkg:{ART.format(28)}",  # overrides of 22.27 first
        f"omgkg:{ART.format(26)}",
        f"omgkg:{ART.format(27)}",  # then 22.27 itself, the article of the note
    ]


def test_endpoint_answers_empty_without_known_wids() -> None:
    assert respond({"background_documents": []}, kg()) == {"answer": []}


def test_saved_tags_and_derive_script_parse() -> None:
    tags = read_tags(TAGS)
    assert len(tags) == 308
    assert sum(len(t.overrides) for t in tags) == 38
    by_number = {t.nummer: t for t in tags}
    assert [vars(o) for o in by_number["22.28"].overrides] == [
        {"target": "22.27", "type": "restriction"}
    ]
    assert [vars(o) for o in by_number["22.23"].overrides] == [  # "a; b" in one cell
        {"target": "22.27", "type": "restriction"},
        {"target": "22.36", "type": "restriction"},
    ]
    assert len(cypher_statements(DERIVE)) == 3


def test_cypher_comments_are_not_statements(tmp_path: Path) -> None:
    script = tmp_path / "s.cypher"
    script.write_text("// a; comment\nMATCH (n) RETURN n;\n\n  // x\nRETURN 1;\n")
    assert cypher_statements(script) == ["MATCH (n) RETURN n", "RETURN 1"]


def test_incoming_references_keep_direction_and_reference_priority() -> None:
    graph = FakeGraph(ART.format(27))
    graph.links_by_source[ART.format(27)].insert(
        0, Link(ART.format(27), ART.format(31), "referred_by")
    )
    texts = {ART.format(n): component(str(n)) for n in (26, 27, 28, 30, 31)}
    knowledge = KnowledgeGraph(graph, texts, limit=3)
    assert [link.target for link in knowledge.related([ART.format(27)])] == [
        ART.format(28),
        ART.format(26),
        ART.format(31),
    ]
    expanded = knowledge.expand([evidence(ART.format(27))])
    assert expanded[-1].graph_paths[0].relations == ["referred_by"]
    assert "verwijst naar [1]" in build_prompt("vraag", expanded)
    result = respond(
        {
            "background_documents": [
                {"id": "q", "meta": {"documentComponentId": ART.format(27)}}
            ]
        },
        knowledge,
    )
    assert result["answer"][-1]["title"] == (
        "Artikel 22.31 (kennisgraaf: verwijst naar Artikel 22.27)"
    )


def test_snapshot_reference_ranges_include_interior_articles() -> None:
    spec = importlib.util.spec_from_file_location(
        "build_graph", PROTOTYPE / "scripts" / "build_graph.py"
    )
    assert spec is not None and spec.loader is not None
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    nodes, _, references, eid_to_wid = loader.parse_text(SNAPSHOT / "Regeling/Tekst.xml")
    by_number = {n["nummer"]: n for n in nodes.values() if n["label"] == "Artikel"}
    source = by_number["22.103"]["wId"] + "__para_1"
    targets = {eid_to_wid[t] for s, t in references if s == source and t in eid_to_wid}
    assert {by_number[f"22.{n}"]["wId"] for n in range(98, 103)} <= targets
    assert by_number["22.104"]["wId"] not in targets
    assert len(references) == len(set(references))
    # Incoming traversal must also reach references to a main rule's lid.
    for supporting, main in [(273, 272), (274, 272), (275, 272), (124, 122), (67, 63)]:
        assert any(
            s.split("__para_", 1)[0] == by_number[f"22.{supporting}"]["wId"]
            and eid_to_wid.get(t, "").split("__para_", 1)[0]
            == by_number[f"22.{main}"]["wId"]
            for s, t in references
        )


def test_override_properties_reach_evidence_prompt_and_endpoint() -> None:
    for relation in ("overridden_by", "overrides"):
        for properties, suffix in [
            ({}, ""),
            ({"mechanism": "measurement"}, ":mechanism=measurement"),
            (
                {"temporal": True, "baseline": "prior_state"},
                ":temporal=true:baseline=prior_state",
            ),
            ({"temporal": False}, ":temporal=false"),
        ]:
            driver = Mock()
            driver.execute_query.return_value = (
                [
                    {
                        "source": ART.format(27),
                        "target": ART.format(28),
                        "relation": relation,
                        "type": "exception",
                        "effect": "exemption",
                        "mechanism": None,
                        "temporal": None,
                        "baseline": None,
                        **properties,
                    }
                ],
                None,
                None,
            )
            graph = Neo4jGraph(driver)
            (link,) = graph.links([ART.format(27)])
            expected = f"{relation}:exception:exemption{suffix}"
            assert _describe(link) == expected
            # Keep this fixture to one hop so it models the actual query's source.
            fake = FakeGraph(ART.format(27))
            fake.links_by_source = {ART.format(27): [link]}
            knowledge = KnowledgeGraph(
                fake, {ART.format(n): component(str(n)) for n in (27, 28)}
            )
            expanded = knowledge.expand([evidence(ART.format(27))])
            assert expanded[1].graph_paths[0].relations == [expected]
            prompt = build_prompt("vraag", expanded)
            result = respond(
                {
                    "background_documents": [
                        {"id": "q", "meta": {"documentComponentId": ART.format(27)}}
                    ]
                },
                knowledge,
            )
            title = result["answer"][-1]["title"]
            for qualifier in suffix.split(":")[1:]:
                assert qualifier in prompt
                assert qualifier in title
            if not properties:
                assert "mechanism=" not in prompt
                assert "temporal=" not in title
