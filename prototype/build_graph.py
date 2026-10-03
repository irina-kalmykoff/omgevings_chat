"""Load a STOP/TPOD omgevingsplan delivery package into Neo4j.

Parses the Maastricht aanleverpakket (the `Regeling/Tekst.xml` body plus the
`OW-bestanden/*.xml` object files) into a labelled property graph and loads it
into a running Neo4j instance.

Graph model:
    (Regeling)-[:BEVAT]->(Hoofdstuk|Afdeling|Paragraaf|Subparagraaf)
        -[:BEVAT]->(Artikel)-[:BEVAT]->(Lid)
    (Regeltekst)-[:IS_TEKST_VAN]->(Artikel|Lid)        joined on wId
    (RegelVoorIedereen)-[:VAN_REGELTEKST]->(Regeltekst)
    (RegelVoorIedereen)-[:GELDT_VOOR]->(Activiteit)
    (RegelVoorIedereen)-[:OP_LOCATIE]->(Locatie)
    (Activiteit)-[:VALT_ONDER]->(Activiteit)
    (Artikel|Lid)-[:VERWIJST_NAAR]->(Artikel|Lid|Component)   from IntRef

Usage:
    pip install neo4j lxml
    python build_graph.py --package "/path/to/Maastricht-DSO-production-2026-10-02"
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

from lxml import etree
from neo4j import GraphDatabase

NS = {
    "tekst": "https://standaarden.overheid.nl/stop/imop/tekst/",
    "regels": "http://www.geostandaarden.nl/imow/regels",
    "rol": "http://www.geostandaarden.nl/imow/regelsoplocatie",
    "l": "http://www.geostandaarden.nl/imow/locatie",
    "xlink": "http://www.w3.org/1999/xlink",
}
STRUCT = {f"{{{NS['tekst']}}}{t}": t for t in
          ("Hoofdstuk", "Afdeling", "Paragraaf", "Subparagraaf", "Artikel", "Lid")}
# the OW files carry a malformed xmlns:schemaLocation, so parse them in recover mode
RECOVER = etree.XMLParser(recover=True, huge_tree=True)


def _q(ns_key, tag):
    """Build a Clark-notation qualified tag name."""
    return f"{{{NS[ns_key]}}}{tag}"


def _nearest_structural_wid(el):
    """Return the wId of the nearest ancestor that is a structural element."""
    parent = el.getparent()
    while parent is not None:
        if parent.tag in STRUCT:
            return parent.get("wId")
        parent = parent.getparent()
    return None


def parse_text(tekst_path):
    """Parse Regeling/Tekst.xml into structure nodes and cross-reference edges.

    Args:
        tekst_path: Path to the regulation body XML.

    Returns:
        A tuple (nodes, bevat, verwijst, eid_to_wid) where nodes maps wId to a
        node dict, bevat is a list of (parent_wId, child_wId), verwijst is a
        list of (source_wId, target_eId), and eid_to_wid resolves IntRef targets.
    """
    root = etree.parse(str(tekst_path)).getroot()
    eid_to_wid = {e.get("eId"): e.get("wId")
                  for e in root.iter() if e.get("eId") and e.get("wId")}

    nodes, bevat, verwijst = {}, [], []
    for el in root.iter():
        if el.tag not in STRUCT:
            continue
        wid = el.get("wId")
        nummer = (el.findtext(f"{_q('tekst','Kop')}/{_q('tekst','Nummer')}") or "").strip()
        opschrift = (el.findtext(f"{_q('tekst','Kop')}/{_q('tekst','Opschrift')}") or "").strip()
        node = {"wId": wid, "eId": el.get("eId"), "label": STRUCT[el.tag],
                "nummer": nummer, "opschrift": opschrift}
        if STRUCT[el.tag] in ("Artikel", "Lid"):
            node["tekst"] = " ".join(
                "".join(al.itertext()).strip()
                for al in el.findall(f"{_q('tekst','Inhoud')}/{_q('tekst','Al')}")
            )
        nodes[wid] = node
        parent = _nearest_structural_wid(el)
        if parent:
            bevat.append((parent, wid))

    for ref in root.iter(_q("tekst", "IntRef")):
        src = _nearest_structural_wid(ref)
        target = ref.get("ref")
        if src and target:
            verwijst.append((src, target))

    return nodes, bevat, verwijst, eid_to_wid


def parse_regelteksten(path):
    """Return a list of (identificatie, wId) for every Regeltekst object."""
    tree = etree.parse(str(path), RECOVER)
    rows = []
    for rt in tree.iter(_q("regels", "Regeltekst")):
        rows.append((rt.findtext(_q("regels", "identificatie")), rt.get("wId")))
    return rows


def parse_activiteiten(path):
    """Return (nodes, hierarchy) for activities.

    nodes maps identificatie to {naam, groep}; hierarchy is a list of
    (child_id, parent_id) VALT_ONDER edges.
    """
    tree = etree.parse(str(path), RECOVER)
    nodes, hierarchy = {}, []
    for act in tree.iter(_q("rol", "Activiteit")):
        aid = act.findtext(_q("rol", "identificatie"))
        nodes[aid] = {"id": aid,
                      "naam": act.findtext(_q("rol", "naam")),
                      "groep": act.findtext(_q("rol", "groep"))}
        parent = act.find(_q("rol", "bovenliggendeActiviteit"))
        if parent is not None:
            ref = parent.find(_q("rol", "ActiviteitRef"))
            if ref is not None:
                hierarchy.append((aid, ref.get(_q("xlink", "href"))))
    return nodes, hierarchy


def parse_regelsvooriedereen(path):
    """Return (rvi_nodes, links) for the rule-on-location join objects.

    links is a list of (rvi_id, rel_type, target_id) for VAN_REGELTEKST,
    GELDT_VOOR and OP_LOCATIE edges.
    """
    tree = etree.parse(str(path), RECOVER)
    rvi_nodes, links = [], []
    for rvi in tree.iter(_q("regels", "RegelVoorIedereen")):
        rid = rvi.findtext(_q("regels", "identificatie"))
        rvi_nodes.append(rid)
        rt_ref = rvi.find(f".//{_q('regels','RegeltekstRef')}")
        if rt_ref is not None:
            links.append((rid, "VAN_REGELTEKST", rt_ref.get(_q("xlink", "href"))))
        act_ref = rvi.find(f".//{_q('rol','ActiviteitRef')}")
        if act_ref is not None:
            links.append((rid, "GELDT_VOOR", act_ref.get(_q("xlink", "href"))))
        loc_ref = rvi.find(f".//{_q('l','LocatieRef')}")
        if loc_ref is not None:
            links.append((rid, "OP_LOCATIE", loc_ref.get(_q("xlink", "href"))))
    return rvi_nodes, links


def _constraints(tx):
    """Create uniqueness constraints (idempotent)."""
    for label, key in [("Regeling", "id"), ("Artikel", "wId"), ("Lid", "wId"),
                       ("Hoofdstuk", "wId"), ("Afdeling", "wId"), ("Paragraaf", "wId"),
                       ("Subparagraaf", "wId"), ("Regeltekst", "id"),
                       ("RegelVoorIedereen", "id"), ("Activiteit", "id"),
                       ("Locatie", "id"), ("Component", "eId")]:
        tx.run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.{key} IS UNIQUE")


def _merge_struct(tx, rows):
    """Upsert structure nodes, one statement per label (no APOC dependency)."""
    by_label = defaultdict(list)
    for r in rows:
        by_label[r["label"]].append(r)
    for label, items in by_label.items():
        tx.run(
            f"UNWIND $rows AS r MERGE (n:{label} {{wId: r.wId}}) SET n += r",
            rows=items,
        )


def _merge_simple(tx, label, key, rows):
    tx.run(
        f"UNWIND $rows AS r MERGE (n:{label} {{{key}: r.{key}}}) SET n += r",
        rows=rows,
    )


def _merge_edges(tx, src_label, src_key, rel, dst_label, dst_key, pairs):
    tx.run(
        f"""
        UNWIND $pairs AS p
        MATCH (a:{src_label} {{{src_key}: p.s}})
        MATCH (b:{dst_label} {{{dst_key}: p.t}})
        MERGE (a)-[:{rel}]->(b)
        """,
        pairs=[{"s": s, "t": t} for s, t in pairs],
    )


def load(driver, package, boundary=None):
    """Parse the package and load the full graph into Neo4j.

    Args:
        driver: An open neo4j driver.
        package: Path to the delivery-package root directory.
    """
    package = Path(package)
    ow = package / "OW-bestanden"

    nodes, bevat, verwijst, eid_to_wid = parse_text(package / "Regeling/Tekst.xml")
    rt_rows = parse_regelteksten(ow / "regelteksten.xml")
    acts, act_hier = parse_activiteiten(ow / "activiteiten.xml")
    rvi_nodes, rvi_links = parse_regelsvooriedereen(ow / "regelsvooriedereen.xml")

    # resolve IntRef targets: a known structural eId, otherwise a Component stub
    verwijst_resolved, component_eids = [], set()
    for src, tgt_eid in verwijst:
        tgt_wid = eid_to_wid.get(tgt_eid)
        if tgt_wid and tgt_wid in nodes:
            verwijst_resolved.append((src, tgt_wid))
        else:
            component_eids.add(tgt_eid)
            verwijst_resolved.append((src, "component:" + tgt_eid))

    with driver.session() as s:
        s.execute_write(_constraints)
        s.execute_write(_merge_simple, "Regeling", "id",
                        [{"id": package.name, "naam": "Omgevingsplan gemeente Maastricht"}])
        s.execute_write(_merge_struct, list(nodes.values()))
        s.execute_write(_merge_simple, "Component", "eId",
                        [{"eId": e} for e in component_eids])
        s.execute_write(_merge_simple, "Regeltekst", "id",
                        [{"id": i, "wId": w} for i, w in rt_rows])
        s.execute_write(_merge_simple, "Activiteit", "id", list(acts.values()))
        s.execute_write(_merge_simple, "RegelVoorIedereen", "id",
                        [{"id": r} for r in rvi_nodes])
        locaties = {t for r, rel, t in rvi_links if rel == "OP_LOCATIE"}
        s.execute_write(_merge_simple, "Locatie", "id", [{"id": x} for x in locaties])
        if boundary:
            geojson_text = Path(boundary).read_text(encoding="utf-8")
            ring = json.loads(geojson_text)["coordinates"][0]
            xs = [pt[0] for pt in ring]
            ys = [pt[1] for pt in ring]
            bbox = {"minx": min(xs), "miny": min(ys), "maxx": max(xs), "maxy": max(ys)}
            s.execute_write(_attach_boundary, geojson_text, bbox)
            print(f"attached RD boundary to ambtsgebied Locatie (bbox {bbox})")

        # structural containment: attach each child to its nearest structural parent
        s.execute_write(_bevat_edges, bevat, nodes)
        # connect the Regeling root to its top-level (parentless) chapters
        child_wids = {t for _, t in bevat}
        roots = [w for w in nodes if w not in child_wids]
        s.execute_write(_regeling_roots, package.name, roots)
        # cross references (split by whether the target is a real node or a Component)
        real = [(s_, t) for s_, t in verwijst_resolved if not t.startswith("component:")]
        comp = [(s_, t.split("component:", 1)[1]) for s_, t in verwijst_resolved if t.startswith("component:")]
        s.execute_write(_verwijst_real, real, nodes)
        s.execute_write(_merge_edges, "Artikel", "wId", "VERWIJST_NAAR", "Component", "eId", comp)
        # regeltekst <-> text, via wId
        s.execute_write(_istekstvan, rt_rows, nodes)
        # rvi links
        s.execute_write(_merge_edges, "RegelVoorIedereen", "id", "VAN_REGELTEKST", "Regeltekst", "id",
                        [(r, t) for r, rel, t in rvi_links if rel == "VAN_REGELTEKST"])
        s.execute_write(_merge_edges, "RegelVoorIedereen", "id", "GELDT_VOOR", "Activiteit", "id",
                        [(r, t) for r, rel, t in rvi_links if rel == "GELDT_VOOR"])
        s.execute_write(_merge_edges, "RegelVoorIedereen", "id", "OP_LOCATIE", "Locatie", "id",
                        [(r, t) for r, rel, t in rvi_links if rel == "OP_LOCATIE"])
        s.execute_write(_merge_edges, "Activiteit", "id", "VALT_ONDER", "Activiteit", "id", act_hier)

    print(f"loaded: {len(nodes)} structure nodes, {len(rt_rows)} regelteksten, "
          f"{len(acts)} activiteiten, {len(rvi_nodes)} regels-voor-iedereen, "
          f"{len(verwijst_resolved)} cross-references")


def _bevat_edges(tx, bevat, nodes):
    pairs = [{"s": s, "t": t, "sl": nodes[s]["label"], "tl": nodes[t]["label"]}
             for s, t in bevat if s in nodes and t in nodes]
    tx.run(
        """
        UNWIND $pairs AS p
        MATCH (a {wId: p.s}) MATCH (b {wId: p.t})
        MERGE (a)-[:BEVAT]->(b)
        """,
        pairs=pairs,
    )


def _verwijst_real(tx, pairs, nodes):
    tx.run(
        """
        UNWIND $pairs AS p
        MATCH (a {wId: p.s}) MATCH (b {wId: p.t})
        MERGE (a)-[:VERWIJST_NAAR]->(b)
        """,
        pairs=[{"s": s, "t": t} for s, t in pairs if s in nodes and t in nodes],
    )


def _istekstvan(tx, rt_rows, nodes):
    tx.run(
        """
        UNWIND $pairs AS p
        MATCH (rt:Regeltekst {id: p.id}) MATCH (n {wId: p.wId})
        MERGE (rt)-[:IS_TEKST_VAN]->(n)
        """,
        pairs=[{"id": i, "wId": w} for i, w in rt_rows if w in nodes],
    )


def _regeling_roots(tx, regeling_id, roots):
    """Link the Regeling node to each top-level (parentless) structural node."""
    tx.run(
        """
        MATCH (r:Regeling {id: $rid})
        UNWIND $roots AS w
        MATCH (n {wId: w})
        MERGE (r)-[:BEVAT]->(n)
        """,
        rid=regeling_id, roots=roots,
    )


def _attach_boundary(tx, geojson_text, bbox):
    """Attach the RD boundary polygon to the ambtsgebied Locatie node(s)."""
    tx.run(
        """
        MATCH (loc:Locatie)
        WHERE loc.id CONTAINS 'ambtsgebied'
        SET loc.naam = 'Ambtsgebied gemeente Maastricht',
            loc.srid = 28992,
            loc.geometry_geojson = $geo,
            loc.bbox_minx = $minx, loc.bbox_miny = $miny,
            loc.bbox_maxx = $maxx, loc.bbox_maxy = $maxy
        """,
        geo=geojson_text, minx=bbox["minx"], miny=bbox["miny"],
        maxx=bbox["maxx"], maxy=bbox["maxy"],
    )


def main():
    parser = argparse.ArgumentParser(description="Load a STOP/TPOD package into Neo4j")
    parser.add_argument("--package", default="../source_data/Maastricht-DSO-production-2026-10-02", help="delivery-package root directory")
    parser.add_argument("--uri", default="bolt://localhost:7687")
    parser.add_argument("--user", default="neo4j")
    parser.add_argument("--password", default="testpassword")
    parser.add_argument("--boundary", default="../source_data/Maastricht-boundary-RD.geojson", help="RD boundary GeoJSON for the ambtsgebied")
    args = parser.parse_args()

    driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password))
    try:
        driver.verify_connectivity()
        load(driver, args.package, args.boundary)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
