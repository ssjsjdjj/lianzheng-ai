import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pytest

from lianzheng.domain import InputError
from lianzheng.project_query import ProjectContextChanged, ProjectQuery, _resolve
from lianzheng.osv import evidence_documents
from lianzheng.providers import ModelWarning
from lianzheng.service import Service
from lianzheng.task_compare import EVIDENCE_BYTES, K

ROOT = Path(__file__).resolve().parent.parent


def bom():
    return {'bomFormat': 'CycloneDX', 'specVersion': '1.5', 'version': 1,
            'metadata': {'component': {'type': 'application', 'bom-ref': 'root', 'name': 'example', 'version': '1.0.0'}},
            'components': [{'type': 'library', 'bom-ref': 'same-ref', 'name': 'minimist', 'version': '1.2.5',
                            'purl': 'pkg:npm/minimist@1.2.5'}],
            'dependencies': [{'ref': 'root', 'dependsOn': ['same-ref']}, {'ref': 'same-ref', 'dependsOn': []}]}


def lockfile():
    return {'name': 'example', 'version': '1.0.0', 'lockfileVersion': 3, 'requires': True,
            'packages': {'': {'name': 'example', 'version': '1.0.0', 'dependencies': {'minimist': '1.2.5'}},
                         'node_modules/minimist': {'version': '1.2.5', 'resolved': 'https://registry.npmjs.org/minimist/-/minimist-1.2.5.tgz',
                                                   'integrity': 'sha512-example'}}}


@pytest.fixture
def query(tmp_path):
    service = Service(tmp_path / 'work.sqlite3', ROOT / 'fixtures')
    service.import_bom(bom(), project='Alpha', label='current', identifier='alpha')
    service.import_bom(bom(), project='Beta', label='current', identifier='beta')
    for identifier in ('alpha', 'beta'):
        scan = {'status': 'checked', 'source': 'test-local-record', 'fetched_at': '2026-01-01', 'error': None,
                'data': {'vulns': [{'id': 'GHSA-test', 'summary': 'minimist test advisory',
                                   'details': 'minimist vulnerability fixture only', 'affected': []}]}}
        node = next(n for n in service.store.get(identifier)['graph']['nodes'] if not n['root'])
        service.store.save_scans(identifier, {'same-ref': scan}, evidence_documents(identifier, node, scan))
    return ProjectQuery(service)


def ask(query, identifier='alpha', question='minimist 的依赖路径和漏洞是什么？', **kwargs):
    context = query.context(identifier)
    return query.ask(identifier, question, context['source']['context_sha256'], **kwargs)


def add_doc(query, identifier='alpha', text='AlphaPrivate 是 minimist 迁移的本项目说明。', **extra):
    payload = {'title': 'minimist 本项目文档', 'package': 'minimist', 'version': '1.2.5',
               'kind': 'project', 'text': text, **extra}
    return query.service.import_document(identifier, payload)


def evidence(result):
    return [d for c in result['columns'] for d in c['evidence']]


def test_identical_sources_have_distinct_context_and_evidence_ids(query):
    a, b = ask(query), ask(query, 'beta')
    assert a['source']['raw_source_sha256'] == b['source']['raw_source_sha256']
    assert a['source']['context_sha256'] != b['source']['context_sha256']
    assert {d['id'] for d in evidence(a)}.isdisjoint(d['id'] for d in evidence(b))
    for result, identifier in ((a, 'alpha'), (b, 'beta')):
        assert result['source']['project'] == identifier.title()
        for column in result['columns']:
            linked = column['evidence_links']
            for item in column['evidence'] + linked['paths'] + linked['facts'] + [linked['source']]:
                assert item['scope'] == 'snapshot'
                assert item['snapshot_id'] == identifier
                assert item['context_sha256'] == result['source']['context_sha256']
            for path in linked['paths']:
                assert all(n['snapshot_id'] == identifier for n in path['nodes'] + path['edges'])
                assert all(n['context_sha256'] == result['source']['context_sha256'] for n in path['nodes'] + path['edges'])


def test_foreign_context_rejected_before_any_model_config(query):
    expected = query.context('alpha')['source']['context_sha256']
    with patch.object(query.service.models, 'current', side_effect=AssertionError('key read')):
        with pytest.raises(ProjectContextChanged):
            query.ask('beta', 'minimist 路径', expected, use_model=True)


def test_offline_never_reads_keys_calls_network_or_changes_database(query):
    before = Path(query.service.store.path).read_bytes()
    with patch.object(query.service.models, 'current', side_effect=AssertionError('key read')), \
         patch.object(query.service.models, 'public', side_effect=AssertionError('key read')), \
         patch.object(query.service.retriever, 'retrieve', side_effect=AssertionError('embedding')), \
         patch('httpx.Client.request', side_effect=AssertionError('network')), \
         patch('lianzheng.project_query.model_explanation', side_effect=AssertionError('model')):
        result = ask(query)
        source = result['source']
        query.source('alpha', 'manifest', source['context_sha256'])
    assert Path(query.service.store.path).read_bytes() == before
    assert result['model_calls_attempted'] == result['embedding_calls'] == 0
    assert result['workspace_modified'] is False
    assert result['task']['kind'] == 'project-question'
    assert result['task']['phase'] == 'snapshot'
    assert result['comparison']['result'] == 'unscored'
    assert result['comparison']['semantic_winner'] is None
    assert 'http-server' not in json.dumps(result)
    for column in result['columns']:
        assert column['metrics']['reference_coverage'] is None
        assert column['metrics']['retrieved'] <= K
        assert column['metrics']['evidence_bytes'] <= EVIDENCE_BYTES


def test_all_download_bytes_hashes_and_cyclonedx_locators(query):
    result = ask(query)
    for doc in evidence(result):
        url = urlsplit(doc['url']); source_id = url.path.rsplit('/', 1)[1]
        assert '/snapshots/alpha/task-comparison/sources/' in url.path
        expected = parse_qs(url.query)['context_sha256'][0]
        filename, data, _ = query.source('alpha', source_id, expected)
        assert filename == doc['filename']
        assert hashlib.sha256(data).hexdigest() == doc['source_sha256']
        if source_id == 'manifest':
            assert _resolve(json.loads(data), doc['locator'])['name'] == 'minimist'
    paths = result['columns'][1]['evidence_links']['paths']
    assert paths
    original = json.loads(query.source('alpha', 'manifest', result['source']['context_sha256'])[1])
    for path in paths:
        for edge in path['edges']:
            assert _resolve(original, edge['locator']) == 'same-ref'


def test_original_lockfile_has_verified_declaration_pointers(query):
    imported = query.service.import_lockfile(lockfile(), project='Lock Project')
    identifier = imported['snapshot']['id']
    result = ask(query, identifier)
    assert result['source']['format'] == 'npm-package-lock'
    raw = json.loads(query.source(identifier, 'manifest', result['source']['context_sha256'])[1])
    assert raw == lockfile()
    for path in result['columns'][1]['evidence_links']['paths']:
        for node in path['nodes']:
            assert _resolve(raw, node['locator'])['version'] in ('1.0.0', '1.2.5')
        for edge in path['edges']:
            assert _resolve(raw, edge['locator']) == '1.2.5'
            assert '/packages/' in edge['locator']


@pytest.mark.parametrize('change', ['scan', 'add-document', 'remove-document'])
def test_context_updates_invalidate_answers_and_downloads(query, change):
    document = add_doc(query)
    expected = query.context('alpha')['source']['context_sha256']
    if change == 'scan':
        scans = query.service.store.scans('alpha')
        scans['same-ref']['fetched_at'] = 'another-scan'
        query.service.store.save_scans('alpha', scans, [])
    elif change == 'add-document':
        add_doc(query, text='Another newer minimist note')
    else:
        query.service.store.remove_document('alpha', document['id'])
    with pytest.raises(ProjectContextChanged):
        query.ask('alpha', 'minimist', expected)
    with pytest.raises(ProjectContextChanged):
        query.source('alpha', 'manifest', expected)


def test_project_documents_and_downloads_are_snapshot_scoped(query):
    alpha = add_doc(query)
    add_doc(query, 'beta', 'BetaPrivate 是 minimist 的另一个项目文档。')
    result = ask(query, question='minimist AlphaPrivate BetaPrivate 本项目文档')
    assert 'AlphaPrivate' in json.dumps(result)
    assert 'BetaPrivate 是' not in json.dumps(result)
    beta_hash = query.context('beta')['source']['context_sha256']
    with pytest.raises(KeyError):
        query.source('beta', alpha['id'], beta_hash)
    name, data, mime = query.source('alpha', alpha['id'], result['source']['context_sha256'])
    assert 'AlphaPrivate' in data.decode() and mime.startswith('text/plain')


def test_target_version_docs_require_the_declared_target(query):
    add_doc(query, text='minimist PRIVATE_TARGET 的升级过程。', target_version='1.2.8', kind='migration')
    assert 'PRIVATE_TARGET' not in json.dumps(evidence(ask(query, question='minimist PRIVATE_TARGET 怎么升级')))
    assert 'PRIVATE_TARGET' not in json.dumps(evidence(ask(query, question='minimist 升级到 1.2.7 PRIVATE_TARGET')))
    assert 'PRIVATE_TARGET' in json.dumps(evidence(ask(query, question='minimist 升级到 1.2.8 PRIVATE_TARGET')))


def test_forged_chunk_url_and_quote_are_rebuilt_from_original_document(query):
    document = add_doc(query)
    with query.service.store.connect() as db:
        row = db.execute('SELECT body FROM knowledge_documents WHERE id=?', (document['id'],)).fetchone()
        body = json.loads(row['body']); body['chunks'][0].update(url='https://evil.example/steal', text='FOREIGN-INJECTED', snapshot_id='beta')
        db.execute('UPDATE knowledge_documents SET body=? WHERE id=?', (json.dumps(body), document['id']))
    result = ask(query, question='minimist AlphaPrivate 文档')
    assert 'FOREIGN-INJECTED' not in json.dumps(result)
    assert 'evil.example' not in json.dumps(result)
    assert 'AlphaPrivate' in json.dumps(result)


def test_foreign_document_body_rejected(query):
    document = add_doc(query)
    with query.service.store.connect() as db:
        body = json.loads(db.execute('SELECT body FROM knowledge_documents WHERE id=?', (document['id'],)).fetchone()['body'])
        body['snapshot_id'] = 'beta'
        db.execute('UPDATE knowledge_documents SET body=? WHERE id=?', (json.dumps(body), document['id']))
    with pytest.raises(InputError, match='归属'):
        query.context('alpha')


def test_persisted_advisory_documents_cannot_inject_foreign_material(query):
    with query.service.store.connect() as db:
        db.execute('UPDATE documents SET body=? WHERE snapshot_id=?', (json.dumps({'text': 'FOREIGN-INJECTED', 'url': 'https://evil.example'}), 'alpha'))
    result = ask(query)
    assert 'FOREIGN-INJECTED' not in json.dumps(result)
    assert 'evil.example' not in json.dumps(result)
    assert any(d['kind'] == 'advisory' for d in evidence(result))


def test_missing_relation_does_not_invent_path(query):
    raw = bom(); raw['dependencies'][0]['dependsOn'] = []
    query.service.import_bom(raw, identifier='unlinked')
    result = ask(query, 'unlinked')
    assert all(not c['evidence_links']['paths'] for c in result['columns'])


def test_graph_tampering_and_partial_lock_import_are_rejected(query):
    with query.service.store.connect() as db:
        raw = json.loads(db.execute('SELECT graph FROM snapshots WHERE id=?', ('alpha',)).fetchone()['graph'])
        raw['edges'] = []
        db.execute('UPDATE snapshots SET graph=? WHERE id=?', (json.dumps(raw), 'alpha'))
    with pytest.raises(InputError, match='依赖图'):
        query.context('alpha')
    from lianzheng.lockfiles import convert_package_lock
    query.service.import_bom(convert_package_lock(lockfile()), identifier='unfinished')
    with pytest.raises(InputError, match='尚未保存完整'):
        query.context('unfinished')


def test_unknown_query_and_unknown_scans_remain_explicit(query):
    result = ask(query, question='quuxxyzunseen987654')
    assert all(not c['evidence'] and not c['evidence_links']['paths'] for c in result['columns'])
    query.service.store.save_scans('alpha', {}, [])
    result = ask(query)
    assert result['coverage']['unknown_components'] == 1
    assert result['coverage']['can_confirm_absence'] is False
    assert any('未知' in c['answer'] for c in result['columns'])


@pytest.mark.parametrize('question', ['', ' ', None, [], 'a' * 1001, 'a\x00'])
def test_question_validation(query, question):
    with pytest.raises(InputError):
        query.ask('alpha', question, 'a' * 64)


@pytest.mark.parametrize('hash_value', [None, '', 'A' * 64, 'a' * 63, '../alpha', 1])
def test_context_hash_validation(query, hash_value):
    with pytest.raises(InputError):
        query.ask('alpha', 'minimist', hash_value)


@pytest.mark.parametrize('value', [None, 'false', 0, 1])
def test_model_flag_validation(query, value):
    with pytest.raises(InputError):
        ask(query, use_model=value)


def model_config():
    return {'provider': 'local', 'base_url': 'http://localhost:1234/v1', 'model': 'fake-model', 'api_key': ''}


def test_model_mock_uses_current_scoped_evidence_budget_and_exact_quotes(query):
    add_doc(query)
    add_doc(query, 'beta', 'BetaPrivate is forbidden')
    seen = []
    def explain(question, context, config, usage_guard):
        assert usage_guard is query.service.call_control
        assert context['facts']['snapshot_id'] == 'alpha'
        assert all(d['snapshot_id'] == 'alpha' for d in context['evidence'])
        assert 'BetaPrivate' not in json.dumps(context)
        doc = context['evidence'][0]; seen.append(context)
        return {'text': 'mock answer', 'metadata': {'returned_model': 'fake-model'}, 'claims': [
            {'text': 'valid cited claim', 'quotes': [{'evidence_id': doc['id'], 'quote': doc['text'].splitlines()[0]}]},
            {'text': 'forged cross-project claim', 'quotes': [{'evidence_id': 'ev-foreign', 'quote': 'fake'}]},
            {'text': 'fabricated quote', 'quotes': [{'evidence_id': doc['id'], 'quote': 'DOES-NOT-EXIST'}]}]}, None
    with patch.object(query.service.models, 'current', return_value=model_config()) as settings, \
         patch('lianzheng.project_query.model_explanation', side_effect=explain):
        result = ask(query, use_model=True)
    assert settings.call_count == 1
    assert result['model_calls_attempted'] == len(seen) == 2
    assert result['fairness']['model_pair_comparable'] is True
    for column in result['columns']:
        claims = [f for f in column['evidence_links']['facts'] if f['kind'] == 'model-claim']
        assert [f['text'] for f in claims] == ['valid cited claim']


def test_context_changes_during_model_call_abort_before_second_call(query):
    def explain(*args, **kwargs):
        add_doc(query, text='new evidence while request was running')
        return {'text': 'old answer', 'claims': []}, None
    with patch.object(query.service.models, 'current', return_value=model_config()), \
         patch('lianzheng.project_query.model_explanation', side_effect=explain) as model:
        with pytest.raises(ProjectContextChanged):
            ask(query, use_model=True)
        assert model.call_count == 1


def test_model_warning_preserves_offline_fallback(query):
    warning = ModelWarning('模型预算不足', {'reason': 'budget'})
    with patch.object(query.service.models, 'current', return_value=model_config()), \
         patch('lianzheng.project_query.model_explanation', return_value=(None, warning)):
        result = ask(query, use_model=True)
    assert all(c['generation'] == 'model-fallback' for c in result['columns'])
    assert all(c['warning'] == '模型预算不足' and c['evidence'] for c in result['columns'])
    assert result['fairness']['model_pair_comparable'] is False


def test_context_uses_one_sqlite_snapshot_despite_concurrent_rescan(query):
    # WAL permits a writer while the read transaction is in progress. The
    # rescan happens after reading snapshot metadata but before reading scans.
    with query.service.store.connect() as db:
        db.execute('PRAGMA journal_mode=WAL')
    initial = query.context('alpha')
    original = query.service.store.connect
    triggered = False
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
    assert triggered
    assert captured['source']['context_sha256'] == initial['source']['context_sha256']
    assert captured['coverage']['unknown_components'] == 0
    assert query.context('alpha')['coverage']['unknown_components'] == 1


@pytest.mark.parametrize('project', ['ietf-tools-datatracker', 'mermaid-js-mermaid-cli'])
def test_public_real_project_import_question_and_evidence(query, project):
    raw = json.loads((ROOT / 'fixtures/public-projects' / project / 'package-lock.json').read_text(encoding='utf-8'))
    imported = query.service.import_lockfile(raw, project=project)
    identifier = imported['snapshot']['id']
    context = query.context(identifier)
    assert context['coverage']['component_count'] == len(raw['packages']) - 1
    package = 'minimist' if any(path.endswith('/minimist') for path in raw['packages']) else 'mermaid'
    result = query.ask(identifier, package + ' 的依赖路径和风险证据是什么？', context['source']['context_sha256'])
    assert result['source']['project'] == project
    assert result['fairness']['candidate_documents'] > 500
    assert result['columns'][1]['evidence_links']['paths']
    assert all(d['snapshot_id'] == identifier for d in evidence(result))
    assert all(c['metrics']['evidence_bytes'] <= EVIDENCE_BYTES for c in result['columns'])
    for path in result['columns'][1]['evidence_links']['paths']:
        for edge in path['edges']:
            assert isinstance(_resolve(raw, edge['locator']), str)
            assert _resolve(raw, edge['source_locator'])
            assert _resolve(raw, edge['target_locator'])


def test_graph_issue_order_from_other_python_process_does_not_reject_valid_bom(query):
    raw = bom()
    raw['dependencies'] = []
    query.service.import_bom(raw, identifier='incomplete')
    with query.service.store.connect() as db:
        graph = json.loads(db.execute('SELECT graph FROM snapshots WHERE id=?', ('incomplete',)).fetchone()['graph'])
        assert len(graph['issues']) > 1
        graph['issues'].reverse()
        db.execute('UPDATE snapshots SET graph=? WHERE id=?', (json.dumps(graph), 'incomplete'))
    result = ask(query, 'incomplete')
    assert result['coverage']['graph_complete'] is False
    assert not result['columns'][1]['evidence_links']['paths']
