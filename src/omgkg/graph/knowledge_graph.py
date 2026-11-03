"""The KG step of Query -> RAG -> KG -> LLM -> Answer.

RAG returns passages identified by their STOP wId (article or lid). The graph,
keyed on the same wIds, adds the articles a reader must see next to them: the
rules that override a retrieved rule (its exceptions and restrictions), the rules
it overrides, and the articles it refers to. A vector search sees separate
paragraphs; the graph sees that 22.28 lifts the exemption in 22.27 from 22.26.

The same ``KnowledgeGraph.related`` call serves ``omgkg ask`` (via ``expand``)
and the OmgevingsChat KG endpoint (``omgkg.graph.kg_service``).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from neo4j import Driver

from omgkg.models import Evidence, GraphPath, TextComponent

Relation = Literal["overridden_by", "overrides", "refers_to"]
# Exceptions to a retrieved rule change its answer most, references least.
PRIORITY: dict[Relation, int] = {"overridden_by": 0, "overrides": 1, "refers_to": 2}


@dataclass(frozen=True)
class Link:
    """``source`` (a retrieved wId) is connected to article ``target``."""

    source: str
    target: str
    relation: Relation
    override_type: str | None = None  # exception | restriction
    derived_effect: str | None = None  # net force, from derive_overrides.cypher


class Graph(Protocol):
    def links(self, wids: Sequence[str]) -> list[Link]: ...


# A lid resolves to its article; leden carry most cross-references, so they are
# followed one BEVAT level down. Only Artikel-to-Artikel results are returned.
LINKS_QUERY = """
UNWIND $wids AS wid
MATCH (n) WHERE (n:Artikel OR n:Lid) AND n.wId = wid
OPTIONAL MATCH (parent:Artikel)-[:BEVAT]->(n)
WITH wid, coalesce(parent, n) AS a
CALL (a) {
    MATCH (b:Artikel)-[o:OVERRIDES]->(a)
    RETURN b, 'overridden_by' AS relation, o.override_type AS type,
           o.derived_effect AS effect
  UNION
    MATCH (a)-[o:OVERRIDES]->(b:Artikel)
    RETURN b, 'overrides' AS relation, o.override_type AS type,
           o.derived_effect AS effect
  UNION
    MATCH (a)-[:BEVAT*0..1]->()-[:VERWIJST_NAAR]->(x)
    OPTIONAL MATCH (xp:Artikel)-[:BEVAT]->(x)
    WITH coalesce(xp, x) AS b WHERE b:Artikel
    RETURN b, 'refers_to' AS relation, null AS type, null AS effect
}
WITH wid, a, b, relation, type, effect WHERE b <> a
RETURN wid AS source, b.wId AS target, relation, type, effect
"""


class Neo4jGraph:
    def __init__(self, driver: Driver) -> None:
        self._driver = driver

    def links(self, wids: Sequence[str]) -> list[Link]:
        records, _, _ = self._driver.execute_query(LINKS_QUERY, wids=list(wids))
        return [
            Link(r["source"], r["target"], r["relation"], r["type"], r["effect"])
            for r in records
        ]


class KnowledgeGraph:
    """The graph plus the article texts it hands back, keyed on wId."""

    def __init__(
        self,
        graph: Graph,
        components: Mapping[str, TextComponent],
        limit: int = 5,
    ) -> None:
        self._graph = graph
        self._components = components
        self._limit = limit

    def related(self, wids: Sequence[str]) -> list[Link]:
        """Best links to articles that are neither retrieved nor already linked."""
        retrieved = set(wids) | {self._article(w) for w in wids}
        links = sorted(
            self._graph.links(wids),
            key=lambda link: (PRIORITY[link.relation], wids.index(link.source)),
        )
        chosen: dict[str, Link] = {}
        for link in links:
            if link.target in retrieved or link.target in chosen:
                continue
            if link.target not in self._components:
                continue  # no text to show: the graph is newer than the snapshot
            chosen[link.target] = link
            if len(chosen) == self._limit:
                break
        return list(chosen.values())

    def force_bearing(self, wids: Sequence[str]) -> set[str]:
        """Retrieved wIds that take part in an override: they must reach the LLM."""
        return {
            link.source
            for link in self._graph.links(wids)
            if link.relation != "refers_to"
        }

    def component(self, wid: str) -> TextComponent:
        return self._components[wid]

    def expand(self, evidence: Sequence[Evidence]) -> list[Evidence]:
        """The retrieved evidence, then each graph-linked article after it."""
        wids = [e.text_component_id for e in evidence]
        added = [
            Evidence(
                text_component_id=link.target,
                text=self.component(link.target).text,
                rank=len(evidence) + i,
                provenance=self.component(link.target).provenance,
                graph_paths=[
                    GraphPath(
                        node_ids=[link.source, link.target],
                        relations=[_describe(link)],
                    )
                ],
            )
            for i, link in enumerate(self.related(wids), start=1)
        ]
        return [*evidence, *added]

    def _article(self, wid: str) -> str:
        # Lid wIds extend their article's wId: "<article>__para_2".
        return wid.split("__para_", 1)[0]


def _describe(link: Link) -> str:
    """The relation, as the answer prompt explains it to the LLM."""
    detail = ":".join(p for p in (link.override_type, link.derived_effect) if p)
    return f"{link.relation}:{detail}" if detail else link.relation
