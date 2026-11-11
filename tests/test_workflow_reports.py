import copy
from html import escape
from html.parser import HTMLParser
from pathlib import Path

import pytest

from lianzheng.reports import report_html
from lianzheng.service import Service


ROOT=Path(__file__).resolve().parent.parent


@pytest.fixture
def analysis(tmp_path,monkeypatch):
    def forbidden(*args,**kwargs):
        raise AssertionError('Report export must not call an external service')
    monkeypatch.setattr('httpx.Client.request',forbidden)
    service=Service(tmp_path/'report.sqlite3',ROOT/'fixtures');service.seed()
    return service.analyze('demo-before')


def reviewed_claim(status='pending'):
    return {'answer_id':7,'question':'发布前要做什么？','claims':[
        {'claim_index':0,'text':'文档要求执行回归测试。',
         'literal_check':{'status':'matched','quotes':[{'evidence_id':'doc-1','quote':'上线前必须执行回归测试。',
                                                     'source_title':'迁移说明','source_locator':'第 2 行'}]},
         'review':{'status':status,'note':'只支持测试要求，不证明已经通过。','updated_at':'2026-11-11'},
         'stale_review_count':0}]}


def task(status='todo'):
    return {'id':'task-1','title':'处理目标公告','focus':'GHSA-example','owner':'张工','status':status,
            'source_snapshot':{'id':'before','label':'初始清单','project':'真实项目','hash':'before-sha'},
            'candidate_versions':['2.0.0'],
            'checks':[{'id':'build','label':'完成构建并保存结果','done':True},
                      {'id':'rollback','label':'准备回滚方案','done':False}],
            'events':[{'created':'2026-11-11','details':{'note':'等待维护者复核'}}],
            'verification':None}


def passed_task():
    result=task('verified')
    result['verification']={'created':'2026-11-11','passed':True,'source_unchanged':True,
                            'comparison_complete':True,'same_knowledge_snapshot':True,'resolved':True,
                            'not_observed':False,'remaining_occurrences':[],'reasons':[],
                            'after_snapshot':{'id':'after','label':'修复后清单','hash':'after-sha'},
                            'note':'目标公告在当时完整清单下无匹配。'}
    return result


def test_legacy_report_without_workflow_fields_remains_exportable(analysis):
    html=report_html(analysis,[])
    assert '本报告未包含逐条人工复核记录' in html
    assert '本报告未包含修复任务记录' in html
    assert '@media print' in html and '@page{size:A4' in html


def test_literal_match_does_not_change_pending_into_supported(analysis):
    analysis['claim_reviews']=[reviewed_claim()]
    html=report_html(analysis,[])
    assert '原文逐字匹配通过' in html and '结论 1 · 待人工复核' in html
    assert '结论 1 · 人工标记：支持' not in html
    assert '不是自动真伪判定' in html and '不能单独证明语义支持' in html


@pytest.mark.parametrize('status,label',[
    ('supported','支持'),('partial','部分支持'),('insufficient','证据不足'),('conflict','来源冲突')])
def test_human_judgments_and_scope_notes_export_with_human_attribution(analysis,status,label):
    record=reviewed_claim(status);record['claims'][0]['stale_review_count']=1
    analysis['claim_reviews']=[record]
    html=report_html(analysis,[])
    assert '结论 1 · 人工标记：'+label in html
    assert '只支持测试要求，不证明已经通过。' in html
    assert '1 份旧内容标注已隔离' in html
    assert '上线前必须执行回归测试。' in html


def test_verified_task_reports_inventory_scope_and_manual_checklist_separately(analysis):
    analysis['remediation_tasks']=[passed_task()]
    html=report_html(analysis,[])
    assert '已记录目标公告清单复核通过' in html
    assert '通过（仅对应当时的目标公告与清单范围）' in html
    assert '不代表全部风险消除、业务测试通过、兼容性保证或可以上线' in html
    assert '人工勾选已完成：完成构建并保存结果' in html
    assert '待完成：准备回滚方案' in html
    assert 'before-sha' in html and 'after-sha' in html and '张工' in html
    assert '这不是依赖可解析或业务兼容性的承诺' in html


@pytest.mark.parametrize('mutate',[
    lambda t:t.update(verification=None),
    lambda t:t['verification'].update(passed=False),
    lambda t:t['verification'].update(comparison_complete=None),
    lambda t:t['verification'].update(not_observed=True),
    lambda t:t['verification'].update(after_snapshot={}),
    lambda t:t['verification'].update(reasons=[{'message':'来源证据已经变化'}]),
])
def test_verified_label_alone_cannot_claim_a_complete_success_receipt(analysis,mutate):
    value=passed_task();mutate(value)
    analysis['remediation_tasks']=[value]
    html=report_html(analysis,[])
    assert '状态记录为 verified，但复核凭据不完整；本报告不确认通过' in html
    assert '结果：通过（仅对应当时的目标公告与清单范围）' not in html


def test_not_observed_is_distinguished_from_resolved(analysis):
    value=task('needs_review')
    value['verification']={'passed':False,'not_observed':True,'after_snapshot':{'id':'after'},
                           'reasons':[{'code':'knowledge_changed','message':'两份清单的公告获取时间不同。'}]}
    analysis['remediation_tasks']=[value]
    html=report_html(analysis,[])
    assert '结果：未通过' in html
    assert '目标公告仅为“未观察到”，不能据此记为已修复' in html
    assert '两份清单的公告获取时间不同。' in html


def test_all_workflow_free_text_is_escaped_and_unrelated_config_is_not_exported(analysis):
    attack='<script>alert("review")</script><img src=x onerror="alert(1)">'
    record=reviewed_claim('partial')
    record.update(question=attack,api_key='secret-should-not-export')
    claim=record['claims'][0]
    claim.update(text=attack)
    claim['review'].update(note=attack,updated_at=attack,protected_key='secret-should-not-export')
    claim['literal_check']['quotes'][0].update(quote=attack,evidence_id=attack,source_title=attack,source_locator=attack)
    value=passed_task();value.update(title=attack,owner=attack,focus=attack,id=attack,api_key='secret-should-not-export')
    value['source_snapshot'].update(id=attack,label=attack,project=attack,hash=attack)
    value['checks'][0]['label']=attack
    value['events'][0]['details']['note']=attack
    value['verification'].update(note=attack,reasons=[{'message':attack}])
    value['verification']['after_snapshot'].update(id=attack,label=attack,hash=attack)
    analysis.update(claim_reviews=[record],remediation_tasks=[value])
    html=report_html(analysis,[])
    assert attack not in html and escape(attack,quote=True) in html
    assert 'secret-should-not-export' not in html
    class Tags(HTMLParser):
        names=[]
        def handle_starttag(self,tag,attrs):self.names.append(tag)
    parsed=Tags();parsed.feed(html)
    assert 'script' not in parsed.names and 'img' not in parsed.names


@pytest.mark.parametrize('reviews,tasks',[
    (None,None),({},{}),('unexpected','unexpected'),([None,False,'legacy'],[None,False,'legacy']),
    ([{'claims':None}],[{'verification':None,'checks':None,'source_snapshot':None}]),
    ([{'claims':[{}, {'review':[], 'literal_check':{'status':[]}}]}],
     [{'status':[],'verification':{'passed':'yes','reasons':'unknown'},'checks':[{'done':'yes'}]}]),
])
def test_missing_or_unknown_workflow_fields_do_not_break_old_exports(analysis,reviews,tasks):
    analysis.update(claim_reviews=reviews,remediation_tasks=tasks)
    html=report_html(analysis,[])
    assert html.startswith('<!doctype html>') and html.endswith('</html>')
    assert '结果：通过（仅对应当时的目标公告与清单范围）' not in html


def test_budget_describes_selected_excerpts_instead_of_document_prefix(analysis):
    answer={'generation':'evidence-template','conclusion':'本地事实。','model_explanation':None,'limits':[],
            'citations':[],'model_budget':{'input_bytes':100,'limit_bytes':48000,'evidence_count':2,
                                         'truncated_evidence':1,'omitted_evidence':0}}
    html=report_html(analysis,[{'question':'迁移要求？','answer':answer}])
    assert '其中节选 1 条' in html and '前段摘取' not in html
