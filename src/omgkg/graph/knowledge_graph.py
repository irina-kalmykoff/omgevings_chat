"""The KG step of Query -> RAG -> KG -> LLM -> Answer.

RAG returns passages identified by their STOP wId: an article, a lid, or an
explanatory note (toelichting) on an article. Each resolves to its article; the
graph, keyed on the same wIds, then adds the articles a reader must see next to
them: the rules that override a retrieved rule (its exceptions and restrictions),
the rules it overrides, and the articles it refers to. A retrieved note also
brings in the article it explains, since a note is not itself a rule. A vector
search sees separate paragraphs; the graph sees that 22.28 lifts the exemption
in 22.27 from 22.26.

The same ``KnowledgeGraph.related`` call serves ``omgkg ask`` (via ``expand``)
and the OmgevingsChat KG endpoint (``omgkg.graph.kg_service``).
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal, Protocol

from neo4j import Driver

from omgkg.models import Evidence, GraphPath, TextComponent

Relation = Literal["overridden_by", "overrides", "explains", "refers_to"]
# Exceptions to a retrieved rule change its answer most, references least.
PRIORITY: dict[Relation, int] = {
    "overridden_by": 0,
    "overrides": 1,
    "explains": 2,
    "refers_to": 3,
}
OVERRIDE = ("overridden_by", "overrides")
ARTICLE_HEADING = re.compile(r"^Artikel (\S+)")


@dataclass(frozen=True)
class Link:
    """``source`` (a retrieved wId) is connected to article ``target``."""

    source: str
    target: str
    relation: Relation
    override_type: str | None = None  # exception | restriction
    derived_effect: str | None = None  # net force, from derive_overrides.cypher


class Graph(Protocol):
    def links(self, wids: Sequence[str]) -> list[Link]:
        """Links of the given *article* wIds, with the article as ``source``."""
        ...


# Leden carry most cross-references, so they are followed one BEVAT level
# down. Only Artikel-to-Artikel results are returned.
LINKS_QUERY = """
UNWIND $wids AS wid
MATCH (a:Artikel {wId: wid})
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


def explained_articles(components: Iterable[TextComponent]) -> dict[str, str]:
    """Explanatory-note wId -> wId of the article it explains.

    An article-by-article note is headed like its article ("Artikel 22.283
    Toepassingsbereik"); notes on a whole paragraph name no article.
    """
    components = list(components)
    by_number = {
        c.number: c.provenance.text_component_id
        for c in components
        if c.kind == "article" and c.provenance.text_component_id
    }
    explained = {}
    for c in components:
        match = ARTICLE_HEADING.match(c.heading)
        wid = c.provenance.text_component_id
        if c.kind == "explanatory_note" and wid and match and match[1] in by_number:
            explained[wid] = by_number[match[1]]
    return explained


class KnowledgeGraph:
    """The graph plus the article texts it hands back, keyed on wId."""

    def __init__(
        self,
        graph: Graph,
        components: Mapping[str, TextComponent],
        explains: Mapping[str, str] | None = None,
        limit: int = 5,
    ) -> None:
        """``components``: articles by wId; ``explains``: note wId -> article wId."""
        self._graph = graph
        self._components = components
        self._explains = explains or {}
        self._limit = limit

    def article_of(self, wid: str) -> str | None:
        """The article a retrieved wId belongs to: itself, its lid's or its note's."""
        # Lid wIds extend their article's wId: "<article>__para_2".
        article = self._explains.get(wid) or wid.split("__para_", 1)[0]
        return article if article in self._components else None

    def _links(self, wids: Sequence[str]) -> list[Link]:
        """Each retrieved wId's links, reported from that wId."""
        first: dict[str, str] = {}  # article -> first retrieved wId resolving to it
        for wid in wids:
            article = self.article_of(wid)
            if article is not None:
                first.setdefault(article, wid)
        found = [
            Link(wid, self._explains[wid], "explains")
            for wid in wids
            if wid in self._explains
        ]
        if first:
            found += [
                replace(link, source=first[link.source])
                for link in self._graph.links(list(first))
            ]
        return found

    def related(self, wids: Sequence[str]) -> list[Link]:
        """Best links to articles whose text the evidence does not hold yet.

        In order: overrides of the retrieved articles, the article of each
        retrieved note, one more override hop from what that added (22.28 ->
        22.27 -> 22.26: the rule an exception is made to), then references.
        Up to ``limit`` graph links; notes' articles (one per note) are extra.
        """
        # A lid's article counts as retrieved; a note's article does not: a
        # note explains a rule, it does not state it.
        held = set(wids) | {w.split("__para_", 1)[0] for w in wids if "__para_" in w}
        chosen: dict[str, Link] = {}
        budget = self._limit

        def add(link: Link) -> None:
            nonlocal budget
            if link.target in held or link.target in chosen:
                return
            if link.target not in self._components:
                return  # no text to show: the graph is newer than the snapshot
            if link.relation != "explains":
                if budget == 0:
                    return
                budget -= 1
            chosen[link.target] = link

        first = self._ranked(self._links(wids), wids)
        for link in first:
            if link.relation != "refers_to":
                add(link)
        hop = [t for t, link in chosen.items() if link.relation in OVERRIDE]
        if hop:
            for link in self._ranked(self._links(hop), hop):
                if link.relation in OVERRIDE:
                    add(link)
        for link in first:
            if link.relation == "refers_to":
                add(link)
        return list(chosen.values())

    @staticmethod
    def _ranked(links: list[Link], sources: Sequence[str]) -> list[Link]:
        return sorted(
            links,
            key=lambda link: (PRIORITY[link.relation], sources.index(link.source)),
        )

    def force_bearing(self, wids: Sequence[str]) -> set[str]:
        """Retrieved articles and leden that take part in an override.

        A note on such an article is not promoted: it explains the rule; the
        article itself is added instead (``related``).
        """
        return {
            link.source
            for link in self._links(wids)
            if link.relation in OVERRIDE and link.source not in self._explains
        }

    def component(self, wid: str) -> TextComponent:
        return self._components[wid]

    def expand(self, evidence: Sequence[Evidence]) -> list[Evidence]:
        """The evidence, each graph-linked article right after what pulled it in.

        So a chain reads in order: 22.28 lid 2, then 22.27 that it restricts,
        then 22.26 that 22.27 is an exception to. ``rank`` keeps the retrieval
        rank (graph articles: after the retrieved ones, in the order added).
        """
        wids = [e.text_component_id for e in evidence]
        children: dict[str, list[Evidence]] = {}
        for i, link in enumerate(self.related(wids), start=1):
            children.setdefault(link.source, []).append(
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
            )

        ordered: list[Evidence] = []

        def emit(item: Evidence) -> None:
            ordered.append(item)
            for child in children.get(item.text_component_id, []):
                emit(child)

        for item in evidence:
            emit(item)
        return ordered


def _describe(link: Link) -> str:
    """The relation, as the answer prompt explains it to the LLM."""
    detail = ":".join(p for p in (link.override_type, link.derived_effect) if p)
    return f"{link.relation}:{detail}" if detail else link.relation
