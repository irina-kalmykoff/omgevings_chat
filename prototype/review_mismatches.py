"""Document deontic-extraction mismatches against the gold sample.

Re-runs the classifier on exactly the gold-labelled articles, compares each
prediction to the human label, and writes a markdown report of every
disagreement together with the full article text, so the labels can be
adjudicated (is the model wrong, or is the gold label wrong?).

Only the gold articles are classified, so a run is cheap even on a hosted
model. Reuses the extractor's own client and classify logic so the report
reflects the same prompt the main pipeline uses.

Usage:
    python review_mismatches.py --backend openai --model gpt-4o
    python review_mismatches.py --backend ollama --model qwen2.5:7b --out mismatches_7b.md
"""

import argparse
import csv

from neo4j import GraphDatabase

from deontic_extract import make_client, classify, read_articles


def load_gold(path):
    """Read a gold CSV into a mapping.

    Args:
        path: Path to a CSV with columns nummer, deontic, statement_type.

    Returns:
        Dict mapping nummer to a (deontic, statement_type) tuple, where an
        empty deontic cell becomes None.
    """
    gold = {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            gold[row["nummer"]] = (row["deontic"] or None, row["statement_type"])
    return gold


def format_block(art, gold_label, pred):
    """Render one mismatch as a markdown block with the article text.

    Args:
        art: Article dict from read_articles (nummer, opschrift, tekst, leden).
        gold_label: The (deontic, statement_type) tuple from the gold file.
        pred: The model's parsed prediction dict.

    Returns:
        A markdown string: headings, gold-vs-predicted, rationale, and the
        article body quoted so the wording can be checked.
    """
    g_deontic, g_type = gold_label
    overrides = ", ".join(
        f"{o.get('target')}:{o.get('type')}" for o in (pred.get("overrides") or [])
    ) or "none"
    lines = [
        f"## {art['nummer']}  {art.get('opschrift') or ''}".rstrip(),
        "",
        f"- gold:      {g_type} / {g_deontic or '-'}",
        f"- predicted: {pred.get('statement_type')} / {pred.get('deontic') or '-'}",
        f"- predicted overrides: {overrides}",
        f"- rationale: {pred.get('rationale', '')}",
        "",
        "> " + (art.get("tekst") or "").replace("\n", " ").strip(),
    ]
    for lid in art.get("leden", []):
        if lid:
            lines.append("> " + lid.replace("\n", " ").strip())
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Write a mismatch report vs the gold sample")
    parser.add_argument("--backend", choices=["ollama", "openai"], default="openai")
    parser.add_argument("--model", help="override the backend's default model")
    parser.add_argument("--gold", default="gold_deontic.csv")
    parser.add_argument("--out", default="mismatches.md")
    parser.add_argument("--uri", default="bolt://localhost:7687")
    parser.add_argument("--user", default="neo4j")
    parser.add_argument("--password", default="testpassword")
    args = parser.parse_args()

    gold = load_gold(args.gold)
    client, model = make_client(args.backend)
    if args.model:
        model = args.model
    driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password))

    try:
        articles = [a for a in read_articles(driver) if a["nummer"] in gold]
        blocks = []
        agree = 0
        for art in articles:
            pred = classify(client, model, art)
            g_deontic, g_type = gold[art["nummer"]]
            matched = (pred.get("deontic") or None) == g_deontic and pred.get("statement_type") == g_type
            if matched:
                agree += 1
            else:
                blocks.append(format_block(art, gold[art["nummer"]], pred))
    finally:
        driver.close()

    header = (
        f"# Deontic mismatches vs gold ({model})\n\n"
        f"{len(blocks)} mismatches out of {len(articles)} gold articles "
        f"({agree} agree). Each block shows gold vs predicted and the article "
        f"text, so you can decide whether the model or the label is wrong.\n\n"
    )
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(blocks))
    print(f"wrote {args.out}: {len(blocks)} mismatches of {len(articles)} gold articles")


if __name__ == "__main__":
    main()
