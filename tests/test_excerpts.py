import copy
import json
from pathlib import Path

from lianzheng.budget import bounded_context
from lianzheng.excerpts import literal_spans, select_excerpt, source_position
from lianzheng.retrieval import model_explanation, quote_catalog
from lianzheng.service import Service


ROOT=Path(__file__).resolve().parent.parent
TARGET='GHSA-29mw-wpgm-hmr9'


def long_document():
    return ('项目背景与常规维护记录，供后续交接参考。\n'*300+
            '🧪 导出快照验收必须保留审批记录，并执行两次回归测试。\n'+
            '没有记录不能推断测试实际未执行。\n')


def test_question_selection_reaches_tail_and_maps_unicode_offsets():
    source=long_document()
    text,ranges=select_excerpt(source,'导出快照验收有什么要求？',400)
    assert '导出快照验收必须保留审批记录' in text and len(text)<=400
    item={'id':'doc','text':text,'excerpt_ranges':ranges}
    catalog=quote_catalog([item],'导出快照验收有什么要求？')
    assert '导出快照验收' in catalog[0]['quote']
    for quote in catalog:
        assert source[quote['source_start']:quote['source_end']]==quote['quote']
    assert catalog[0]['source_start']>4000


def test_omission_boundaries_cannot_be_quoted_as_original():
    item={'text':'原文第一段内容。\n[…]\n原文另一段内容。',
          'excerpt_ranges':[{'text_start':0,'text_end':8,'source_start':0,'source_end':8},
                            {'text_start':13,'text_end':21,'source_start':100,'source_end':108}]}
    assert source_position(item,4,18) is None
    assert source_position(item,13,21)==(100,108)


def test_catalog_is_bounded_literal_and_does_not_repeat_overlaps():
    source='prefixword '*40+' apiendpoint targetword '+('trailingword '*50)
    catalog=quote_catalog([{'id':'doc','text':source}],'apiendpoint targetword')
    assert 1<=len(catalog)<=4 and 'apiendpoint' in catalog[0]['quote']
    for i,a in enumerate(catalog):
        assert 8<=len(a['quote'])<=200
        assert source[a['source_start']:a['source_end']]==a['quote']
        for b in catalog[i+1:]:
            assert a['source_end']<=b['source_start'] or b['source_end']<=a['source_start']


def test_bounded_selection_keeps_original_and_receipt():
    source={'facts':{'fixed_versions':['4.17.21']},'paths':['root → target'],
            'evidence':[{'id':str(i),'text':long_document()+str(i)} for i in range(8)]}
    original=copy.deepcopy(source)
    result,receipt=bounded_context('system','导出快照验收',source,limit_bytes=12000,excerpt_selector=select_excerpt)
    assert source==original and result['facts']==source['facts'] and result['paths']==source['paths']
    assert not receipt['blocked'] and receipt['input_bytes']<=12000
    assert receipt['excerpt_selection']=='question-ranked'
    assert all('导出快照验收' in d['text'] for d in result['evidence'])


def test_empty_short_and_no_match_text_has_safe_behavior():
    assert literal_spans('')==[]
    assert select_excerpt('短文','query',20)==('短文',[])
    text,ranges=select_excerpt('unrelated content sentence.\n'*50,'不存在',240)
    assert len(text)<=240
    assert all(0<=r['source_start']<r['source_end'] for r in ranges)


def test_model_selection_returns_original_tail_location(monkeypatch):
    calls=[]
    def complete(self,messages,**kwargs):
        calls.append(messages)
        context=json.loads(messages[-1]['content'])
        quote=next(q for q in context['quote_catalog'] if '导出快照验收' in q['quote'])
        return json.dumps({'claims':[{'text':'验收需要审批记录与回归测试。','quote_ids':[quote['id']]}],
                           'follow_up_questions':[]}),{'provider':'openai'}
    monkeypatch.setattr('lianzheng.retrieval.ChatClient.complete',complete)
    source=long_document()
    answer,warning=model_explanation('导出快照验收有什么要求？',
        {'facts':{},'paths':[],'evidence':[{'id':'long-doc','text':source}]},
        {'provider':'openai','base_url':'https://api.openai.com/v1','model':'test','strict_citations':True})
    assert warning is None and len(calls)==1
    quote=answer['claims'][0]['quotes'][0]
    assert source[quote['source_start']:quote['source_end']]==quote['quote']
    assert quote['source_start']>4000


def test_answer_paths_are_exact_snapshot_edges_and_persist(tmp_path):
    service=Service(tmp_path/'links.sqlite3',ROOT/'fixtures');service.seed()
    answer=service.ask('demo-before','漏洞从哪里引入？',TARGET)
    graph=service.analyze('demo-before',TARGET)
    actual={(e['source'],e['target']):e['locator'] for e in graph['edges']}
    assert len(answer['path_details'])==2
    assert [p['nodes'] for p in answer['path_details']]==answer['paths']
    for path in answer['path_details']:
        assert path['snapshot_id']=='demo-before'
        assert all(actual[e['source'],e['target']]==e['locator'] for e in path['edges'])
    other=service.ask('demo-partial','漏洞从哪里引入？',TARGET)
    assert not {p['id'] for p in other['path_details']}&{p['id'] for p in answer['path_details']}
    assert service.ask('demo-before','漏洞从哪里引入？',TARGET,mode='text')['path_details']==[]
