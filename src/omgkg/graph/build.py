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


SPATIAL = PROTOTYPE / "tags" / "spatial_conditions_all_cases.csv"

# CSV supports one AND/OR group of atomic tests per legal branch.
TEST_EDGES = {
    "inside": ("VEREIST_BINNEN", "Gebiedstype"),
    "outside": ("VEREIST_BUITEN", "Gebiedstype"),
    "covered_by": ("GEDEKT_DOOR", "Aanwijzingstype"),
    "exceeds": ("OVERSCHRIJDT", "Risicocriterium"),
    "within_prescribed_distance": ("BINNEN_AFSTAND_VOLGENS", "Wetsverwijzing"),
}


def read_spatial_rows(path: Path) -> list[dict]:
    rows = []
    ids = set()
    with path.open(encoding="utf-8-sig", newline="") as source:
        for line, row in enumerate(csv.DictReader(source), 2):
            try:
                key = row["branch_id"]
                if not all(row[k] for k in ("branch_id", "anchor_wId", "source_wId",
                                             "subject_role", "effect", "source_text")) or key in ids:
                    raise ValueError("Missing required field or duplicate branch_id")
                test = json.loads(row["spatial_test"])
                (op,) = test.keys()
                group = op if op in ("all_of", "any_of") else "all_of"
                atoms = test[op] if op in ("all_of", "any_of") else [test]
                inherits = []
                if op == "inherits_any_branch":
                    group, inherits, atoms = "any_of", test[op], []
                    if not isinstance(inherits, list) or not inherits:
                        raise ValueError("Expected a nonempty list of inherited branch IDs")
                elif not isinstance(atoms, list) or not atoms:
                    raise ValueError("Expected one or more spatial tests")
                conditions = []
                for atom in atoms:
                    (predicate,) = atom.keys()
                    if predicate not in TEST_EDGES or not isinstance(atom[predicate], str) or not atom[predicate]:
                        raise ValueError(f"Invalid spatial test: {atom!r}")
                    conditions.append({"predicate": predicate, "target": atom[predicate]})
                props = {k: v for k, v in row.items() if v}
                for name, convert in (("value", float), ("percentile", int), ("table_row", int)):
                    if name in props:
                        props[name] = convert(props[name])
                props["condition_group"] = group
                rows.append({"props": props, "anchor": row["anchor_wId"],
                             "label": "Lid" if row["lid"] else "Artikel",
                             "tests": conditions, "inherits": inherits})
                ids.add(key)
            except (KeyError, ValueError, TypeError, AttributeError) as exc:
                raise ValueError(f"{path}, record {line}: {exc}") from exc
    if not rows:
        raise ValueError(f"Empty spatial CSV: {path}")
    for row in rows:
        if set(row["inherits"]) - ids:
            raise ValueError(f"Unresolved branch reference in {row['props']['branch_id']}")
    return rows


def write_spatial(tx, snapshot_name: str, rows: list[dict]) -> None:
    # Serialize refreshes of this import and roll back on a missing anchor.
    params = {"snapshot": snapshot_name, "rows": rows}
    tx.run("""
        MERGE (d:SpatialImport {snapshot: $snapshot})
        SET d.revision = coalesce(d.revision, 0) + 1
    """, snapshot=snapshot_name).consume()
    tx.run("""
        MATCH (d:SpatialImport {snapshot: $snapshot})-[:IMPORTED]->(b:RuimtelijkeTak)
        WHERE NOT b.branch_id IN [r IN $rows | r.props.branch_id]
        DETACH DELETE b
    """, **params).consume()
    # Refresh only relationships managed by this importer on retained branches.
    managed = ["HEEFT_NORMRIJ", "HEEFT_RUIMTELIJKE_TAK", "BEOORDEELT",
               "ERFT_VOORWAARDE_VAN", *(rel for rel, _ in TEST_EDGES.values())]
    tx.run("""
        MATCH (:SpatialImport {snapshot: $snapshot})-[:IMPORTED]->(b)-[r]-()
        WHERE type(r) IN $managed
        DELETE r
    """, snapshot=snapshot_name, managed=managed).consume()
    for label in ("Artikel", "Lid"):
        subset = [r for r in rows if r["label"] == label]
        record = tx.run(f"""
            MATCH (d:SpatialImport {{snapshot: $snapshot}})
            UNWIND $rows AS r
            MATCH (a:{label} {{wId: r.anchor}})
            MERGE (b:RuimtelijkeTak {{snapshot: $snapshot, branch_id: r.props.branch_id}})
            SET b = r.props, b.snapshot = $snapshot
            MERGE (d)-[:IMPORTED]->(b)
            REMOVE b:Normrij
            FOREACH (_ IN CASE WHEN r.props.table IS NULL THEN [] ELSE [1] END |
                SET b:Normrij MERGE (a)-[:HEEFT_NORMRIJ]->(b))
            FOREACH (_ IN CASE WHEN r.props.table IS NULL THEN [1] ELSE [] END |
                MERGE (a)-[:HEEFT_RUIMTELIJKE_TAK]->(b))
            MERGE (role:Objectrol {{naam: r.props.subject_role}})
            MERGE (b)-[:BEOORDEELT]->(role)
            RETURN count(*) AS written
        """, snapshot=snapshot_name, rows=subset).single(strict=True)
        if record["written"] != len(subset):
            raise ValueError(f"Spatial CSV does not match the loaded {label} anchors")
    for predicate, (relation, label) in TEST_EDGES.items():
        tx.run(f"""
            UNWIND $rows AS r
            MATCH (b:RuimtelijkeTak {{snapshot: $snapshot, branch_id: r.props.branch_id}})
            UNWIND r.tests AS t
            WITH b, t WHERE t.predicate = $predicate
            MERGE (target:{label} {{naam: t.target}})
            MERGE (b)-[:{relation}]->(target)
        """, predicate=predicate, **params).consume()
    tx.run("""
        UNWIND $rows AS r
        MATCH (b:RuimtelijkeTak {snapshot: $snapshot, branch_id: r.props.branch_id})
        UNWIND r.inherits AS inherited
        MATCH (parent:RuimtelijkeTak {snapshot: $snapshot, branch_id: inherited})
        MERGE (b)-[:ERFT_VOORWAARDE_VAN]->(parent)
    """, **params).consume()

def build_graph(driver: Driver, snapshot: Path = SNAPSHOT, *,
                spatial_csv: Path | None = None) -> dict[str, int]:
    snapshot = Path(snapshot)
    if spatial_csv is None and snapshot.resolve() == SNAPSHOT.resolve():
        spatial_csv = SPATIAL
    branches = read_spatial_rows(spatial_csv) if spatial_csv is not None else []

    spec = importlib.util.spec_from_file_location(
        "build_graph", PROTOTYPE / "scripts" / "build_graph.py"
    )
    if spec is None or spec.loader is None:
        raise ImportError("prototype/scripts/build_graph.py not found")
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    loader.load(driver, str(snapshot), str(BOUNDARY))

    tags = [
        {**vars(t), "overrides": [vars(o) for o in t.overrides]}
        for t in read_tags(TAGS)
    ]
    driver.execute_query(WRITE_TAGS, rows=tags)
    for statement in cypher_statements(DERIVE):
        driver.execute_query(statement)

    if branches:
        driver.execute_query(
            "CREATE CONSTRAINT IF NOT EXISTS FOR (d:SpatialImport) "
            "REQUIRE d.snapshot IS UNIQUE"
        )
        with driver.session() as session:
            session.execute_write(write_spatial, snapshot.name, branches)

    records, _, _ = driver.execute_query(
        "RETURN COUNT { (:Artikel) } AS articles, "
        "COUNT { ()-[:OVERRIDES]->() } AS overrides, "
        "COUNT { ()-[:VERWIJST_NAAR]->() } AS references, "
        "COUNT { (:SpatialImport {snapshot: $snapshot})-[:IMPORTED]->() } "
        "AS spatial_branches",
        snapshot=snapshot.name,
    )
    return dict(records[0])

