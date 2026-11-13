"""Bounded, source-verified replay of observed retrieval decisions.

Ranking diagnostics never leave the server directly. Candidate rows are not
citations; only IDs in this column's selected evidence can become citations.
Graph paths describe the shortest paths actually used for priority ordering,
not all BFS visits, model reasoning, runtime reachability or proof of safety.
"""
import json

from .task_compare import EVIDENCE_BYTES, K, digest, node_id


SCHEMA = 'lianzheng-retrieval-trace-v1'
MAX_CANDIDATES = 32
MAX_TARGETS = 12
MAX_PATHS = 3
MAX_PATH_NODES = 16
MAX_TRACE_BYTES = 64000
MAX_DECLARATION_EXCERPT = 800


def unavailable_trace(binding, method):
    return {**binding, 'schema': SCHEMA, 'method': method, 'status': 'unavailable',
            'reason': '本次检索轨迹校验未通过，可继续查看答案与已取回证据。'}


def _resolve(value, pointer):
    for part in pointer.lstrip('/').split('/') if pointer else []:
        part = part.replace('~1', '/').replace('~0', '~')
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def build_retrieval_trace(state, method, documents, selected, identifiers,
                          ranked, ranking, selection, used_bytes, locators):
    """Serialize only actual rank/selection decisions in one captured context.

    ``documents`` have internal IDs, whereas ``selected`` have public scoped
    IDs. A failed invariant raises instead of guessing a replacement trace.
    The caller can then present a small, non-replayable unavailable record.
    """
    binding = state['binding']
    if method not in ('bm25', 'bm25+graph') or binding.get('scope') != 'snapshot':
        raise ValueError('Invalid trace binding')
    lookup = {d['id']: d for d in documents}
    if identifiers != {key: 'ev-' + digest([binding, key])[:32] for key in lookup}:
        raise ValueError('Invalid evidence namespace')
    public_lookup = {identifiers[key]: doc for key, doc in lookup.items()}
    selected_ids = [d['id'] for d in selected]
    if len(set(selected_ids)) != len(selected_ids):
        raise ValueError('Duplicate selected evidence')
    for doc in selected:
        if doc['id'] not in public_lookup or any(doc.get(k) != v for k, v in binding.items()):
            raise ValueError('Foreign selected evidence')
        if doc != {**public_lookup[doc['id']], 'id': doc['id']}:
            raise ValueError('Changed selected evidence')
    if used_bytes != sum(len(json.dumps(d, ensure_ascii=False).encode()) for d in selected):
        raise ValueError('Evidence byte budget mismatch')
    if len(selected) > K or not 0 <= used_bytes <= EVIDENCE_BYTES:
        raise ValueError('Evidence budget exceeded')
    if len(set(ranked)) != len(ranked) or any(key not in lookup for key in ranked):
        raise ValueError('Invalid final ranking')
    decisions = selection['decisions']
    expected_selected = [identifiers[key] for key in ranked if decisions.get(identifiers[key]) == 'selected']
    if expected_selected != selected_ids:
        raise ValueError('Selection differs from recorded decisions')
    if set(decisions) - {identifiers[key] for key in ranked}:
        raise ValueError('Unranked selection decision')
    if any(value not in ('selected', 'skipped-budget') for value in decisions.values()):
        raise ValueError('Unobserved selection reason')
    if selection['not_considered_count'] != len(ranked) - len(decisions):
        raise ValueError('Selection count mismatch')
    if selection['skipped_budget_count'] != sum(v == 'skipped-budget' for v in decisions.values()):
        raise ValueError('Skipped count mismatch')
    stop = selection['stop_rank']
    if stop is not None and (stop != len(decisions) + 1 or len(selected) != K):
        raise ValueError('Invalid count-limit boundary')
    if (stop is None) != (len(decisions) == len(ranked)):
        raise ValueError('Unrecorded count-limit boundary')
    for position, key in enumerate(ranked, 1):
        if (identifiers[key] in decisions) != (stop is None or position < stop):
            raise ValueError('Non-contiguous selection decisions')

    lexical = {key: index for index, key in enumerate(ranking['lexical_ids'], 1)}
    priority = {key: index for index, key in enumerate(ranking['priority_ids'], 1)}
    positions = {key: index for index, key in enumerate(ranked, 1)}
    # Retain every selected row even if the first candidates all exceeded the
    # byte budget. Show a bounded sample of both lexical and final orderings.
    visible = set(ranked[:16]) | set(ranking['lexical_ids'][:8])
    visible.update(key for key in ranked if identifiers[key] in selected_ids)
    candidates = []
    for key in sorted(visible, key=positions.__getitem__):
        public_id = identifiers[key]
        decision = decisions.get(public_id, 'not-considered-limit')
        row = {**binding, 'id': 'candidate-' + digest([binding, key])[:32],
               'title': lookup[key]['title'][:200], 'final_rank': positions[key],
               'lexical_rank': lexical.get(key), 'graph_priority_rank': priority.get(key),
               'status': decision}
        if decision == 'selected':
            row['evidence_id'] = public_id
        candidates.append(row)
    if len(candidates) > MAX_CANDIDATES:
        raise ValueError('Candidate display limit exceeded')

    nodes = {n['id']: n for n in state['graph']['nodes']}
    actual_edges = {(e['source'], e['target']): e for e in state['graph']['edges']}
    source = state['source']
    common = {**binding, 'filename': source['filename'], 'source_sha256': source['raw_source_sha256']}
    selected_nodes = {}
    selected_edges = {}
    for doc in selected:
        if doc.get('kind') == 'occurrence' and doc.get('source_sha256') == source['raw_source_sha256']:
            selected_nodes.setdefault(doc['ref'], []).append(doc['id'])
            for edge in doc.get('relations', []):
                pair = (edge['source'], edge['target'])
                if pair in actual_edges and all(edge.get(k) == v for k, v in binding.items()):
                    selected_edges.setdefault(pair, []).append(doc['id'])

    def source_node(ref):
        node = nodes[ref]
        pointer = locators[ref]
        expected_pointer = node['locator']
        if state['is_lock']:
            component = _resolve(state['raw'], node['locator'])
            props = {p['name']: p['value'] for p in component.get('properties', [])}
            expected_pointer = props.get('lianzheng:npm:source-pointer')
        if pointer != expected_pointer:
            raise ValueError('Graph node points to a different source component')
        if not isinstance(_resolve(state['origin'], pointer), dict):
            raise ValueError('Invalid graph node source')
        return {**common, 'ref': ref, 'name': node['name'], 'version': node['version'],
                'locator': pointer, 'evidence_ids': selected_nodes.get(ref, [])}

    targets = []
    for ref in ranking['matched_refs'][:MAX_TARGETS]:
        row = source_node(ref)
        if row['evidence_ids']:
            row['evidence_id'] = row['evidence_ids'][0]
        targets.append(row)
    declarations = {}
    if state['is_lock']:
        for relation in json.loads(state['properties'].get('lianzheng:import:relationships', '[]')):
            declarations.setdefault((relation['source'], relation.get('target')), relation)

    def source_edge(a, b):
        edge = actual_edges[(a, b)]  # Never synthesize a missing graph edge.
        if state['is_lock']:
            relation = declarations[(a, b)]
            pointer = relation['source_pointer']
            declaration = _resolve(state['origin'], pointer)
            if declaration != relation['declared_spec']:
                raise ValueError('Graph declaration differs from saved lockfile')
        else:
            pointer = edge['locator']
            declaration = _resolve(state['origin'], pointer)
            if declaration != b:
                raise ValueError('Graph declaration differs from saved manifest')
        excerpt = json.dumps(declaration, ensure_ascii=False, sort_keys=True)
        evidence_ids = []
        for identifier in selected_edges.get((a, b), []):
            doc = next(d for d in selected if d['id'] == identifier)
            if any(r['source'] == a and r['target'] == b and r['locator'] == pointer
                   for r in doc.get('relations', [])):
                evidence_ids.append(identifier)
        return {**common, 'source': a, 'target': b, 'locator': pointer,
                'source_locator': locators[a], 'target_locator': locators[b],
                'evidence_ids': evidence_ids, 'declaration_excerpt': excerpt[:MAX_DECLARATION_EXCERPT],
                'declaration_excerpt_truncated': len(excerpt) > MAX_DECLARATION_EXCERPT,
                'declaration_excerpt_kind': 'saved-source-content'}

    paths = []
    for full_path in ranking['priority_paths'][:MAX_PATHS]:
        if not full_path or full_path[0] != state['graph']['root'] or full_path[-1] not in ranking['matched_refs']:
            raise ValueError('Unmatched graph traversal path')
        refs = full_path[:MAX_PATH_NODES]
        truncated = len(refs) < len(full_path)
        paths.append({**binding, 'id': 'retrieval-path-' + digest([binding, full_path])[:24],
                      'nodes': [source_node(ref) for ref in refs],
                      'edges': [source_edge(a, b) for a, b in zip(refs, refs[1:])],
                      'node_count': len(full_path), 'complete': not truncated, 'truncated': truncated})
    status = ranking['graph_status']
    if status not in ('text-only', 'no-matched-targets', 'no-path-intent', 'applied'):
        raise ValueError('Unknown graph decision')
    if (method == 'bm25') != (status == 'text-only'):
        raise ValueError('Graph decision does not match method')
    if status != 'applied' and (paths or priority):
        raise ValueError('Graph priority was not executed')
    graph = {**binding, 'status': status, 'matched_targets': targets,
             'matched_target_count': len(ranking['matched_refs']),
             'targets_truncated': len(targets) < len(ranking['matched_refs']),
             'paths': paths, 'path_count': len(ranking['priority_paths']),
             'paths_truncated': len(paths) < len(ranking['priority_paths']) or any(p['truncated'] for p in paths)}
    explanation = {'text-only': '本侧仅按 BM25 文本相关度排序，未执行组件匹配或图优先排序。',
                   'no-matched-targets': '没有按组件名和版本规则命中目标，沿用文本排序。',
                   'no-path-intent': '命中了组件，但问题未触发路径类检索，沿用文本排序。',
                   'applied': '实际优先放入目标位置，再沿根到目标的最短路径逆序补入祖先；不补造缺失边。'}
    steps = [
        {'id': 'lexical', 'label': '文本召回', 'count': len(lexical),
         'detail': 'BM25 只保留正分候选；同分按内部稳定标识排序。'},
        {'id': 'entity-match', 'label': '目标匹配', 'count': len(ranking['matched_refs']),
         'detail': '文本侧不执行此步骤。' if status == 'text-only' else '使用问题中的完整组件名；出现版本号时同时约束版本。'},
        {'id': 'graph-priority', 'label': '图优先排序', 'count': len(priority), 'detail': explanation[status]},
        {'id': 'budget', 'label': '证据入选', 'count': len(selected),
         'detail': '按最终顺序入选；超字节预算的条目跳过，达到 8 条后停止。候选不等于回答证据。'},
    ]
    trace = {**binding, 'schema': SCHEMA, 'status': 'ready', 'method': method,
             'graph': graph, 'candidates': candidates, 'candidate_count': len(ranked),
             'candidates_truncated': len(candidates) < len(ranked),
             'lexical_candidate_count': len(lexical), 'graph_priority_count': len(priority),
             'selected_evidence_ids': selected_ids,
             'selection': {'limit': K, 'max_bytes': EVIDENCE_BYTES, 'used_bytes': used_bytes,
                           'selected_count': len(selected), 'skipped_budget_count': selection['skipped_budget_count'],
                           'not_considered_count': selection['not_considered_count']},
             'steps': [{**binding, **step} for step in steps],
             'note': '记录本次排序与截断的实际过程；不是模型思维过程、全图遍历或答案正确性评分。未入选位置无原文引用入口。'}
    # Source paths can contain long refs/locators. Enforce a serialized cap as
    # well as list limits, retaining every selected candidate throughout.
    while len(json.dumps(trace, ensure_ascii=False).encode()) > MAX_TRACE_BYTES:
        if paths:
            paths.pop(); graph['paths_truncated'] = True
        elif targets:
            targets.pop(); graph['targets_truncated'] = True
        else:
            removable = next((i for i in range(len(candidates) - 1, -1, -1)
                              if candidates[i]['status'] != 'selected'), None)
            if removable is None:
                raise ValueError('Trace exceeds presentation budget')
            candidates.pop(removable); trace['candidates_truncated'] = True
    return trace
