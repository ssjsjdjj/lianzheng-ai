"""Current-project brief and answer-card HTTP integration, without a provider."""
import json

import pytest
from fastapi.testclient import TestClient

from lianzheng.app import ROOT, create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    app = create_app(tmp_path / 'cards.sqlite3', seed=False)
    monkeypatch.setattr(app.state.service.models, 'current', lambda: pytest.fail('Offline API read private model settings'))
    return TestClient(app)


def import_project(client, label='版本一'):
    lock = {'name': 'v011-example', 'version': '1.0.0', 'lockfileVersion': 3,
            'packages': {'': {'name': 'v011-example', 'version': '1.0.0', 'dependencies': {'minimist': '1.2.5'}},
                         'node_modules/minimist': {'version': '1.2.5'}}}
    response = client.post('/api/snapshots', json={'project': '验收项目', 'label': label, 'bom': lock})
    assert response.status_code == 201
    return response.json()['snapshot']['id']


def context(client, identifier):
    response = client.get(f'/api/snapshots/{identifier}/task-comparison/context')
    assert response.status_code == 200
    return response.json()


def ask(client, identifier, ctx, question='minimist 升级有哪些项目检查要求？'):
    response = client.post(f'/api/snapshots/{identifier}/task-comparison/ask', json={
        'question': question, 'expected_context_sha256': ctx['source']['context_sha256']})
    assert response.status_code == 200
    return response.json()


def test_brief_and_cards_only_reference_current_snapshot(client):
    identifier = import_project(client)
    ctx = context(client, identifier)
    brief = ctx['brief']
    assert brief['snapshot_id'] == identifier and brief['context_sha256'] == ctx['source']['context_sha256']
    assert brief['component_count'] == brief['unknown_components'] == 1
    assert brief['checked_components'] == brief['knowledge_documents'] == 0
    assert 1 <= len(brief['suggestions']) <= 3
    assert all(isinstance(s['question'], str) and s['question'].strip() for s in brief['suggestions'])
    result = ask(client, identifier, ctx)
    assert result['release'] == '0.12.0' and result['model_calls_attempted'] == 0
    for column in result['columns']:
        card = column['answer_card']
        assert card['snapshot_id'] == identifier and card['context_sha256'] == ctx['source']['context_sha256']
        assert card['generation'] == 'offline-evidence'
        evidence_ids = {item['id'] for item in column['evidence']}
        for item in [card['conclusion'], *card['reasons'], *card['unknowns'], *card['next_steps']]:
            assert isinstance(item['text'], str) and item['text'].strip()
            assert set(item['evidence_ids']).issubset(evidence_ids)
    assert not client.app.state.service.store.history(identifier)


def test_added_document_preserves_unchanged_evidence_identity_but_not_old_context(client):
    identifier = import_project(client)
    old_context = context(client, identifier)
    before = ask(client, identifier, old_context)
    response = client.post(f'/api/snapshots/{identifier}/documents', json={
        'title': '项目检查要求', 'package': 'minimist', 'version': '1.2.5',
        'kind': 'project', 'text': 'minimist 升级检查要求：核对命令行参数解析回归。此要求尚未执行。'})
    assert response.status_code == 201
    fresh = context(client, identifier)
    after = ask(client, identifier, fresh)
    assert fresh['brief']['knowledge_documents'] == 1
    assert fresh['source']['context_sha256'] != old_context['source']['context_sha256']
    old_evidence = {e['stable_key']: e for c in before['columns'] for e in c['evidence']}
    new_evidence = {e['stable_key']: e for c in after['columns'] for e in c['evidence']}
    shared = old_evidence.keys() & new_evidence.keys()
    assert shared
    assert any(old_evidence[k]['content_sha256'] == new_evidence[k]['content_sha256'] for k in shared)
    assert all(old_evidence[k]['id'] != new_evidence[k]['id'] for k in shared)
    assert new_evidence.keys() - old_evidence.keys()
    assert client.get(old_context['source']['url']).status_code == 409


def test_identical_inputs_still_have_separate_briefs_and_card_evidence(client):
    a = import_project(client)
    b = import_project(client)
    ca, cb = context(client, a), context(client, b)
    ra, rb = ask(client, a, ca), ask(client, b, cb)
    assert ca['brief']['snapshot_id'] != cb['brief']['snapshot_id']
    keys_a = {e['stable_key'] for col in ra['columns'] for e in col['evidence']}
    keys_b = {e['stable_key'] for col in rb['columns'] for e in col['evidence']}
    assert not keys_a.intersection(keys_b)


def test_cyclonedx_brief_does_not_assume_lockfile_input(client):
    bom = json.loads((ROOT / 'fixtures/before.cdx.json').read_bytes())
    result = client.post('/api/snapshots', json={'bom': bom, 'project': 'CDX 测试', 'label': '导入'}).json()
    ctx = context(client, result['snapshot']['id'])
    assert ctx['brief']['format'] == 'cyclonedx'
    assert ctx['brief']['component_count'] == 4
