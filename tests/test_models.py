import copy
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from lianzheng.app import create_app
from lianzheng.domain import InputError
from lianzheng.providers import ChatClient,ModelError,parse_json_content
from lianzheng.retrieval import model_explanation
from lianzheng.service import Service
from lianzheng.settings import ModelSettings,protect_key,unprotect_key

ROOT=Path(__file__).resolve().parent.parent
TARGET='GHSA-29mw-wpgm-hmr9'
KEY='test-placeholder-not-a-real-api-key'


def fake_client(monkeypatch,handler):
    original=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))


def response(content,**changes):
    return httpx.Response(200,json={'id':'test-request','model':'deepseek-flash','choices':[{'message':{'content':json.dumps(content,ensure_ascii=False)},'finish_reason':'stop'}],
                                    'usage':{'prompt_tokens':10,'completion_tokens':20,'total_tokens':30},**changes})


def configuration():
    return {'provider':'deepseek','base_url':'https://api.deepseek.com','model':'deepseek-flash',
            'api_key':KEY,'json_mode':True,'remember_key':True,'strict_citations':True}


@pytest.fixture
def service(tmp_path):
    service=Service(tmp_path/'test.sqlite3',ROOT/'fixtures');service.seed();return service


@pytest.fixture
def context():
    return {'facts':{'focus':TARGET,'fixed_versions':['4.17.21'],'target_version':'4.18.1'},
            'paths':[],'evidence':[{'id':'source-1','text':'迁移后执行报表与导出入口的回归测试。','version':'4.17.20','target_version':'4.18.1'}]}


def claim():
    return {'claims':[{'text':'升级到 4.18.1 后应执行导出回归测试，并由项目维护者核对结果。',
                       'evidence_ids':['source-1'],'quotes':[{'evidence_id':'source-1','quote':'迁移后执行报表与导出入口的回归测试。'}]}],
            'follow_up_questions':['哪些依赖路径仍需要复核？']}


def test_real_contract_uses_json_and_disables_deepseek_thinking(monkeypatch):
    seen={}
    def handler(request):
        seen['body']=json.loads(request.content);seen['authorization']=request.headers.get('authorization')
        return response({'ok':True})
    fake_client(monkeypatch,handler)
    result=ChatClient(configuration()).probe()
    assert seen['body']['thinking']=={'type':'disabled'}
    assert seen['body']['response_format']=={'type':'json_object'}
    assert seen['authorization']=='Bearer '+KEY
    assert KEY not in json.dumps(seen['body'])
    assert result['usage']['total_tokens']==30


def test_successful_probe_saves_without_exposing_credential(tmp_path,monkeypatch):
    fake_client(monkeypatch,lambda request:response({'ok':True}))
    settings=ModelSettings(tmp_path/'model.json')
    result=settings.test_and_save(configuration())
    assert result['verified'] and result['has_key']
    assert KEY not in json.dumps(result)
    reloaded=ModelSettings(tmp_path/'model.json')
    assert reloaded.current()['api_key']==KEY
    assert reloaded.public()['verified']
    if result['storage']=='windows-dpapi':assert KEY not in (tmp_path/'model.json').read_text()


def test_memory_only_key_does_not_survive_restart(tmp_path,monkeypatch):
    fake_client(monkeypatch,lambda request:response({'ok':True}))
    settings=ModelSettings(tmp_path/'model.json')
    settings.test_and_save({**configuration(),'remember_key':False})
    assert settings.public()['verified']
    reloaded=ModelSettings(tmp_path/'model.json')
    assert not reloaded.public()['has_key'] and not reloaded.public()['verified']
    assert KEY not in (tmp_path/'model.json').read_text()


def test_failed_probe_cannot_claim_verified_or_replace_existing(tmp_path,monkeypatch):
    fake_client(monkeypatch,lambda request:httpx.Response(401,text='echo '+KEY))
    settings=ModelSettings(tmp_path/'model.json')
    with pytest.raises(ModelError) as caught:settings.test_and_save(configuration())
    assert KEY not in str(caught.value)
    assert not settings.public()['verified'] and not (tmp_path/'model.json').exists()


@pytest.mark.parametrize('url',['http://remote.example/v1','https://user:password@example.com/v1','https://example.com/v1?key=secret','https://example.com/chat/completions'])
def test_unsafe_configuration_endpoints_rejected(tmp_path,url):
    with pytest.raises(InputError):ModelSettings(tmp_path/'model.json').candidate({**configuration(),'base_url':url,'provider':'compatible'})


def test_official_mode_does_not_route_keys_to_custom_host(tmp_path):
    with pytest.raises(InputError):ModelSettings(tmp_path/'model.json').candidate({**configuration(),'base_url':'https://provider.invalid/v1'})


def test_blank_key_cannot_reuse_credential_on_changed_endpoint(tmp_path,monkeypatch):
    fake_client(monkeypatch,lambda request:response({'ok':True}))
    settings=ModelSettings(tmp_path/'model.json');settings.test_and_save(configuration())
    with pytest.raises(InputError):settings.candidate({**configuration(),'provider':'compatible','base_url':'https://provider.invalid/v1','api_key':''})


@pytest.mark.parametrize('status',[401,402,403,404,429,500,302])
def test_provider_errors_are_sanitized(monkeypatch,status):
    fake_client(monkeypatch,lambda request:httpx.Response(status,text='sensitive '+KEY))
    with pytest.raises(ModelError) as caught:ChatClient(configuration()).probe()
    assert KEY not in str(caught.value)


def test_truncated_model_completion_is_rejected(monkeypatch):
    fake_client(monkeypatch,lambda request:httpx.Response(200,json={'choices':[{'message':{'content':'{"ok":true}'},'finish_reason':'length'}]}))
    with pytest.raises(ModelError,match='截断'):ChatClient(configuration()).probe()


def test_code_fenced_json_is_accepted():
    assert parse_json_content('```json\n{"ok":true}\n```')=={'ok':True}


def test_strict_explanation_checks_quotes_and_collects_metadata(monkeypatch,context):
    fake_client(monkeypatch,lambda request:response(claim()))
    result,warning=model_explanation('迁移要求？',context,config=configuration())
    assert result and warning is None
    assert result['claims'][0]['quotes'][0]['evidence_id']=='source-1'
    assert result['metadata']['usage']['total_tokens']==30


@pytest.mark.parametrize('mutation',['invented-id','invented-quote','unscoped-version','empty-claims'])
def test_unverified_model_claims_are_not_displayed(monkeypatch,context,mutation):
    output=claim()
    if mutation=='invented-id':output['claims'][0]['evidence_ids']=['invented']
    elif mutation=='invented-quote':output['claims'][0]['quotes'][0]['quote']='不存在于原始文档的证明与结论。'
    elif mutation=='unscoped-version':output['claims'][0]['text']='升级到 99.99.99 就完全修复。'
    else:output['claims']=[]
    fake_client(monkeypatch,lambda request:response(output))
    result,warning=model_explanation('why',context,config=configuration())
    assert result is None and warning
    assert warning.metadata['usage']['total_tokens']==30


@pytest.mark.parametrize('invalid_quote',['只做回归','不存在于原文的迁移测试要求。'])
def test_rejected_quotes_keep_usage_and_safe_diagnostic(monkeypatch,context,invalid_quote):
    output=claim();output['claims'][0]['quotes'][0]['quote']=invalid_quote
    fake_client(monkeypatch,lambda request:response(output))
    result,warning=model_explanation('缺少哪些证据？',context,config=configuration())
    assert result is None
    assert warning.metadata['usage']['total_tokens']==30
    assert warning.metadata['citation_validation']['status']=='rejected'
    assert invalid_quote not in json.dumps(warning.metadata,ensure_ascii=False)


def test_live_receipt_retains_failed_billable_attempt():
    from scripts.verify_live_model import answer_receipt
    metadata={'provider':'openai','transport':'http-request','api_family':'responses',
              'requested_model':'gpt-6-luna','returned_model':'gpt-6-luna','usage':{'total_tokens':321}}
    answer={'question':'缺项？','id':3,'parent_id':2,'facts':{'target_version':'4.18.1'},
            'generation':'evidence-template','model_explanation':None,'model_attempt':metadata,
            'elapsed_ms':42,'limits':['引用未通过']}
    receipt=answer_receipt(answer,'openai')
    assert receipt['passed'] is False and receipt['claims']==[]
    assert receipt['model_metadata']['usage']['total_tokens']==321


def test_followup_retains_target_but_retrieves_again(service):
    service.import_document('demo-before',{'title':'迁移要求','package':'lodash','version':'4.17.20','target_version':'4.18.1','kind':'migration','text':'# 检查\n迁移后执行报表与导出入口的回归测试。','url':''})
    first=service.ask('demo-before','升级到 4.18.1 有哪些迁移检查？',TARGET)
    second=service.ask('demo-before','那这些检查还需要注意什么？',TARGET,parent_id=first['id'])
    assert second['facts']['target_version']=='4.18.1'
    assert second['parent_id']==first['id'] and second['conversation_depth']==1
    assert any(c['source']=='user-document' for c in second['citations'])


def test_followup_cannot_cross_snapshot_or_mode(service):
    first=service.ask('demo-before','影响依据',TARGET)
    with pytest.raises(KeyError):service.ask('demo-partial','继续',TARGET,parent_id=first['id'])
    with pytest.raises(InputError):service.ask('demo-before','继续',TARGET,mode='text',parent_id=first['id'])


def test_followup_explicit_target_overrides_previous_target(service):
    first=service.ask('demo-before','升级到 4.18.1 的要求？',TARGET)
    second=service.ask('demo-before','那升级到 4.17.21 呢？',TARGET,parent_id=first['id'])
    assert second['facts']['target_version']=='4.17.21'


def test_new_question_without_parent_does_not_inherit_target(service):
    service.ask('demo-before','升级到 4.18.1 的要求？',TARGET)
    assert service.ask('demo-before','来源？',TARGET)['facts']['target_version'] is None


def test_configuration_validation_never_echoes_secret(tmp_path):
    with TestClient(create_app(tmp_path/'api.sqlite3')) as client:
        bad={**configuration(),'api_key':'secret-value-'*1000}
        result=client.post('/api/model/connect',json=bad)
        assert result.status_code==422 and 'secret-value-' not in result.text
        assert not client.get('/api/model/settings').json()['verified']


def test_demo_is_idempotent_and_reports_are_escaped(tmp_path):
    with TestClient(create_app(tmp_path/'api.sqlite3')) as client:
        first=client.post('/api/demo/prepare').json();second=client.post('/api/demo/prepare').json()
        assert first['document']['id']==second['document']['id']
        assert len(client.get('/api/snapshots/demo-before/documents').json())==1
        client.post('/api/snapshots/demo-before/ask',json={'question':'<script>alert(1)</script> 这个漏洞来源？','focus':TARGET})
        report=client.get('/api/demo/report')
        assert report.status_code==200 and 'text/html' in report.headers['content-type']
        assert '<script>alert(1)</script>' not in report.text
        assert '&lt;script&gt;' in report.text
        assert client.get('/api/snapshots/demo-before/report?format=html').status_code==200
        assert client.get('/api/snapshots/demo-before/report?format=other').status_code==400


def test_graph_paths_are_quotable_evidence_only_in_graph_mode(service,monkeypatch):
    service.models.saved=configuration()
    seen=[]
    def handler(request):
        payload=json.loads(request.content);context=json.loads(payload['messages'][-1]['content']);seen.append(context)
        graphs=[e for e in context['evidence'] if e['source']=='graph-evidence']
        evidence=graphs[0] if graphs else context['evidence'][0]
        text='1.0.0 业务组件通过已声明的依赖关系引入受影响组件。' if graphs else '应依据公告与项目回归测试核对处理结果。'
        return response({'claims':[{'text':text,'evidence_ids':[evidence['id']],
                                    'quotes':[{'evidence_id':evidence['id'],'quote':evidence['text'][:100]}]}]})
    fake_client(monkeypatch,handler)
    graph=service.ask('demo-before','来源路径？',TARGET,use_model=True)
    assert graph['generation']=='model-assisted'
    assert any(c['source']=='graph-evidence' for c in graph['citations'])
    text=service.ask('demo-before','公告依据？',TARGET,mode='text',use_model=True)
    assert not any(e['source']=='graph-evidence' for e in seen[-1]['evidence'])
    assert text['generation']=='model-assisted' and not text['paths']


def test_invalid_environment_url_does_not_echo_a_secret(tmp_path,monkeypatch):
    monkeypatch.setenv('LZ_LLM_BASE_URL','https://example.com/v1?api_key=private-placeholder')
    monkeypatch.setenv('LZ_LLM_API_KEY',KEY);monkeypatch.setenv('LZ_LLM_MODEL','model')
    result=ModelSettings(tmp_path/'model.json').public()
    assert not result['configured'] and 'private-placeholder' not in json.dumps(result)
