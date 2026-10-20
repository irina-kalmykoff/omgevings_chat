// Build the tagged Omgevingsplan knowledge graph on a fresh machine.
//
// Full sequence from an empty Neo4j:
//   1. Start Neo4j (Docker) with APOC, e.g.
//        docker run -p7474:7474 -p7687:7687 \
//          -e NEO4J_AUTH=neo4j/testpassword \
//          -e NEO4J_PLUGINS='["apoc"]' \
//          --name neo4j-omgeving neo4j:5
//   2. Load the structure from the committed delivery package:
//        python build_graph.py
//      (build_graph.py also applies constraints.cypher)
//   3. Run THIS file to add the ontology v0 layer (deontic tags + OVERRIDES):
//        docker exec -i neo4j-omgeving cypher-shell -u neo4j -p testpassword < build_and_tag.cypher
//
// The tagging below is a deterministic heuristic (deontic_source = rule_based),
// driven by article titles and a few text cues. It needs no LLM, so the tagged
// graph is fully reproducible from the committed data. It is a first pass, to be
// refined by the LLM extractor (deontic_extract.py) once the pre-write guards
// are in. Every statement is safe to re-run.


// --- statement type --------------------------------------------------------

// baseline: every article is a prescriptive norm until classified otherwise
MATCH (a:Artikel) SET a.statement_type = 'prescriptive', a.deontic_source = 'rule_based';

// constitutive (definitions) carry no deontic force
MATCH (a:Artikel) WHERE toLower(a.opschrift) CONTAINS 'begripsbepaling'
SET a.statement_type = 'constitutive', a.deontic = null;


// --- deontic tags, in precedence order (guarded by: not yet set) -----------

MATCH (a:Artikel) WHERE a.statement_type = 'prescriptive' AND a.deontic IS NULL
  AND toLower(a.opschrift) CONTAINS 'uitzondering' SET a.deontic = 'exemption';

MATCH (a:Artikel) WHERE a.statement_type = 'prescriptive' AND a.deontic IS NULL
  AND toLower(a.opschrift) CONTAINS 'inperking' SET a.deontic = 'prohibition';

MATCH (a:Artikel) WHERE a.statement_type = 'prescriptive' AND a.deontic IS NULL
  AND (toLower(a.opschrift) CONTAINS 'vergunningvrij'
       OR toLower(a.tekst) CONTAINS 'van rechtswege in overeenstemming') SET a.deontic = 'permission';

MATCH (a:Artikel) WHERE a.statement_type = 'prescriptive' AND a.deontic IS NULL
  AND (toLower(a.opschrift) CONTAINS 'vergunning'
       OR toLower(a.tekst) CONTAINS 'het is verboden') SET a.deontic = 'prohibition';

MATCH (a:Artikel) WHERE a.statement_type = 'prescriptive' AND a.deontic IS NULL
  AND (toLower(a.opschrift) CONTAINS 'aanvraagvereist'
       OR toLower(a.tekst) CONTAINS 'worden verstrekt') SET a.deontic = 'obligation';


// --- OVERRIDES: the force-bearing subset of cross-references ----------------
// The reference can sit on the article's own leden, so reach one level down
// with BEVAT*0..1. "uitzondering" lifts the base (exception); "inperking"
// reinstates it (restriction).

MATCH (src:Artikel)-[:BEVAT*0..1]->()-[:VERWIJST_NAAR]->(tgt:Artikel)
WHERE toLower(src.opschrift) CONTAINS 'uitzondering'
MERGE (src)-[o:OVERRIDES]->(tgt) SET o.override_type = 'exception';

MATCH (src:Artikel)-[:BEVAT*0..1]->()-[:VERWIJST_NAAR]->(tgt:Artikel)
WHERE toLower(src.opschrift) CONTAINS 'inperking'
MERGE (src)-[o:OVERRIDES]->(tgt) SET o.override_type = 'restriction';


// --- sanity: tag distribution ----------------------------------------------
MATCH (a:Artikel)
RETURN a.statement_type AS type, a.deontic AS deontic, count(*) AS n
ORDER BY n DESC;
