/**
 * omgkg bridge: runs OmgevingsChat's own retrieval for one question and prints
 * the selected sources as JSON (contract: src/omgkg/retrieval/omgevingschat.py).
 *
 * Kept in the knowledge-graph repo and copied into
 * omgevingschat-platform/apps/benchmark-service/src/ before it runs, so its
 * imports resolve against their workspace. Their code is not modified.
 *
 * Source-bound scope: retrieval is pinned to one document (the Maastricht
 * omgevingsplan), so no location lookups, no DSO/RP/BAG API calls and no
 * knowledge graph. The wiring mirrors apps/benchmark-service (retrieval.ts,
 * production-runtime.ts): production retrieval config, OpenAI embeddings,
 * Cohere rerank-v3.5, structural expansion.
 */
import { createCohere } from "@ai-sdk/cohere";
import { createOpenAI } from "@ai-sdk/openai";
import {
  createEvidenceCandidate,
  mergeProtectedRecallEvidenceCandidates,
} from "@omgevingschat/chat-runtime";
import {
  CandidateMappingService,
  CandidateSearchRetriever,
  CandidateSearchServiceLayer,
  DsoRpAnnotationService,
  KnowledgeGraphService,
  RetrievalConfig,
  RetrievalError,
  RetrievalProgram,
  RetrievalRerankServiceLayer,
  Reranker,
  StructuralExpansionScroller,
  StructuralExpansionServiceLayer,
  attachPostSelectionStructuralContext,
  buildRerankDocumentText,
  denseRetrieveV1,
  hybridRetrieve,
  mapQdrantPointToRetrievedChunk,
  mapStructuralExpansionScrollPoint,
  productionRetrievalConfig,
  runRetrieval,
  type RetrievalEvidenceCandidate,
  type RetrievalQuery,
  type RetrievalScope,
  type RetrievedChunk,
  type RetrievedSource,
} from "@omgevingschat/retrieval";
import { QdrantClient } from "@qdrant/js-client-rest";
import { embed, rerank } from "ai";
import { Cause, Effect, Layer } from "effect";

// Their code may log to stdout; keep stdout for the JSON contract only.
const writeStdout = process.stdout.write.bind(process.stdout);
process.stdout.write = process.stderr.write.bind(
  process.stderr
) as typeof process.stdout.write;
console.log = console.info = console.debug = console.error;

if (process.env.OMGKG_ENV_FILE) process.loadEnvFile(process.env.OMGKG_ENV_FILE);

const required = (name: string): string => {
  const value = process.env[name];
  if (!value) throw new Error(`missing environment variable ${name}`);
  return value;
};

const collection = required("OMGKG_QDRANT_COLLECTION");
const sourceId = required("OMGKG_SOURCE_ID");
const schemaVersion = process.env.OMGKG_METADATA_SCHEMA === "v1" ? "v1" : "v2";

const openai = createOpenAI({ apiKey: required("OPENAI_API_KEY") });
const cohere = createCohere({ apiKey: required("COHERE_API_KEY") });
const qdrant = new QdrantClient({
  url: required("QDRANT_URL"),
  apiKey: process.env.QDRANT_API_KEY,
});
const embeddingModel = openai.embedding(
  process.env.OPENAI_EMBEDDING_MODEL ?? "text-embedding-3-large"
);

const embedQuery = async (value: string) =>
  (await embed({ model: embeddingModel, value, maxRetries: 0 })).embedding;

const unknownError = (cause: unknown) => new Cause.UnknownError(cause);

const firstString = (...values: readonly unknown[]): string | undefined =>
  values.find(
    (value): value is string => typeof value === "string" && value.trim() !== ""
  );

// A lean copy of benchmark-service chunkToSource, for the fields our contract
// reads. Source-bound scope only returns the one DSO document.
const chunkToSource = (chunk: RetrievedChunk, order: number): RetrievedSource => {
  const m = chunk.metadata;
  const identifier = firstString(m.source_id, m.reg_id);
  const componentId = firstString(m.component_id, m.doc_componentId, m.doc_artikelId);
  const kop = firstString(m.component_title, m.doc_componentKop, m.doc_titel);
  const url = firstString(m.component_url, m.source_url, m.doc_url, m.reg_url);
  return {
    type: "DSO",
    id: chunk.id,
    ...(identifier ? { identifier } : {}),
    title: firstString(m.source_title, m.reg_title) ?? "",
    text: chunk.text,
    score: chunk.score,
    order,
    citationId: `dso-${chunk.id}`,
    ...(url ? { url } : {}),
    ...(kop ? { documentKop: kop } : {}),
    ...(componentId ? { documentComponentId: componentId } : {}),
  };
};

const toCandidates = (
  query: RetrievalQuery,
  chunks: readonly Readonly<{ chunk: RetrievedChunk; reason?: string }>[],
  stage: "reranked" | "protected_recall"
): RetrievalEvidenceCandidate[] =>
  chunks.map(({ chunk, reason }, index) =>
    createEvidenceCandidate({
      source: chunkToSource(chunk, index + 1),
      chunk,
      query: query.query,
      evidenceGoal: query.evidenceGoal,
      evidenceNeed: query.evidenceNeed,
      retrievalStage: stage,
      ...(reason ? { retrievalReason: reason } : {}),
    })
  );

const mapDsoRp: (typeof CandidateMappingService.Service)["mapDsoRp"] = ({
  query,
  reranked,
  kgBypassChunks,
  protectedRecall,
  includeProtectedRecallCandidates,
}) =>
  Effect.try({
    try: () => {
      const selected = toCandidates(
        query,
        [...kgBypassChunks, ...reranked].map((chunk) => ({ chunk })),
        "reranked"
      );
      const evidenceCandidates = includeProtectedRecallCandidates
        ? mergeProtectedRecallEvidenceCandidates({
            selectedCandidates: selected,
            protectedRecallCandidates: toCandidates(
              query,
              protectedRecall,
              "protected_recall"
            ),
          })
        : selected;
      return {
        evidenceCandidates,
        mappedCandidates: evidenceCandidates.map((candidate) => ({
          source: candidate.source,
          ...(candidate.chunk ? { chunk: candidate.chunk } : {}),
          stage:
            candidate.retrievalStage === "protected_recall"
              ? ("protected_recall" as const)
              : ("reranked" as const),
          ...(candidate.retrievalReason ? { reason: candidate.retrievalReason } : {}),
        })),
        sourceCount: evidenceCandidates.length,
      };
    },
    catch: (cause) =>
      RetrievalError.fromUnknown("mapping", cause, "Failed to map omgkg candidates"),
  });

const config = Layer.succeed(RetrievalConfig, productionRetrievalConfig);

const search = CandidateSearchServiceLayer.pipe(
  Layer.provide(
    Layer.merge(
      config,
      Layer.succeed(CandidateSearchRetriever, {
        hybrid: (request) =>
          Effect.tryPromise({
            try: () =>
              hybridRetrieve(request, {
                getEmbeddings: () => ({ embedQuery }),
                getQdrantClient: async () => qdrant,
                getDataSourceForCollection: async (collectionName) => ({
                  search: async (query, options) => {
                    if (!collectionName) return [];
                    const result = await qdrant.query(collectionName, {
                      query: await embedQuery(query),
                      limit: options?.topK ?? 10,
                      filter: options?.filter,
                      with_payload: true,
                    });
                    return result.points.map(mapQdrantPointToRetrievedChunk);
                  },
                }),
              }),
            catch: unknownError,
          }),
        denseV1: (request) =>
          Effect.tryPromise({
            try: () =>
              denseRetrieveV1(request, {
                embedQuery,
                query: async (collectionName, query) => ({
                  points: (await qdrant.query(collectionName, query)).points,
                }),
              }),
            catch: unknownError,
          }),
      })
    )
  )
);

const rerankLayer = RetrievalRerankServiceLayer.pipe(
  Layer.provide(
    Layer.merge(
      config,
      Layer.succeed(Reranker, {
        rerank: ({ candidates, query, topN }) =>
          Effect.tryPromise({
            try: async () => {
              if (candidates.length <= topN) {
                return candidates.map((chunk) => ({ chunk, relevanceScore: 1 }));
              }
              const result = await rerank({
                model: cohere.reranking("rerank-v3.5"),
                documents: candidates.map((chunk, index) => ({
                  index,
                  text: buildRerankDocumentText(chunk),
                })),
                query,
                topN,
                maxRetries: 0,
              });
              return result.ranking.flatMap(({ document, score }) => {
                const chunk = candidates[document.index];
                return chunk ? [{ chunk, relevanceScore: score }] : [];
              });
            },
            catch: unknownError,
          }),
      })
    )
  )
);

const structuralExpansion = StructuralExpansionServiceLayer.pipe(
  Layer.provide(
    Layer.merge(
      config,
      Layer.succeed(StructuralExpansionScroller, {
        scroll: ({ collectionName, filter, limit }) =>
          Effect.tryPromise({
            try: async () =>
              (
                await qdrant.scroll(collectionName, {
                  filter,
                  limit,
                  with_payload: true,
                  with_vector: false,
                })
              ).points.map(mapStructuralExpansionScrollPoint),
            catch: unknownError,
          }),
      })
    )
  )
);

const layer = Layer.mergeAll(
  config,
  search,
  rerankLayer,
  structuralExpansion,
  // Source-bound scope never resolves location annotations.
  Layer.succeed(DsoRpAnnotationService, {
    resolve: () =>
      Effect.fail(
        new RetrievalError({
          stage: "annotations",
          message: "omgkg bridge runs source-bound only",
        })
      ),
  }),
  // Configuration A has no knowledge graph: candidates pass through unchanged.
  Layer.succeed(KnowledgeGraphService, {
    enrich: ({ candidates }) =>
      Effect.succeed({
        bypassChunks: [],
        cohereCandidates: [...candidates],
        kgOnlyDocuments: [],
      }),
  }),
  Layer.succeed(CandidateMappingService, {
    mapDsoRp,
    mapCustom: () =>
      Effect.succeed({ evidenceCandidates: [], sourceCount: 0 }),
  })
);

const scope: RetrievalScope = {
  mode: "source",
  organization: { id: "omgkg", collectionTitle: collection, topK: null },
  dsoRpSources: [{ identifier: sourceId, type: "DSO", annotationsUrl: null }],
  customFileSourceIdentifiers: [],
  heritageStatus: null,
  metadataSchemaVersion: schemaVersion,
  knowledgeGraphEnabled: false,
  kgConversationHistory: [],
};

const readStdin = async (): Promise<string> => {
  const chunks: Buffer[] = [];
  for await (const chunk of process.stdin) chunks.push(chunk as Buffer);
  return Buffer.concat(chunks).toString("utf8");
};

const main = async () => {
  const { query } = JSON.parse(await readStdin()) as { query: string };
  const startedAt = performance.now();
  const result = await runRetrieval({
    scope,
    queries: [{ query }],
    options: { includeProtectedRecallCandidates: true },
    combineStrategy: "rrf",
    retrieveOne: (retrievalScope, retrievalQuery, options) =>
      Effect.runPromise(
        RetrievalProgram(retrievalScope, retrievalQuery, options).pipe(
          Effect.provide(layer)
        )
      ),
    attachStructuralContext: (input) =>
      Effect.runPromise(
        attachPostSelectionStructuralContext(input).pipe(Effect.provide(layer))
      ),
  });
  const latencyMs = performance.now() - startedAt;
  const sources = [...result.selected, ...result.structuralContext.buildingChain].map(
    (candidate, index) => ({
      ...candidate.source,
      order: index + 1,
      retrievalStage: candidate.retrievalStage,
    })
  );
  writeStdout(JSON.stringify({ latencyMs, sources }));
};

main().catch((error: unknown) => {
  console.error(error instanceof Error ? (error.stack ?? error.message) : error);
  process.exit(1);
});
