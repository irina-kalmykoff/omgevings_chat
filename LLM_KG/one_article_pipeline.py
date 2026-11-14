import argparse
from datetime import datetime, timezone
from uuid import uuid4

from common1 import ROOT, ModelClient, fingerprint, read_json, read_jsonl, write_json
from align1 import ALIGN_PROMPT, alignment_payload
from verify1 import VERIFY_PROMPT, verification_payload, validate_verification
from extract1 import extract, retry_extraction, select_reference_passages
from resolve1 import resolve
from validate1 import validate_extraction, validate_alignment

"""read article by number
  -> extract (model)
  -> validate_extraction
       |- only ambiguous-reference errors -> model picks a candidate passage -> re-validate
       |- any other errors                -> one full retry with the error list -> re-validate
       '- still errors                     -> print FAIL lines and exit (nothing saved)
  -> resolve references (deterministic)
  -> build the record (hashes, run id, provenance)
  -> align   (model, validated, one repair attempt)
  -> verify  (model, validated, one repair attempt, optionally a different model)
  -> save to data/extractions/maastricht-<number>.json"""

ARTICLE_NUMBER = "22.28"
BACKEND = "openai"
MODEL = "gpt-4.1-mini"
OUTPUT_DIR = ROOT / "data" / "extractions"
DEBUG_LOG_DIR = ROOT / "data" / "debug_Log"


def checked_stage(client, article, stage, prompt, payload, validator, attempts):
    """a generic wrapper used for alignment and verification. It makes up to two attempts:
    Attempt 0 sends the normal prompt and payload, under the stage name (align, verify).
    If validation fails, attempt 1 sends the same prompt plus an extra line (“Correct the listed validation errors...”)"""
    request = payload
    for attempt in range(2):
        instruction = prompt if attempt == 0 else prompt + '\nCorrect the listed validation errors; return the full response using the original context.'
        try:
            value = client.call(stage if attempt == 0 else stage + '_repair',
                                article['id'], instruction, request)
        except Exception as error:
            attempts.append({'stage': stage, 'attempt': attempt, 'response': None, 'errors': [str(error)]})
            raise
        errors = validator(value)
        attempts.append({'stage': stage, 'attempt': attempt, 'response': value, 'errors': errors})
        if not errors:
            return value
        request = {**payload, 'previous_response': value, 'validation_errors': errors,
                   'repair_instruction': 'Return the complete corrected response using the original context.'}
    raise ValueError(stage + ' failed validation: ' + '; '.join(errors))


def enrich(record, article, articles, profile, client, mode='verified', verifier=None):
    """Retain failed stage diagnostics; never turn a negative review into success."""
    if mode not in ('extract', 'aligned', 'verified'):
        raise ValueError('Unknown mode')
    record.update(status='completed', mode=mode, stage_attempts=[],
                  review_status='not_run', alignment=None, verification=None)
    if mode == 'extract':
        return record
    record['profile'] = {'id': profile['id'], 'version': profile['version'],
                         'sha256': fingerprint(profile)}
    extraction = record['extraction']
    try:
        record['alignment'] = checked_stage(client, article, 'align', ALIGN_PROMPT,
            alignment_payload(article, extraction, profile),
            lambda value: validate_alignment(value, extraction['statements'], profile), record['stage_attempts'])
        if mode == 'verified':
            record['verification'] = checked_stage(verifier or client, article, 'verify', VERIFY_PROMPT,
                verification_payload(article, extraction, record['alignment'], record['resolutions'], articles, profile),
                lambda value: validate_verification(value, extraction), record['stage_attempts'])
            verdicts = [j['verdict'] for j in record['verification']['judgments']]
            verdicts.append(record['verification']['article_review']['verdict'])
            record['review_status'] = ('unsupported' if 'unsupported' in verdicts else
                                       'uncertain' if 'uncertain' in verdicts else 'supported')
    except Exception as error:
        record.update(status='failed', review_status='incomplete', error=str(error))
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description='Extract, align and review one article with full text evidence.')
    parser.add_argument('--article', default=ARTICLE_NUMBER)
    parser.add_argument('--backend', choices=('openai', 'ollama'), default=BACKEND)
    parser.add_argument('--model', help='Defaults to MODEL for OpenAI or qwen2.5:32b for Ollama')
    parser.add_argument('--verifier-model', help='Optional separate review model on the same backend')
    parser.add_argument('--mode', choices=('extract', 'aligned', 'verified'), default='verified')
    args = parser.parse_args(argv)
    args.model = args.model or (MODEL if args.backend == 'openai' else 'qwen2.5:32b')
    articles = read_jsonl(ROOT / "data" / "cleaned" / "articles.jsonl")
    matches = [
        article for article in articles
        if article["number"] == args.article
    ]

    if len(matches) != 1:
        raise SystemExit(
            f"Expected one article numbered {args.article!r}, "
            f"found {len(matches)}"
        )

    article = matches[0]
    output_path = OUTPUT_DIR / f"maastricht-{article['number']}.json"
    log_path = DEBUG_LOG_DIR / f"{output_path.name}.calls.jsonl"
    client = ModelClient(args.backend, args.model, log_path)
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

    record = {
        "article_id": article["id"],
        "article_number": article["number"],
        "provenance": article["provenance"],
        "backend": args.backend,
        "model": args.model,
        "verifier_model": args.verifier_model or args.model,
        "run_id": str(uuid4()),
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "input_sha256": fingerprint(article),
        "code_sha256": {p.name: fingerprint(p.read_text(encoding='utf-8'))
                        for p in sorted((ROOT / 'scripts').glob('*.py'))},
        "extraction": result,
        "validation": {"corrections": corrections, "warnings": warnings},
        "resolutions": resolutions,
    }
    profile = read_json(ROOT / 'ontology' / 'automatic-profile1.json')
    verifier = (ModelClient(args.backend, args.verifier_model, log_path)
                if args.mode == 'verified' and args.verifier_model else client)
    enrich(record, article, articles, profile, client, args.mode, verifier)
    if record['status'] == 'failed':
        failure_path = output_path.with_suffix('.failed.json')
        write_json(failure_path, record)
        raise SystemExit(f"Stage failed; diagnostics saved to {failure_path}. Previous result preserved. {record['error']}")
    write_json(output_path, record)
    print(f"Result saved to {output_path}; model review: {record['review_status']} (not legal approval)")
    for item in resolutions:
        for reference in item["references"]:
            print(f"{reference['resolution'].upper()} | {item['statement_id']} — {reference['wording']}")


if __name__ == "__main__":
    main()
