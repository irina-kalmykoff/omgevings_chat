# Prototype — interactive visualization

Presentation-ready view of the Maastricht omgevingsplan knowledge graph.

## Files

- `maastricht-rule-graph.html` — a self-contained interactive graph. Open it in
  any browser (double-click, no server needed). The toggle contrasts what plain
  vector retrieval surfaces (article 22.27 alone) with what the graph adds by
  following cross-references (22.26 → 22.27 → 22.28, the monument restriction a
  similarity search misses).
- `graph.json` — the subgraph the page draws (the article 22.28 neighbourhood),
  kept for reference and editing. The page also has this data embedded inline.

## Relationship to the rest of the repo

The live graph database, the loader (`build_graph.py`), the schema and the
Cypher queries live in [`../neo4j`](../neo4j). This folder is only the
presentation layer built on top of that data.
