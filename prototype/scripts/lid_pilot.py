"""Lid-level pilot: tag each lid separately and test roll-ups against the silver sets.

The article-level extractor misses mixed articles (a primary norm plus an
exemption or a different norm in another lid). This pilot classifies each lid of
the multi-lid silver articles with the same prompt as deontic_extract.py, rolls
the lid tags up to one article label in three ways, and scores the roll-ups
against silver, split into flagged (mixed / not v0) and clean articles.

Lid text comes from LLM_KG/data/cleaned/articles.jsonl (paragraph offsets per
lid); lid wIds match the Lid nodes in the graph.

Usage (from prototype/):
    python scripts/lid_pilot.py --dry-run
    python scripts/lid_pilot.py --out runs/lid_pilot.csv
    python scripts/lid_pilot.py --score runs/lid_pilot.csv
"""
import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ARTICLES = "../LLM_KG/data/cleaned/articles.jsonl"
FEWSHOT = {"1.1", "22.26", "22.27", "22.28"}


def label(row):
    """Collapse a prediction or silver row to one label."""
    return row.get("deontic") or row.get("statement_type") or "none"


def load_articles(path):
    """Read the cleaned articles keyed by number."""
    with open(path, encoding="utf-8") as f:
        return {a["number"]: a for a in map(json.loads, f)}


def load_silver(v1, v2):
    """Merge silver v1 and v2 into nummer -> (label, flagged, set)."""
    silver = {}
    for r in csv.DictReader(open(v1, encoding="utf-8")):
        silver[r["nummer"]] = (label(r), None, "v1")
    for r in csv.DictReader(open(v2, encoding="utf-8")):
        silver[r["nummer"]] = (label(r), r["v0_fit"] == "no" or bool(r["category"]), "v2")
    return silver


def lids(article):
    """Split an article into (number, wId, text) per lid using the stored offsets."""
    text = article["text"]
    return [(p["number"].rstrip("."), p["wId"], text[p["start"]:p["end"]].strip())
            for p in article["provenance"].get("paragraphs", [])]


def select(articles, silver):
    """Silver articles with more than one lid, few-shot articles excluded."""
    return sorted((n for n in silver
                   if n not in FEWSHOT and n in articles and len(lids(articles[n])) > 1),
                  key=lambda n: [int(x) if x.isdigit() else x for x in n.replace("a", ".a").split(".")])


def run(args, articles, chosen):
    """Classify every lid of the chosen articles and write one row per lid."""
    from deontic_extract import classify, make_client
    client, model = make_client("openai")
    model = args.model or model
    rows = []
    for n in chosen:
        art = articles[n]
        parts = lids(art)
        for nr, wid, text in parts:
            pred = classify(client, model, {
                "nummer": f"{n} lid {nr}",
                "opschrift": f"{art['heading']} (lid {nr} van {len(parts)})",
                "tekst": text, "leden": [], "refs": []})
            ov = "; ".join(f"{o.get('target')}:{o.get('type')}" for o in (pred.get("overrides") or []))
            rows.append({"nummer": n, "lid": nr, "wId": wid,
                         "statement_type": pred.get("statement_type"), "deontic": pred.get("deontic") or "",
                         "overrides": ov, "rationale": pred.get("rationale", "")})
            print(f"{n:>8} lid {nr:<3} {str(pred.get('statement_type')):13} {pred.get('deontic') or '-':12} {ov}")
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} lid rows: {args.out}")


def rollups(lid_labels):
    """Three ways to turn an article's lid labels into one article label."""
    first = lid_labels[0]
    forceful = [x for x in lid_labels if x != "constitutive"]
    first_force = forceful[0] if forceful else "constitutive"
    majority = Counter(lid_labels).most_common(1)[0][0]
    return {"first lid": first, "first lid with force": first_force, "majority": majority}


def score(args, silver, chosen):
    """Score the roll-ups and the article-level baseline against silver."""
    by_art = defaultdict(list)
    for r in csv.DictReader(open(args.score, encoding="utf-8")):
        by_art[r["nummer"]].append(label(r))
    base = {r["nummer"]: label(r) for r in csv.DictReader(open(args.baseline, encoding="utf-8"))}
    groups = {"v2 flagged": [n for n in chosen if silver[n][2] == "v2" and silver[n][1]],
              "v2 clean": [n for n in chosen if silver[n][2] == "v2" and not silver[n][1]],
              "v1": [n for n in chosen if silver[n][2] == "v1"]}
    groups["all"] = [n for g in ("v2 flagged", "v2 clean", "v1") for n in groups[g]]
    methods = ["article-level (baseline)", "first lid", "first lid with force", "majority"]
    print(f"\n  {'':26}" + "".join(f"{g:>14}" for g in groups))
    for m in methods:
        cells = []
        for g, members in groups.items():
            members = [n for n in members if n in by_art]
            if m.startswith("article"):
                hits = sum(base.get(n) == silver[n][0] for n in members)
            else:
                hits = sum(rollups(by_art[n])[m] == silver[n][0] for n in members)
            cells.append(f"{hits}/{len(members)}")
        print(f"  {m:26}" + "".join(f"{c:>14}" for c in cells))
    mixed = [n for n in by_art if len(set(by_art[n])) > 1]
    print(f"\n  articles whose lids carry different labels: {len(mixed)} of {len(by_art)}")
    print("\n  per article (silver | baseline | lid labels):")
    for n in groups["all"]:
        if n in by_art:
            flag = "flagged" if silver[n][1] else ""
            print(f"  {n:8} {silver[n][0]:13} {base.get(n, '-'):13} {' '.join(by_art[n]):60} {flag}")


def main():
    parser = argparse.ArgumentParser(description="Lid-level pilot")
    parser.add_argument("--articles", default=ARTICLES)
    parser.add_argument("--v1", default="silver_deontic_v1.csv")
    parser.add_argument("--v2", default="silver_deontic_v2.csv")
    parser.add_argument("--model", help="override the default gpt-4o")
    parser.add_argument("--out", default="runs/lid_pilot.csv")
    parser.add_argument("--dry-run", action="store_true", help="show the selection, no API calls")
    parser.add_argument("--score", help="score an existing lid CSV instead of running")
    parser.add_argument("--baseline", default="tags/gpt4o_2026-11-01.csv", help="article-level predictions")
    args = parser.parse_args()

    articles = load_articles(args.articles)
    silver = load_silver(args.v1, args.v2)
    chosen = select(articles, silver)
    if args.dry_run:
        n_lids = sum(len(lids(articles[n])) for n in chosen)
        sets = Counter(("v2 flagged" if silver[n][1] else "v2 clean") if silver[n][2] == "v2" else "v1" for n in chosen)
        print(f"{len(chosen)} articles, {n_lids} lids ({n_lids} API calls): {dict(sets)}")
        for n in chosen:
            print(f"  {n:8} silver={silver[n][0]:13} lids={len(lids(articles[n]))}"
                  + ("  flagged" if silver[n][1] else ""))
        return
    if args.score:
        score(args, silver, chosen)
        return
    run(args, articles, chosen)


if __name__ == "__main__":
    main()
