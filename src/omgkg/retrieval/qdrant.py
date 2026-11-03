"""The local Qdrant that holds the OmgevingsChat index (the RAG step's data).

``import_snapshot`` backs ``omgkg import-snapshot``: Qdrant restores an uploaded
snapshot into the named collection, replacing it if it exists. The file is
streamed, so multi-GB snapshots do not load into memory.
"""

import http.client
import json
import uuid
from pathlib import Path
from urllib.parse import quote, urlsplit

CHUNK = 1 << 20


def _connection(qdrant_url: str) -> tuple[http.client.HTTPConnection, str]:
    url = urlsplit(qdrant_url)
    if url.scheme not in {"http", "https"} or not url.hostname:
        raise ValueError(f"Not an http(s) Qdrant URL: {qdrant_url!r}")
    cls = (
        http.client.HTTPSConnection
        if url.scheme == "https"
        else http.client.HTTPConnection
    )
    return cls(url.hostname, url.port), url.path.rstrip("/")


def _headers(api_key: str | None) -> dict[str, str]:
    return {"api-key": api_key} if api_key else {}


def import_snapshot(
    snapshot: Path, collection: str, qdrant_url: str, api_key: str | None = None
) -> int:
    """Restore ``snapshot`` as ``collection``; returns its number of points."""
    boundary = uuid.uuid4().hex
    filename = snapshot.name.replace('"', "")
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="snapshot"; filename="{filename}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()

    connection, base = _connection(qdrant_url)
    name = quote(collection, safe="")
    connection.putrequest(
        "POST",
        f"{base}/collections/{name}/snapshots/upload?priority=snapshot&wait=true",
    )
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(head) + snapshot.stat().st_size + len(tail)),
        **_headers(api_key),
    }
    for key, value in headers.items():
        connection.putheader(key, value)
    connection.endheaders()
    connection.send(head)
    with snapshot.open("rb") as f:
        while chunk := f.read(CHUNK):
            connection.send(chunk)
    connection.send(tail)
    response = connection.getresponse()
    body = response.read()
    connection.close()
    if response.status != 200:
        raise RuntimeError(
            f"Qdrant refused the snapshot (HTTP {response.status}): {body[:500]!r}"
        )
    return points(collection, qdrant_url, api_key)


def points(collection: str, qdrant_url: str, api_key: str | None = None) -> int:
    connection, base = _connection(qdrant_url)
    connection.request(
        "GET",
        f"{base}/collections/{quote(collection, safe='')}",
        headers=_headers(api_key),
    )
    response = connection.getresponse()
    body = response.read()
    connection.close()
    if response.status != 200:
        raise RuntimeError(
            f"Collection {collection!r} not found (HTTP {response.status})"
        )
    return int(json.loads(body)["result"]["points_count"])


def collection_wids(
    collection: str, qdrant_url: str, api_key: str | None = None
) -> set[str]:
    """The STOP wIds their index carries (``component_id`` in the payload)."""
    wids: set[str] = set()
    offset: object = None
    while True:
        request: dict[str, object] = {"limit": 256, "with_payload": True}
        if offset is not None:
            request["offset"] = offset
        connection, base = _connection(qdrant_url)
        connection.request(
            "POST",
            f"{base}/collections/{quote(collection, safe='')}/points/scroll",
            body=json.dumps(request),
            headers={"Content-Type": "application/json", **_headers(api_key)},
        )
        response = connection.getresponse()
        body = response.read()
        connection.close()
        if response.status != 200:
            raise RuntimeError(
                f"Scrolling {collection!r} failed (HTTP {response.status})"
            )
        result = json.loads(body)["result"]
        for point in result["points"]:
            payload = point.get("payload") or {}
            meta = payload.get("metadata") or payload
            wid = meta.get("component_id") or meta.get("doc_componentId")
            if isinstance(wid, str) and wid:
                wids.add(wid)
        offset = result.get("next_page_offset")
        if offset is None:
            return wids
