"""Bound model input without changing the original, user-visible evidence."""
import copy
import json


MAX_INPUT_BYTES = 48_000
MAX_EVIDENCE_CHARS = 4_000
MIN_EVIDENCE_CHARS = 240


def input_size(system, question, context):
    messages = [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': json.dumps({'question': question, **context}, ensure_ascii=False)},
    ]
    return len(json.dumps(messages, ensure_ascii=False).encode('utf-8'))


def bounded_context(system, question, context, limit_bytes=MAX_INPUT_BYTES,excerpt_selector=None):
    """Return a bounded copy and an explicit receipt; bytes are not token counts.

    Facts, versions and complete path strings are never silently rewritten. If
    those immutable facts alone are too large, the caller must skip the API.
    Optional excerpt selection retains explicit source ranges; the default uses prefixes.
    """
    result = copy.deepcopy(context)
    evidence = result.setdefault('evidence', [])
    original = {item['id']: item.get('text', '') for item in evidence}
    omitted_ids = [item['id'] for item in evidence[8:]]
    result['evidence'] = evidence = evidence[:8]
    def resize(item,limit):
        source=original[item['id']]
        if excerpt_selector:
            item['text'],ranges=excerpt_selector(source,question,limit)
            if ranges:item['excerpt_ranges']=ranges
            else:item.pop('excerpt_ranges',None)
        else:item['text']=source[:limit]
    for item in evidence:resize(item,MAX_EVIDENCE_CHARS)
    original_turns = len(result.get('conversation', []))
    result['conversation'] = result.get('conversation', [])[-3:]
    for turn in result['conversation']:
        if isinstance(turn.get('question'), str):
            turn['question'] = turn['question'][:800]

    def size():
        return input_size(system, question, result)

    while size() > limit_bytes:
        longest = max(evidence, key=lambda item: len(item['text']), default=None)
        if longest and len(longest['text']) > MIN_EVIDENCE_CHARS:
            resize(longest,max(MIN_EVIDENCE_CHARS, len(longest['text']) // 2))
        elif result['conversation']:
            result['conversation'].pop(0)
        elif len(evidence) > 1:
            omitted_ids.append(evidence.pop()['id'])
        else:
            break
    truncated_ids = [item['id'] for item in evidence if item['text'] != original[item['id']]]
    # Account for the marker itself in the final limit rather than hiding it.
    for item in evidence:
        if item['id'] in truncated_ids:
            item['excerpted'] = True
    while size() > limit_bytes and len(evidence) > 1:
        omitted_ids.append(evidence.pop()['id'])
    truncated_ids = [item['id'] for item in evidence if item['text'] != original[item['id']]]
    used = size()
    report = {
        'input_bytes': used,
        'limit_bytes': limit_bytes,
        'unit': 'UTF-8 serialized messages; not a token count',
        'evidence_count': len(evidence),
        'truncated_evidence': len(truncated_ids),
        'truncated_evidence_ids': truncated_ids,
        'omitted_evidence': len(omitted_ids),
        'omitted_evidence_ids': omitted_ids,
        'history_turns': len(result['conversation']),
        'omitted_history_turns': original_turns - len(result['conversation']),
        'blocked': used > limit_bytes,
        'excerpt_selection':'question-ranked' if excerpt_selector else 'prefix',
    }
    return result, report
