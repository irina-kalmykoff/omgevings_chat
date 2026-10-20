"""Deontic extraction for the omgevingsplan knowledge graph.

Classifies each article's normative force (statement_type + deontic tag) and its
override relations, using the ontology v0 schema. One code path drives either a
local model via Ollama or the OpenAI API, because Ollama exposes an
OpenAI-compatible endpoint — switching is only a matter of base_url / model.

Reads articles from Neo4j, calls the model with the v0 definitions and a few
worked examples, optionally writes the tags and OVERRIDES edges back, and can
score itself against a human-labelled gold file.

Usage:
    pip install openai neo4j
    # local (needs: ollama pull qwen2.5:32b):
    python deontic_extract.py --backend ollama --write
    # hosted:
    export OPENAI_API_KEY=...
    python deontic_extract.py --backend openai --model gpt-4o --write
    # evaluate against the gold sample without writing:
    python deontic_extract.py --backend ollama --eval gold_deontic.csv
"""

import argparse
import csv
import json
import os
from collections import Counter

from neo4j import GraphDatabase
from openai import OpenAI

BACKENDS = {
    "ollama": {"base_url": "http://localhost:11434/v1", "api_key": "ollama", "model": "qwen2.5:32b"},
    "openai": {"base_url": None, "api_key_env": "OPENAI_API_KEY", "model": "gpt-4o"},
}

SYSTEM_PROMPT = """You classify Dutch environmental-law rules (omgevingsplan) under a fixed ontology.

For one article, return STRICT JSON with these fields:
- statement_type: "prescriptive" or "constitutive".
- deontic: for a prescriptive statement, EXACTLY one of "obligation", "prohibition", "permission", "exemption"; for a constitutive statement, null.
- overrides: a list of {"target": "<article number>", "type": "exception" | "restriction"}. Empty list if none.
- rationale: one short clause quoting the decisive wording.

statement_type decision (decide this first):
- "prescriptive" = the article bears on conduct: it requires, forbids, allows, or lifts a requirement on what someone must build, do, submit, or refrain from. Dutch legal drafting states obligations as facts in the present tense ("is aangesloten op", "wordt verstrekt", "voldoet aan", "bedraagt ten minste"). A declarative phrasing does NOT make it constitutive: if, read as an instruction, it tells a norm-addressee to achieve or maintain a state, it is prescriptive (an obligation).
- "constitutive" = the article has no such behavioural content: a definition (begripsbepaling), a statement of the aim/oogmerk of a set of rules, a scope/applicability clause ("deze afdeling is van toepassing op ...", "dit hoofdstuk geldt voor ..."), a deeming or measurement convention. Scope clauses are constitutive even though they contain "van toepassing", because they set where rules apply rather than disapplying a specific rule.

deontic value (only when prescriptive):
- obligation = a positive duty: moet, is verplicht, wordt verstrekt, is aangesloten op, voldoet aan, draagt zorg voor.
- prohibition = conduct forbidden or made subject to a permit: het is verboden, mag niet, is niet toegestaan, vergunningplicht, alleen met omgevingsvergunning.
- permission = conduct allowed without a permit, or an explicit right: mag, is toegestaan, vergunningvrij, van rechtswege.
- exemption = a base rule lifted for stated cases: het verbod geldt niet voor, is niet van toepassing op (when it lifts a specific named rule for a case), vrijstelling, niet vereist.
- "restriction" and "exception" are OVERRIDE types, never deontic values. An article that re-imposes a base rule by cancelling an exemption is itself a "prohibition" (or "obligation"), carrying an overrides entry of type "restriction".

overrides: add one entry per article this one explicitly disapplies or narrows.
- "exception" = this article lifts the target rule for stated cases ("het verbod, bedoeld in artikel X, geldt niet voor ...").
- "restriction" = this article cancels or narrows the target ("artikel X is niet van toepassing op ...").
- target MUST be a bare article number from this same regulation, exactly as it appears (e.g. "22.26"). Never target the article itself. Never target a lid or subparagraaf number (no "22.2.7.3"), a maatwerk/instrument name, or an article of another law (e.g. Bbl/Bal numbers like "4.x", "3.x"). If no same-regulation article is named, return an empty list.

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
    ({"nummer": "22.8", "opschrift": "Aansluiting op de riolering",
      "tekst": "Met het oog op het doelmatig beheer van afvalwater is een bouwwerk aangesloten op de openbare riolering.", "refs": []},
     {"statement_type": "prescriptive", "deontic": "obligation", "overrides": [],
      "rationale": "is aangesloten op de openbare riolering (positive duty stated declaratively)"}),
    ({"nummer": "22.41", "opschrift": "Toepassingsbereik",
      "tekst": "Deze afdeling is van toepassing op het bouwen van bouwwerken in het plangebied.", "refs": []},
     {"statement_type": "constitutive", "deontic": None, "overrides": [],
      "rationale": "scope clause: deze afdeling is van toepassing op (sets where rules apply, disapplies nothing)"}),
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


def evaluate(preds, gold_path):
    """Print per-tag agreement of predictions against a gold CSV (nummer,deontic,statement_type)."""
    gold = {}
    with open(gold_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            gold[row["nummer"]] = (row["deontic"] or None, row["statement_type"])
    hits = Counter()
    total = Counter()
    wrong = []
    for nummer, p in preds.items():
        if nummer not in gold:
            continue
        g_deontic, g_type = gold[nummer]
        key = g_deontic or f"({g_type})"
        total[key] += 1
        if (p.get("deontic") or None) == g_deontic and p.get("statement_type") == g_type:
            hits[key] += 1
        else:
            wrong.append((nummer, g_deontic or g_type, p.get("deontic") or p.get("statement_type")))
    print("\nagreement vs gold:")
    for key in sorted(total):
        print(f"  {key:12} {hits[key]}/{total[key]}")
    print(f"  overall      {sum(hits.values())}/{sum(total.values())}")
    if wrong:
        print("\ndisagreements (nummer: gold -> predicted):")
        for n, g, p in wrong:
            print(f"  {n}: {g} -> {p}")


def main():
    parser = argparse.ArgumentParser(description="Deontic extraction, switchable local/OpenAI")
    parser.add_argument("--backend", choices=list(BACKENDS), default="ollama")
    parser.add_argument("--model", help="override the backend's default model")
    parser.add_argument("--limit", type=int, help="process only the first N articles")
    parser.add_argument("--write", action="store_true", help="write tags/edges back to Neo4j")
    parser.add_argument("--eval", dest="gold", help="score against a gold CSV")
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
        preds = {}
        for art in articles:
            pred = classify(client, model, art)
            preds[art["nummer"]] = pred
            flag = " ".join(f"{o['target']}:{o['type']}" for o in (pred.get("overrides") or []))
            print(f"{art['nummer']:>8}  {pred.get('statement_type','?'):12} {str(pred.get('deontic')):11} {flag}")
            if args.write:
                write_back(driver, art["nummer"], pred, f"{args.backend}:{model}")
        if args.gold:
            evaluate(preds, args.gold)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
