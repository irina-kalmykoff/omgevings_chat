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
