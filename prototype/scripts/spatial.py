"""Point-in-polygon lookup against the Maastricht boundary, then rules from Neo4j.

The municipal boundary (RD / EPSG:28992) is the only geometry in the current
delivery package, so this answers the coarse question: does the Maastricht
omgevingsplan apply at a given RD point, and if so which rules. Per-zone rule
selection needs the per-rule GIO geometries, which are not yet delivered.

Neo4j Community has no polygon point-in-polygon test, so the geometric gate runs
here in Python; the rule lookup runs in Neo4j.

Usage:
    python spatial.py 177088 318726
"""

import argparse
import json
from pathlib import Path

from neo4j import GraphDatabase


def load_boundary(path):
    """Load the outer ring of the boundary polygon from a GeoJSON geometry file."""
    geo = json.loads(Path(path).read_text(encoding="utf-8"))
    return geo["coordinates"][0]


def point_in_ring(x, y, ring):
    """Ray-casting point-in-polygon test for a single ring.

    Args:
        x: Point x coordinate (RD).
        y: Point y coordinate (RD).
        ring: List of [x, y] vertices.

    Returns:
        True if the point lies inside the ring.
    """
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def rules_at_point(driver, ring, x, y, limit=25):
    """Return rules that apply at an RD point, or None if outside the boundary.

    Args:
        driver: An open neo4j driver.
        ring: The boundary outer ring from load_boundary.
        x: RD x coordinate.
        y: RD y coordinate.
        limit: Maximum rules to return.

    Returns:
        A list of (nummer, opschrift) tuples, or None when the point is outside
        the municipality.
    """
    if not point_in_ring(x, y, ring):
        return None
    query = """
        MATCH (loc:Locatie)<-[:OP_LOCATIE]-(:RegelVoorIedereen)
              -[:VAN_REGELTEKST]->(:Regeltekst)-[:IS_TEKST_VAN]->(art:Artikel)
        WHERE loc.id CONTAINS 'ambtsgebied'
        RETURN DISTINCT art.nummer AS nummer, art.opschrift AS opschrift
        ORDER BY nummer
        LIMIT $limit
    """
    with driver.session() as session:
        return [(r["nummer"], r["opschrift"]) for r in session.run(query, limit=limit)]


def main():
    parser = argparse.ArgumentParser(description="Which rules apply at an RD point?")
    parser.add_argument("x", type=float, help="RD x coordinate")
    parser.add_argument("y", type=float, help="RD y coordinate")
    parser.add_argument("--boundary", default="../source_data/Maastricht-boundary-RD.geojson")
    parser.add_argument("--uri", default="bolt://localhost:7687")
    parser.add_argument("--user", default="neo4j")
    parser.add_argument("--password", default="testpassword")
    args = parser.parse_args()

    ring = load_boundary(args.boundary)
    driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password))
    try:
        rules = rules_at_point(driver, ring, args.x, args.y)
    finally:
        driver.close()

    if rules is None:
        print(f"point ({args.x}, {args.y}) is outside the Maastricht omgevingsplan")
    else:
        print(f"point ({args.x}, {args.y}) is inside Maastricht; {len(rules)} rules apply (showing up to 25):")
        for nummer, opschrift in rules:
            print(f"  {nummer}: {opschrift}")


if __name__ == "__main__":
    main()
