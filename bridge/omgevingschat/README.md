# OmgevingsChat bridge (configuration A)

`omgkg-bridge.ts` runs OmgevingsChat's own retrieval for one question and prints
the sources as JSON. `src/omgkg/retrieval/omgevingschat.py` calls it; that module
documents the contract. Retrieval is pinned to the Maastricht omgevingsplan, so
it needs only Qdrant, OpenAI (embeddings) and Cohere (rerank-v3.5): no location
or DSO API calls, and their knowledge graph is off.

## One-time setup

Next to this repository (`../omgevingschat-platform`):

```bash
gh repo clone Omgevingschat/omgevingschat-platform
cd omgevingschat-platform
npm install -g pnpm@11.9.0                       # the version their repo pins
SHARP_IGNORE_GLOBAL_LIBVIPS=1 pnpm install       # the variable avoids a sharp build failure when libvips is installed system-wide
```

Their settings go in `omgevingschat-platform/apps/web/.env.local` (ask the team;
never commit it). The bridge reads `OPENAI_API_KEY`, `COHERE_API_KEY` and
`QDRANT_URL` from it.

## Qdrant with the Maastricht snapshot

```bash
docker run -d --name qdrant -p 6333:6333 -v qdrant_storage:/qdrant/storage qdrant/qdrant:latest
curl -X POST "http://localhost:6333/collections/<collection>/snapshots/upload?priority=snapshot" \
  -F "snapshot=@<file>.snapshot"
```

## Check it works

From the knowledge-graph root:

```bash
uv run python scripts/omgevingschat_smoke.py overlap --collection <collection>
uv run python scripts/omgevingschat_smoke.py ask "mag ik een dakkapel bouwen?" --collection <collection>
```

`overlap` shows how many of their wIds exist in our 2026-10-02 snapshot; `ask`
shows the top-5 evidence and whether each links to an article or lid in our
graph. If `ask` finds no sources, check the source ID (`--source-id`) and
metadata version (`--schema v1`) against the snapshot's payload.

The bridge is copied into `apps/benchmark-service/src/` of their checkout when it
runs; add `apps/benchmark-service/src/omgkg-bridge.ts` to their
`.git/info/exclude` to keep their `git status` clean.
