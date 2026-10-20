// Use-case demo queries for the Omgevingsplan knowledge graph.
//
// Prerequisite: build_and_tag.cypher has been run, so every article carries
// statement_type / deontic and the OVERRIDES edges exist.
//
// Run in Neo4j Browser (http://localhost:7474) ONE block at a time, so the
// node-returning queries draw on the canvas instead of returning a table.


// ===========================================================================
// 0. Colour by force. Neo4j Browser colours nodes by label, not by property,
//    so mirror each article's deontic onto a label (Permission / Prohibition /
//    Exemption / Obligation). Needs APOC; safe to re-run.
// ===========================================================================
MATCH (a:Artikel) WHERE a.deontic IS NOT NULL
CALL apoc.create.addLabels(a, [apoc.text.capitalize(a.deontic)]) YIELD node
RETURN count(node);

// Then in the Browser style panel: set the node caption to `opschrift` (or
// `nummer` for compactness), colour Permission green and Prohibition red, and
// set the OVERRIDES relationship caption to `override_type`.


// ===========================================================================
// A. The defeasibility chain (the monument / dakkapel story).
//    22.26 requires a permit -> 22.27 exempts stated cases -> 22.28 lifts that
//    exemption again for monuments, so the permit requirement returns. Follows
//    OVERRIDES outward from the most specific rule. A vector search sees three
//    separate paragraphs; the graph sees the chain.
// ===========================================================================
MATCH p = (:Artikel {nummer: '22.28'})-[:OVERRIDES*1..2]->(:Artikel)
RETURN p;


// ===========================================================================
// B. A question answered on the graph:
//    "Mag ik bouwen (bouwactiviteit) vergunningvrij van rechtswege?"
//    22.36 (permission) governs the building activity; 22.38 (cultureel
//    erfgoed) and 22.39 (externe veiligheid) restrict it. The Regeltekst /
//    RegelVoorIedereen plumbing is collapsed into one virtual GOVERNS edge so
//    the canvas reads as the inquiry, not the schema. Needs APOC.
//
//    Note: all three rules attach to the SAME generic activity. The cultural-
//    heritage and external-safety triggers live in the rule text, not as
//    separate Activiteit or Locatie nodes (see FINDINGS.md, current issues).
// ===========================================================================
MATCH (base:Artikel {nummer: '22.36'})
OPTIONAL MATCH (base)-[:IS_TEKST_VAN|VAN_REGELTEKST|GELDT_VOOR*1..3]-(bact:Activiteit)
OPTIONAL MATCH (defeater:Artikel)-[ov:OVERRIDES]->(base)
OPTIONAL MATCH (defeater)-[:IS_TEKST_VAN|VAN_REGELTEKST|GELDT_VOOR*1..3]-(dact:Activiteit)
RETURN base, bact, defeater, ov, dact,
  CASE WHEN bact IS NOT NULL THEN apoc.create.vRelationship(base, 'GOVERNS', {}, bact) END AS g1,
  CASE WHEN dact IS NOT NULL THEN apoc.create.vRelationship(defeater, 'GOVERNS', {}, dact) END AS g2;


// ===========================================================================
// Reset the colour labels (optional), e.g. before re-running block 0.
// ===========================================================================
MATCH (a:Artikel) REMOVE a:Permission:Prohibition:Exemption:Obligation;
