import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from lianzheng.app import create_app
from lianzheng.domain import InputError
from lianzheng.knowledge import chunk_lines
from lianzheng.retrieval import Retriever
from lianzheng.service import Service

ROOT=Path(__file__).resolve().parent.parent
TARGET='GHSA-29mw-wpgm-hmr9'


@pytest.fixture
def service(tmp_path):
    instance=Service(tmp_path/'db.sqlite3',ROOT/'fixtures');instance.seed()
    return instance


@pytest.fixture
def payload():
    return {'title':'升级迁移说明','package':'lodash','version':'4.17.20',
            'target_version':'4.18.1','kind':'migration','url':'',
            'text':'# 导出快照校验\n升级前必须保存报表快照。\n\n## 检查项\n迁移后执行导出回归测试。\n'}


def test_chunks_reconstruct_original_content_with_line_locations():
    text='# 标题\n'+('长行'*1600)+'\n\n## 下一节\n迁移检查\n'
    chunks=chunk_lines(text,max_chars=100)
    assert ''.join(c['text'] for c in chunks)==text
    lines=text.splitlines(keepends=True)
    for c in chunks:
        assert len(c['text'])<=100
        start=sum(len(s) for s in lines[:c['line_start']-1])+c['column_start']-1
        end=sum(len(s) for s in lines[:c['line_end']-1])+c['column_end']
        assert text[start:end]==c['text']


def test_import_is_idempotent_and_keeps_timestamp(service,payload):
    first=service.import_document('demo-before',payload)
    second=service.import_document('demo-before',payload)
    assert first==second
    assert len(service.list_documents('demo-before'))==1
    assert first['chunk_count']==2


def test_wrong_package_or_version_is_rejected(service,payload):
    payload['version']='4.17.21'
    with pytest.raises(InputError,match='不在当前快照'):service.import_document('demo-before',payload)


@pytest.mark.parametrize('change',[
 {'version':'^4.17.20'}, {'target_version':'latest'}, {'target_version':'4.x'},
 {'url':'javascript:alert(1)'}, {'url':'https://user:secret@example.com/'},
 {'title':'  '}, {'text':'  '}, {'text':'abc\x00def'}, {'kind':'official-certified'},
])
def test_document_metadata_validation(service,payload,change):
    payload.update(change)
    with pytest.raises(InputError):service.import_document('demo-before',payload)


def test_retrieved_migration_has_line_reference_and_target_version(service,payload):
    summary=service.import_document('demo-before',payload)
    answer=service.ask('demo-before','升级到 4.18.1 有哪些迁移检查？',TARGET)
    knowledge=[c for c in answer['citations'] if c['source']=='user-document']
    assert knowledge and any('导出' in c['text'] for c in knowledge)
    assert all(c['document_id']==summary['id'] and '行第' in c['locator'] for c in knowledge)
    assert all(c['target_version']=='4.18.1' for c in knowledge)
    assert any('导入文档' in line for line in answer['statements'])
    assert any(c['source']=='frozen-osv' for c in answer['citations'])


def test_wrong_target_version_never_enters_context(service,payload):
    service.import_document('demo-before',payload)
    answer=service.ask('demo-before','升级到 4.17.21 的迁移要求？',TARGET)
    assert not any(c['source']=='user-document' for c in answer['citations'])


def test_no_cross_snapshot_document_leak(service,payload):
    service.import_document('demo-before',payload)
    answer=service.ask('demo-partial','升级到 4.18.1 需要哪些迁移检查？',TARGET)
    assert not any(c['source']=='user-document' for c in answer['citations'])


def test_same_package_wrong_source_version_is_excluded(service,payload):
    payload['version']='4.17.21'
    service.import_document('demo-partial',payload)
    # The selected ReDoS advisory affects only the 4.17.20 occurrence in this snapshot.
    answer=service.ask('demo-partial','升级到 4.18.1 的迁移要求？',TARGET)
    assert not any(c['source']=='user-document' for c in answer['citations'])


def test_user_documents_survive_rescans(service,payload):
    summary=service.import_document('demo-before',payload)
    service.scan('demo-before',live=False)
    assert service.list_documents('demo-before')[0]['id']==summary['id']
    assert any(d.get('document_id')==summary['id'] for d in service.store.documents('demo-before'))


def test_removal_stops_retrieval_but_history_keeps_original_evidence(service,payload):
    summary=service.import_document('demo-before',payload)
    service.ask('demo-before','升级到 4.18.1 迁移检查？',TARGET)
    service.store.remove_document('demo-before',summary['id'])
    answer=service.ask('demo-before','升级到 4.18.1 迁移检查？',TARGET)
    assert not any(c['source']=='user-document' for c in answer['citations'])
    older=service.store.history('demo-before')[1]['answer']
    assert any(c['document_id']==summary['id'] for c in older['citations'])


def test_compatibility_is_not_guaranteed_even_with_document(service,payload):
    service.import_document('demo-before',payload)
    assert service.ask('demo-before','升级到 4.18.1 后一定兼容吗？',TARGET)['insufficient']


def test_resolved_snapshot_can_answer_package_document_questions(service,payload):
    payload['version']=service.osv.fixture['demo_resolved_version']
    payload['target_version']=None
    service.import_document('demo-resolved',payload)
    answer=service.ask('demo-resolved','lodash 的迁移检查要求？')
    assert any(c['source']=='user-document' for c in answer['citations'])


def test_unknown_selected_focus_is_not_silently_replaced(service):
    answer=service.ask('demo-before','这个漏洞从哪里来？','GHSA-unknown-unknown-unknown')
    assert answer['insufficient'] and not answer['paths'] and not answer['citations']


def test_multiple_distinct_vulnerabilities_request_split(service):
    answer=service.ask('demo-before','GHSA-29mw-wpgm-hmr9 和 GHSA-35jh-r3h4-6jhm 分别如何修复？')
    assert answer['insufficient'] and '拆分' in answer['conclusion'] and not answer['citations']


def test_text_baseline_model_context_does_not_contain_graph_statistics(service,monkeypatch):
    import lianzheng.service as module
    seen={}
    def model(question,context,usage_guard=None):
        seen.update(context)
        return None,None
    monkeypatch.setattr(module,'model_explanation',model)
    service.ask('demo-before','这个漏洞的依据？',TARGET,mode='text',use_model=True)
    assert seen['paths']==[]
    assert 'matched_occurrences' not in seen['facts']
    assert 'graph_complete' not in seen['facts']


def test_list_and_compare_skip_full_document_reads(service,monkeypatch):
    def fail(*args,**kwargs):raise AssertionError('summary loaded document bodies')
    monkeypatch.setattr(service.store,'documents',fail)
    assert len(service.list_snapshots())==3
    assert service.compare('demo-before','demo-partial')['remaining']


def fake_client(monkeypatch,handler):
    original=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))


def test_embedding_zero_keyword_match_is_retained(monkeypatch):
    monkeypatch.setenv('LZ_EMBEDDING_BASE_URL','https://provider.invalid/v1')
    monkeypatch.setenv('LZ_EMBEDDING_MODEL','model')
    fake_client(monkeypatch,lambda request:httpx.Response(200,json={'data':[{'index':i,'embedding':[1.0,float(i)]} for i in range(len(json.loads(request.content)['input']))]}))
    documents=[{'id':'one','title':'Automobile','text':'A vehicle.','package':'example','version':'1.0.0','vulnerability':'A','source':'frozen-osv'}]
    results,mode,_=Retriever().retrieve('汽车',documents)
    assert mode=='bm25+embedding-rrf' and results and results[0]['score']==0


def test_embedding_cache_deduplicates_text_and_reuses_vectors(monkeypatch):
    monkeypatch.setenv('LZ_EMBEDDING_BASE_URL','https://provider.invalid/v1')
    monkeypatch.setenv('LZ_EMBEDDING_MODEL','model')
    calls=[]
    def handler(request):
        data=json.loads(request.content)['input'];calls.append(data)
        return httpx.Response(200,json={'data':[{'index':i,'embedding':[1.,2.]} for i in range(len(data))]})
    fake_client(monkeypatch,handler)
    retriever=Retriever()
    assert retriever.embed(['same','same'])==[[1.,2.],[1.,2.]]
    assert retriever.embed(['same'])==[[1.,2.]]
    assert calls==[['same']]


def test_embedding_duplicate_indices_are_rejected(monkeypatch):
    monkeypatch.setenv('LZ_EMBEDDING_BASE_URL','https://provider.invalid/v1')
    monkeypatch.setenv('LZ_EMBEDDING_MODEL','model')
    fake_client(monkeypatch,lambda request:httpx.Response(200,json={'data':[{'index':0,'embedding':[1.,2.]},{'index':0,'embedding':[1.,3.]}]}))
    retriever=Retriever()
    with pytest.raises(ValueError,match='索引'):retriever.embed(['a','b'])
    assert not retriever.embedding_cache


def test_version_bound_upload_api_and_scoped_removal(tmp_path,payload):
    with TestClient(create_app(tmp_path/'api.sqlite3')) as client:
        result=client.post('/api/snapshots/demo-before/documents',json=payload)
        assert result.status_code==201
        identifier=result.json()['id']
        assert client.get('/api/snapshots/demo-before/documents').json()[0]['id']==identifier
        assert client.get('/api/snapshots/demo-before/documents/'+identifier).json()['text']==payload['text']
        assert client.delete('/api/snapshots/demo-partial/documents/'+identifier).status_code==404
        assert client.delete('/api/snapshots/demo-before/documents/'+identifier).status_code==200
        assert client.get('/api/snapshots/demo-before/documents').json()==[]


def test_import_limit_is_reported(tmp_path,payload):
    with TestClient(create_app(tmp_path/'api.sqlite3')) as client:
        payload['text']='x'*200001
        assert client.post('/api/snapshots/demo-before/documents',json=payload).status_code==422
