# Contributing

## Project rules

These follow from the project requirements. Enforce them in code and tests, not
only in documentation.

1. **Provenance on everything.** Every text component, graph node and graph edge
   that represents a legal claim or rule references its origin: a DSO
   resource/document/text-component ID, or the exact source passage it was
   extracted from. No provenance means the write is rejected.
2. **Origin stays distinguishable.** Every edge records `origin` ∈
   `{dso_explicit, deterministic_transform, llm_extracted}`. Inferred data must
   never look like authoritative DSO data.
3. **No DSO semantics in the extraction pipeline.** The LLM-induced builder
   receives legal text plus structural provenance only (document ID, version,
   article path), never DSO activity/location/authority annotations. DSO data
   may be used afterwards, for evaluation only.
4. **Graph retrieval returns source text.** Graph-assisted retrievers return the
   same evidence type as the baseline (source-linked text passages), never raw
   triples.
5. **Controlled experiment.** Corpus, chunking, embeddings, reranking, generator,
   prompt and context budget are defined once (`configs/`, `.env.example`) and
   reused by every configuration.
6. **Reproducibility.** Every run stores its full config, graph ID and version,
   corpus snapshot ID and all outputs, and can be re-executed from that config.
7. **Logging.** Per question: ranked retrieved sources, graph paths used, the
   answer, citations, retrieval latency and evaluation scores.
8. **Modularity.** Ingestion, graph construction, retrieval, generation and
   evaluation are separate modules that talk through typed interfaces.
9. **Local snapshot only.** DSO data is downloaded once and recorded in
   `data/manifests/`. No live API calls during graph construction, experiments
   or tests.
10. **Not legal advice.** Say so in any output a person might read as advice.

## Code conventions

- Python 3.11+, fully typed. `mypy --strict` runs on `src/`.
- Cross-module types are pydantic v2 models in `src/omgkg/models/`.
- Every change comes with tests. Tests use small fixtures in `tests/fixtures/`
  and never touch the network; pytest blocks sockets, so a test that tries
  fails.
- No secrets in the repository. Local settings go in `.env` (gitignored); add
  new variables to `.env.example` with a safe placeholder.
- Where a design decision is still open (for example, waiting on the client),
  implement behind an interface and leave a `TODO(decision): ...` comment
  instead of picking silently.
- Formatting and linting are ruff's job; don't hand-format.

## Git workflow

1. Branch from `main`: `feat/<short-name>`, `fix/<short-name>`,
   `docs/<short-name>`, ...
2. Commit using [Conventional Commits](https://www.conventionalcommits.org/),
   as in the OmgevingsChat repository: `feat: add provenance model`,
   `fix: reject edges without origin`, `docs: ...`, `test: ...`,
   `refactor: ...`, `chore: ...`.
3. The lefthook pre-commit hook lints, formats and type-checks staged Python
   files. Run `uv run poe check` before pushing.
4. Open a pull request using the template. Every PR is reviewed by a second
   team member before it is merged, and CI must be green.
