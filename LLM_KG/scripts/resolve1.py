"""Resolve model-extracted visible references against text-only document structure."""
import re


def normal(value):
    return str(value or '').strip().rstrip('.').casefold()


def resolve_reference(ref, article, corpus):
    target = ref['target']
    result = dict(ref)
    result.update(resolution='unresolved', target_ids=[])
    scope, kind = target['scope'], target['kind']
    if scope == 'external':
        result['resolution'] = 'external'
        return result
    if scope == 'unknown':
        return result
    number = article['number'] if scope == 'same_article' else target.get('number')
    if not number:
        return result
    if kind == 'section':
        # Context headings are visible source structure. Do not use XML ref attributes.
        candidates = {}
        for record in corpus:
            if record['provenance']['expression_id'] != article['provenance']['expression_id']:
                continue
            for context in record['context']:
                heading = context['heading']
                match = re.match(r'\S+\s+([\d.]+)(?:\s|$)', heading)
                if match and normal(match.group(1)) == normal(number):
                    key = (record['provenance']['expression_id'], context['kind'], heading)
                    candidates[key] = {'kind': context['kind'], 'heading': heading}
        result['section_targets'] = list(candidates.values())
        result['resolution'] = 'resolved_section' if len(candidates) == 1 else 'ambiguous' if candidates else 'unresolved'
        return result
    matches = [a for a in corpus if a['provenance']['expression_id'] == article['provenance']['expression_id']
               and normal(a['number']) == normal(number)]
    if kind == 'paragraph':
        ids = [a['id'] + '#paragraph:' + p['wId'] for a in matches
               for p in a['provenance']['paragraphs'] if normal(p['number']) == normal(target.get('paragraph'))]
    else:
        ids = [a['id'] for a in matches]
    result['target_ids'] = ids
    result['resolution'] = 'resolved' if len(ids) == 1 else 'ambiguous' if ids else 'unresolved'
    if scope == 'same_article' and kind == 'article':
        result['warning'] = 'Self reference retained; not automatically interpreted as self-override'
    return result


def resolve(extraction, article, corpus):
    return [{'statement_id': s['id'], 'references': [resolve_reference(r, article, corpus)
             for r in s['references']]} for s in extraction['statements']]
