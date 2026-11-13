"""HTTP contracts for isolated current-project questions and source downloads."""
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from lianzheng.app import ROOT, create_app
from lianzheng.project_query import ProjectQuery


@pytest.fixture
def client(tmp_path, monkeypatch):
    app = create_app(tmp_path / 'review.sqlite3', seed=False)
    # Any private settings read in the default offline flow is a regression.
    monkeypatch.setattr(app.state.service.models, 'current', lambda: pytest.fail('Offline flow read model credentials'))
    return TestClient(app)


def imported(client, project='同名项目'):
    bom = json.loads((ROOT / 'fixtures/before.cdx.json').read_bytes())
    response = client.post('/api/snapshots', json={'project': project, 'label': '同名快照', 'bom': bom})
    assert response.status_code == 201
    identifier = response.json()['snapshot']['id']
    context = client.get(f'/api/snapshots/{identifier}/task-comparison/context')
    assert context.status_code == 200
    return identifier, context.json()


def test_import_question_and_hash_checked_source_download(client):
    identifier, context = imported(client)
    source = context['source']
    question = client.post(f'/api/snapshots/{identifier}/task-comparison/ask', json={
        'question': 'lodash 通过哪些依赖路径进入当前项目？',
        'expected_context_sha256': source['context_sha256']})
    assert question.status_code == 200
    result = question.json()
    assert result['release'] == '0.11.0'
    assert result['source']['snapshot_id'] == identifier
    assert result['comparison']['result'] == 'unscored'
    download = client.get(source['url'])
    assert download.status_code == 200
    assert hashlib.sha256(download.content).hexdigest() == source['raw_source_sha256']
    assert 'attachment' in download.headers['content-disposition']
    assert 'no-store' in download.headers['cache-control']
    assert not client.app.state.service.store.history(identifier)


def test_identical_imports_do_not_accept_each_others_context(client):
    a, ca = imported(client)
    b, cb = imported(client)
    assert a != b and ca['source']['context_sha256'] != cb['source']['context_sha256']
    response = client.post(f'/api/snapshots/{b}/task-comparison/ask', json={
        'question': 'lodash 引入路径', 'expected_context_sha256': ca['source']['context_sha256']})
    assert response.status_code == 409
    assert client.get(ca['source']['url'].replace('/' + a + '/', '/' + b + '/')).status_code == 409


def test_document_change_invalidates_answer_and_download_then_refresh_recovers(client):
    identifier, context = imported(client)
    url = f'/api/snapshots/{identifier}'
    doc = client.post(url + '/documents', json={
        'title': '验收专用迁移要求', 'package': 'lodash', 'version': '4.17.20',
        'kind': 'project', 'text': '验收专用：升级之前须由项目维护者核对调用入口。'})
    assert doc.status_code == 201
    body = {'question': 'lodash 升级要求', 'expected_context_sha256': context['source']['context_sha256']}
    assert client.post(url + '/task-comparison/ask', json=body).status_code == 409
    assert client.get(context['source']['url']).status_code == 409
    fresh = client.get(url + '/task-comparison/context').json()
    body['expected_context_sha256'] = fresh['source']['context_sha256']
    assert client.post(url + '/task-comparison/ask', json=body).status_code == 200
    assert client.delete(url + '/documents/' + doc.json()['id']).status_code == 200
    assert client.get(fresh['source']['url']).status_code == 409


@pytest.mark.parametrize('body', [{}, {'question': ''}, {'question': 2},
    {'question': 'x'*1001}, {'question': '路径', 'expected_context_sha256': 'bad'},
    {'question': '路径', 'use_model': 'false'}, {'question': '路径', 'use_model': 1}])
def test_reject_invalid_requests_before_execution(client, monkeypatch, body):
    monkeypatch.setattr(ProjectQuery, 'ask', lambda *a, **k: pytest.fail('Invalid request executed'))
    payload = {'question': '路径', 'expected_context_sha256': 'a'*64, **body}
    if not body:
        payload = {}
    assert client.post('/api/snapshots/id/task-comparison/ask', json=payload).status_code == 422


def test_cross_origin_and_unknown_sources_fail_closed(client):
    identifier, context = imported(client)
    endpoint = f'/api/snapshots/{identifier}/task-comparison'
    assert client.post(endpoint + '/ask', json={'question': '路径',
        'expected_context_sha256': context['source']['context_sha256']},
        headers={'Origin': 'https://outside.example'}).status_code == 403
    assert client.get(endpoint + '/sources/not-a-source', params={
        'context_sha256': context['source']['context_sha256']}).status_code == 404
    assert client.get(endpoint + '/sources/manifest').status_code == 422
    assert client.get('/api/snapshots/missing/task-comparison/context').status_code == 404


def test_explicit_model_choice_is_forwarded_but_never_inferred(client, monkeypatch):
    calls = []
    def ask(self, identifier, question, expected, use_model=False):
        calls.append(use_model)
        return {'requested_model': use_model}
    monkeypatch.setattr(ProjectQuery, 'ask', ask)
    body = {'question': '路径', 'expected_context_sha256': 'a'*64}
    assert client.post('/api/snapshots/id/task-comparison/ask', json=body).json()['requested_model'] is False
    body['use_model'] = True
    assert client.post('/api/snapshots/id/task-comparison/ask', json=body).json()['requested_model'] is True
    assert calls == [False, True]
