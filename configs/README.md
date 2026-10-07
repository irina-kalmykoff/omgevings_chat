# configs

- `shared.yaml` — corpus, chunking, embedder, generator, prompt, context budget
  and `k`. Defined once and reused by every configuration.
- `experiments/` — one file per configuration (A baseline, B DSO-native,
  C LLM-induced, D hybrid). These may only differ in the source and use of graph
  structure; everything else comes from `shared.yaml`.
- `prompts/answer.txt` — the single answer prompt shared by all configurations.
