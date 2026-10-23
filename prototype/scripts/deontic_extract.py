"""Deontic extraction for the omgevingsplan knowledge graph.

Classifies each article's normative force (statement_type + deontic tag) and its
override relations, using the ontology v0 schema. One code path drives either a
local model via Ollama or the OpenAI API, because Ollama exposes an
OpenAI-compatible endpoint — switching is only a matter of base_url / model.

Reads articles from Neo4j, calls the model with the v0 definitions and a few
worked examples, optionally writes the tags and OVERRIDES edges back, and can
score itself against a labelled reference file (silver set).

Usage:
    pip install openai neo4j
    # local (needs: ollama pull qwen2.5:32b):
    python deontic_extract.py --backend ollama --write
    # hosted:
    export OPENAI_API_KEY=...
    python deontic_extract.py --backend openai --model gpt-4o --write
    # evaluate against the silver sample without writing:
    python deontic_extract.py --backend ollama --eval silver_deontic_v1.csv
"""

import argparse
import csv
import json
import os
from collections import Counter
from datetime import datetime

from neo4j import GraphDatabase
from openai import OpenAI

BACKENDS = {
    "ollama": {"base_url": "http://localhost:11434/v1", "api_key": "ollama", "model": "qwen2.5:32b"},
    "openai": {"base_url": None, "api_key_env": "OPENAI_API_KEY", "model": "gpt-4o"},
}

VALID_DEONTIC = {"obligation", "prohibition", "permission", "exemption"}

SYSTEM_PROMPT = """You classify Dutch environmental-law rules (omgevingsplan) under a fixed ontology.

For one article, return STRICT JSON with these fields:
- statement_type: "prescriptive" or "constitutive".
- deontic: for a prescriptive statement, EXACTLY one of "obligation", "prohibition", "permission", "exemption"; for a constitutive statement, null.
- overrides: a list of {"target": "<article number>", "type": "exception" | "restriction"}. Empty list if none.
- rationale: one short clause quoting the decisive wording.

statement_type decision (decide this first):
- "prescriptive" = the article bears on conduct: it requires, forbids, allows, or lifts a requirement on what someone must build, do, submit, or refrain from. Dutch legal drafting states these as facts in the present tense ("is aangesloten op", "wordt verstrekt", "voldoet aan", "is zodanig dat", "bedraagt ten minste", "ligt haaks"). A declarative phrasing does NOT make it constitutive: if, read as an instruction, it tells a norm-addressee to achieve or maintain a state, it is prescriptive. A performance, presence or dimension requirement written as a plain statement is an obligation; a statement that a thing or state shall not be present ("is geen ... aanwezig", "wordt niet ... toegepast") is a prohibition.
- "constitutive" = the article has no such behavioural content: a definition (begripsbepaling), a statement of the aim/oogmerk, a scope/applicability clause ("deze afdeling is van toepassing op ..."), or a measurement/counting/deeming convention ("een aangebroken verpakking wordt als een volle meegerekend"). A measurement or counting convention is constitutive ONLY when it stands alone; when it sits beside a behavioural norm in the same article, classify the article by that norm, not by the convention.

deontic value (only when prescriptive):
- obligation = a positive duty: moet, is verplicht, wordt verstrekt, is aangesloten op, voldoet aan, draagt zorg voor, is zodanig dat.
- prohibition = conduct forbidden or made subject to a permit, or a required absence: het is verboden, mag niet, is niet toegestaan, vergunningplicht, alleen met omgevingsvergunning, "is geen ... aanwezig".
- permission = conduct allowed without a permit, or an explicit right: mag, is toegestaan, vergunningvrij, van rechtswege.
- exemption = a base rule lifted for stated cases: het verbod geldt niet voor, is niet van toepassing op (lifting a specific named rule for a case), vrijstelling, niet vereist.
- "restriction" and "exception" are OVERRIDE types, NEVER deontic values. An article that re-imposes a base rule by cancelling an exemption is itself a "prohibition" (or "obligation") carrying an overrides entry of type "restriction".

overrides: add one entry per article this one explicitly disapplies or narrows.
- "exception" = this article lifts the target rule for stated cases ("het verbod, bedoeld in artikel X, geldt niet voor ...").
- "restriction" = this article cancels or narrows the target ("artikel X is niet van toepassing op ...").
- target MUST be a bare article number from this same regulation, exactly as it appears (e.g. "22.26"). Never target the article itself. Never target a lid or subparagraaf ("eerste lid", "22.2.7.3"), a whole afdeling ("Afdeling 22.3"), a maatwerk instrument, or an article of another law (Bbl/Bal numbers like "4.1057"). If no same-regulation article is named, return an empty list.

Return only the JSON object."""

FEWSHOT = [
    ({"nummer": "22.26", "opschrift": "Binnenplanse vergunning omgevingsplanactiviteit bouwwerken",
      "tekst": "Het is verboden zonder omgevingsvergunning een bouwactiviteit te verrichten...", "refs": []},
     {"statement_type": "prescriptive", "deontic": "prohibition", "overrides": [],
      "rationale": "het is verboden zonder omgevingsvergunning"}),
    ({"nummer": "22.27", "opschrift": "Uitzonderingen op vergunningplicht artikel 22.26",
      "tekst": "Het verbod, bedoeld in Artikel 22.26, geldt niet voor...", "refs": ["22.26"]},
     {"statement_type": "prescriptive", "deontic": "exemption",
      "overrides": [{"target": "22.26", "type": "exception"}], "rationale": "het verbod geldt niet voor"}),
    ({"nummer": "22.28", "opschrift": "Inperkingen artikel 22.27 vanwege cultureel erfgoed",
      "tekst": "Op een activiteit... is Artikel 22.27 niet van toepassing.", "refs": ["22.27"]},
     {"statement_type": "prescriptive", "deontic": "prohibition",
      "overrides": [{"target": "22.27", "type": "restriction"}], "rationale": "Artikel 22.27 niet van toepassing"}),
    ({"nummer": "1.1", "opschrift": "Begripsbepalingen", "tekst": "Begripsbepalingen die... zijn van toepassing op...", "refs": []},
     {"statement_type": "constitutive", "deontic": None, "overrides": [], "rationale": "definition"}),
]


def make_client(backend):
    """Build an OpenAI-compatible client and resolve the model for a backend."""
    cfg = BACKENDS[backend]
    api_key = cfg.get("api_key") or os.environ.get(cfg["api_key_env"], "")
    client = OpenAI(base_url=cfg["base_url"], api_key=api_key or "none",
            default_headers={"Accept-Encoding": "identity"})
    return client, cfg["model"]


def read_articles(driver, limit=None):
    """Read articles with their text, leden text and outgoing cross-references."""
    query = """
        MATCH (a:Artikel)
        OPTIONAL MATCH (a)-[:BEVAT]->(l:Lid)
        WITH a, [x IN collect(l.tekst) WHERE x IS NOT NULL] AS leden
        OPTIONAL MATCH (a)-[:BEVAT*0..1]->()-[:VERWIJST_NAAR]->(t:Artikel)
        WITH a, leden, [n IN collect(DISTINCT t.nummer) WHERE n IS NOT NULL] AS refs
        RETURN a.nummer AS nummer, a.opschrift AS opschrift,
               coalesce(a.tekst, '') AS tekst, leden, refs
        ORDER BY a.nummer
    """
    if limit:
        query += f"\nLIMIT {int(limit)}"
    with driver.session() as session:
        return [dict(r) for r in session.run(query)]


def classify(client, model, art):
    """Classify one article; returns the parsed JSON dict (with a single retry)."""
    text = (art["tekst"] + " " + " ".join(art.get("leden", [])))[:2500]
    user = json.dumps({"nummer": art["nummer"], "opschrift": art["opschrift"],
                       "tekst": text, "refereert_naar": art.get("refs", [])}, ensure_ascii=False)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for ex_in, ex_out in FEWSHOT:
        messages.append({"role": "user", "content": json.dumps(ex_in, ensure_ascii=False)})
        messages.append({"role": "assistant", "content": json.dumps(ex_out, ensure_ascii=False)})
    messages.append({"role": "user", "content": user})

    for attempt in range(2):
        resp = client.chat.completions.create(
            model=model, messages=messages, temperature=0,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            if attempt == 1:
                return {"statement_type": None, "deontic": None, "overrides": [], "rationale": "parse_error"}


def write_back(driver, nummer, pred, source):
    """Write deontic tags and OVERRIDES edges for one article back to Neo4j."""
    with driver.session() as session:
        session.run(
            """
            MATCH (a:Artikel {nummer: $nummer})
            SET a.statement_type = $st, a.deontic = $deontic,
                a.deontic_source = $src, a.deontic_rationale = $rat
            WITH a
            UNWIND $overrides AS ov
            MATCH (t:Artikel {nummer: ov.target})
            MERGE (a)-[o:OVERRIDES]->(t)
            SET o.override_type = ov.type, o.override_source = $src
            """,
            nummer=nummer, st=pred.get("statement_type"), deontic=pred.get("deontic"),
            src=source, rat=pred.get("rationale", ""), overrides=pred.get("overrides") or [],
        )


def evaluate(preds, silver_path):
    """Score predictions against a silver CSV, overall and held-out.

    The held-out score excludes the articles used as few-shot examples in
    FEWSHOT, since the model has seen their answers in the prompt.

    Args:
        preds: Mapping of article nummer to predicted dict.
        silver_path: CSV with columns nummer, deontic, statement_type.

    Returns:
        Tuple (overall, held_out) of "hits/total" strings.
    """
    silver = {}
    with open(silver_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            silver[row["nummer"]] = (row["deontic"] or None, row["statement_type"])
    fewshot = {example["nummer"] for example, _ in FEWSHOT}
    hits, total = Counter(), Counter()
    hits_ho, total_ho = Counter(), Counter()
    wrong = []
    for nummer, p in preds.items():
        if nummer not in silver:
            continue
        g_deontic, g_type = silver[nummer]
        key = g_deontic or f"({g_type})"
        correct = (p.get("deontic") or None) == g_deontic and p.get("statement_type") == g_type
        total[key] += 1
        hits[key] += correct
        if nummer not in fewshot:
            total_ho[key] += 1
            hits_ho[key] += correct
        if not correct:
            tag = " [few-shot]" if nummer in fewshot else ""
            wrong.append((nummer, g_deontic or g_type, p.get("deontic") or p.get("statement_type"), tag))
    print("\nagreement vs silver:")
    print(f"  {'':14} {'all':>7} {'held-out':>9}")
    for key in sorted(total):
        print(f"  {key:14} {f'{hits[key]}/{total[key]}':>7} {f'{hits_ho[key]}/{total_ho[key]}':>9}")
    overall = f"{sum(hits.values())}/{sum(total.values())}"
    held_out = f"{sum(hits_ho.values())}/{sum(total_ho.values())}"
    print(f"  {'overall':14} {overall:>7} {held_out:>9}")
    excluded = sorted(fewshot & set(silver) & set(preds))
    print(f"  held-out excludes few-shot articles: {', '.join(excluded) or 'none'}")
    if wrong:
        print("\ndisagreements (nummer: silver -> predicted):")
        for n, g, pr, tag in wrong:
            print(f"  {n}: {g} -> {pr}{tag}")
    return overall, held_out


def sanitize_prediction(pred, nummer, valid_nummers):
    """Enforce the ontology schema on one prediction before it is used.

    Removes values a prompt cannot reliably prevent: a deontic outside the four
    valid values, a self-override, an override target that is not a real article
    in this regulation, and any override on a constitutive statement.

    Args:
        pred: The model's parsed prediction dict.
        nummer: The article's own number, to catch self-overrides.
        valid_nummers: Set of every article number present in the graph.

    Returns:
        A tuple (clean_pred, changes); changes lists what was altered.
    """
    changes = []
    clean = dict(pred)
    st = clean.get("statement_type")
    deontic = clean.get("deontic")

    if st == "constitutive" and deontic is not None:
        changes.append(f"deontic {deontic!r} -> null (constitutive)")
        clean["deontic"] = None
    elif st != "constitutive" and deontic is not None and deontic not in VALID_DEONTIC:
        changes.append(f"deontic {deontic!r} -> null (not one of the four)")
        clean["deontic"] = None

    kept = []
    for ov in clean.get("overrides") or []:
        target = (ov or {}).get("target")
        if st == "constitutive":
            changes.append(f"dropped override -> {target} (constitutive carries none)")
        elif target == nummer:
            changes.append(f"dropped self-override -> {target}")
        elif target not in valid_nummers:
            changes.append(f"dropped override -> {target} (not an article in this regulation)")
        else:
            kept.append(ov)
    clean["overrides"] = kept
    return clean, changes


def report_guards(guard_log, applied):
    """Print what the schema guards changed, or would change.

    Args:
        guard_log: List of (nummer, change) tuples collected over the run.
        applied: Whether the changes were applied (guards on) or only detected.
    """
    if not guard_log:
        print("\nguards: no schema violations found")
        return
    verb = "applied" if applied else "would apply (re-run with --guards to apply)"
    print(f"\nguards {verb}: {len(guard_log)} change(s)")
    for nummer, change in guard_log:
        print(f"  {nummer}: {change}")


def write_predictions_csv(preds, path, source):
    """Write the run's predictions as a CSV snapshot (overwritten each run).

    Args:
        preds: Mapping of nummer to the (guarded) prediction dict.
        path: Output CSV path.
        source: The backend:model string recorded on every row.
    """
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["nummer", "statement_type", "deontic", "overrides", "rationale", "source"])
        for nummer, p in preds.items():
            overrides = "; ".join(f"{o.get('target')}:{o.get('type')}"
                                  for o in (p.get("overrides") or []))
            writer.writerow([nummer, p.get("statement_type"), p.get("deontic") or "",
                             overrides, p.get("rationale", ""), source])


def append_diary(path, meta):
    """Append a dated run summary to a markdown diary (created if absent).

    Args:
        path: Markdown file to append to.
        meta: Run metadata (when, model, guards, n, limit, agreement,
            guard_changes, out).
    """
    new_file = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as f:
        if new_file:
            f.write("# Extraction run diary\n\n")
        f.write(f"## {meta['when']} - {meta['model']}\n\n")
        f.write(f"- guards: {'on' if meta['guards'] else 'off'}\n")
        f.write(f"- articles: {meta['n']}"
                + (f" (limit {meta['limit']})" if meta['limit'] else "") + "\n")
        if meta.get("agreement"):
            overall, held_out = meta["agreement"]
            f.write(f"- agreement vs silver: {overall} (held-out, excl. few-shot: {held_out})\n")
        f.write(f"- guard changes: {meta['guard_changes']}\n")
        if meta.get("out"):
            f.write(f"- predictions snapshot: {meta['out']}\n")
        f.write("\n")


def main():
    parser = argparse.ArgumentParser(description="Deontic extraction, switchable local/OpenAI")
    parser.add_argument("--backend", choices=list(BACKENDS), default="ollama")
    parser.add_argument("--model", help="override the backend's default model")
    parser.add_argument("--limit", type=int, help="process only the first N articles")
    parser.add_argument("--write", action="store_true", help="write tags/edges back to Neo4j")
    parser.add_argument("--eval", dest="silver", help="score against a silver reference CSV")
    parser.add_argument("--guards", action="store_true",
                        help="enforce the schema on predictions before eval/write (auto-on with --write)")
    parser.add_argument("--out", help="write the run's predictions to this CSV")
    parser.add_argument("--diary", help="append a dated run summary to this markdown file")
    parser.add_argument("--uri", default="bolt://localhost:7687")
    parser.add_argument("--user", default="neo4j")
    parser.add_argument("--password", default="testpassword")
    args = parser.parse_args()

    client, model = make_client(args.backend)
    if args.model:
        model = args.model
    driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password))

    try:
        articles = read_articles(driver, args.limit)
        valid_nummers = {a["nummer"] for a in articles}
        guards_on = args.guards or args.write
        if args.write and not args.guards:
            print("note: guards auto-enabled for --write")
        preds = {}
        guard_log = []
        for art in articles:
            raw = classify(client, model, art)
            clean, changes = sanitize_prediction(raw, art["nummer"], valid_nummers)
            pred = clean if guards_on else raw
            preds[art["nummer"]] = pred
            guard_log.extend((art["nummer"], c) for c in changes)
            flag = " ".join(f"{o['target']}:{o['type']}" for o in (pred.get("overrides") or []))
            print(f"{art['nummer']:>8}  {str(pred.get('statement_type')):12} {str(pred.get('deontic')):11} {flag}")
            if args.write:
                write_back(driver, art["nummer"], pred, f"{args.backend}:{model}")
        report_guards(guard_log, guards_on)
        source = f"{args.backend}:{model}"
        if args.out:
            write_predictions_csv(preds, args.out, source)
            print(f"\nwrote predictions: {args.out}")
        agreement = evaluate(preds, args.silver) if args.silver else None
        if args.diary:
            append_diary(args.diary, {
                "when": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "model": source, "guards": guards_on, "n": len(preds),
                "limit": args.limit, "agreement": agreement,
                "guard_changes": len(guard_log), "out": args.out,
            })
            print(f"appended diary entry: {args.diary}")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
