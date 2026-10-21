# Demo video script (3 minutes)

Group 2 — Knowledge Graphs for Reliable Legal RAG

A 3-minute screen recording of the Maastricht omgevingsplan knowledge graph. One
idea to land: the graph answers a legal question correctly where vector search
fails, because it captures deontic force and defeasibility — a permit-free rule
quietly overridden by an exception a similarity search would miss.

Mostly Neo4j Browser (live), one optional cutaway to the ontology one-pager.
Narration lines double as on-screen captions if recording silent. Hard cap 3:00.

---

## Before you record

### 1. Check the setup

- Neo4j running with APOC enabled, and Neo4j Browser open (the URL your Neo4j
  shows for it).
- Graph loaded and tagged — run:

  ```cypher
  MATCH (n) RETURN labels(n)[0] AS type, count(*) AS n ORDER BY n DESC;
  ```

  Expect roughly 308 Artikel plus Regeltekst, RegelVoorIedereen, Activiteit,
  Locatie and the structure labels. If it comes back near-empty, run
  `scripts/build_graph.py` then `cypher/build_and_tag.cypher` first.

### 2. Fire the prep (not recorded, one statement at a time)

Why: the live graph holds the gpt-4o LLM tags, which mislabel some of the
showcase articles — e.g. 22.38 comes out `exemption`, when its effect is a
`prohibition` (it reimposes a permit by switching off the permit-free rule
22.36). Overwrite ONLY these six articles with the hand-verified labels
(`deontic_source = 'manual'`) so the on-screen example is correct and stable; the
rest of the graph keeps its LLM tags. Restore them afterwards with
`python scripts/deontic_extract.py --backend openai --model gpt-4o --write`.

```cypher
// a. clear any stale colour labels (addLabels only adds, so an old one lingers)
MATCH (a:Artikel) REMOVE a:Permission:Prohibition:Exemption:Obligation;
```

```cypher
// b. verified deontic tags for the six showcase articles
UNWIND [
  {nummer:'22.26', deontic:'prohibition'}, {nummer:'22.27', deontic:'exemption'},
  {nummer:'22.28', deontic:'prohibition'}, {nummer:'22.36', deontic:'permission'},
  {nummer:'22.38', deontic:'prohibition'}, {nummer:'22.39', deontic:'prohibition'}
] AS row
MATCH (a:Artikel {nummer: row.nummer})
SET a.statement_type='prescriptive', a.deontic=row.deontic, a.deontic_source='manual';
```

```cypher
// c. verified OVERRIDES edges (MERGE: no duplicates)
UNWIND [
  {src:'22.27', tgt:'22.26', type:'exception'}, {src:'22.28', tgt:'22.27', type:'restriction'},
  {src:'22.38', tgt:'22.36', type:'restriction'}, {src:'22.39', tgt:'22.36', type:'restriction'}
] AS r
MATCH (s:Artikel {nummer:r.src}), (t:Artikel {nummer:r.tgt})
MERGE (s)-[o:OVERRIDES]->(t) SET o.override_type=r.type, o.override_source='manual';
```

```cypher
// d. mirror deontic onto a label so Browser can colour by force (= block 0)
MATCH (a:Artikel) WHERE a.deontic IS NOT NULL
CALL apoc.create.addLabels(a, [apoc.text.capitalize(a.deontic)]) YIELD node
RETURN count(node);
```

### 3. Check it looks right

- Verify the six — run:

  ```cypher
  MATCH (a:Artikel) WHERE a.nummer IN ['22.26','22.27','22.28','22.36','22.38','22.39']
  RETURN a.nummer, a.deontic, labels(a) ORDER BY a.nummer;
  ```

  Expect: 22.26 prohibition, 22.27 exemption, 22.28 prohibition, 22.36 permission,
  22.38 prohibition, 22.39 prohibition — each with one matching deontic label.

- Style the canvas: run Beat 3's query (below), then in the Browser style panel
  set the node caption to `opschrift`, colour Permission green and Prohibition
  red, and set the OVERRIDES caption to `override_type`. Bump the font, collapse
  the left sidebar, full-screen the window.

- How Beat 3 should look before you record: one building-activity node, 22.36
  (green) with a GOVERNS edge to it, and 22.38 + 22.39 (red) pointing back at
  22.36 with `restriction` edges. If that's what you see, you're ready.

---

## Shot list (3:00)

### 0:00–0:15 — Hook

On screen: the Beat 3 graph already drawn, or a title card.

Narration: "This is the Maastricht environmental plan as a knowledge graph. I'll
show what it is, the legal layer we added, and one question it answers that plain
search gets wrong."

### 0:15–0:45 — Beat 1: the graph is real

```cypher
MATCH (n) RETURN labels(n)[0] AS type, count(*) AS n ORDER BY n DESC;
```
```cypher
MATCH p = (r:Regeling)-[:BEVAT]->(h:Hoofdstuk) RETURN p;
```

Narration: "The whole plan — 308 articles and their structure — loaded from the
official STOP/TPOD delivery, with chapters, articles and their rule text as
nodes."

### 0:45–1:25 — Beat 2: the ontology layer

```cypher
CALL db.schema.visualization();
```
Optional cutaway: the ontology one-pager (deontic tags + the VERWIJST_NAAR ->
OVERRIDES split), 10–15s, then back to Browser.

Narration: "On top of the structure we add the legal layer. Every rule gets a
normative force — obligation, prohibition, permission, or exemption — and the
plain cross-references split into force-bearing overrides: an exception that lifts
a rule, or a restriction that reimposes it. That force and those overrides are
what the raw text and a vector index don't encode."

### 1:25–2:45 — Beat 3: one worked example (the payoff)

```cypher
MATCH (base:Artikel {nummer: '22.36'})
OPTIONAL MATCH (base)-[:IS_TEKST_VAN|VAN_REGELTEKST|GELDT_VOOR*1..3]-(bact:Activiteit)
OPTIONAL MATCH (defeater:Artikel)-[ov:OVERRIDES]->(base)
OPTIONAL MATCH (defeater)-[:IS_TEKST_VAN|VAN_REGELTEKST|GELDT_VOOR*1..3]-(dact:Activiteit)
RETURN base, bact, defeater, ov, dact,
  CASE WHEN bact IS NOT NULL THEN apoc.create.vRelationship(base, 'GOVERNS', {}, bact) END AS g1,
  CASE WHEN dact IS NOT NULL THEN apoc.create.vRelationship(defeater, 'GOVERNS', {}, dact) END AS g2;
```

Narration, as the contrast: "Here's the question: can I build this, permit-free?
A similarity search finds article 22.36 — 'permit-free of right' — and answers
yes. But follow the override edge: 22.36 is cut back by 22.38 for cultural
heritage and by 22.39 for external safety. So the correct answer is 'yes, unless'
— and that 'unless' is exactly what a text search misses. The graph makes the
exception reachable."

Optional tighter second illustration, if time:
```cypher
MATCH p = (:Artikel {nummer:'22.28'})-[:OVERRIDES*1..2]->(:Artikel) RETURN p;
```
"Same mechanism, three articles deep: a permit rule, its exception, and a
restriction that brings the permit back for monuments."

### 2:45–3:00 — Close

Narration: "Deontic force plus defeasibility, as a graph the retrieval pipeline
can traverse — that's how the knowledge graph makes legal answers reliable."
