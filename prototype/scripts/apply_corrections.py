"""Apply the ontology correction layer on top of the tagged graph.

The correction file (tags/corrections_v1_<date>.csv) holds hand-checked
OVERRIDES edges in the v1 vocabulary: operation, override type, derived effect,
mechanism, temporal flag and baseline. For every source article in the file, its
outgoing OVERRIDES are replaced by the corrected set; all other articles keep
their gpt-4o edges. Corrected edges carry override_source = 'manual:ontology-v1',
so they stay separable from the model output and can be counted or removed.

Run after the tags are written and after cypher/derive_overrides.cypher, which
skips manual edges, so their effects are not overwritten.

Usage (from prototype/):
    python scripts/apply_corrections.py --dry-run
    python scripts/apply_corrections.py
"""
import argparse
import csv
from collections import defaultdict

from neo4j import GraphDatabase

SOURCE = "manual:ontology-v1"
DEFAULT_FILE = "tags/corrections_v1_2026-11-11.csv"

REPLACE = """
MATCH (a:Artikel {nummer: $source})
OPTIONAL MATCH (a)-[old:OVERRIDES]->()
DELETE old
WITH DISTINCT a
UNWIND $rows AS row
MATCH (t:Artikel {nummer: row.target})
MERGE (a)-[o:OVERRIDES]->(t)
SET o.operation = row.operation,
    o.override_type = row.override_type,
    o.derived_effect = row.derived_effect,
    o.target_deontic = t.deontic,
    o.mechanism = row.mechanism,
    o.temporal = row.temporal,
    o.baseline = row.baseline,
    o.note = row.note,
    o.override_source = $label
RETURN count(o) AS written
"""

EXISTING = "MATCH (a:Artikel) WHERE a.nummer IN $numbers RETURN a.nummer AS nummer"


def load(path):
    """Read the correction file grouped by source article.

    Args:
        path: CSV with columns source, target, operation, override_type,
            derived_effect, mechanism, temporal, baseline, note.

    Returns:
        Dict source nummer -> list of row dicts, with empty strings as None
        and temporal as a boolean.
    """
    by_source = defaultdict(list)
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            clean = {k: (v.strip() or None) for k, v in row.items()}
            clean["temporal"] = clean["temporal"] == "true"
            by_source[clean.pop("source")].append(clean)
    return by_source


def main():
    parser = argparse.ArgumentParser(description="Apply the ontology correction layer")
    parser.add_argument("--file", default=DEFAULT_FILE)
    parser.add_argument("--dry-run", action="store_true", help="show the plan, write nothing")
    parser.add_argument("--uri", default="bolt://localhost:7687")
    parser.add_argument("--user", default="neo4j")
    parser.add_argument("--password", default="testpassword")
    args = parser.parse_args()

    by_source = load(args.file)
    n_rows = sum(len(r) for r in by_source.values())
    print(f"{args.file}: {n_rows} edges for {len(by_source)} source articles")
    for source, rows in by_source.items():
        print(f"  {source:7} -> " + ", ".join(f"{r['target']}:{r['operation']}:{r['derived_effect'] or '-'}" for r in rows))
    if args.dry_run:
        return

    driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password))
    try:
        with driver.session() as session:
            numbers = sorted(set(by_source) | {r["target"] for rows in by_source.values() for r in rows})
            found = {r["nummer"] for r in session.run(EXISTING, numbers=numbers)}
            missing = sorted(set(numbers) - found)
            if missing:
                raise SystemExit(f"articles not in the graph: {', '.join(missing)}")
            written = 0
            for source, rows in by_source.items():
                written += session.run(REPLACE, source=source, rows=rows, label=SOURCE).single()["written"]
        print(f"written: {written} OVERRIDES edges with override_source = {SOURCE!r}")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
