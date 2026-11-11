import hashlib
from io import BytesIO
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from lianzheng.app import ROOT, create_app
from lianzheng.case_decisions import CaseDecisions
from lianzheng.case_export import evidence_archive
from lianzheng.domain import InputError
from lianzheng.real_case import RealCase
from lianzheng.service import Service
from lianzheng.task_compare import TaskComparison


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path/'api.sqlite3'))


def test_comparison_route_defaults_to_no_model_and_forwards_explicit_true(client,monkeypatch):
    calls=[]
    def run(self,task_id,use_model=False):
        calls.append((task_id,use_model));return {'requested_model':use_model}
    monkeypatch.setattr(TaskComparison,'run',run)
    assert client.post('/api/task-comparison/run',json={'task_id':'task-1'}).json()=={'requested_model':False}
    assert client.post('/api/task-comparison/run',json={'task_id':'task-1','use_model':True}).json()=={'requested_model':True}
    assert calls==[('task-1',False),('task-1',True)]


@pytest.mark.parametrize('body',[{}, {'task_id':''}, {'task_id':'x'*101},
                                 {'task_id':'one','use_model':'true'}, {'task_id':'one','use_model':1}])
def test_comparison_route_rejects_invalid_requests_without_running(client,monkeypatch,body):
    monkeypatch.setattr(TaskComparison,'run',lambda *a,**k:pytest.fail('Invalid body was executed'))
    assert client.post('/api/task-comparison/run',json=body).status_code==422


def test_cross_origin_comparison_request_is_rejected(client,monkeypatch):
    monkeypatch.setattr(TaskComparison,'run',lambda *a,**k:pytest.fail('Cross-origin request executed'))
    assert client.post('/api/task-comparison/run',json={'task_id':'one'},headers={'Origin':'https://outside.test'}).status_code==403


def test_task_list_and_invalid_task(client):
    response=client.get('/api/task-comparison/tasks')
    assert response.status_code==200 and len(response.json()['tasks'])>=15
    assert client.post('/api/task-comparison/run',json={'task_id':'unknown-task'}).status_code in (400,404)


def test_decision_routes_default_and_parameter_forwarding(client,monkeypatch):
    monkeypatch.setattr(CaseDecisions,'report',lambda self,from_phase='before',to_phase='after':{'from':from_phase,'to':to_phase})
    assert client.get('/api/real-case/decisions').json()=={'from':'before','to':'after'}
    result=client.get('/api/real-case/decisions/report?from_phase=partial&to_phase=after')
    assert result.json()=={'from':'partial','to':'after'}
    assert 'attachment' in result.headers['content-disposition']


def test_unknown_phases_are_not_silently_defaulted(client):
    assert client.get('/api/real-case/decisions?from_phase=unknown').status_code in (400,404)


def test_evidence_zip_exact_public_allowlist_integrity_and_no_database_change(client,monkeypatch):
    service=client.app.state.service
    original=service.store.list()
    monkeypatch.setattr(service.models,'current',lambda:pytest.fail('Export must not read a model key'))
    result=client.get('/api/real-case/evidence.zip')
    assert result.status_code==200 and result.headers['content-type']=='application/zip'
    folder=ROOT/'fixtures/real-case/http-server-minimist'
    case=json.loads((folder/'case.json').read_bytes())
    expected={'case.json','decisions.json','bundle-index.json'}|{e['name'] for e in case['files']}
    with zipfile.ZipFile(BytesIO(result.content)) as archive:
        prefix='lianzheng-case-evidence/'
        assert set(archive.namelist())=={prefix+n for n in expected}
        index=json.loads(archive.read(prefix+'bundle-index.json'))
        assert len(index['files'])==len(expected)-1
        for entry in index['files']:
            content=archive.read(prefix+entry['name'])
            assert hashlib.sha256(content).hexdigest()==entry['sha256']
            if entry['name']!='decisions.json':assert content==(folder/entry['name']).read_bytes()
        assert json.loads(archive.read(prefix+'decisions.json'))['bundle_sha256']==index['case_manifest_sha256']
    assert service.store.list()==original


def test_export_rejects_changed_source_between_reads(tmp_path):
    real_case=RealCase(Service(tmp_path/'db.sqlite3',ROOT/'fixtures'),ROOT/'fixtures/real-case')
    class ChangedReport:
        def report(self):return {'bundle_sha256':'0'*64}
    with pytest.raises(InputError,match='变化'):
        evidence_archive(real_case,ChangedReport())


def test_export_never_reads_additional_unlisted_files(tmp_path):
    class VerifiedFiles(dict):pass
    files=VerifiedFiles();files.contents={'proof.txt':b'public proof'};files.manifest_bytes=b'{}'
    class FixedCase:
        def _bundle(self):return {'id':'test-only'},files,'a'*64,None
    class Decisions:
        def report(self):return {'bundle_sha256':'a'*64}
    (tmp_path/'model-settings.json').write_text('must stay local',encoding='utf-8')
    with zipfile.ZipFile(BytesIO(evidence_archive(FixedCase(),Decisions()))) as archive:
        assert len(archive.namelist())==4
        assert not any('model-settings' in n for n in archive.namelist())
