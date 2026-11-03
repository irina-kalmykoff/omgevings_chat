# configs

- `prompts/answer.txt` — the answer prompt of the LLM step
  (`src/omgkg/generation/answer.py`), shared by every configuration so that
  only the retrieval and the graph differ between runs.

Runtime settings (models, collection, endpoints) are environment variables; see
`.env.example`.
