"""Probe whether finer override flavors are distinguishable and worth adding.

Standalone experiment, separate from deontic_extract.py: reads articles straight
from Tekst.xml (no Neo4j), asks the model to label every derogation clause on
three independent axes (target scope, flavor, temporal), runs the whole set
more than once, and reports flavor counts, flavor-by-silver-group cross-tabs and
run-to-run stability.

Usage (from prototype/):
    python scripts/derogation_probe.py --runs 2 --controls 15
"""
import argparse
import csv
import json
import os
import random
import re
from collections import Counter, defaultdict
from xml.etree import ElementTree as ET

from openai import OpenAI

CUE = re.compile(r"in afwijking van", re.I)
CONTROL_CUE = re.compile(r"geldt niet|gelden niet|niet van toepassing|hoeft niet|hoeven niet", re.I)
AUTHORITY_CUE = re.compile(r"bevoegd gezag|college|omgevingsvergunning|vergunning|maatwerk|besluit", re.I)

# Silver grouping from the 2026-10-23 read of all 35 "in afwijking van" articles.
SILVER = {
    **{n: "A_same_article" for n in ["22.19", "22.54", "22.57", "22.60", "22.63", "22.90", "22.92",
                                       "22.122", "22.138", "22.144", "22.148", "22.149", "22.190"]},
    **{n: "B_modification" for n in ["22.64", "22.65", "22.66", "22.103"]},
    **{n: "C_permissive" for n in ["22.99", "22.104", "22.105"]},
    **{n: "D_eerbiedigend" for n in ["22.55", "22.84", "22.91", "22.215"]},
    **{n: "E_discretionary" for n in ["22.29", "22.32", "22.33", "22.278"]},
    **{n: "F_external" for n in ["22.161", "22.172", "22.173", "22.174", "22.175", "22.198", "22.204"]},
}

FLAVORS = ["disapply", "modification", "discretionary"]
SCOPES = ["same_article", "other_article", "external"]
NET = ["obligation", "prohibition", "permission", "exemption", "undetermined"]

SYSTEM_PROMPT = f"""You analyse Dutch environmental-law articles (omgevingsplan).

Find every clause in the article that departs from, disapplies or bends another rule
(cues include "in afwijking van", "geldt niet", "is niet van toepassing", "hoeft niet",
"mag ... toch", "kan ... toch worden verleend"). For each such clause return:

- quote: the decisive words, at most 25 words, copied from the text.
- target_scope: one of {SCOPES}
    same_article  = a lid or onderdeel of this same article ("het eerste lid", "onder a")
    other_article = another article of this regulation ("Artikel 22.63")
    external      = a national law article (Bal, Bbl, artikel 4.x) or a standard (NEN, NEN-EN)
- target: the referenced lid/article/source as written, e.g. "eerste lid", "22.63", "NEN-EN 1825-1".
- flavor: one of {FLAVORS}
    disapply      = the target rule, or part of it, does not apply to the stated cases, or applies
                    only to some cases ("geldt niet voor", "is niet van toepassing", "hoeft niet",
                    "is alleen van toepassing voor zover", "mag ... in afwijking van"). Label only this
                    local operation; do not judge whether the target is itself a prohibition, a
                    permission or an exemption.
    modification  = the target rule keeps applying to the same cases, but its content changes:
                    different values, limits, distances, deadlines, frequencies or method
                    ("gelden in plaats van ... de volgende eisen", "is ... niet hoger dan [other value]").
                    Narrowing or widening WHEN or TO WHOM a rule applies is disapply, not modification.
    discretionary = the competent authority (bevoegd gezag, college, the body granting a permit or
                    maatwerk) may decide differently from what the target prescribes ("kan het
                    bevoegd gezag", "kan de omgevingsvergunning toch worden verleend"). Actor test:
                    ask who decides. If "kan" or "mag" gives the regulated party room to act
                    ("kan ... worden geloosd", "kan met een lagere frequentie worden volstaan"),
                    there is no authority decision: that is disapply, not discretionary.
- temporal: true if the clause depends on an existing or earlier situation, a date, a transition,
  or eerbiedigende werking / overgangsrecht; else false.
- net_effect: the resulting position of the regulated party, one of {NET}
  ("undetermined" when it depends on a decision of the authority).

Return STRICT JSON: {{"clauses": [ ... ]}}. Return an empty list if the article has no such clause."""


def local(tag):
    """Strip the XML namespace from a tag."""
    return tag.split("}")[-1]


def read_articles(path):
    """Read every Artikel from Tekst.xml.

    Args:
        path: Path to Regeling/Tekst.xml.

    Returns:
        Dict of nummer -> {"opschrift", "tekst"}.
    """
    root = ET.parse(path).getroot()
    out = {}
    for art in root.iter():
        if local(art.tag) != "Artikel":
            continue
        nummer = opschrift = ""
        for el in art.iter():
            if local(el.tag) == "Nummer" and not nummer:
                nummer = "".join(el.itertext()).strip()
            elif local(el.tag) == "Opschrift" and not opschrift:
                opschrift = "".join(el.itertext()).strip()
        tekst = re.sub(r"\s+", " ", " ".join(art.itertext())).strip()
        out[nummer] = {"opschrift": opschrift, "tekst": tekst}
    return out


def pick(articles, n_controls, seed):
    """Select the cue articles plus a random control sample without the cue.

    Args:
        articles: Output of read_articles.
        n_controls: Number of "geldt niet / niet van toepassing" articles to add.
        seed: Random seed for the control sample.

    Returns:
        List of (nummer, group) tuples.
    """
    cue = [n for n, a in articles.items() if CUE.search(a["tekst"])]
    ctrl_pool = sorted(n for n, a in articles.items()
                       if CONTROL_CUE.search(a["tekst"]) and not CUE.search(a["tekst"]))
    ctrl = random.Random(seed).sample(ctrl_pool, min(n_controls, len(ctrl_pool)))
    return [(n, SILVER.get(n, "unlabelled")) for n in cue] + [(n, "control") for n in sorted(ctrl)]


def label(client, model, nummer, art):
    """Ask the model for the clause labels of one article.

    Args:
        client: OpenAI client.
        model: Model name.
        nummer: Article number.
        art: Dict with opschrift and tekst.

    Returns:
        List of clause dicts (empty on a parse failure).
    """
    user = json.dumps({"nummer": nummer, "opschrift": art["opschrift"],
                       "tekst": art["tekst"][:3500]}, ensure_ascii=False)
    resp = client.chat.completions.create(
        model=model, temperature=0, response_format={"type": "json_object"},
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
    )
    try:
        return json.loads(resp.choices[0].message.content).get("clauses") or []
    except json.JSONDecodeError:
        return []


def actor_guard(clause):
    """Keep a discretionary label only when the clause names an authority or decision.

    The prompt alone cannot separate authority discretion from a passive "kan ...
    worden" that gives the regulated party room to act, so this is checked in code.

    Args:
        clause: One clause dict from the model.

    Returns:
        A tuple (clause, changed); a rejected discretionary label becomes disapply.
    """
    if clause.get("flavor") == "discretionary" and not AUTHORITY_CUE.search(clause.get("quote") or ""):
        return {**clause, "flavor": "disapply"}, True
    return clause, False


def signature(clauses):
    """Order-free summary of an article's clauses, used to compare runs."""
    return tuple(sorted((c.get("target_scope"), c.get("flavor"), bool(c.get("temporal"))) for c in clauses))


def crosstab(rows, row_key, col_key, cols):
    """Print a small count table of row_key by col_key."""
    table = defaultdict(Counter)
    for r in rows:
        table[r[row_key]][r[col_key]] += 1
    width = max(len(c) for c in cols) + 1
    print(f"  {'':18}" + "".join(f"{c:>{width}}" for c in cols))
    for key in sorted(table):
        print(f"  {key:18}" + "".join(f"{table[key][c]:>{width}}" for c in cols))


def main():
    parser = argparse.ArgumentParser(description="Probe finer override flavors")
    parser.add_argument("--tekst", default="../source_data/Maastricht-DSO-production-2026-10-02/Regeling/Tekst.xml")
    parser.add_argument("--model", default="gpt-4o")
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--controls", type=int, default=15)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", default="runs/derogation_probe_v3.csv")
    args = parser.parse_args()

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    articles = read_articles(args.tekst)
    selection = pick(articles, args.controls, args.seed)
    print(f"{len(selection)} articles ({sum(g != 'control' for _, g in selection)} cue, "
          f"{sum(g == 'control' for _, g in selection)} control), {args.runs} runs")

    rows, sigs, guarded = [], defaultdict(list), []
    for run in range(1, args.runs + 1):
        for nummer, group in selection:
            raw = label(client, args.model, nummer, articles[nummer])
            clauses = []
            for c in raw:
                clean, changed = actor_guard(c)
                clauses.append(clean)
                if changed:
                    guarded.append((run, nummer))
            sigs[nummer].append(signature(clauses))
            for c, r in zip(clauses, raw):
                rows.append({"run": run, "nummer": nummer, "group": group,
                             "raw_flavor": r.get("flavor"),
                             "target_scope": c.get("target_scope"), "target": c.get("target"),
                             "flavor": c.get("flavor"), "temporal": bool(c.get("temporal")),
                             "net_effect": c.get("net_effect"), "quote": c.get("quote")})
        print(f"run {run} done")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} clause rows: {args.out}")

    print(f"actor guard: {len(guarded)} discretionary labels without an authority -> disapply"
          + (f" ({', '.join(f'run {r} {n}' for r, n in guarded)})" if guarded else ""))

    first = [r for r in rows if r["run"] == 1]
    print("\nflavor by silver group (run 1, clauses):")
    crosstab(first, "group", "flavor", FLAVORS)
    print("\ntarget scope by silver group (run 1, clauses):")
    crosstab(first, "group", "target_scope", SCOPES)
    print("\ntemporal by silver group (run 1, clauses):")
    for r in first:
        r["temporal_s"] = str(r["temporal"])
    crosstab(first, "group", "temporal_s", ["True", "False"])
    invalid = [r for r in rows if r["flavor"] not in FLAVORS or r["net_effect"] not in NET
               or r["target_scope"] not in SCOPES]
    print(f"\nschema violations (flavor, net_effect or scope outside the allowed values): {len(invalid)}")
    for r in invalid:
        print(f"  {r['run']} {r['nummer']}: {r['flavor']} / {r['net_effect']} / {r['target_scope']}")
    print("\nflavor counts per run:")
    for run in range(1, args.runs + 1):
        print(f"  run {run}: {dict(Counter(r['flavor'] for r in rows if r['run'] == run))}")

    if args.runs > 1:
        unstable = [n for n, s in sigs.items() if len(set(s)) > 1]
        print(f"\nstability: {len(sigs) - len(unstable)}/{len(sigs)} articles identical across runs")
        for n in unstable:
            print(f"  {n}: " + "  |  ".join(str(s) for s in sigs[n]))


if __name__ == "__main__":
    main()
