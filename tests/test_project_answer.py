"""Answer cards and briefs must reflect actual, isolated saved evidence."""
import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from lianzheng.osv import evidence_documents
from lianzheng.project_query import ProjectQuery
from lianzheng.providers import ModelWarning
from lianzheng.service import Service


ROOT = Path(__file__).resolve().parent.parent


def manifest():
    return {'bomFormat': 'CycloneDX', 'specVersion': '1.5', 'version': 1,
            'metadata': {'component': {'type': 'application', 'bom-ref': 'root', 'name': 'example', 'version': '1.0.0'}},
            'components': [{'type': 'library', 'bom-ref': 'same-ref', 'name': 'minimist', 'version': '1.2.5',
                            'purl': 'pkg:npm/minimist@1.2.5'}],
            'dependencies': [{'ref': 'root', 'dependsOn': ['same-ref']}, {'ref': 'same-ref', 'dependsOn': []}]}


@pytest.fixture
def query(tmp_path):
    service = Service(tmp_path / 'cards.sqlite3', ROOT / 'fixtures')
    for identifier in ('alpha', 'beta'):
        service.import_bom(manifest(), project=identifier, label='current', identifier=identifier)
    return ProjectQuery(service)


def ask(query, question='minimist 的依赖路径、查询证据和处理方案是什么？', identifier='alpha', **kwargs):
    return query.ask(identifier, question, query.context(identifier)['source']['context_sha256'], **kwargs)


def document(query, identifier='alpha', text='minimist 处理方案：先核对调用入口，再验证异常参数。'):
    return query.service.import_document(identifier, {'title': 'minimist 项目说明', 'package': 'minimist',
        'version': '1.2.5', 'kind': 'project', 'text': text})


def scan(query, fetched_at='2026-01-01', details='minimist saved advisory details'):
    result = {'status': 'checked', 'source': 'test-saved', 'fetched_at': fetched_at, 'error': None,
              'data': {'vulns': [{'id': 'GHSA-fixture', 'summary': 'minimist test advisory',
                                 'details': details, 'affected': []}]}}
    node = next(n for n in query.service.store.get('alpha')['graph']['nodes'] if not n['root'])
    query.service.store.save_scans('alpha', {'same-ref': result}, evidence_documents('alpha', node, result))


def corpus(query, identifier='alpha'):
    state = query._capture(identifier)
    return {d['stable_key']: d for d in query._corpus(state, 'minimist 处理与依赖路径')[0]}


def rows(card):
    return [card['conclusion']] + card['reasons'] + card['unknowns'] + card['next_steps']


def assert_card_bindings(result):
    for column in result['columns']:
        card = column['answer_card']
        for key in ('scope', 'snapshot_id', 'context_sha256'):
            assert card[key] == result['source'][key]
        selected = {d['id'] for d in column['evidence']}
        assert all(set(row['evidence_ids']) <= selected for row in rows(card))
        assert all(row['text'] for row in rows(card))
        assert all(row['evidence_ids'] for row in card['reasons'])


def test_brief_and_cards_are_offline_read_only_and_bound_to_current_source(query):
    before = Path(query.service.store.path).read_bytes()
    with patch.object(query.service.models, 'current', side_effect=AssertionError('credential read')), \
         patch.object(query.service.models, 'public', side_effect=AssertionError('credential read')), \
         patch('httpx.Client.request', side_effect=AssertionError('network')):
        context = query.context('alpha')
        result = ask(query)
    brief = context['brief']
    assert {key: brief[key] for key in ('scope', 'snapshot_id', 'context_sha256')} == {
        key: context['source'][key] for key in ('scope', 'snapshot_id', 'context_sha256')}
    assert brief['component_count'] == brief['unknown_components'] == 1
    assert brief['checked_components'] == brief['knowledge_documents'] == brief['issue_count'] == 0
    assert brief['graph_complete'] is True
    assert 1 <= len(brief['suggestions']) <= 3
    assert all('minimist@1.2.5' in s['question'] for s in brief['suggestions'])
    assert all(s['id'] and s['label'] for s in brief['suggestions'])
    assert '未知' in ''.join(brief['notes'])
    assert_card_bindings(result)
    assert all(c['answer_card']['generation'] == 'offline-evidence' for c in result['columns'])
    assert Path(query.service.store.path).read_bytes() == before


def test_brief_and_evidence_remain_isolated_for_identical_projects(query):
    document(query, text='AlphaPrivate minimist 处理方案仅供甲项目使用。')
    alpha, beta = ask(query), ask(query, identifier='beta')
    assert query.context('alpha')['brief']['knowledge_documents'] == 1
    assert query.context('beta')['brief']['knowledge_documents'] == 0
    assert 'AlphaPrivate' not in json.dumps(beta)
    a, b = corpus(query), corpus(query, 'beta')
    assert set(a).isdisjoint(b)
    for result in (alpha, beta):
        assert_card_bindings(result)
    # Stable content can match, but identity never crosses snapshots.
    occurrence_a = next(d for d in a.values() if d['kind'] == 'occurrence')
    occurrence_b = next(d for d in b.values() if d['kind'] == 'occurrence')
    assert occurrence_a['content_sha256'] == occurrence_b['content_sha256']


def test_document_addition_only_changes_coverage_and_new_document_evidence(query):
    scan(query)
    initial = corpus(query)
    initial_answer = ask(query)
    assert initial == corpus(query)
    assert [c['answer_card'] for c in initial_answer['columns']] == [c['answer_card'] for c in ask(query)['columns']]
    document(query)
    final = corpus(query)
    assert set(initial) <= set(final)
    assert len(set(final) - set(initial)) == 1
    changed = [initial[key]['kind'] for key in initial if initial[key]['content_sha256'] != final[key]['content_sha256']]
    assert changed == ['coverage']  # The document count changed, not every source wrapper.
    assert all(d['context_sha256'] != final[key]['context_sha256'] for key, d in initial.items())
    final_answer = ask(query)
    for column in final_answer['columns']:
        card = column['answer_card']
        assert '导入文档' in card['conclusion']['text']
        assert '核对调用入口' in card['conclusion']['text']
        assert '尚不能' in card['conclusion']['text']
    assert_card_bindings(final_answer)


def test_fingerprint_ignores_fetch_time_but_detects_full_source_changes(query):
    scan(query)
    initial = corpus(query)
    scan(query, fetched_at='2026-02-01')
    refreshed = corpus(query)
    assert set(initial) == set(refreshed)
    assert all(d['content_sha256'] == refreshed[key]['content_sha256'] for key, d in initial.items())
    assert all(d['context_sha256'] != refreshed[key]['context_sha256'] for key, d in initial.items())
    scan(query, fetched_at='2026-02-01', details='new saved substantive advisory finding')
    changed = corpus(query)
    changed_kinds = {d['kind'] for key, d in refreshed.items() if d['content_sha256'] != changed[key]['content_sha256']}
    assert changed_kinds == {'scan', 'advisory'}


def test_original_source_change_after_excerpt_limit_still_changes_fingerprint(query):
    scan(query, details='x' * 2500 + ' original conclusion')
    initial = corpus(query)
    scan(query, details='x' * 2500 + ' changed conclusion')
    changed = corpus(query)
    before = next(d for d in initial.values() if d['kind'] == 'scan')
    after = changed[before['stable_key']]
    assert before['source_excerpt'] == after['source_excerpt']
    assert before['content_sha256'] != after['content_sha256']


def test_no_evidence_card_does_not_invent_answer_or_success(query):
    result = ask(query, 'zzqxyunmatchable')
    for column in result['columns']:
        card = column['answer_card']
        assert not column['evidence'] and not card['reasons']
        assert not card['conclusion']['evidence_ids']
        assert '无法回答' in card['conclusion']['text']
        assert card['unknowns'] and card['next_steps']
    assert_card_bindings(result)


def test_imported_test_claim_is_document_report_not_executed_test(query):
    document(query, text='minimist 处理方案：我们的测试全部通过，已安全上线。')
    result = ask(query, 'minimist 处理方案和测试结果是什么？')
    for column in result['columns']:
        card = column['answer_card']
        assert card['conclusion']['text'].startswith('导入文档提供了处理线索')
        assert '这些是文档记载，尚不能据此确认' in card['conclusion']['text']
        assert any('未运行项目测试' in u['text'] for u in card['unknowns'])
        assert any('未验证' in reason['text'] for reason in card['reasons'])
    assert_card_bindings(result)


MODEL = {'provider': 'local', 'base_url': 'http://localhost:1234/v1', 'model': 'fake', 'api_key': ''}


def test_model_card_uses_only_checked_claim_quotes_not_unverified_summary(query):
    def explain(question, context, config, usage_guard):
        doc = context['evidence'][0]
        return {'text': 'UNVERIFIED_FREE_PROSE', 'claims': [
            {'text': 'VALID_CHECKED_CLAIM', 'quotes': [{'evidence_id': doc['id'], 'quote': doc['text'].splitlines()[0]}]},
            {'text': 'FOREIGN_PROJECT_CLAIM', 'quotes': [{'evidence_id': 'ev-other-project', 'quote': doc['text']}]},
            {'text': 'FABRICATED_QUOTE_CLAIM', 'quotes': [{'evidence_id': doc['id'], 'quote': 'not in original text'}]}]}, None
    with patch.object(query.service.models, 'current', return_value=MODEL), \
         patch('lianzheng.project_query.model_explanation', side_effect=explain):
        result = ask(query, use_model=True)
    for column in result['columns']:
        card = column['answer_card']; encoded = json.dumps(card)
        assert card['generation'] == 'model-assisted'
        assert card['conclusion']['text'] == 'VALID_CHECKED_CLAIM'
        assert all(bad not in encoded for bad in ('UNVERIFIED_FREE_PROSE', 'FOREIGN_PROJECT_CLAIM', 'FABRICATED_QUOTE_CLAIM'))
        assert '语义' in card['note']
    assert_card_bindings(result)


@pytest.mark.parametrize('response', [
    (None, ModelWarning('测试模拟：预算不足', {'reason': 'budget'})),
    ({'text': 'UNVERIFIED_SUCCESS', 'claims': []}, None),
])
def test_failed_or_unquotable_model_uses_explicit_offline_card_fallback(query, response):
    with patch.object(query.service.models, 'current', return_value=MODEL), \
         patch('lianzheng.project_query.model_explanation', return_value=response):
        result = ask(query, use_model=True)
    for column in result['columns']:
        card = column['answer_card']
        assert card['generation'] == 'model-fallback'
        assert 'UNVERIFIED_SUCCESS' not in json.dumps(card)
        assert any('离线取证' in u['text'] for u in card['unknowns'])
    assert_card_bindings(result)


def test_empty_or_incomplete_project_brief_adapts_without_invented_packages(query):
    empty = manifest(); empty['components'] = []; empty['dependencies'] = [{'ref': 'root', 'dependsOn': []}]
    query.service.import_bom(empty, identifier='empty')
    brief = query.context('empty')['brief']
    assert brief['component_count'] == brief['checked_components'] == brief['unknown_components'] == 0
    assert len(brief['suggestions']) == 1
    assert 'minimist' not in json.dumps(brief)
    incomplete = manifest(); incomplete['dependencies'] = []
    query.service.import_bom(incomplete, identifier='incomplete')
    brief = query.context('incomplete')['brief']
    assert brief['graph_complete'] is False and brief['issue_count'] > 0
    result = ask(query, identifier='incomplete')
    for column in result['columns']:
        assert not column['evidence_links']['paths']
        assert '连通 1 条' not in column['answer_card']['conclusion']['text']
        assert any('不能补造' in u['text'] for u in column['answer_card']['unknowns'])


def test_brief_is_from_the_same_sqlite_read_snapshot_as_source(query):
    scan(query)
    with query.service.store.connect() as db:
        db.execute('PRAGMA journal_mode=WAL')
    initial = query.context('alpha')
    original = query.service.store.connect; triggered = False
    @contextmanager
    def interleaved():
        nonlocal triggered
        with original() as db:
            class Proxy:
                def execute(self, sql, parameters=()):
                    nonlocal triggered
                    if sql.startswith('SELECT ref,result') and not triggered:
                        triggered = True
                        with original() as writer:
                            writer.execute('DELETE FROM scans WHERE snapshot_id=?', ('alpha',))
                    return db.execute(sql, parameters)
            yield Proxy()
    with patch.object(query.service.store, 'connect', interleaved):
        captured = query.context('alpha')
    assert triggered and captured['brief'] == initial['brief']
    assert captured['source'] == initial['source']
    assert query.context('alpha')['brief']['unknown_components'] == 1


@pytest.mark.parametrize('project', ['ietf-tools-datatracker', 'mermaid-js-mermaid-cli'])
def test_brief_and_cards_on_two_public_project_inputs(query, project):
    raw = json.loads((ROOT / 'fixtures/public-projects' / project / 'package-lock.json').read_text(encoding='utf-8'))
    identifier = query.service.import_lockfile(raw, project=project)['snapshot']['id']
    context = query.context(identifier)
    assert context['brief']['component_count'] == len(raw['packages']) - 1
    assert context['brief']['project'] == project
    names = {n['name'] for n in query.service.store.get(identifier)['graph']['nodes'] if not n['root']}
    assert all(any(name in s['question'] for name in names) for s in context['brief']['suggestions'])
    package = 'minimist' if 'minimist' in names else 'mermaid'
    result = ask(query, question=package + ' 的依赖路径和风险证据是什么？', identifier=identifier)
    assert_card_bindings(result)
    graph_card = result['columns'][1]['answer_card']
    assert '代表性引入路径' in graph_card['conclusion']['text']
    assert graph_card['conclusion']['evidence_ids']
    assert result['model_calls_attempted'] == result['embedding_calls'] == 0
