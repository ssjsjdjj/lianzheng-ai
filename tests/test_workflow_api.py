import json
from pathlib import Path

from fastapi.testclient import TestClient
from lianzheng.app import create_app

ROOT=Path(__file__).resolve().parent.parent
TARGET='GHSA-29mw-wpgm-hmr9'


def test_lockfile_import_preserves_original_and_generated_sbom(tmp_path):
    raw={'name':'test-real-input','version':'1.0.0','lockfileVersion':3,'packages':{
         '':{'name':'test-real-input','version':'1.0.0','dependencies':{'lodash':'4.17.20'}},
         'node_modules/lodash':{'version':'4.17.20','resolved':'https://registry.npmjs.org/lodash/-/lodash-4.17.20.tgz'}}}
    with TestClient(create_app(tmp_path/'api.sqlite3')) as client:
        response=client.post('/api/snapshots',json={'bom':raw,'project':'导入验收','label':'初始锁文件'})
        assert response.status_code==201
        body=response.json();snapshot=body['snapshot']['id']
        assert body['import_format']=='npm-package-lock' and len(body['nodes'])==2
        assert client.get(f'/api/snapshots/{snapshot}/lockfile').json()==raw
        assert client.get(f'/api/snapshots/{snapshot}/bom').json()['bomFormat']=='CycloneDX'
        assert client.get('/api/snapshots/demo-before/lockfile').status_code==404


def test_task_lifecycle_cannot_be_completed_with_a_status_patch(tmp_path):
    with TestClient(create_app(tmp_path/'api.sqlite3')) as client:
        result=client.post('/api/snapshots/demo-before/tasks',json={'focus':TARGET,'owner':'验收负责人'})
        assert result.status_code==201
        task=result.json();path='/api/tasks/'+task['id']
        assert client.patch(path,json={'status':'verified','revision':task['revision']}).status_code==400
        assert client.patch(path,json={'owner':'缺少版本'}).status_code==422
        assert client.post(path+'/verify',json={'after_snapshot_id':'demo-partial'}).status_code==422
        partial=client.post(path+'/verify',json={'after_snapshot_id':'demo-partial','revision':task['revision']}).json()
        assert partial['status']=='needs_review' and not partial['verification']['passed']
        assert client.patch(path,json={'owner':'过期覆盖','revision':task['revision']}).status_code==400
        assert client.post(path+'/verify',json={'after_snapshot_id':'demo-resolved','revision':task['revision']}).status_code==400
        assert client.get(path).json()['owner']=='验收负责人'
        complete=client.post(path+'/verify',json={'after_snapshot_id':'demo-resolved','revision':partial['revision']}).json()
        assert complete['status']=='verified' and complete['verification']['passed']
        report=client.get(path+'/report')
        assert report.status_code==200 and 'attachment' in report.headers['content-disposition']
        assert report.json()['current_basis_matches'] is True
        assert len(client.get('/api/snapshots/demo-before/tasks').json())==1


def test_reviews_persist_on_original_claim_and_reject_stale_revision(tmp_path):
    app=create_app(tmp_path/'api.sqlite3');service=app.state.service
    answer=service.ask('demo-before','测试原文引用',TARGET)
    evidence=answer['citations'][0]
    answer['model_explanation']={'claims':[{'text':'检查公告原文。','quotes':[{'evidence_id':evidence['id'],'quote':evidence['text'][:30]}],'evidence_ids':[evidence['id']]}]}
    service.store.add_history('demo-before',answer['question'],answer)
    with TestClient(app) as client:
        path=f"/api/snapshots/demo-before/history/{answer['id']}/reviews"
        result=client.get(path).json();claim=result['claims'][0]
        body={'status':'partial','note':'只确认公告描述，未验证运行时影响。','fingerprint':claim['fingerprint'],'revision':0}
        response=client.put(path+'/0',json=body)
        assert response.status_code==200
        assert client.get(path).json()['claims'][0]['review']['status']=='partial'
        assert client.put(path+'/0',json=body).status_code==400
        assert client.get(path.replace('demo-before','demo-partial')).status_code==404


def test_policy_and_task_routes_reject_cross_origin_writes(tmp_path):
    with TestClient(create_app(tmp_path/'api.sqlite3')) as client:
        policy={'daily_calls':3,'daily_budget_usd':.08,'enabled':True}
        assert client.put('/api/model/usage/policy',json=policy,headers={'Origin':'https://foreign.invalid'}).status_code==403
        assert client.put('/api/model/usage/policy',json=policy).status_code==200
        assert client.get('/api/model/usage').json()['policy']==policy
        assert client.put('/api/model/usage/policy',json={**policy,'daily_calls':True}).status_code==422
        assert client.post('/api/snapshots/demo-before/tasks',json={'focus':TARGET},headers={'Origin':'https://foreign.invalid'}).status_code==403
