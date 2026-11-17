"""Add the cross-references that the delivery package does not mark up.

`build_graph.py` loads VERWIJST_NAAR edges only from the IntRef elements in
`Regeling/Tekst.xml`. Four kinds of reference in the text have no IntRef, or an
incomplete one, so they never reach the graph:

    unmarked     "artikel 22.76" written without IntRef markup (lower-case drafting)
    range        "Artikel 22.63 tot en met Artikel 22.71": IntRef marks only the two
                 endpoints; the articles in between are missing
    paragraph    "deze paragraaf", "deze afdeling", "dit hoofdstuk": the enclosing
                 unit, never marked up
    same_article "het eerste lid", "in afwijking van het tweede lid": a lid of the
                 same article, never marked up

This script finds them with deterministic text rules (no LLM) and writes them as
VERWIJST_NAAR edges with `ref_source = 'text_rule'`, the `rule` that found them
and the quoted words, so they stay distinguishable from the IntRef edges. The
source is the Lid (or the Artikel, if it has no leden) whose text holds the
reference, as for IntRef.

"Deze paragraaf" resolves to the nearest enclosing Paragraaf or Subparagraaf:
the plan uses "paragraaf" for both (e.g. 22.96, the scope of Subparagraaf
22.3.6.2). The exception is a subparagraaf titled "Algemene bepalingen", whose
scope clauses speak for the whole Paragraaf (22.54, 22.90). References to other laws ("artikel 22.1, onder a, van de
Omgevingswet") are skipped.

Run after build_graph.py, from prototype/:
    python scripts/complete_references.py              # dry run: counts + report CSV
    python scripts/complete_references.py --write      # also write the edges
Safe to re-run: it MERGEs on (source, target, rule).
"""

import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path

from lxml import etree
from neo4j import GraphDatabase

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_graph import STRUCT, _nearest_structural_wid, _q, parse_text  # noqa: E402

ORDINALS = {"eerste": 1, "tweede": 2, "derde": 3, "vierde": 4, "vijfde": 5,
            "zesde": 6, "zevende": 7, "achtste": 8, "negende": 9, "tiende": 10}
ORD = "|".join(ORDINALS)
NUM = r"\d+\.\d+[a-z]?(?![\d.])"
# "artikel 22.76", optionally with ", eerste lid"
ARTICLE_RE = re.compile(rf"\b[Aa]rtikel(?:en)?\s+({NUM})(?:,\s*({ORD})\s+lid)?")
RANGE_RE = re.compile(rf"\b[Aa]rtikel(?:en)?\s+({NUM})(?:,\s*(?:{ORD})\s+lid,)?\s+tot en met\s+(?:[Aa]rtikel\s+)?({NUM})")
UNIT_RE = re.compile(r"\b(deze paragraaf|deze subparagraaf|deze afdeling|dit hoofdstuk)\b", re.I)
# "het eerste lid", "het eerste en tweede lid", "het eerste tot en met derde lid", "de eerste twee leden" is not covered
LID_RE = re.compile(rf"\b((?:{ORD})(?:\s*(?:,|en|of|tot en met)\s*(?:{ORD}))*)\s+(?:lid|leden)\b")
# a reference to another law follows the number: ", onder a, van de Omgevingswet"
EXTERNAL_AFTER = re.compile(r"^(?:,?\s*(?:eerste|tweede|derde|vierde|vijfde|zesde|zevende|achtste|negende|tiende|"
                            r"aanhef|onder|lid|en|[a-z]|\d+°?|,)\s*)*,?\s*van\s+(?:de|het)\s+(?!dit\b)", re.I)
UNIT_LABELS = {"deze paragraaf": ("Subparagraaf", "Paragraaf"), "deze subparagraaf": ("Subparagraaf",),
               "deze afdeling": ("Afdeling",), "dit hoofdstuk": ("Hoofdstuk",)}


def lid_number(wid):
    """The lid number from a Lid wId ('..._art_22.63__para_2' -> 2)."""
    m = re.search(r"__para_(\d+)$", wid or "")
    return int(m.group(1)) if m else None


def ordinals(phrase):
    """'eerste tot en met derde' -> [1, 2, 3]; 'eerste en tweede' -> [1, 2]."""
    nums = [ORDINALS[w] for w in re.findall(ORD, phrase)]
    if "tot en met" in phrase and len(nums) == 2:
        return list(range(nums[0], nums[1] + 1))
    return nums


def source_texts(root, nodes):
    """Yield (source wId, plain text) for each Lid and each Artikel without leden."""
    for el in root.iter(_q("tekst", "Lid"), _q("tekst", "Artikel")):
        if el.tag == _q("tekst", "Artikel") and el.find(_q("tekst", "Lid")) is not None:
            continue
        inhoud = el.find(_q("tekst", "Inhoud"))
        if inhoud is not None and el.get("wId") in nodes:
            yield el.get("wId"), re.sub(r"\s+", " ", "".join(inhoud.itertext())).strip()


def find_references(tekst_path):
    """Return (rows, existing) where rows are the new references found by the text rules."""
    root = etree.parse(str(tekst_path)).getroot()
    nodes, bevat, verwijst, eid_to_wid = parse_text(tekst_path)
    parent = {c: p for p, c in bevat}

    def up(wid, labels):
        while wid and nodes.get(wid, {}).get("label") not in labels:
            wid = parent.get(wid)
        return wid

    articles = [w for w, n in nodes.items() if n["label"] == "Artikel"]  # document order
    by_number = {nodes[w]["nummer"]: w for w in articles}
    leden = {}  # (article wId, lid number) -> lid wId
    for p, c in bevat:
        if nodes.get(c, {}).get("label") == "Lid" and lid_number(c):
            leden[(p, lid_number(c))] = c

    # what IntRef already covers, per source, at node and at article level
    existing = set()
    for s, eid in verwijst:
        t = eid_to_wid.get(eid)
        if t in nodes:
            existing.add((s, t))
            existing.add((s, up(t, ("Artikel",))))

    rows = []

    def add(src, tgt, rule, quote, target_range=""):
        if tgt and tgt != src and (src, tgt) not in existing:
            existing.add((src, tgt))
            rows.append({"source": src, "source_article": nodes[up(src, ("Artikel",))]["nummer"],
                         "target": tgt, "target_label": nodes[tgt]["label"],
                         "target_nummer": nodes[tgt]["nummer"] or f"lid {lid_number(tgt)}",
                         "rule": rule, "quote": quote, "target_range": target_range})

    for src, text in source_texts(root, nodes):
        own_article = up(src, ("Artikel",))

        for m in RANGE_RE.finditer(text):
            a, b = by_number.get(m.group(1)), by_number.get(m.group(2))
            if not (a and b) or EXTERNAL_AFTER.match(text[m.end():m.end() + 60]):
                continue
            i, j = articles.index(a), articles.index(b)
            for w in articles[min(i, j):max(i, j) + 1]:
                if w != own_article:
                    add(src, w, "range", m.group(0), f"{m.group(1)} tot en met {m.group(2)}")

        for m in ARTICLE_RE.finditer(text):
            art = by_number.get(m.group(1))
            if not art or art == own_article or EXTERNAL_AFTER.match(text[m.end():m.end() + 60]):
                continue
            if (src, art) in existing:
                continue
            tgt = leden.get((art, ORDINALS[m.group(2)])) if m.group(2) else None
            add(src, tgt or art, "unmarked", m.group(0))

        for m in UNIT_RE.finditer(text):
            unit = up(parent.get(own_article), UNIT_LABELS[m.group(1).lower()])
            # a scope clause in "Subparagraaf x.1 Algemene bepalingen" speaks for the whole Paragraaf (22.54, 22.90)
            if unit and nodes[unit]["label"] == "Subparagraaf" and nodes[unit]["opschrift"].startswith("Algemene bepalingen"):
                unit = up(parent.get(unit), ("Paragraaf",))
            add(src, unit, "paragraph", m.group(0))

        if nodes[src]["label"] == "Lid":
            for m in LID_RE.finditer(text):
                before, after = text[max(0, m.start() - 40):m.start()], text[m.end():m.end() + 40]
                # "Artikel 22.63, eerste lid" or "eerste lid van Artikel 22.63" is another article
                if re.search(rf"[Aa]rtikel\s+[\w.]+(?:\s*\([^)]*\))?,\s*(?:(?:{ORD}|lid|leden|en|of|tot en met)[\s,]*)*$", before) \
                        or re.match(r"\s*,?\s*(?:(?:aanhef|onder|en|of|[a-z]|\d+°?)[\s,]*)*van\s+(?:[Aa]rtikel|de|het|dat|dit)\b", after):
                    continue
                for k in ordinals(m.group(1)):
                    add(src, leden.get((own_article, k)), "same_article", m.group(0))

    return rows


def write_edges(driver, rows):
    """MERGE the found references as VERWIJST_NAAR edges marked ref_source = text_rule."""
    with driver.session() as s:
        s.run(
            """
            UNWIND $rows AS r
            MATCH (a:Artikel|Lid {wId: r.source})
            MATCH (b {wId: r.target}) WHERE NOT b:Regeltekst  // Regeltekst nodes carry the same wId
            MERGE (a)-[e:VERWIJST_NAAR {ref_source: 'text_rule', rule: r.rule}]->(b)
            SET e.quote = r.quote, e.target_range = CASE r.target_range WHEN '' THEN null ELSE r.target_range END
            """,
            rows=rows,
        )


def main():
    parser = argparse.ArgumentParser(description="Add cross-references the delivery package does not mark up")
    parser.add_argument("--tekst", default="../source_data/Maastricht-DSO-production-2026-10-02/Regeling/Tekst.xml")
    parser.add_argument("--report", default="runs/text_rule_references.csv", help="CSV of every reference found")
    parser.add_argument("--write", action="store_true", help="write the edges to Neo4j (default: dry run)")
    parser.add_argument("--uri", default="bolt://localhost:7687")
    parser.add_argument("--user", default="neo4j")
    parser.add_argument("--password", default="testpassword")
    args = parser.parse_args()

    rows = find_references(args.tekst)
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    with open(args.report, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["source"])
        writer.writeheader()
        writer.writerows(rows)

    counts = Counter(r["rule"] for r in rows)
    print("found: " + ", ".join(f"{n} {rule}" for rule, n in sorted(counts.items())) + f" (report: {args.report})")
    if args.write:
        driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password))
        write_edges(driver, rows)
        driver.close()
        print(f"wrote {len(rows)} VERWIJST_NAAR edges with ref_source = 'text_rule'")


if __name__ == "__main__":
    main()
