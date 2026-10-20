// Exploration and demo queries for the Omgevingsplan knowledge graph.
//
// HOW TO USE
//   In Neo4j Browser (http://localhost:7474): copy ONE block (between the
//   banners) into the editor and press Cmd/Ctrl+Enter. Run them one at a time
//   so node-returning queries render as a graph instead of a table of
//   statements.
//
//   Headless / tabular (whole file at once):
//     docker exec -i neo4j-omgeving cypher-shell -u neo4j -p testpassword < queries.cypher
//
// Prerequisite: build_graph.py has been run against the delivery package.


// ===========================================================================
// 1. Sanity check — node counts per label (compare with the script's output)
// ===========================================================================
MATCH (n)
RETURN labels(n)[0] AS type, count(*) AS n
ORDER BY n DESC;


// ===========================================================================
// 2. Relationship counts per type
// ===========================================================================
MATCH ()-[r]->()
RETURN type(r) AS relatie, count(*) AS n
ORDER BY n DESC;


// ===========================================================================
// 3. The data model, drawn from the live database (good presentation slide)
// ===========================================================================
CALL db.schema.visualization();


// ===========================================================================
// 4. The monument story — the 22.26 -> 22.27 -> 22.28 cross-reference chain
//    22.26 permit rule, 22.27 its exceptions, 22.28 restricts those for
//    cultural heritage. The edge is what a vector search cannot see.
// ===========================================================================
MATCH p = (a:Artikel)-[:VERWIJST_NAAR]-(b:Artikel)
WHERE a.nummer IN ['22.26', '22.27', '22.28']
RETURN p;


// ===========================================================================
// 5. Full applicability context of one article in a single hop:
//    the rule, the activity it governs, and where it applies
// ===========================================================================
MATCH (art:Artikel {nummer: '22.28'})<-[:IS_TEKST_VAN]-(:Regeltekst)
      <-[:VAN_REGELTEKST]-(rvi:RegelVoorIedereen)-[:GELDT_VOOR]->(act:Activiteit)
RETURN art, rvi, act;


// ===========================================================================
// 6. Structural centrality — the most cross-referenced articles
//    (the rules a correct answer most often depends on)
// ===========================================================================
MATCH (a:Artikel)<-[:VERWIJST_NAAR]-()
RETURN a.nummer AS artikel, a.opschrift AS titel, count(*) AS inkomend
ORDER BY inkomend DESC
LIMIT 10;


// ===========================================================================
// 7. The whole plan from the root — Regeling down through its chapters.
//    The final structural visualization: run alone to see the tree fan out
//    from one root node.
// ===========================================================================
MATCH p = (:Regeling)-[:BEVAT*1..2]->()
RETURN p LIMIT 300;


// ===========================================================================
// 8. Location context: the ambtsgebied (now carrying the RD boundary geometry)
//    and a sample of the rules that apply there. The point-in-polygon test
//    itself runs in spatial.py, since Neo4j Community has no polygon PIP.
// ===========================================================================
MATCH (loc:Locatie)<-[:OP_LOCATIE]-(:RegelVoorIedereen)
      -[:VAN_REGELTEKST]->(:Regeltekst)-[:IS_TEKST_VAN]->(art:Artikel)
WHERE loc.id CONTAINS 'ambtsgebied'
RETURN loc, art LIMIT 50;


// ===========================================================================
// 9. SHOWCASE — article 22.28 and everything it connects to, all relation
//    types at once (not just the BEVAT hierarchy). The best single live view
//    of what the graph adds: cross-references to 22.27 / 22.22, and the chain
//    out to the activity the rule governs.
//    BEVAT*0..1 reaches one level down because the cross-references live on
//    22.28's leden, not on the article node itself.
// ===========================================================================
MATCH (a:Artikel {nummer: '22.28'})
OPTIONAL MATCH leden = (a)-[:BEVAT]->(:Lid)
OPTIONAL MATCH kruis = (a)-[:BEVAT*0..1]->()-[:VERWIJST_NAAR]->(:Artikel)
OPTIONAL MATCH regel = (a)-[:BEVAT*0..1]->()<-[:IS_TEKST_VAN]-(:Regeltekst)
                       <-[:VAN_REGELTEKST]-(:RegelVoorIedereen)-[:GELDT_VOOR]->(:Activiteit)
RETURN a, leden, kruis, regel;

// Check data loaded
// For gemeente Maastricht: Regeltekst ~597, RegelVoorIedereen ~597, Lid ~473, 
//Artikel ~308, Activiteit 90, plus Hoofdstuk/Afdeling/Paragraaf/Subparagraaf, 
// Locatie, Component, Regeling 1

MATCH (n) RETURN labels(n)[0] AS type, count(*) AS n ORDER BY n DESC;

// Check relationships 
//You should see BEVAT, VERWIJST_NAAR, IS_TEKST_VAN, VAN_REGELTEKST, GELDT_VOOR, OP_LOCATIE, VALT_ONDER.

MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS n ORDER BY n DESC;

// Ontology v0 — enrichment pass over the loaded graph.
// Heuristic first pass driven by article titles; flagged rule_based, to be
// corrected during the ten-location validation and test-set review.

// baseline: every article is a prescriptive norm until classified otherwise
MATCH (a:Artikel) SET a.statement_type = 'prescriptive', a.deontic_source = 'rule_based';

// constitutive (definitions) carry no deontic force
MATCH (a:Artikel) WHERE toLower(a.opschrift) CONTAINS 'begripsbepaling'
SET a.statement_type = 'constitutive', a.deontic = null;

// deontic tags, in precedence order (guarded by: not yet set)
MATCH (a:Artikel) WHERE a.statement_type='prescriptive' AND a.deontic IS NULL
  AND toLower(a.opschrift) CONTAINS 'uitzondering' SET a.deontic='exemption';

MATCH (a:Artikel) WHERE a.statement_type='prescriptive' AND a.deontic IS NULL
  AND toLower(a.opschrift) CONTAINS 'inperking' SET a.deontic='prohibition';   // restriction effect

MATCH (a:Artikel) WHERE a.statement_type='prescriptive' AND a.deontic IS NULL
  AND (toLower(a.opschrift) CONTAINS 'vergunningvrij'
       OR toLower(a.tekst) CONTAINS 'van rechtswege in overeenstemming') SET a.deontic='permission';

MATCH (a:Artikel) WHERE a.statement_type='prescriptive' AND a.deontic IS NULL
  AND (toLower(a.opschrift) CONTAINS 'vergunning'
       OR toLower(a.tekst) CONTAINS 'het is verboden') SET a.deontic='prohibition';

MATCH (a:Artikel) WHERE a.statement_type='prescriptive' AND a.deontic IS NULL
  AND (toLower(a.opschrift) CONTAINS 'aanvraagvereist'
       OR toLower(a.tekst) CONTAINS 'worden verstrekt') SET a.deontic='obligation';

// split cross-references into OVERRIDES (force-bearing). The source article's
// own leden can hold the reference, so reach one level down with BEVAT*0..1.
MATCH (src:Artikel)-[:BEVAT*0..1]->()-[:VERWIJST_NAAR]->(tgt:Artikel)
WHERE toLower(src.opschrift) CONTAINS 'uitzondering'
MERGE (src)-[o:OVERRIDES]->(tgt) SET o.override_type='exception';

MATCH (src:Artikel)-[:BEVAT*0..1]->()-[:VERWIJST_NAAR]->(tgt:Artikel)
WHERE toLower(src.opschrift) CONTAINS 'inperking'
MERGE (src)-[o:OVERRIDES]->(tgt) SET o.override_type='restriction';

// distribution of tags
MATCH (a:Artikel)
RETURN a.statement_type AS type, a.deontic AS deontic, count(*) AS n
ORDER BY n DESC;

// the two chains, now typed
MATCH (a:Artikel)-[o:OVERRIDES]->(b:Artikel)
WHERE a.nummer IN ['22.27','22.28','22.38','22.39']
RETURN a.nummer, a.deontic, o.override_type, b.nummer, b.deontic
ORDER BY a.nummer;

// what still needs a human/LLM tag
MATCH (a:Artikel)
WHERE a.statement_type='prescriptive' AND a.deontic IS NULL
RETURN a.nummer, a.opschrift LIMIT 30;
