import copy
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from lianzheng.domain import InputError, npm_identity, parse_bom, representative_paths, reachable_nodes, affected_fixed_versions
from lianzheng.service import Service
from lianzheng.osv import OSVClient
from lianzheng.retrieval import Retriever, model_explanation
from lianzheng.app import create_app

ROOT=Path(__file__).resolve().parent.parent
TARGET='GHSA-29mw-wpgm-hmr9'


@pytest.fixture
def service(tmp_path):
    instance=Service(tmp_path/'test.sqlite3',ROOT/'fixtures')
    instance.seed()
    return instance


@pytest.fixture
def bom():
    return json.loads((ROOT/'fixtures/before.cdx.json').read_text(encoding='utf-8'))


def test_two_independent_occurrences_are_preserved(service):
    analysis=service.analyze('demo-before',TARGET)
    assert len(analysis['nodes'])==5
    assert len(analysis['paths'])==2
    assert {p[-1] for p in analysis['paths']}=={'lodash-report','lodash-export'}


def test_partial_fix_keeps_target_vulnerability(service):
    result=service.compare('demo-before','demo-partial')
    assert TARGET in result['remaining']
    assert TARGET not in result['resolved']
    partial=service.analyze('demo-partial',TARGET)
    assert len(partial['paths'])==1


def test_resolved_fix_checks_full_graph(service):
    result=service.compare('demo-before','demo-resolved')
    assert TARGET in result['resolved']
    assert result['remaining']==[]
    assert result['after_stats']['vulnerabilities']==0


def test_41721_is_not_assumed_free_of_all_vulnerabilities(service):
    analysis=service.analyze('demo-partial')
    hits=[v for v in analysis['findings'] if v['version']=='4.17.21']
    assert hits and TARGET not in {v['id'] for v in hits}


def test_missing_dependency_reference_is_never_invented(bom):
    bom['dependencies'][1]['dependsOn'].append('missing-node')
    graph=parse_bom(bom)
    assert not graph['complete']
    assert any(i['code']=='dangling' for i in graph['issues'])
    assert not any(e['target']=='missing-node' for e in graph['edges'])


def test_missing_leaf_declaration_limits_coverage(bom):
    bom['dependencies'].pop()
    assert not parse_bom(bom)['complete']


def test_duplicate_ref_rejected(bom):
    bom['components'].append(copy.deepcopy(bom['components'][0]))
    with pytest.raises(InputError,match='重复'):
        parse_bom(bom)


def test_root_must_be_declared(bom):
    del bom['metadata']
    with pytest.raises(InputError):parse_bom(bom)


def test_scoped_npm_identity():
    assert npm_identity({'name':'thing','group':'@scope','version':'1.2.3','purl':'pkg:npm/%40scope/thing@1.2.3'})==('@scope/thing','1.2.3',None)


@pytest.mark.parametrize('component',[
 {'name':'lodash','version':'4.17.20','purl':'pkg:npm/lodash@4.17.21'},
 {'name':'other','version':'4.17.20','purl':'pkg:npm/lodash@4.17.20'},
 {'name':'lodash','purl':'pkg:npm/lodash@%5E4.0.0'},
 {'name':'lodash','version':'4.17.20'},
 {'name':'lodash','purl':'pkg:pypi/lodash@4.17.20'},
])
def test_ambiguous_package_identity_is_not_guessed(component):
    assert npm_identity(component)[2]


def test_display_path_limit_does_not_limit_reachability():
    edges=[{'source':'root','target':str(i)} for i in range(9)]
    edges += [{'source':str(i),'target':'target'} for i in range(9)]
    graph={'root':'root','edges':edges}
    shown=representative_paths(graph,'target',limit=2)
    assert len(shown['paths'])==2 and shown['truncated']
    assert 'target' in reachable_nodes('root',edges)


def test_cycle_terminates_without_losing_reachability():
    graph={'root':'r','edges':[{'source':'r','target':'a'},{'source':'a','target':'r'},{'source':'a','target':'b'}]}
    assert representative_paths(graph,'b')['paths']==[['r','a','b']]


def test_deep_path_can_be_reachable_even_when_display_is_truncated():
    edges=[{'source':str(i),'target':str(i+1)} for i in range(30)]
    result=representative_paths({'root':'0','edges':edges},'30',max_depth=5)
    assert result['reachable'] and result['truncated'] and not result['paths']


def test_unknown_version_is_unscanned_not_clean(service,bom):
    for component in bom['components']:
        if component['name']=='lodash':
            component['version']='999.0.0';component['purl']='pkg:npm/lodash@999.0.0'
    result=service.import_bom(bom,project='unknown')
    assert result['stats']['unknown']>=2
    assert not result['can_confirm_absence']
    assert all(n['scan_status']=='unscanned' for n in result['nodes'] if n['name']=='lodash')


def test_incomplete_new_snapshot_does_not_claim_resolution(service,bom):
    clean=json.loads((ROOT/'fixtures/resolved.cdx.json').read_text(encoding='utf-8'))
    clean['dependencies'][1]['dependsOn'].append('missing')
    result=service.import_bom(clean,project='商城运营工作台')
    compared=service.compare('demo-before',result['snapshot']['id'])
    assert not compared['comparison_complete']
    assert compared['resolved']==[] and TARGET in compared['not_observed']


def test_fixed_versions_are_scoped_to_exact_package():
    record={'affected':[{'package':{'ecosystem':'npm','name':'lodash'},'ranges':[{'events':[{'fixed':'4.17.21'}]}]},
                        {'package':{'ecosystem':'npm','name':'lodash.template'},'ranges':[{'events':[{'fixed':'5.0.0'}]}]}]}
    assert affected_fixed_versions(record,'lodash')==['4.17.21']


def test_question_returns_citations_and_real_paths(service):
    answer=service.ask('demo-before','这个漏洞从哪里进入项目？',TARGET)
    assert len(answer['paths'])==2 and answer['citations']
    assert answer['generation']=='evidence-template'
    assert '规则' not in answer['conclusion']


def test_unknown_vulnerability_does_not_fall_back_to_selected_risk(service):
    answer=service.ask('demo-before','CVE-2099-999999 是否影响项目？',TARGET)
    assert answer['insufficient']
    assert not answer['citations'] and not answer['paths']


def test_exploitability_and_compatibility_are_unknown(service):
    answer=service.ask('demo-before','这个漏洞可利用吗，升级后兼容吗？',TARGET)
    assert answer['insufficient'] and '证据不足' in answer['conclusion']


def test_text_baseline_does_not_leak_graph_paths(service):
    answer=service.ask('demo-before','这个漏洞从哪里进入？',TARGET,mode='text')
    assert answer['paths']==[] and answer['citations']
    assert '不提供依赖路径' in answer['conclusion']


def test_history_and_snapshot_persist(service):
    service.ask('demo-before','查询依据',TARGET)
    another=Service(service.store.path,ROOT/'fixtures')
    assert len(another.store.history('demo-before'))==1
    assert len(another.list_snapshots())==3


def mocked_client(monkeypatch,handler):
    original=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))


def test_osv_pagination_is_fully_read(service,monkeypatch):
    requests=[]
    def handler(request):
        body=json.loads(request.content);requests.append(body)
        return httpx.Response(200,json={'vulns':[{'id':'A'}],'next_page_token':'page2'} if 'page_token' not in body else {'vulns':[{'id':'B'}]})
    mocked_client(monkeypatch,handler)
    result=service.osv.query('some-package','1.0.0',live=True)
    assert result['status']=='checked'
    assert [x['id'] for x in result['data']['vulns']]==['A','B']
    assert requests[1]['page_token']=='page2'


def test_osv_failure_is_not_clean(service,monkeypatch):
    mocked_client(monkeypatch,lambda request:httpx.Response(503,text='unavailable'))
    result=service.osv.query('some-package','1.0.0',live=True)
    assert result['status']=='failed' and result['error']


def test_bm25_only_retrieves_selected_vulnerability(service):
    docs=service.store.documents('demo-before')
    results,mode,warning=Retriever().retrieve('lodash',docs,focus=TARGET)
    assert results and all(d['vulnerability']==TARGET for d in results)
    assert mode=='bm25'


def test_embedding_fuses_real_vectors_and_falls_back(service,monkeypatch):
    monkeypatch.setenv('LZ_EMBEDDING_BASE_URL','https://provider.invalid/v1')
    monkeypatch.setenv('LZ_EMBEDDING_MODEL','test-model')
    def handler(request):
        inputs=json.loads(request.content)['input']
        return httpx.Response(200,json={'data':[{'index':i,'embedding':[float(i+1),1.0]} for i in range(len(inputs))]})
    mocked_client(monkeypatch,handler)
    results,mode,warning=Retriever().retrieve('lodash',service.store.documents('demo-before'),focus=TARGET)
    assert mode=='bm25+embedding-rrf' and results


def test_invalid_model_citation_is_rejected(monkeypatch):
    monkeypatch.setenv('LZ_LLM_BASE_URL','https://provider.invalid/v1');monkeypatch.setenv('LZ_LLM_MODEL','test')
    mocked_client(monkeypatch,lambda request:httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'explanation':'unsupported','evidence_ids':['invented']})}}]}))
    result,warning=model_explanation('why',{'facts':{},'evidence':[{'id':'real'}]})
    assert result is None and warning


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path/'api.sqlite3')) as instance:
        yield instance


def test_api_complete_flow(client,bom):
    assert client.get('/api/health').json()['status']=='ok'
    assert len(client.get('/api/snapshots').json())==3
    imported=client.post('/api/snapshots',json={'bom':bom,'project':'test project','label':'uploaded'})
    assert imported.status_code==201
    identifier=imported.json()['snapshot']['id']
    answer=client.post(f'/api/snapshots/{identifier}/ask',json={'question':'依赖路径？','focus':TARGET})
    assert answer.status_code==200 and answer.json()['citations']
    assert client.get(f'/api/snapshots/{identifier}/report').status_code==200
    assert client.get(f'/api/snapshots/{identifier}/bom').json()==bom


@pytest.mark.parametrize('payload',[[],{}, {'bom':{'bomFormat':'SPDX'}},{'bom':{'bomFormat':'CycloneDX','specVersion':'1.6','metadata':[]}}])
def test_invalid_uploads_have_clear_errors(client,payload):
    assert client.post('/api/snapshots',json=payload).status_code==400


def test_other_project_comparison_rejected(client,bom):
    result=client.post('/api/snapshots',json={'bom':bom,'project':'unrelated'}).json()
    response=client.get('/api/compare',params={'before':'demo-before','after':result['snapshot']['id']})
    assert response.status_code==400


def test_cross_site_write_is_rejected(client):
    response=client.post('/api/snapshots/demo-before/scan',json={'live':False},headers={'Origin':'https://untrusted.invalid'})
    assert response.status_code==403


def test_missing_snapshot_is_404(client):
    assert client.get('/api/snapshots/missing').status_code==404


def test_csp_and_frontend_are_served(client):
    response=client.get('/')
    assert response.status_code==200
    assert "script-src 'self'" in response.headers['Content-Security-Policy']
    assert client.get('/static/app.js').status_code==200
