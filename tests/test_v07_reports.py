from pathlib import Path

from lianzheng.reports import report_html
from lianzheng.service import Service

ROOT=Path(__file__).resolve().parent.parent


def test_case_report_escapes_sources_and_keeps_recorded_scope(tmp_path):
    service=Service(tmp_path/'db.sqlite3',ROOT/'fixtures');service.seed();analysis=service.analyze('demo-before')
    analysis['snapshot']['demo']=False
    payload='<img src=x onerror=alert(1)>'
    analysis['real_case']={'available':True,'title':payload,'source':{'url':payload,'commit':payload},
        'verification':{'target_before_count':2,'target_partial_count':1,'target_after_count':0,'comparison_complete':False},
        'current':{'basis_matches_recorded':False},'tests':{'after':{'command':payload,'exit_code':0,'summary':payload}},
        'limitations':[payload]}
    report=report_html(analysis,[])
    assert '<img src=x' not in report and '&lt;img src=x' in report
    assert '冻结记录' in report and '当前工作空间的扫描依据已变化' in report
    assert '不能把已知位置的命中下降解释成完整风险已消除' in report
    assert '该快照来自导入清单' in report and '演示业务拓扑和迁移检查样例为人为构造' not in report


def test_missing_case_does_not_invent_execution_results(tmp_path):
    service=Service(tmp_path/'db.sqlite3',ROOT/'fixtures');service.seed()
    report=report_html(service.analyze('demo-before'),[])
    assert '真实项目修复实验' not in report and '实际执行记录' not in report
