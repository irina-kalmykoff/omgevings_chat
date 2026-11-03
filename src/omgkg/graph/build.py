"""``omgkg build-graph``: the knowledge graph from the committed DSO snapshot.

Three idempotent steps, no LLM calls:

1. structure, rule texts, activities, locations and cross-references
   (``prototype/scripts/build_graph.py``, loaded as-is);
2. the team's saved gpt-4o tags: deontic force per article and the OVERRIDES
   edges (``prototype/tags/gpt4o_2026-11-01.csv``), with the same write semantics
   as ``deontic_extract.py --write``;
3. each OVERRIDES edge's net effect (``prototype/cypher/derive_overrides.cypher``).
"""

import csv
import importlib.util
from dataclasses import dataclass, field
from pathlib import Path

from neo4j import Driver

ROOT = Path(__file__).parents[3]
PROTOTYPE = ROOT / "prototype"
SNAPSHOT = ROOT / "source_data" / "Maastricht-DSO-production-2026-10-02"
BOUNDARY = ROOT / "source_data" / "Maastricht-boundary-RD.geojson"
TAGS = PROTOTYPE / "tags" / "gpt4o_2026-11-01.csv"
DERIVE = PROTOTYPE / "cypher" / "derive_overrides.cypher"

# deontic_extract.write_back, for one article: its old outgoing OVERRIDES are
# replaced, so the result does not depend on what the database held before.
WRITE_TAGS = """
UNWIND $rows AS row
MATCH (a:Artikel {nummer: row.nummer})
SET a.statement_type = row.statement_type, a.deontic = row.deontic,
    a.deontic_source = row.source, a.deontic_rationale = row.rationale
WITH a, row
OPTIONAL MATCH (a)-[old:OVERRIDES]->()
DELETE old
WITH DISTINCT a, row
UNWIND row.overrides AS ov
MATCH (t:Artikel {nummer: ov.target})
MERGE (a)-[o:OVERRIDES]->(t)
SET o.override_type = ov.type, o.override_source = row.source
"""


@dataclass(frozen=True)
class Override:
    target: str
    type: str


@dataclass(frozen=True)
class Tags:
    nummer: str
    statement_type: str
    deontic: str | None
    rationale: str
    source: str
    overrides: list[Override] = field(default_factory=list)


def read_tags(path: Path) -> list[Tags]:
    """One row per article; ``overrides`` is ``"22.27:restriction; 22.36:..."``."""
    with path.open(encoding="utf-8", newline="") as f:
        return [
            Tags(
                nummer=row["nummer"],
                statement_type=row["statement_type"],
                deontic=row["deontic"] or None,
                rationale=row["rationale"],
                source=row["source"],
                overrides=[
                    Override(*part.strip().split(":", 1))
                    for part in row["overrides"].split(";")
                    if part.strip()
                ],
            )
            for row in csv.DictReader(f)
        ]


def cypher_statements(path: Path) -> list[str]:
    """Statements of a cypher-shell script; ``//`` lines are comments.

    ponytail: splits on ``;``, enough for the committed scripts (no ``;`` in a
    string, no trailing comments); a script needing more should go through
    cypher-shell.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    code = "\n".join(line for line in lines if not line.lstrip().startswith("//"))
    return [part.strip() for part in code.split(";") if part.strip()]


def build_graph(driver: Driver, snapshot: Path = SNAPSHOT) -> dict[str, int]:
    spec = importlib.util.spec_from_file_location(
        "build_graph", PROTOTYPE / "scripts" / "build_graph.py"
    )
    if spec is None or spec.loader is None:
        raise ImportError("prototype/scripts/build_graph.py not found")
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    loader.load(driver, str(snapshot), str(BOUNDARY))

    rows = [
        {**vars(t), "overrides": [vars(o) for o in t.overrides]}
        for t in read_tags(TAGS)
    ]
    driver.execute_query(WRITE_TAGS, rows=rows)
    for statement in cypher_statements(DERIVE):
        driver.execute_query(statement)

    records, _, _ = driver.execute_query(
        "MATCH (a:Artikel) WITH count(a) AS articles "
        "MATCH ()-[o:OVERRIDES]->() WITH articles, count(o) AS overrides "
        "MATCH ()-[r:VERWIJST_NAAR]->() "
        "RETURN articles, overrides, count(r) AS references"
    )
    return dict(records[0])
