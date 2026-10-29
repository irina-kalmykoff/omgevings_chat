# omgevings_chat

Irina's code for the Omgevingschat project (project 3-1).

## Local setup

- Neo4j runs in Docker (`neo4j-omgeving`): browser at http://localhost:7474, Bolt at `bolt://localhost:7687`.
- Python environment: `../.venv` with `neo4j` and `lxml`.

## LLM graph text preparation

See [LLM_KG/README.md](LLM_KG/README.md) for the independent text-only input
pipeline. Run `python3 LLM_KG/scripts/clean_text.py` to export the legal articles
without DSO semantic annotations. It does not require Neo4j or an API key.
