# knowledge-graph

Research prototype for **OmgevingsChat**: does a knowledge graph improve
retrieval, grounding and traceability when answering questions about the Dutch
Omgevingswet? We compare a graph derived from explicit DSO structure with a graph
extracted automatically from the same legal text, against a conventional
text-retrieval baseline. Scope: gemeente Maastricht and a limited set of
activities.

> **Disclaimer.** This is a research demonstrator built by students of Maastricht
> University (DACS). It is not legal advice and must not be used as such.
> Consult the official sources (Omgevingsloket / DSO) or a legal professional.

## Setup

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/) and git.
uv installs the right Python version for you.

```bash
git clone https://github.com/Omgevingschat/knowledge-graph.git
cd knowledge-graph
uv sync                     # create .venv and install everything from uv.lock
uv run lefthook install     # install the git hooks
cp .env.example .env        # local settings (Windows cmd: copy .env.example .env)
uv run poe check            # lint, format check, type-check, tests
```

The last command is exactly what CI runs; if it passes locally, CI passes.

The DSO snapshot is not in git; [`data/README.md`](data/README.md) explains how
to get it. The Neo4j database and the existing concept prototype have their own
guides: [`docs/neo4j-setup.md`](docs/neo4j-setup.md) and
[`prototype/README.md`](prototype/README.md).

## Everyday commands

| Command | What it does |
| --- | --- |
| `uv run poe check` | everything CI runs |
| `uv run poe test` | tests only (`uv run pytest -k name` for a subset) |
| `uv run poe lint` / `uv run poe lint:fix` | lint / lint and apply safe fixes |
| `uv run poe format` | format the code |
| `uv run poe typecheck` | mypy (strict on `src/`) |
| `uv add <package>` | add a runtime dependency (`--dev` for tooling) |

## Repository layout

```
configs/       shared experiment settings, one file per configuration, the answer prompt
data/          local DSO snapshot and corpus (gitignored); manifests and eval set (committed)
docs/          setup guides and notes
src/omgkg/
  models/      shared pydantic types (TextComponent, Node, Edge, Provenance, Evidence, ...)
  ingest/      DSO snapshot readers, normalization, chunking
  graph/       Neo4j store, ontology, and the graph builders per configuration
  retrieval/   text baseline and graph-assisted retriever
  generation/  answer generation with citations
  evaluation/  graph-quality, retrieval and answer metrics
  experiments/ runner and configuration registry
scripts/       one-off utilities
notebooks/     exploration only
tests/         pytest suite with small committed fixtures
prototype/     the concept demonstrator (to be ported into src/omgkg)
```

## Experimental configurations

| ID | Name | Graph |
| --- | --- | --- |
| A | Conventional RAG baseline | none |
| B | DSO-native KG-RAG | built from DSO structure and metadata |
| C | LLM-induced KG-RAG | extracted from the legal text, without DSO annotations |
| D | Hybrid KG-RAG (optional) | DSO core plus selected extracted relations |

All configurations share the same corpus, chunking, embeddings, generator,
prompt and context budget; only the graph differs.

## CI

GitHub Actions runs `uv run poe check` on every pull request and on `main`
(`.github/workflows/ci.yml`). `bitbucket-pipelines.yml` mirrors it in the shape
of the OmgevingsChat pipeline, for when this repository is connected to the
client's Bitbucket.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the project rules, code conventions
and git workflow.

## License

[Apache 2.0](LICENSE)
