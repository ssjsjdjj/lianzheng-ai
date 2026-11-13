"""Reference scoring is separate from retrieval and never a semantic score."""
from copy import deepcopy
import hashlib
import json

import pytest

from scripts.evaluate_project_questions import ROOT, checked_file, frozen, load_fixture, matches, render_html, score_references


def test_project_split_and_frozen_source_integrity():
    fixture=load_fixture()
    assert len(fixture['projects'])==3
    assert sum(len(p['tasks']) for p in fixture['projects'])==24
    assert fixture['frozen_before_retrieval'] is True
    for project in fixture['projects']:
        source=json.loads((ROOT/project['source']['path']).read_bytes())
        for task in project['tasks']:
            assert task['semantic_review']=='pending-independent-human-review'
            for ref in task['references']:
                if 'ref' in ref:
                    location=ref['ref'].removeprefix('npm:')
                    assert location in source['packages']
                    if ref['kind']=='occurrence':
                        assert ref['locator']=='/packages/'+location.replace('~','~0').replace('/','~1')
            if task['supplement']:
                assert '尚未执行测试' in task['supplement']['text']


def test_source_tampering_and_path_escape_rejected(tmp_path):
    (tmp_path/'source.json').write_bytes(b'{}')
    with pytest.raises(ValueError,match='hash mismatch'):
        checked_file(tmp_path,'source.json','0'*64)
    with pytest.raises(ValueError,match='escapes'):
        checked_file(tmp_path,'../outside.json','0'*64)
    assert checked_file(tmp_path,'source.json',hashlib.sha256(b'{}').hexdigest())==b'{}'


def test_exact_reference_scoring_keeps_misses_and_unscored_boundaries():
    refs=[{'kind':'occurrence','ref':'npm:node_modules/a'}, {'kind':'scan','ref':'npm:node_modules/a'}]
    docs=[{'kind':'occurrence','ref':'npm:node_modules/a','id':'a'}, {'kind':'occurrence','ref':'npm:node_modules/b','id':'b'}]
    assert score_references(refs,docs)=={'found':1,'total':2,'coverage':.5,'missing':[refs[1]]}
    assert score_references([],docs)=={'found':0,'total':0,'coverage':None,'missing':[]}
    assert not matches({'kind':'project','source':'user-document'}, {'kind':'project','source':'fixture'})


def test_fixture_rejects_project_split_leakage(tmp_path):
    fixture=deepcopy(load_fixture());fixture['projects'][2]['source']=fixture['projects'][0]['source']
    path=tmp_path/'fixture.json';path.write_text(json.dumps(fixture),encoding='utf-8')
    with pytest.raises(ValueError,match='overlap'):load_fixture(path)


def test_html_escapes_all_authored_question_and_answer_content():
    x='<script>alert(1)</script>'
    report={'project_count':1,'question_count':1,'model_calls':0,'passed':1,'total':1,'summary':[],
            'limitations':[x],'results':[{'id':'1','question':x,'project_id':'x','split':'dev','columns':[
                {'method':'bm25','reference_evidence':{'found':0,'total':0,'coverage':None,'missing':[]},
                 'answer_card':{'conclusion':{'text':x}},'selected':[]}]}]}
    html=render_html(report)
    assert '<script>' not in html and '&lt;script&gt;' in html
    assert '待人工复核' in html and '不计分' in html


def test_frozen_report_cannot_keep_dead_temporary_source_links():
    value={'source':{'snapshot_id':'temp','url':'/api/snapshots/temp'},'paths':[{'url':'/dead','locator':'/packages/x'}]}
    result=frozen(value)
    assert result=={'source':{'snapshot_id':'temp'},'paths':[{'locator':'/packages/x'}]}
    assert 'url' in value['source']


def test_report_endpoints_serve_offline_artifact_without_model_settings(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from lianzheng.app import create_app
    app=create_app(tmp_path/'report.sqlite3',seed=False)
    monkeypatch.setattr(app.state.service.models,'current',lambda:pytest.fail('Unexpected model settings access'))
    client=TestClient(app)
    page=client.get('/project-evaluation')
    assert page.status_code==200 and '多项目问答评测' in page.text
    download=client.get('/api/project-evaluation/report')
    assert download.status_code==200 and 'attachment' in download.headers['content-disposition']
    report=download.json()
    assert report['question_count']==24 and report['model_calls']==report['network_calls']==0
    assert all(row['answer_accuracy'] is None for row in report['summary'])
    assert not any('url' in row['source'] for row in report['results'])
    assert all(doc.get('source_excerpt') for row in report['results'] for col in row['columns'] for doc in col['selected'])
