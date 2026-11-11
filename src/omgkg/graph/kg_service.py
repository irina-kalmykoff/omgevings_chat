"""``omgkg serve-kg``: our graph in OmgevingsChat's KG slot, with no code changes.

OmgevingsChat calls its knowledge graph between candidate retrieval and the
Cohere rerank (``KnowledgeGraphService.enrich`` in their ``packages/retrieval``).
The production client (``apps/web/src/lib/retrieval/ydigital-kg.ts``) POSTs

    {"query": ..., "background_documents": [{"id", "content", "meta": {
        "documentComponentId": <STOP wId>, ...}}, ...], ...}

with an ``X-API-Key`` header to ``YDIGITAL_KG_API_URL`` and reads
``{"answer": [{"id", "content"?, "title"?, ...}]}``. An answer whose ``id`` is a
candidate's skips the rerank and goes to the LLM (bypass, max 5); one with a new
``id`` and ``content`` is added as a graph-only source (max 3). So pointing
``YDIGITAL_KG_API_URL`` at ``http://<host>:8765/api/query`` and setting
``YDIGITAL_KG_API_KEY`` to our key puts this graph into their pipeline.
"""

import hmac
import json
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from omgkg.graph.knowledge_graph import KnowledgeGraph, Link

MAX_BODY_BYTES = 10_000_000
PHRASE = {
    "overridden_by": "maakt een {kind} op",
    "overrides": "is de regel waarop een {kind} wordt gemaakt door",
    "refers_to": "waarnaar wordt verwezen door",
}


def _title(link: Link, kg: KnowledgeGraph) -> str:
    target = kg.component(link.target)
    if link.relation == "explains":
        return (
            f"{target.heading} (kennisgraaf: het artikel bij een gevonden toelichting)"
        )
    source = kg.article_of(link.source)
    source_heading = kg.component(source).heading if source else link.source
    kind = "uitzondering" if link.override_type == "exception" else "inperking"
    relation = PHRASE[link.relation].format(kind=kind)
    return f"{target.heading} (kennisgraaf: {relation} {source_heading})"


def respond(body: Mapping[str, Any], kg: KnowledgeGraph) -> dict[str, Any]:
    """The KG answer for one request; unknown or malformed documents are skipped."""
    candidate: dict[str, str] = {}  # wId -> the first candidate id carrying it
    for doc in body.get("background_documents") or []:
        meta = doc.get("meta") if isinstance(doc, dict) else None
        wid = meta.get("documentComponentId") if isinstance(meta, dict) else None
        if isinstance(wid, str) and wid and isinstance(doc.get("id"), str):
            candidate.setdefault(wid, doc["id"])
    wids = list(candidate)
    if not wids:
        return {"answer": []}
    force = kg.force_bearing(wids)
    promoted = [{"id": candidate[w]} for w in wids if w in force]
    added = []
    for link in kg.related(wids):
        component = kg.component(link.target)
        added.append(
            {
                "id": f"omgkg:{link.target}",
                "content": component.text,
                "title": _title(link, kg),
                "identifier": component.provenance.document_id,
                "componentId": link.target,
                "componentTitle": component.provenance.structural_path,
            }
        )
    return {"answer": promoted + added}


def serve(kg: KnowledgeGraph, api_key: str, host: str, port: int) -> None:
    if not api_key:
        raise ValueError("OMGKG_KG_API_KEY must be set: their client sends a key")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/health":
                self._send(200, {"status": "ok"})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self) -> None:
            if self.path != "/api/query":
                return self._send(404, {"error": "not found"})
            given = self.headers.get("X-API-Key", "")
            if not hmac.compare_digest(given.encode(), api_key.encode()):
                return self._send(401, {"error": "invalid API key"})
            length_header = self.headers.get("Content-Length") or "0"
            length = int(length_header) if length_header.isdigit() else 0
            if not 0 < length <= MAX_BODY_BYTES:
                return self._send(413, {"error": "body missing or too large"})
            try:
                body = json.loads(self.rfile.read(length))
            except ValueError:
                return self._send(400, {"error": "body is not JSON"})
            if not isinstance(body, dict):
                return self._send(400, {"error": "body must be a JSON object"})
            self._send(200, respond(body, kg))

        def _send(self, status: int, payload: Mapping[str, Any]) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"KG endpoint on http://{host}:{port}/api/query (health: /health)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
