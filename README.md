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

## How it works

```
Query ──> RAG ──────────────────> KG ─────────────────────> LLM ───────> Answer
          OmgevingsChat's own     our Neo4j graph adds the  gpt-4o answers
          retrieval (Qdrant +     rules that override, are  from the numbered
          Cohere rerank), through overridden by or are      sources, citing
          bridge/omgevingschat    referred to by each hit   them as [n]
```

RAG returns passages identified by their STOP wId; the graph is keyed on the same
wIds, so the KG step joins on them directly. Example: RAG finds 22.27 (dakkapel
permit-free); the graph adds 22.28, which switches that exemption off for
monuments. Code: `src/omgkg/pipeline.py`, one function per step.

The same KG step also runs as **OmgevingsChat's own KG endpoint** (`omgkg
serve-kg`, below), so their platform can use our graph without code changes.

## Setup

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/), git and
Docker (with Compose; on Arch/CachyOS `sudo pacman -S docker-compose`).

```bash
git clone https://github.com/Omgevingschat/knowledge-graph.git
cd knowledge-graph
uv sync                     # create .venv and install everything from uv.lock
uv run lefthook install     # install the git hooks
cp .env.example .env        # then fill in OPENAI_API_KEY (Windows: copy ...)
uv run poe check            # lint, format check, type-check, tests (= CI)
```

The RAG step runs OmgevingsChat's retrieval code, so it needs their repository
next to this one, installed once; see
[`bridge/omgevingschat/README.md`](bridge/omgevingschat/README.md).

## Run it

```bash
docker compose up -d                                  # Qdrant + Neo4j
uv run omgkg build-graph                              # KG from the committed DSO snapshot
uv run omgkg import-snapshot <file>.snapshot --collection <name>   # RAG index
# set OMGKG_QDRANT_COLLECTION=<name> in .env
uv run omgkg ask "Mag ik een dakkapel plaatsen op een monument?"
```

- `build-graph` needs no LLM: it loads the structure from `source_data/`, the
  team's saved gpt-4o tags (deontic force and 38 `OVERRIDES` edges) and their
  net effects. Re-running it gives the same graph.
- `import-snapshot` restores the Qdrant snapshot of the OmgevingsChat index
  (from the company) into the local Qdrant; it replaces a collection of the same
  name.
- `ask --no-kg` answers the same question without the graph (the baseline);
  `omgkg overlap` shows how many wIds of their index our graph knows.

### Our KG inside OmgevingsChat

Their pipeline calls a KG between candidate retrieval and rerank, at
`YDIGITAL_KG_API_URL`. Serve ours on the same protocol:

```bash
OMGKG_KG_API_KEY=<a secret> uv run omgkg serve-kg     # http://127.0.0.1:8765/api/query
```

and in their `apps/web/.env.local`:

```
YDIGITAL_KG_API_URL=http://127.0.0.1:8765/api/query
YDIGITAL_KG_API_KEY=<the same secret>
```

with the knowledge graph enabled for the organisation. Candidates that take part
in an override then skip their rerank, and the graph-linked articles are added as
sources. The protocol is documented in `src/omgkg/graph/kg_service.py`.

## Everyday commands

| Command | What it does |
| --- | --- |
| `uv run poe check` | everything CI runs |
| `uv run poe test` | tests only (`uv run pytest -k name` for a subset) |
| `uv run poe lint` / `uv run poe lint:fix` | lint / lint and apply safe fixes |
| `uv run poe format` | format the code |
| `uv run poe typecheck` | mypy (strict on `src/`) |
| `uv run omgkg --help` | the pipeline commands above |
| `uv add <package>` | add a runtime dependency (`--dev` for tooling) |

## Repository layout

```
src/omgkg/
  pipeline.py    Query -> RAG -> KG -> LLM -> Answer
  cli.py         the `omgkg` command
  retrieval/     RAG: OmgevingsChat retrieval via the bridge; Qdrant snapshot import
  graph/         KG: graph build, graph expansion, the OmgevingsChat KG endpoint
  generation/    LLM: cited answer from the evidence
  ingest/        STOP/TPOD reader: legal text and lid offsets per article
  models/        shared pydantic types (TextComponent, Evidence, Provenance)
bridge/          TypeScript bridge into OmgevingsChat's retrieval
configs/prompts/ the answer prompt
source_data/     the DSO snapshot (Maastricht, 2026-10-02); hashes in data/manifests/
data/            snapshot manifests
docs/            Neo4j guide
tests/           pytest suite, no network
prototype/       the concept demonstrator: graph loader, tagging, cypher, findings
LLM_KG/          text-only LLM graph input pipeline (being ported into src/omgkg)
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
