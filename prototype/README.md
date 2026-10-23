# Prototype — knowledge graph loader, queries and visualization

The prototype of the Maastricht omgevingsplan knowledge graph: the code that
builds, tags and queries it, plus the presentation visuals. It talks to a Neo4j
database you run yourself; the source files it reads are committed in
[`../source_data`](../source_data).

## Layout

```
prototype/
  scripts/          Python: graph loader, LLM extractor, spatial + visual tools
  visualizations/   self-contained HTML graph pages (open in a browser)
  cypher/           the tagging and query layers, run in Neo4j
  silver_deontic_v1.csv  38 articles labelled by us (silver v1)
  silver_deontic_v2.csv  50 more articles labelled by Claude, stratified (silver v2)
  demo-script.md    the 3-minute demo-video script
  FINDINGS.md       running log of results and decisions
```

Run every command below **from this `prototype/` folder** (not from inside
`scripts/`). The scripts find `../source_data` and `silver_deontic_v1.csv` relative
to it.

## Build the graph (for the demo)

You do not need to run all the cypher. Steps 1–3 below build the structure and
the tagging layer; that is enough for the demo. `scripts/deontic_extract.py`,
`cypher/derive_overrides.cypher`, `cypher/queries.cypher` and `scripts/spatial.py`
are the rest of the pipeline, not required for the demo.

1. **Start Neo4j** (version 5) with the **APOC** plugin enabled, however you
   normally run it (Docker, Neo4j Desktop, a server). Note three things you will
   pass to the tools: the Bolt URL, the username and the password. The scripts
   and the examples below assume the common defaults — Bolt `bolt://localhost:7687`,
   user `neo4j`, password `testpassword` — so if yours differ, add
   `--uri/--user/--password` (Python) or edit the connection line (cypher-shell).

2. **Python environment**, from this folder:

   ```
   python3 -m venv .venv
   source .venv/bin/activate          # Windows: .venv\Scripts\activate
   pip install neo4j lxml
   ```

3. **Load the structure** (reads `../source_data`, applies the schema
   constraints automatically):

   ```
   python scripts/build_graph.py
   ```

   On success it prints `loaded: 876 structure nodes, 597 regelteksten, ...`. It
   uses `MERGE`, so re-running does not duplicate anything.

4. **Add the ontology v0 tags** (normative force + OVERRIDES edges). Open
   `cypher/build_and_tag.cypher` in Neo4j Browser and run its blocks, or feed the
   file to `cypher-shell`:

   ```
   cypher-shell -a bolt://localhost:7687 -u neo4j -p testpassword < cypher/build_and_tag.cypher
   ```

   (If Neo4j runs in a container, reach the same shell with
   `docker exec -i <container> cypher-shell -u neo4j -p testpassword < cypher/build_and_tag.cypher`.)

   This is a deterministic heuristic (title/text cues), recorded as
   `deontic_source = 'rule_based'`, so the tagged graph is reproducible from the
   committed data without an LLM.

5. **Follow `demo-script.md`** for the recording: its "Before you record"
   section seeds the six showcase articles and their verified labels, then styles
   the canvas; the shot list gives the exact on-screen queries.

## Files

| File | What it is |
| --- | --- |
| `scripts/build_graph.py` | parses the STOP/TPOD delivery package and loads the full graph; applies the schema constraints |
| `scripts/deontic_extract.py` | LLM deontic extractor, switchable local (Ollama) / OpenAI, with schema guards, write hygiene and evaluation against the silver set |
| `scripts/review_mismatches.py` | writes a mismatch report of the extractor against the silver set, with article text |
| `scripts/spatial.py` | point-in-polygon lookup: which rules apply at an RD point |
| `scripts/generate_visualisation.py` | renders any Cypher query's result as a self-contained HTML graph with SVG/PNG export |
| `cypher/constraints.cypher` | the schema (uniqueness constraints); applied automatically by `build_graph.py`, kept as the canonical definition |
| `cypher/build_and_tag.cypher` | the ontology v0 tagging layer, run after `build_graph.py`; deterministic heuristic, no LLM |
| `cypher/derive_overrides.cypher` | composes each OVERRIDES edge's net effect from the target's deontic (restriction-on-permission -> prohibition, ...) and writes it onto the edge |
| `cypher/queries.cypher` | general exploration queries, one block each |
| `cypher/use_case_queries.cypher` | demo queries on the tagged graph: colour-by-force, the defeasibility chain, and a question answered on the graph |
| `silver_deontic_v1.csv` | silver v1: 38 articles labelled by us, used to score the extractor |
| `silver_deontic_v2.csv` | silver v2: 50 articles labelled by Claude, stratified by predicted tag, with v0-fit flags |
| `silver_v2_annotation.xlsx` | the blind annotation sheet behind silver v2, with codebook |
| `demo-script.md` | shot-by-shot 3-minute demo-video script, with the pre-recording graph prep |
| `visualizations/maastricht-rule-graph.html` | self-contained interactive graph (open in a browser) |
| `visualizations/graph.json` | the subgraph that page draws (also embedded in the page) |
| `FINDINGS.md` | running log of results and decisions |

## Deontic extraction and evaluation

`scripts/deontic_extract.py` tags each article with an LLM, on one code path that
switches between a local model (Ollama) and the OpenAI API. Schema guards run
before any write (auto-on with `--write`), and `--write` clears an article's
prior OVERRIDES so re-tagging replaces rather than accumulates.

```
pip install openai neo4j
# local (needs: ollama pull qwen2.5:32b)
python scripts/deontic_extract.py --backend ollama --eval silver_deontic_v1.csv
# hosted
export OPENAI_API_KEY=...        # or put it in ../.env (gitignored)
python scripts/deontic_extract.py --backend openai --model gpt-4o --eval silver_deontic_v1.csv
# write the tags to the graph, logging the run
python scripts/deontic_extract.py --backend openai --model gpt-4o --write \
  --out runs/gpt4o_write.csv --diary runs/extraction_diary.md
```

`--eval silver_deontic_v1.csv` scores the predictions against the 38 silver v1
articles without writing; `--out` / `--diary` save a predictions CSV and a dated
run summary. `review_mismatches.py` writes a markdown report of every
disagreement with the article text, to adjudicate label vs model:

```
python scripts/review_mismatches.py --backend openai --model gpt-4o
```

See `FINDINGS.md` for results and open issues.

## Derive override effects

`cypher/derive_overrides.cypher` composes each OVERRIDES edge's net effect from the
override type and the target's deontic (e.g. a restriction on a permission is a
prohibition), writes it onto the edge as `derived_effect`, and reports where an
article's own tag disagrees with the composition. Run after tagging, in Neo4j
Browser or via `cypher-shell` as in step 4.

## Query

Open `cypher/queries.cypher` (general exploration) or `cypher/use_case_queries.cypher`
(the tagged-graph demo) and run one block at a time in Neo4j Browser (copy a block,
Cmd/Ctrl+Enter). Run them individually so node-returning queries render as a
graph rather than a table.

## Spatial lookup

The ambtsgebied `Locatie` node carries the RD boundary (loaded by default), so
`spatial.py` can test a point and return the rules that apply there:

```
python scripts/spatial.py 177088 318726     # a point in Maastricht
```

## Reset

To wipe the data and reload (constraints are kept), run in Neo4j Browser:

```cypher
MATCH (n) DETACH DELETE n;
```

then re-run step 3 (`scripts/build_graph.py`) and step 4 (`cypher/build_and_tag.cypher`).

## The visualization

`visualizations/maastricht-rule-graph.html` opens in any browser, no server
needed. The toggle contrasts what plain vector retrieval surfaces (article 22.27
alone) with what the graph adds by following cross-references (22.26 -> 22.27 ->
22.28, the monument restriction a similarity search misses).

## Visualise any query

`scripts/generate_visualisation.py` runs a Cypher query and writes a
self-contained HTML page of the nodes, relationships and paths it returns: force
or radial-tree layout, hover details, a legend, light/dark, and **Download SVG /
PNG** buttons for slides and documents. Colours are fixed per label, so figures
stay consistent.

```
python scripts/generate_visualisation.py "MATCH p = (:Regeling)-[:BEVAT*1..2]->() RETURN p LIMIT 300" --title "Structure of the omgevingsplan" --out plan-structure.html --open
```

Options: `--subtitle`, `--layout auto|force|tree`, `--collapse_connections`
(draw all relationships between two nodes as one edge; clearer for
`CALL db.schema.visualization()`), `--json FILE` (also save the nodes and edges),
and the usual `--uri/--user/--password`. The query must return graph elements
(`RETURN p` or `RETURN n, r, m`), not only property values.

## Known limitation

Spatial lookup is municipal-level only: every rule in this delivery applies to
the whole municipality, so there is one boundary to test against. Selecting rules
by *zone* (a specific gebiedsaanwijzing or bestemmingsvlak) needs the per-rule GIO
geometries, which are not in the current delivery package. Those would attach to
additional `Locatie` nodes the same way. Related: the triggers that decide when a
restriction fires (cultural heritage, external safety) currently live in the rule
text, not as graph nodes, so the graph shows which rules can apply, not whether
they fire for a given case (see `FINDINGS.md`).
