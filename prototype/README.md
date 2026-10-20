# Prototype — knowledge graph loader, queries and visualization

The prototype of the Maastricht omgevingsplan knowledge graph: the code that
builds, tags and queries it, plus the presentation visual. The Neo4j database it
talks to is set up in [`../neo4j`](../neo4j); the source files it reads are
committed in [`../source_data`](../source_data).

## Files

| File | What it is |
| --- | --- |
| `build_graph.py` | parses the STOP/TPOD delivery package and loads the full graph |
| `constraints.cypher` | the schema (uniqueness constraints); applied automatically by `build_graph.py`, kept as the canonical definition |
| `build_and_tag.cypher` | the ontology v0 tagging layer (statement_type, deontic tags, OVERRIDES edges), run after `build_graph.py`; deterministic heuristic, no LLM |
| `queries.cypher` | general exploration and demo queries, one block each |
| `use_case_queries.cypher` | demo queries on the tagged graph: colour-by-force, the defeasibility chain, and a question answered on the graph |
| `deontic_extract.py` | LLM deontic extractor, switchable local (Ollama) / OpenAI, with gold evaluation |
| `review_mismatches.py` | writes a mismatch report of the extractor against the gold set, with article text |
| `gold_deontic.csv` | 38 hand-labelled articles used to score the extractor |
| `spatial.py` | point-in-polygon lookup: which rules apply at an RD point |
| `generate_visualisation.py` | renders any Cypher query's result as a self-contained HTML graph with SVG/PNG export |
| `maastricht-rule-graph.html` | self-contained interactive graph (open in a browser) |
| `graph.json` | the subgraph the page draws (also embedded in the page) |
| `FINDINGS.md` | running log of results and decisions |

## Load

With the Neo4j container running ([`../neo4j`](../neo4j), steps 2–4) and the
`.venv` active, from this folder:

```bash
python build_graph.py
```

The source files are committed in [`../source_data`](../source_data), which is
the default `--package` / `--boundary` location, so no arguments are needed.
Pass `--package` / `--boundary` only to load data from elsewhere.

On success it prints `loaded: 876 structure nodes, 597 regelteksten, ...`. It is
idempotent: the load uses `MERGE`, so re-running does not duplicate nodes.

## Tag (ontology v0)

`build_graph.py` loads the structure; the ontology v0 layer (normative force and
override relations) is added on top by `build_and_tag.cypher`:

```bash
docker exec -i neo4j-omgeving cypher-shell -u neo4j -p testpassword < build_and_tag.cypher
```

This is a deterministic heuristic (title/text cues), recorded as
`deontic_source = 'rule_based'`, so the tagged graph is fully reproducible from
the committed data without an LLM. It is a first pass; `deontic_extract.py`
refines it (next section).

## Deontic extraction and evaluation

`deontic_extract.py` tags each article with an LLM, on one code path that
switches between a local model (Ollama) and the OpenAI API:

```bash
pip install openai neo4j
# local (needs: ollama pull qwen2.5:32b)
python deontic_extract.py --backend ollama --eval gold_deontic.csv
# hosted
export OPENAI_API_KEY=...        # or put it in ../.env (gitignored)
python deontic_extract.py --backend openai --model gpt-4o --eval gold_deontic.csv
```

`--eval gold_deontic.csv` scores the predictions against the 38 hand-labelled
articles without writing. `review_mismatches.py` writes a markdown report of
every disagreement with the article text, to adjudicate label vs model:

```bash
python review_mismatches.py --backend openai --model gpt-4o
```

See `FINDINGS.md` for results and open issues (including the pre-write guards
still needed before `--write`).

## Query

Open `queries.cypher` (general exploration) or `use_case_queries.cypher` (the
tagged-graph demo) and run one block at a time in Neo4j Browser (copy a block,
Cmd/Ctrl+Enter). Run them individually so node-returning queries render as a
graph rather than a table of statements. Headless (tabular) for a whole file:

```bash
docker exec -i neo4j-omgeving cypher-shell -u neo4j -p testpassword < queries.cypher
```

## Spatial lookup

The ambtsgebied `Locatie` node carries the RD boundary (loaded by default), so
`spatial.py` can test a point and return the rules that apply there:

```bash
python spatial.py 177088 318726     # a point in Maastricht
```

## Reset

To wipe the data and reload (constraints are kept):

```cypher
MATCH (n) DETACH DELETE n;
```

then re-run `python build_graph.py` and `build_and_tag.cypher`.

## The visualization

`maastricht-rule-graph.html` opens in any browser, no server needed. The toggle
contrasts what plain vector retrieval surfaces (article 22.27 alone) with what
the graph adds by following cross-references (22.26 → 22.27 → 22.28, the monument
restriction a similarity search misses).

## Visualise any query

`generate_visualisation.py` runs a Cypher query and writes a self-contained HTML
page of the nodes, relationships and paths it returns: force or radial-tree
layout, hover details, a legend, light/dark, and **Download SVG / PNG** buttons
for slides and documents. Colours are fixed per label, so figures stay
consistent.

```bash
python generate_visualisation.py "MATCH p = (:Regeling)-[:BEVAT*1..2]->() RETURN p LIMIT 300" --title "Structure of the omgevingsplan" --out plan-structure.html --open
```

Options: `--subtitle`, `--layout auto|force|tree`, `--collapse_connections`
(draw all relationships between two nodes as one edge; clearer for
`CALL db.schema.visualization()`), `--json FILE` (also save the nodes and edges), and the usual `--uri/--user/--password`. The query must return
graph elements (`RETURN p` or `RETURN n, r, m`), not only property values.

## Known limitation

Spatial lookup is municipal-level only: every rule in this delivery applies to
the whole municipality, so there is one boundary to test against. Selecting rules
by *zone* (a specific gebiedsaanwijzing or bestemmingsvlak) needs the per-rule GIO
geometries, which are not in the current delivery package. Those would attach to
additional `Locatie` nodes the same way. Related: the triggers that decide when a
restriction fires (cultural heritage, external safety) currently live in the rule
text, not as graph nodes, so the graph shows which rules can apply, not whether
they fire for a given case (see `FINDINGS.md`).
