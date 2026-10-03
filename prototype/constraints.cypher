// Schema constraints for the Omgevingsplan knowledge graph.
//
// These enforce node uniqueness and create the indexes the load relies on.
// build_graph.py applies these automatically, so you normally do NOT need to
// run this file by hand. It is kept here as the canonical schema definition,
// and for loading the schema without the Python script, e.g.:
//
//   docker exec -i neo4j-omgeving cypher-shell -u neo4j -p testpassword < constraints.cypher
//
// Every statement is idempotent (IF NOT EXISTS): safe to re-run.

CREATE CONSTRAINT regeling_id     IF NOT EXISTS FOR (n:Regeling)          REQUIRE n.id  IS UNIQUE;
CREATE CONSTRAINT hoofdstuk_wid   IF NOT EXISTS FOR (n:Hoofdstuk)         REQUIRE n.wId IS UNIQUE;
CREATE CONSTRAINT afdeling_wid    IF NOT EXISTS FOR (n:Afdeling)          REQUIRE n.wId IS UNIQUE;
CREATE CONSTRAINT paragraaf_wid   IF NOT EXISTS FOR (n:Paragraaf)         REQUIRE n.wId IS UNIQUE;
CREATE CONSTRAINT subparagraaf_wid IF NOT EXISTS FOR (n:Subparagraaf)     REQUIRE n.wId IS UNIQUE;
CREATE CONSTRAINT artikel_wid     IF NOT EXISTS FOR (n:Artikel)           REQUIRE n.wId IS UNIQUE;
CREATE CONSTRAINT lid_wid         IF NOT EXISTS FOR (n:Lid)               REQUIRE n.wId IS UNIQUE;
CREATE CONSTRAINT regeltekst_id   IF NOT EXISTS FOR (n:Regeltekst)        REQUIRE n.id  IS UNIQUE;
CREATE CONSTRAINT rvi_id          IF NOT EXISTS FOR (n:RegelVoorIedereen) REQUIRE n.id  IS UNIQUE;
CREATE CONSTRAINT activiteit_id   IF NOT EXISTS FOR (n:Activiteit)        REQUIRE n.id  IS UNIQUE;
CREATE CONSTRAINT locatie_id      IF NOT EXISTS FOR (n:Locatie)           REQUIRE n.id  IS UNIQUE;
CREATE CONSTRAINT component_eid   IF NOT EXISTS FOR (n:Component)          REQUIRE n.eId IS UNIQUE;
