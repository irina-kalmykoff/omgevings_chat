// Build the tagged Omgevingsplan knowledge graph on a fresh machine.
//
// Full sequence from an empty Neo4j (see ../README.md; my own exact commands
// are in ../local-setup.md):
//   1. Start Neo4j 5 with the APOC plugin; note its Bolt URL, user, password.
//   2. Load the structure from the committed delivery package:
//        python scripts/build_graph.py        (also applies the schema constraints)
//   3. Run THIS file to add the ontology v0 layer (deontic tags + OVERRIDES),
//      in Neo4j Browser or headless:
//        cypher-shell -a <bolt-url> -u <user> -p <password> < cypher/build_and_tag.cypher
//
// The tagging below is a deterministic heuristic (deontic_source = rule_based),
// driven by article titles and a few text cues. It needs no LLM, so the tagged
// graph is fully reproducible from the committed data. It is a first pass, to be
// refined by the LLM extractor (scripts/deontic_extract.py) once the pre-write guards
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
