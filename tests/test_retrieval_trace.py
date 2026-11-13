"""Regression coverage for observed, scoped retrieval replay (no model calls)."""
import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from lianzheng.project_query import ProjectContextChanged, ProjectQuery, _resolve
from lianzheng.retrieval_trace import (MAX_CANDIDATES, MAX_DECLARATION_EXCERPT, MAX_PATH_NODES, MAX_PATHS,
                                     MAX_TARGETS, MAX_TRACE_BYTES, build_retrieval_trace)
from lianzheng.service import Service
from lianzheng.task_compare import (EVIDENCE_BYTES, K, digest, entities, lexical_rank,
                                   node_id, rank, rank_with_trace, select_evidence,
                                   select_evidence_with_trace)


ROOT = Path(__file__).resolve().parent.parent


def manifest(count=2, same_name=False, chain=False):
    refs = ['ref-' + str(i) for i in range(count)]
    return {'bomFormat': 'CycloneDX', 'specVersion': '1.5', 'version': 1,
            'metadata': {'component': {'type': 'application', 'bom-ref': 'root', 'name': 'example', 'version': '1.0.0'}},
            'components': [{'type': 'library', 'bom-ref': ref,
                            'name': 'minimist' if same_name or i == count - 1 else 'helper' + str(i),
                            'version': '1.2.5'} for i, ref in enumerate(refs)],
            'dependencies': [{'ref': 'root', 'dependsOn': refs[:1] if chain else refs}] +
                            [{'ref': ref, 'dependsOn': refs[i+1:i+2] if chain else []} for i, ref in enumerate(refs)]}


@pytest.fixture
def query(tmp_path):
    service = Service(tmp_path / 'work.sqlite3', ROOT / 'fixtures')
    for identifier in ('alpha', 'beta'):
        service.import_bom(manifest(chain=True), project=identifier, label='current', identifier=identifier)
    return ProjectQuery(service)


def ask(query, identifier='alpha', question='minimist 的依赖路径是什么？'):
    context = query.context(identifier)
    return query.ask(identifier, question, context['source']['context_sha256'])


def trace_input(query, question='minimist 的依赖路径是什么？', method='bm25+graph'):
    state = query._capture('alpha')
    docs, locators = query._corpus(state, question)
    ids = {d['id']: 'ev-' + digest([state['binding'], d['id']])[:32] for d in docs}
    public = [{**d, 'id': ids[d['id']]} for d in docs]
    ranked, ranking = rank_with_trace(question, docs, state['graph'], method)
    selected, used, selection = select_evidence_with_trace([ids[key] for key in ranked], public)
    return dict(state=state, method=method, documents=docs, selected=selected,
                identifiers=ids, ranked=ranked, ranking=ranking, selection=selection,
                used_bytes=used, locators=locators)


def test_actual_rank_matches_legacy_priority_and_lexical_order(query):
    data = trace_input(query)
    question = 'minimist 的依赖路径是什么？'
    docs, graph = data['documents'], data['state']['graph']
    lexical = lexical_rank(question, docs)
    promoted = [node_id('ref-1'), node_id('ref-0')]
    expected = list(dict.fromkeys(promoted + lexical))
    assert rank(question, docs, graph, 'bm25') == lexical
    assert data['ranked'] == rank(question, docs, graph, 'bm25+graph') == expected
    assert data['ranking']['lexical_ids'] == lexical
    assert data['ranking']['priority_ids'] == promoted
    assert data['ranking']['priority_paths'] == [['root', 'ref-0', 'ref-1']]
    assert data['ranking']['matched_refs'] == ['ref-1']
    trace = build_retrieval_trace(**data)
    assert [c['final_rank'] for c in trace['candidates']] == list(range(1, len(expected) + 1))
    for row in trace['candidates']:
        internal = expected[row['final_rank'] - 1]
        assert row['lexical_rank'] == (lexical.index(internal) + 1 if internal in lexical else None)
        assert row['graph_priority_rank'] == (promoted.index(internal) + 1 if internal in promoted else None)


@pytest.mark.parametrize('question,status,targets', [
    ('minimist 路径', 'applied', ['ref-1']),
    ('MINIMIST 直接依赖', 'applied', ['ref-1']),
    ('minimist 1.2.5 路径', 'applied', ['ref-1']),
    ('minimist 2.0.0 路径', 'no-matched-targets', []),
    ('x-minimist 路径', 'no-matched-targets', []),
    ('minimist-extra 路径', 'no-matched-targets', []),
    ('@scope/minimist 路径', 'no-matched-targets', []),
    ('minimist的依赖', 'no-matched-targets', []),
    ('minimist 是什么', 'no-path-intent', ['ref-1']),
    ('未知组件 路径', 'no-matched-targets', []),
    ('', 'no-matched-targets', []),
])
def test_named_target_matching_preserves_existing_semantics(query, question, status, targets):
    state = query._capture('alpha')
    docs, _ = query._corpus(state, question)
    ranked, observed = rank_with_trace(question, docs, state['graph'], 'bm25+graph')
    assert observed['matched_refs'] == entities(question, state['graph']) == targets
    assert observed['graph_status'] == status
    assert ranked == rank(question, docs, state['graph'], 'bm25+graph')
    if status != 'applied':
        assert ranked == lexical_rank(question, docs)
        assert observed['priority_ids'] == observed['priority_paths'] == []


def test_empty_corpus_has_no_invented_selection():
    graph = {'root': 'root', 'nodes': [], 'edges': []}
    ranked, observed = rank_with_trace('', [], graph, 'bm25+graph')
    selected, used, selection = select_evidence_with_trace(ranked, [])
    assert ranked == selected == observed['matched_refs'] == []
    assert used == selection['not_considered_count'] == selection['skipped_budget_count'] == 0
    assert selection['decisions'] == {}


def test_budget_skip_and_count_limit_are_different_actual_decisions():
    docs = [{'id': 'too-large', 'title': 'oversize', 'text': 'x' * EVIDENCE_BYTES}]
    docs += [{'id': 'small-' + str(i), 'title': 'small', 'text': 'x'} for i in range(K + 3)]
    ids = [d['id'] for d in docs]
    selected, used, observed = select_evidence_with_trace(ids, docs)
    assert (selected, used) == select_evidence(ids, docs)
    assert [d['id'] for d in selected] == ids[1:K+1]
    assert observed['decisions']['too-large'] == 'skipped-budget'
    assert observed['skipped_budget_count'] == 1
    assert observed['stop_rank'] == K + 2
    assert observed['not_considered_count'] == 3
    assert ids[-1] not in observed['decisions']


def test_budget_skips_remain_candidates_without_citations_and_late_selection_is_visible(query):
    data = trace_input(query)
    original = data['documents']
    large = [{**original[0], 'id': 'oversize-' + str(i), 'title': 'oversize',
              'text': 'x' * EVIDENCE_BYTES} for i in range(40)]
    small = [{**original[0], 'id': 'small-' + str(i), 'title': 'small'} for i in range(12)]
    data['documents'] = large + small
    binding = data['state']['binding']
    data['identifiers'] = {d['id']: 'ev-' + digest([binding, d['id']])[:32] for d in data['documents']}
    data['ranked'] = [d['id'] for d in data['documents']]
    data['ranking'] = {'lexical_ids': data['ranked'], 'matched_refs': [],
                       'priority_ids': [], 'priority_paths': [], 'graph_status': 'text-only'}
    data['method'] = 'bm25'
    public = [{**d, 'id': data['identifiers'][d['id']]} for d in data['documents']]
    data['selected'], data['used_bytes'], data['selection'] = select_evidence_with_trace(
        [data['identifiers'][key] for key in data['ranked']], public)
    trace = build_retrieval_trace(**data)
    assert trace['selection']['skipped_budget_count'] == 40
    assert trace['selection']['not_considered_count'] == 4
    assert trace['candidates_truncated']
    assert {c['evidence_id'] for c in trace['candidates'] if c['status'] == 'selected'} == set(trace['selected_evidence_ids'])
    assert all(c['final_rank'] > 40 for c in trace['candidates'] if c['status'] == 'selected')
    assert all('evidence_id' not in c and 'url' not in c for c in trace['candidates'] if c['status'] == 'skipped-budget')


def test_trace_is_read_only_and_exactly_bound_to_its_column(query):
    before = Path(query.service.store.path).read_bytes()
    with patch.object(query.service.models, 'current', side_effect=AssertionError('no keys')), \
         patch('httpx.Client.request', side_effect=AssertionError('no network')), \
         patch('lianzheng.project_query.model_explanation', side_effect=AssertionError('no model')):
        a, b = ask(query), ask(query, 'beta')
    assert Path(query.service.store.path).read_bytes() == before
    candidate_sets = []
    for result in (a, b):
        for column in result['columns']:
            trace = column['retrieval_trace']
            assert trace['status'] == 'ready'
            assert trace['method'] == column['id']
            assert trace['selected_evidence_ids'] == [d['id'] for d in column['evidence']]
            assert trace['selection']['used_bytes'] == column['metrics']['evidence_bytes']
            assert [s['id'] for s in trace['steps']] == ['lexical', 'entity-match', 'graph-priority', 'budget']
            for row in trace['candidates']:
                assert row['snapshot_id'] == result['source']['snapshot_id']
                assert row['context_sha256'] == result['source']['context_sha256']
                assert row['id'].startswith('candidate-') and 'url' not in row
                if row['status'] == 'selected':
                    assert row['evidence_id'] in trace['selected_evidence_ids']
                else:
                    assert 'evidence_id' not in row
        candidate_sets.append({r['id'] for c in result['columns'] for r in c['retrieval_trace']['candidates']})
    assert candidate_sets[0].isdisjoint(candidate_sets[1])
    text_trace = a['columns'][0]['retrieval_trace']
    assert text_trace['graph']['status'] == 'text-only'
    assert text_trace['graph']['matched_targets'] == text_trace['graph']['paths'] == []


def verify_source_paths(query, identifier, result):
    source = result['source']
    _, source_bytes, _ = query.source(identifier, 'manifest', source['context_sha256'])
    original = json.loads(source_bytes)
    for column in result['columns']:
        trace = column['retrieval_trace']
        selected = {d['id']: d for d in column['evidence']}
        for path in trace['graph']['paths']:
            refs = [n['ref'] for n in path['nodes']]
            assert [(e['source'], e['target']) for e in path['edges']] == list(zip(refs, refs[1:]))
            for item in path['nodes'] + path['edges']:
                assert item['snapshot_id'] == identifier
                assert item['context_sha256'] == source['context_sha256']
                assert item['source_sha256'] == source['raw_source_sha256']
                assert 'url' not in item
                assert set(item['evidence_ids']) <= selected.keys()
                _resolve(original, item['locator'])
            for edge in path['edges']:
                for evidence_id in edge['evidence_ids']:
                    assert any((r['source'], r['target'], r['locator']) ==
                               (edge['source'], edge['target'], edge['locator'])
                               for r in selected[evidence_id]['relations'])
    return original


def test_cyclonedx_graph_trace_is_actual_declared_source_relation(query):
    result = ask(query)
    original = verify_source_paths(query, 'alpha', result)
    graph = result['columns'][1]['retrieval_trace']['graph']
    assert graph['path_count'] == 1
    for edge in graph['paths'][0]['edges']:
        assert _resolve(original, edge['locator']) == edge['target']
        assert edge['declaration_excerpt'] == json.dumps(edge['target'], ensure_ascii=False, sort_keys=True)
        assert edge['declaration_excerpt_kind'] == 'saved-source-content'
        assert not edge['declaration_excerpt_truncated']


def test_npm_graph_trace_uses_original_lockfile_pointers(query):
    lock = {'name': 'example', 'version': '1.0.0', 'lockfileVersion': 3,
            'packages': {'': {'name': 'example', 'version': '1.0.0', 'dependencies': {'minimist': '^1.2.5'}},
                         'node_modules/minimist': {'version': '1.2.5'}}}
    identifier = query.service.import_lockfile(lock, project='Lock', label='current')['snapshot']['id']
    result = ask(query, identifier)
    original = verify_source_paths(query, identifier, result)
    trace = result['columns'][1]['retrieval_trace']
    assert trace['status'] == 'ready'
    edge = trace['graph']['paths'][0]['edges'][0]
    assert _resolve(original, edge['locator']) == '^1.2.5'
    assert edge['locator'] == '/packages//dependencies/minimist'
    assert _resolve(original, edge['target_locator'])['version'] == '1.2.5'
    assert edge['declaration_excerpt'] == '"^1.2.5"'
    assert edge['declaration_excerpt_kind'] == 'saved-source-content'
    assert not edge['declaration_excerpt_truncated']


def test_relation_excerpt_is_bounded_original_declaration_not_target_component(query):
    raw = manifest(chain=True)
    long_ref = 'actual-source-target-' + 'x' * MAX_DECLARATION_EXCERPT
    raw['components'][1]['bom-ref'] = long_ref
    raw['dependencies'][1]['dependsOn'] = [long_ref]
    raw['dependencies'][2]['ref'] = long_ref
    query.service.import_bom(raw, project='Long declaration', label='current', identifier='long-declaration')
    result = ask(query, 'long-declaration')
    original = verify_source_paths(query, 'long-declaration', result)
    edge = result['columns'][1]['retrieval_trace']['graph']['paths'][0]['edges'][-1]
    exact = json.dumps(_resolve(original, edge['locator']), ensure_ascii=False, sort_keys=True)
    assert edge['declaration_excerpt'] == exact[:MAX_DECLARATION_EXCERPT]
    assert len(edge['declaration_excerpt']) == MAX_DECLARATION_EXCERPT
    assert edge['declaration_excerpt_truncated']
    assert '"version"' not in edge['declaration_excerpt']


def test_many_targets_are_bounded_and_all_selected_candidates_survive(query):
    query.service.import_bom(manifest(300, same_name=True), project='Large', label='current', identifier='large')
    result = ask(query, 'large')
    for column in result['columns']:
        trace = column['retrieval_trace']
        assert trace['status'] == 'ready'
        assert len(trace['candidates']) <= MAX_CANDIDATES
        assert len(trace['graph']['matched_targets']) <= MAX_TARGETS
        assert len(trace['graph']['paths']) <= MAX_PATHS
        assert len(json.dumps(trace, ensure_ascii=False).encode()) <= MAX_TRACE_BYTES
        assert {c['evidence_id'] for c in trace['candidates'] if c['status'] == 'selected'} == set(trace['selected_evidence_ids'])
        assert trace['candidate_count'] >= 300 and trace['candidates_truncated']
        assert trace['selection']['not_considered_count'] > 0
        assert all('evidence_id' not in c for c in trace['candidates'] if c['status'] != 'selected')
    trace = result['columns'][1]['retrieval_trace']
    assert trace['graph']['matched_target_count'] == trace['graph']['path_count'] == 300
    assert trace['graph']['targets_truncated'] and trace['graph']['paths_truncated']


def test_long_paths_are_contiguous_prefixes_not_invented_shortcuts(query):
    query.service.import_bom(manifest(40, chain=True), project='Long', label='current', identifier='long')
    result = ask(query, 'long')
    verify_source_paths(query, 'long', result)
    trace = result['columns'][1]['retrieval_trace']
    path = trace['graph']['paths'][0]
    assert len(path['nodes']) == MAX_PATH_NODES
    assert path['node_count'] == 41
    assert path['truncated'] and not path['complete'] and trace['graph']['paths_truncated']
    assert path['nodes'][0]['ref'] == 'root'
    assert path['nodes'][-1]['ref'] != 'ref-39'
    # This prefix did not make the budget. It must not inherit target citations.
    assert all(not edge['evidence_ids'] for edge in path['edges'])


@pytest.mark.parametrize('mutation', ['foreign-selected', 'selection-mismatch', 'hypothetical-edge',
                                      'invalid-pointer', 'wrong-valid-pointer', 'raw-evidence-namespace'])
def test_trace_fails_closed_on_unverifiable_diagnostics(query, mutation):
    data = copy.deepcopy(trace_input(query))
    if mutation == 'foreign-selected':
        data['selected'][0]['snapshot_id'] = 'beta'
    elif mutation == 'selection-mismatch':
        data['selection']['decisions'][data['selected'][0]['id']] = 'skipped-budget'
    elif mutation == 'hypothetical-edge':
        data['ranking']['priority_paths'] = [['root', 'ref-1']]
    elif mutation == 'invalid-pointer':
        data['locators']['ref-1'] = '/components/99999'
    elif mutation == 'wrong-valid-pointer':
        data['locators']['ref-1'] = data['locators']['ref-0']
    else:
        data['identifiers'] = {key: key for key in data['identifiers']}
    with pytest.raises((ValueError, KeyError, IndexError)):
        build_retrieval_trace(**data)


def test_trace_failure_returns_no_partial_diagnostics_or_sensitive_error(query):
    baseline = ask(query)
    with patch('lianzheng.project_query.build_retrieval_trace', side_effect=RuntimeError('secret-from-different-project')):
        result = ask(query)
    assert 'secret-from-different-project' not in json.dumps(result)
    for expected, column in zip(baseline['columns'], result['columns']):
        assert column['evidence'] == expected['evidence']
        assert column['answer'] == expected['answer']
        trace = column['retrieval_trace']
        assert trace['status'] == 'unavailable' and trace['snapshot_id'] == 'alpha'
        assert set(trace) == {'schema', 'status', 'method', 'scope', 'snapshot_id', 'context_sha256', 'reason'}


def test_context_change_during_trace_build_still_rejects_old_answer(query):
    expected = query.context('alpha')['source']['context_sha256']
    calls = 0

    def changing(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            with query.service.store.connect() as db:
                db.execute('UPDATE snapshots SET label=? WHERE id=?', ('changed during replay', 'alpha'))
        return build_retrieval_trace(*args, **kwargs)

    with patch('lianzheng.project_query.build_retrieval_trace', side_effect=changing):
        with pytest.raises(ProjectContextChanged):
            query.ask('alpha', 'minimist 路径', expected)
