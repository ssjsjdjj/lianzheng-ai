import copy
import sqlite3

import pytest
from fastapi.testclient import TestClient

from lianzheng.app import ROOT, create_app
from lianzheng.case_decisions import CaseDecisions
from lianzheng.demo_readiness import DemoReadiness
from lianzheng.domain import InputError
from lianzheng.real_case import RealCase
from lianzheng.task_compare import TaskComparison


@pytest.fixture
def context(tmp_path, monkeypatch):
    app = create_app(tmp_path/'review.sqlite3')
    service = app.state.service
    monkeypatch.setattr(service.models, 'public', lambda: {'configured': False, 'verified': False, 'model': None})
    real = RealCase(service, ROOT/'fixtures/real-case')
    comparison = TaskComparison(service, real, ROOT/'fixtures/task-comparison.json')
    return TestClient(app), service, real, DemoReadiness(service, real, comparison, CaseDecisions(real))


def test_preflight_is_read_only_and_no_provider_call(context, monkeypatch):
    client, service, _, _ = context
    monkeypatch.setattr(service.models, 'current', lambda: pytest.fail('No private model config needed'))
    monkeypatch.setattr(service.models, 'test_and_save', lambda *a, **k: pytest.fail('Preflight connected to model'))
    before = service.store.list()
    calls = service.call_control.public()
    result = client.get('/api/demo/preflight')
    body = result.json()
    assert result.status_code == 200 and body['offline_ready']
    assert not body['case']['prepared']
    assert body['model']['remote_checked'] is False
    assert body['model_calls'] == body['network_calls'] == 0
    assert body['workspace_modified'] is False
    assert service.store.list() == before and service.call_control.public() == calls
    assert 'no-store' in result.headers['cache-control']
    assert 'api_key' not in result.text and 'recent' not in body['usage']


def test_prepared_case_is_accepted_but_scan_drift_blocks_start(context):
    _, service, real, readiness = context
    prepared = real.prepare()
    result = readiness.report()
    assert result['offline_ready'] and result['case']['prepared']
    assert result['case']['basis_matches_recorded'] is True
    with service.store.connect() as db:
        db.execute('DELETE FROM scans WHERE snapshot_id=?', (prepared['before_snapshot_id'],))
    result = readiness.report()
    assert not result['offline_ready']
    assert next(c for c in result['checks'] if c['id']=='workspace')['status']=='fail'


def test_readiness_detects_case_changed_between_checks(context, monkeypatch):
    _, _, _, readiness = context
    catalog = readiness.comparison.tasks()
    catalog['source']['case_bundle_sha256'] = 'f'*64
    monkeypatch.setattr(readiness.comparison, 'tasks', lambda: catalog)
    result = readiness.report()
    assert not result['offline_ready']
    assert next(c for c in result['checks'] if c['id']=='task-set')['status']=='fail'


@pytest.mark.parametrize('target', ['real_case', 'comparison', 'decisions'])
def test_corrupt_materials_block_without_leaking_exception_details(context, monkeypatch, target):
    _, _, _, readiness = context
    method = {'real_case':'status', 'comparison':'tasks', 'decisions':'report'}[target]
    def broken():
        raise InputError('private details must not be echoed')
    monkeypatch.setattr(getattr(readiness,target), method, broken)
    result = readiness.report()
    assert not result['offline_ready']
    assert 'private details' not in str(result)
    assert any(row['status']=='fail' for row in result['checks'])


def test_local_model_check_does_not_claim_remote_availability(context, monkeypatch):
    _, service, _, readiness = context
    monkeypatch.setattr(service.models, 'public', lambda: {'configured': True, 'verified': True, 'model':'configured-model', 'api_key':'never-return'})
    result = readiness.report()
    assert result['offline_ready'] and result['usage']['model_pair_locally_allowed']
    assert result['model']['remote_checked'] is False and 'never-return' not in str(result)
    service.call_control.update({'daily_calls':1})
    result = readiness.report()
    assert result['offline_ready'] and not result['usage']['model_pair_locally_allowed']


def test_unreadable_usage_does_not_block_offline(context, monkeypatch):
    _, service, _, readiness = context
    monkeypatch.setattr(service.call_control,'public',lambda: (_ for _ in ()).throw(sqlite3.OperationalError('private database path')))
    result = readiness.report()
    assert result['offline_ready']
    assert result['usage']['calls_today'] is None
    assert not result['usage']['model_pair_locally_allowed']
    assert 'private database path' not in str(result)


def test_free_route_defaults_offline_and_forwards_parameters(context, monkeypatch):
    client, _, _, _ = context
    calls = []
    def ask(self, question, phase='before', use_model=False):
        calls.append((question,phase,use_model));return {'question':question}
    monkeypatch.setattr(TaskComparison,'ask',ask,raising=False)
    assert client.post('/api/task-comparison/ask',json={'question':'为什么仍有残留？'}).status_code==200
    assert client.post('/api/task-comparison/ask',json={'question':'测试失败了吗？','phase':'after','use_model':True}).status_code==200
    assert calls==[('为什么仍有残留？','before',False),('测试失败了吗？','after',True)]


@pytest.mark.parametrize('body',[{}, {'question':''}, {'question':'x'*1001}, {'question':2},
                                {'question':'test','phase':'other'}, {'question':'test','use_model':'false'},
                                {'question':'test','use_model':1}])
def test_free_route_rejects_invalid_parameters(context, monkeypatch, body):
    client, _, _, _ = context
    monkeypatch.setattr(TaskComparison,'ask',lambda *a,**k: pytest.fail('Invalid request executed'),raising=False)
    assert client.post('/api/task-comparison/ask',json=body).status_code==422


def test_free_route_rejects_cross_origin(context, monkeypatch):
    client, _, _, _ = context
    monkeypatch.setattr(TaskComparison,'ask',lambda *a,**k: pytest.fail('Cross-origin request executed'),raising=False)
    result = client.post('/api/task-comparison/ask',json={'question':'test'},headers={'Origin':'https://untrusted.example'})
    assert result.status_code==403
