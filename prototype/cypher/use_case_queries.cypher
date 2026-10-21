// Use-case demo queries for the Omgevingsplan knowledge graph.
//
// Prerequisite: build_and_tag.cypher (or deontic_extract.py --write) has run, so
// every article carries statement_type / deontic and the OVERRIDES edges exist.
//
// Run in Neo4j Browser ONE block at a time, so the
// node-returning queries draw on the canvas instead of returning a table.


// ===========================================================================
// DEMO PREP (run before recording, one statement at a time).
//
// What this overwrites, and why: the live graph holds the gpt-4o LLM tags
// (deontic_source = 'openai:gpt-4o'). The model mislabels some showcase
// articles -- e.g. it tags 22.38 as 'exemption', when its effect is a
// 'prohibition': it reimposes a permit by switching off the permit-free rule
// 22.36. For a correct, stable on-screen example we overwrite ONLY these six
// articles with the hand-verified labels (deontic_source = 'manual'); the rest
// of the graph keeps its LLM tags. To restore the LLM tags afterwards, re-run
// deontic_extract.py --write.
// ===========================================================================

// prep 1 -- clear any mirrored deontic labels. addLabels (block 0) only ADDS, so
// a stale label from an earlier mirror (e.g. 22.38 left as :Exemption) would
// otherwise stick alongside the corrected one and confuse the colours.
MATCH (a:Artikel) REMOVE a:Permission:Prohibition:Exemption:Obligation;

// prep 2 -- overwrite the six showcase articles with the verified deontic tags.
UNWIND [
  {nummer:'22.26', deontic:'prohibition'}, {nummer:'22.27', deontic:'exemption'},
  {nummer:'22.28', deontic:'prohibition'}, {nummer:'22.36', deontic:'permission'},
  {nummer:'22.38', deontic:'prohibition'}, {nummer:'22.39', deontic:'prohibition'}
] AS row
MATCH (a:Artikel {nummer: row.nummer})
SET a.statement_type = 'prescriptive', a.deontic = row.deontic, a.deontic_source = 'manual';

// prep 3 -- ensure the verified OVERRIDES edges exist (MERGE: no duplicates).
UNWIND [
  {src:'22.27', tgt:'22.26', type:'exception'}, {src:'22.28', tgt:'22.27', type:'restriction'},
  {src:'22.38', tgt:'22.36', type:'restriction'}, {src:'22.39', tgt:'22.36', type:'restriction'}
] AS r
MATCH (s:Artikel {nummer:r.src}), (t:Artikel {nummer:r.tgt})
MERGE (s)-[o:OVERRIDES]->(t) SET o.override_type = r.type, o.override_source = 'manual';


// ===========================================================================
// 0. Colour by force. Neo4j Browser colours nodes by label, not by property,
//    so mirror each article's deontic onto a label (Permission / Prohibition /
//    Exemption / Obligation). This is prep step 4; run it after prep 1-3.
//    Needs APOC; safe to re-run.
// ===========================================================================
MATCH (a:Artikel) WHERE a.deontic IS NOT NULL
CALL apoc.create.addLabels(a, [apoc.text.capitalize(a.deontic)]) YIELD node
RETURN count(node);

// Then in the Browser style panel: set the node caption to `opschrift` (or
// `nummer` for compactness), colour Permission green and Prohibition red, and
// set the OVERRIDES relationship caption to `override_type`.


// ===========================================================================
// VERIFY (not recorded) -- each showcase article should show its correct
// deontic plus exactly one matching label (e.g. 22.36 -> permission :Permission,
// 22.38 -> prohibition :Prohibition).
// ===========================================================================
MATCH (a:Artikel) WHERE a.nummer IN ['22.26','22.27','22.28','22.36','22.38','22.39']
RETURN a.nummer AS nummer, a.deontic AS deontic, labels(a) AS labels
ORDER BY nummer;


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
// Reset: remove the mirrored colour labels (does not touch deontic/overrides).
// ===========================================================================
MATCH (a:Artikel) REMOVE a:Permission:Prohibition:Exemption:Obligation;
