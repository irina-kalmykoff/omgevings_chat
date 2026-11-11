from common1 import ROOT, ModelClient, read_jsonl, write_json
from extract1 import extract, retry_extraction, select_reference_passages
from resolve1 import resolve
from validate1 import validate_extraction


ARTICLE_NUMBER = "22.28"
BACKEND = "openai"
MODEL = "gpt-4.1-mini"
OUTPUT_DIR = ROOT / "data" / "extractions"
DEBUG_LOG_DIR = ROOT / "data" / "debug_Log"


def main():
    articles = read_jsonl(ROOT / "data" / "cleaned" / "articles.jsonl")
    matches = [
        article for article in articles
        if article["number"] == ARTICLE_NUMBER
    ]

    if len(matches) != 1:
        raise SystemExit(
            f"Expected one article numbered {ARTICLE_NUMBER!r}, "
            f"found {len(matches)}"
        )

    article = matches[0]
    output_path = OUTPUT_DIR / f"maastricht-{article['number']}.json"
    log_path = DEBUG_LOG_DIR / f"{output_path.name}.calls.jsonl"
    client = ModelClient(BACKEND, MODEL, log_path)
    raw = extract(client, article)
    ambiguities = {}
    result, errors, corrections, warnings = validate_extraction(raw, article, ambiguities)
    if errors and len(errors) == len(ambiguities):
        print(f"Retrying {len(ambiguities)} ambiguous references with candidate passages.", flush=True)
        choices = select_reference_passages(client, article, ambiguities)
        if isinstance(choices, dict) and choices.keys() == ambiguities.keys() and all(
            type(choices[path]) is int and 1 <= choices[path] <= len(spans)
            for path, (_, spans) in ambiguities.items()
        ):
            for path, (evidence, spans) in ambiguities.items():
                start, end = spans[choices[path] - 1]
                corrections.append({
                    "path": path,
                    "old_start": evidence.get("start"),
                    "old_end": evidence.get("end"),
                    "old_quote": evidence["quote"],
                    "start": start,
                    "end": end,
                    "candidate": choices[path],
                })
                evidence.update(quote=article["text"][start:end], start=start, end=end)
            result, errors, new_corrections, warnings = validate_extraction(result, article)
            corrections.extend(new_corrections)
        else:
            errors.append("The retry did not select a valid passage for every ambiguous reference.")
    elif errors:
        print(f"Retrying extraction after {len(errors)} validation error(s).", flush=True)
        raw = retry_extraction(client, article, raw, errors)
        result, errors, corrections, warnings = validate_extraction(raw, article)
    print(f"Model calls logged to {log_path}")
    if errors:
        for error in errors:
            print(f"FAIL | {error}")
        raise SystemExit("Extraction failed validation. The previous result, if any, is still available.")

    print(f"PASS | Extraction validated ({len(corrections)} evidence locations calculated or corrected).")
    for warning in warnings:
        print(f"WARNING | {warning}")

    resolutions = resolve(result, article, articles)

    write_json(output_path, {
        "article_id": article["id"],
        "article_number": article["number"],
        "provenance": article["provenance"],
        "backend": BACKEND,
        "model": MODEL,
        "extraction": result,
        "validation": {"corrections": corrections, "warnings": warnings},
        "resolutions": resolutions,
    })

    print(f"Extraction saved to {output_path}")
    for item in resolutions:
        for reference in item["references"]:
            print(f"{reference['resolution'].upper()} | {item['statement_id']} — {reference['wording']}")


if __name__ == "__main__":
    main()
