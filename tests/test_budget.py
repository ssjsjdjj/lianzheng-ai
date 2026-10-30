import copy
import json

from lianzheng.budget import MAX_INPUT_BYTES, bounded_context, input_size
from lianzheng.providers import ModelError
from lianzheng.retrieval import model_explanation


def context(text='迁移后应分别执行报表与导出入口的回归测试。'):
    return {'facts': {'fixed_versions': ['4.17.21']}, 'paths': [],
            'evidence': [{'id': 'source-1', 'text': text, 'version': '4.17.20'}]}


def config():
    return {'provider': 'deepseek', 'base_url': 'https://api.deepseek.com',
            'model': 'deepseek-flash', 'api_key': 'test-only-placeholder', 'strict_citations': True}


def test_long_multibyte_input_is_bounded_without_changing_original():
    original = context('原文证据内容。' * 30_000)
    original['evidence'] *= 8
    original['evidence'] = [{**item, 'id': f'source-{i}'} for i, item in enumerate(original['evidence'])]
    original['conversation'] = [{'question': '历史问题' * 1000} for _ in range(5)]
    before = copy.deepcopy(original)
    bounded, receipt = bounded_context('系统提示', '当前问题', original)
    assert not receipt['blocked']
    assert receipt['input_bytes'] == input_size('系统提示', '当前问题', bounded)
    assert receipt['input_bytes'] <= MAX_INPUT_BYTES
    assert receipt['truncated_evidence'] > 0
    assert receipt['history_turns'] <= 3
    assert original == before
    for item in bounded['evidence']:
        source = next(value for value in original['evidence'] if value['id'] == item['id'])
        assert source['text'].startswith(item['text'])


def test_immutable_facts_over_budget_prevent_a_paid_request(monkeypatch):
    original = context()
    original['facts']['large_fact'] = '不能静默改写的结构化事实' * 10_000
    def should_not_call(*args, **kwargs):
        raise AssertionError('A blocked budget must not call the API')
    monkeypatch.setattr('lianzheng.retrieval.ChatClient.complete', should_not_call)
    result, warning = model_explanation('说明影响', original, config())
    assert result is None and '预算' in str(warning)
    assert warning.metadata['input_budget']['blocked']
    assert 'usage' not in warning.metadata


def test_accepted_quote_comes_from_sent_excerpt_and_full_source_is_retained(monkeypatch):
    quote = '迁移后应分别执行报表与导出入口的回归测试。'
    original = context(quote + '冗长公告内容' * 20_000)
    seen = {}
    def complete(_self, messages, **kwargs):
        seen['messages'] = messages
        return json.dumps({'claims': [{'text': '应执行两类入口的回归测试。',
                          'evidence_ids': ['source-1'],
                          'quotes': [{'evidence_id': 'source-1', 'quote': quote}]}],
                          'follow_up_questions': []}, ensure_ascii=False), {'usage': {'total_tokens': 30}}
    monkeypatch.setattr('lianzheng.retrieval.ChatClient.complete', complete)
    result, warning = model_explanation('需要哪些测试？', original, config())
    assert warning is None and result['claims'][0]['quotes'][0]['quote'] == quote
    assert len(original['evidence'][0]['text']) > 4000
    sent = json.loads(seen['messages'][-1]['content'])
    assert len(sent['evidence'][0]['text']) <= 4000
    assert sent['evidence'][0]['excerpted']
    assert result['metadata']['input_budget']['truncated_evidence'] == 1


def test_unseen_tail_cannot_be_used_as_a_model_quote(monkeypatch):
    tail = '末尾新增要求需要人工审批并执行额外测试。'
    original = context('前段无关文字。' * 1000 + tail)
    def complete(*args, **kwargs):
        return json.dumps({'claims': [{'text': '需要人工审批。', 'evidence_ids': ['source-1'],
                           'quotes': [{'evidence_id': 'source-1', 'quote': tail}]}]}), {'usage': {'total_tokens': 40}}
    monkeypatch.setattr('lianzheng.retrieval.ChatClient.complete', complete)
    result, warning = model_explanation('要求？', original, config())
    assert result is None and '摘录' in str(warning)
    assert warning.metadata['usage']['total_tokens'] == 40


def test_provider_failure_still_preserves_available_usage(monkeypatch):
    def complete(*args, **kwargs):
        error = ModelError('输出未完整返回')
        error.metadata = {'usage': {'total_tokens': 27}}
        raise error
    monkeypatch.setattr('lianzheng.retrieval.ChatClient.complete', complete)
    result, warning = model_explanation('依据？', context(), config())
    assert result is None
    assert warning.metadata['usage']['total_tokens'] == 27
    assert warning.metadata['input_budget']['input_bytes'] <= MAX_INPUT_BYTES


def test_fallback_report_keeps_the_failed_attempt_usage(tmp_path,monkeypatch):
    from pathlib import Path
    from lianzheng.reports import report_html
    from lianzheng.service import Service
    service=Service(tmp_path/'report.sqlite3',Path(__file__).resolve().parent.parent/'fixtures')
    service.seed()
    service.models.saved=config()
    def complete(*args,**kwargs):
        raise ModelError('回复未完整返回',{'usage':{'total_tokens':27},'transport':'http-request','provider':'deepseek'})
    monkeypatch.setattr('lianzheng.retrieval.ChatClient.complete',complete)
    answer=service.ask('demo-before','这个漏洞从哪里进入？','GHSA-29mw-wpgm-hmr9',use_model=True)
    assert answer['generation']=='evidence-template' and answer['model_attempt']['usage']['total_tokens']==27
    html=report_html(service.analyze('demo-before'),service.store.history('demo-before'))
    assert '已有用量 27 tokens' in html and '仍可能计费' in html
    assert '不是 token 数' in html and 'test-only-placeholder' not in html
