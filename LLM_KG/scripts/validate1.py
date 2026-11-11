"""Fail-closed evidence/schema validation. Raw responses are retained separately."""
import copy
import math
import re

RELATIONS = {'refers_to', 'excepts', 'restricts', 'modifies', 'takes_precedence_over', 'applies_analogously'}


def evidence_check(evidence, text, path, errors, corrections, parent_span=None, ambiguities=None):
    if not isinstance(evidence, dict) or not isinstance(evidence.get('quote'), str) or not evidence['quote'].strip():
        errors.append(path + ': missing nonempty exact evidence'); return
    quote = evidence['quote']
    start, end = evidence.get('start'), evidence.get('end')
    if type(start) is int and type(end) is int and 0 <= start < end <= len(text) and text[start:end] == quote:
        return start, end

    first = text.find(quote)
    if first >= 0 and text.find(quote, first + 1) >= 0:
        first = -1
        if parent_span is not None:
            parent_start, parent_end = parent_span
            match = text.find(quote, parent_start, parent_end)
            if match >= 0 and text.find(quote, match + 1, parent_end) < 0:
                first = match

    correction = {'path': path, 'old_start': start, 'old_end': end}
    if first >= 0:
        start, end = first, first + len(quote)
    else:
        # Allow layout differences while preserving the exact wording and punctuation.
        pattern = re.compile(r'\s+'.join(re.escape(word) for word in quote.split()))
        match = unique_match(pattern, text, 0, len(text))
        if match is None and parent_span is not None:
            match = unique_match(pattern, text, *parent_span)
        if match is None:
            if ambiguities is not None:
                bounds = parent_span or (0, len(text))
                spans = list(matching_spans(pattern, text, *bounds))
                if len(spans) < 2 and parent_span is not None:
                    spans = list(matching_spans(pattern, text, 0, len(text)))
                if len(spans) > 1:
                    ambiguities[path] = (evidence, spans)
            errors.append(path + ': quotation absent or offsets ambiguous')
            return None

        start, end = match
        correction['old_quote'] = quote
        evidence['quote'] = text[start:end]

    correction.update(start=start, end=end)
    corrections.append(correction)
    evidence.update(start=start, end=end)
    return start, end


def matching_spans(pattern, text, start, end):
    match = pattern.search(text, start, end)
    while match is not None:
        yield match.span()
        match = pattern.search(text, match.start() + 1, end)


def unique_match(pattern, text, start, end):
    matches = matching_spans(pattern, text, start, end)
    first = next(matches, None)
    if first is not None and next(matches, None) is None:
        return first
    return None


def validate_extraction(value, article, ambiguities=None):
    clean = copy.deepcopy(value)
    errors, corrections, warnings = [], [], []
    if not isinstance(clean, dict) or not isinstance(clean.get('statements'), list):
        return clean, ['Expected an object containing statements list'], [], []
    if not isinstance(clean.get('coverage_note'), str):
        errors.append('coverage_note must be a string')
    seen = set()
    for index, statement in enumerate(clean['statements']):
        path = f'statements[{index}]'
        if not isinstance(statement, dict):
            errors.append(path + ': must be an object'); continue
        sid = statement.get('id')
        if not isinstance(sid, str) or not sid or sid in seen:
            errors.append(path + ': id must be a unique nonempty string')
        else:
            seen.add(sid)
        for field in ('description', 'legal_character'):
            if not isinstance(statement.get(field), str) or not statement[field].strip():
                errors.append(path + ': missing ' + field)
        parent_span = evidence_check(
            statement.get('evidence'), article['text'], path + '.evidence', errors, corrections
        )
        confidence = statement.get('confidence')
        if type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            errors.append(path + ': confidence must be a finite number in [0,1]')
        if not isinstance(statement.get('uncertainty'), list) or any(not isinstance(s, str) for s in statement.get('uncertainty', [])):
            errors.append(path + ': uncertainty must be a list of strings')
        parts = []
        for field in ('action', 'addressee'):
            if field not in statement:
                errors.append(path + ': missing ' + field)
            elif statement[field] is not None:
                parts.append((field, statement[field]))
        for field in ('conditions', 'temporal'):
            if not isinstance(statement.get(field), list):
                errors.append(path + ': ' + field + ' must be a list')
            else:
                parts.extend((field + f'[{i}]', v) for i, v in enumerate(statement[field]))
        for name, part in parts:
            if not isinstance(part, dict) or not isinstance(part.get('text'), str) or not part['text'].strip():
                errors.append(path + '.' + name + ': invalid text object'); continue
            evidence_check(
                part.get('evidence'), article['text'], path + '.' + name, errors, corrections, parent_span
            )
        if not isinstance(statement.get('references'), list):
            errors.append(path + ': references must be a list'); continue
        for i, ref in enumerate(statement['references']):
            rpath = path + f'.references[{i}]'
            if not isinstance(ref, dict):
                errors.append(rpath + ': invalid reference'); continue
            evidence_check(
                ref.get('evidence'), article['text'], rpath, errors, corrections, parent_span, ambiguities
            )
            if not isinstance(ref.get('wording'), str) or not ref['wording'].strip():
                errors.append(rpath + ': missing wording')
            if not isinstance(ref.get('relation'), str) or ref['relation'] not in RELATIONS:
                errors.append(rpath + ': invalid relation')
            target = ref.get('target')
            if not isinstance(target, dict):
                errors.append(rpath + ': invalid target'); continue
            if target.get('scope') not in ('same_article', 'same_document', 'external', 'unknown'):
                errors.append(rpath + ': invalid target scope')
            if target.get('kind') not in ('article', 'paragraph', 'section'):
                errors.append(rpath + ': invalid target kind')
            for field in ('number', 'paragraph', 'external_document'):
                if target.get(field) is not None and not isinstance(target[field], str):
                    errors.append(rpath + ': target fields must be strings or null')
    if not clean['statements']:
        warnings.append('No statements extracted; inspect coverage_note, not a claim of complete coverage')
    if errors:
        return clean, errors, corrections, warnings
    # Flag overlaps/duplicates and conflicting interpretations without deleting them.
    for i, a in enumerate(clean['statements']):
        for b in clean['statements'][i + 1:]:
            if a['evidence']['quote'] == b['evidence']['quote']:
                warnings.append(f'Overlapping evidence: {a["id"]}, {b["id"]}; possible duplicate or mixed interpretation')
    return clean, errors, corrections, warnings


def validate_baseline(value):
    if not isinstance(value, dict):
        return ['Expected baseline object']
    errors = []
    st, deontic = value.get('statement_type'), value.get('deontic')
    if st not in {'prescriptive', 'constitutive'}:
        errors.append('Invalid statement_type')
    if (st == 'constitutive' and deontic is not None) or (st == 'prescriptive' and deontic not in {'obligation', 'prohibition', 'permission', 'exemption'}):
        errors.append('Invalid deontic for statement type')
    if not isinstance(value.get('overrides'), list):
        errors.append('overrides must be a list')
    else:
        for ref in value['overrides']:
            if not isinstance(ref, dict) or ref.get('type') not in {'exception', 'restriction'} or not isinstance(ref.get('target'), str):
                errors.append('Invalid baseline override')
    if not isinstance(value.get('rationale'), str):
        errors.append('Missing rationale')
    return errors


def validate_alignment(value, statements, profile):
    if not isinstance(value, dict) or not isinstance(value.get('alignments'), list):
        return ['Expected alignments list']
    expected = {s['id'] for s in statements}
    seen, errors = set(), []
    for item in value['alignments']:
        if not isinstance(item, dict):
            errors.append('Invalid alignment object'); continue
        sid, status = item.get('statement_id'), item.get('status')
        if sid not in expected or sid in seen:
            errors.append('Unknown/duplicate statement alignment')
        seen.add(sid)
        if status not in profile['alignment_statuses']:
            errors.append('Unknown alignment status')
        if status == 'mapped' and item.get('concept') not in profile['concepts']:
            errors.append('Mapped concept outside profile')
        if status != 'mapped' and item.get('concept') is not None:
            errors.append('Unmapped/ambiguous alignment must have null concept')
        alternatives = item.get('alternatives')
        if not isinstance(alternatives, list) or any(c not in profile['concepts'] for c in alternatives):
            errors.append('Invalid alternatives')
        if not isinstance(item.get('rationale'), str) or not item['rationale'].strip():
            errors.append('Missing alignment rationale')
    if expected != seen:
        errors.append('Every statement must have exactly one alignment')
    return errors
