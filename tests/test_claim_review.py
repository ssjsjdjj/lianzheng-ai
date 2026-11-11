import copy
import json
from pathlib import Path

import pytest

from lianzheng.claim_review import ClaimReviews
from lianzheng.domain import InputError
from lianzheng.service import Service


ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def records(tmp_path, monkeypatch):
    monkeypatch.delenv('LZ_EMBEDDING_BASE_URL', raising=False)
    monkeypatch.delenv('LZ_EMBEDDING_MODEL', raising=False)
    def forbidden(*args, **kwargs):
        raise AssertionError('Claim review tests must not call external HTTP services')
    monkeypatch.setattr('httpx.Client.request', forbidden)
    service = Service(tmp_path / 'reviews.sqlite3', ROOT / 'fixtures')
    service.seed()
    source = '🧪 发布前必须执行回归测试并提供审批记录。'
    quote = source[2:]
    answer = {'facts': {'snapshot_id': 'demo-before'},
              'citations': [{'id': 'doc-a', 'text': source, 'version': '4.17.20',
                             'title': '发布要求', 'locator': '第 1 行', 'snapshot_id': 'demo-before'}],
              'model_explanation': {'claims': [
                  {'text': '发布前需要提供回归测试和审批记录。', 'evidence_ids': ['doc-a'],
                   'quotes': [{'evidence_id': 'doc-a', 'quote': quote, 'source_start': 2, 'source_end': len(source)}]},
                  {'text': '测试已经通过，可以直接上线。', 'evidence_ids': ['doc-a'],
                   'quotes': [{'evidence_id': 'doc-a', 'quote': quote}]}]}}
    identifier = service.store.add_history('demo-before', '发布有什么要求？', answer)
    return service, ClaimReviews(service), identifier


def save(reviews, identifier, status='supported', note='仅支持要求提供记录，不证明已经完成。', index=0, **overrides):
    current = reviews.get('demo-before', identifier)['claims'][index]
    options = {'expected_fingerprint': current['fingerprint'], 'expected_revision': current['review']['revision']}
    options.update(overrides)
    return reviews.save('demo-before', identifier, index, status, note, **options)


def replace_answer(service, identifier, change):
    answer = service.store.history_item('demo-before', identifier)['answer']
    change(answer)
    with service.store.connect() as db:
        db.execute('UPDATE history SET answer=? WHERE id=?', (json.dumps(answer, ensure_ascii=False), identifier))


def test_literal_match_does_not_automatically_approve_semantic_claim(records):
    _, reviews, identifier = records
    result = reviews.get('demo-before', identifier)
    assert result['model_calls'] == 0
    assert all(c['literal_check']['status'] == 'matched' for c in result['claims'])
    assert all(c['review']['status'] == 'pending' for c in result['claims'])
    assert len(result['claims'][1]['attention_points']) == 2
    assert '不是错误判定' in result['claims'][1]['attention_points'][0]


def test_review_persists_without_rewriting_original_answer(records):
    service, reviews, identifier = records
    original = copy.deepcopy(service.store.history_item('demo-before', identifier)['answer'])
    result = save(reviews, identifier, status='partial')
    assert result['claims'][0]['review']['status'] == 'partial'
    assert result['claims'][0]['review']['method'] == 'human'
    assert result['claims'][0]['event_count'] == 1
    assert ClaimReviews(service).get('demo-before', identifier)['claims'][0]['review']['status'] == 'partial'
    assert service.store.history_item('demo-before', identifier)['answer'] == original
    assert result['claims'][1]['review']['status'] == 'pending'


def test_wrong_snapshot_and_other_answer_cannot_reuse_judgment(records):
    service, reviews, identifier = records
    with pytest.raises(KeyError):
        reviews.get('demo-partial', identifier)
    answer = service.store.history_item('demo-before', identifier)['answer']
    other = service.store.add_history('demo-before', '另一条问题', copy.deepcopy(answer))
    fingerprint = reviews.get('demo-before', identifier)['claims'][0]['fingerprint']
    with pytest.raises(InputError, match='已变化'):
        reviews.save('demo-before', other, 0, 'supported', 'note', expected_fingerprint=fingerprint)
    assert reviews.get('demo-before', other)['claims'][0]['event_count'] == 0


@pytest.mark.parametrize('change', [
    lambda a: a['model_explanation']['claims'][0].update(text='改写后的结论。'),
    lambda a: a['citations'][0].update(text='新来源文本：必须提供另一份证据。'),
    lambda a: a['facts'].update(target_version='9.9.9'),
])
def test_changed_claim_or_source_invalidates_old_review_and_old_submit(records, change):
    service, reviews, identifier = records
    saved = save(reviews, identifier)['claims'][0]
    replace_answer(service, identifier, change)
    current = reviews.get('demo-before', identifier)['claims'][0]
    assert current['review']['status'] == 'pending' and current['stale_review_count'] == 1
    assert current['events'][0]['current_content'] is False
    with pytest.raises(InputError, match='已变化'):
        reviews.save('demo-before', identifier, 0, 'supported', 'stale judgment', expected_fingerprint=saved['fingerprint'])


def test_concurrent_reviewer_must_reload_and_duplicate_save_is_idempotent(records):
    _, reviews, identifier = records
    original = reviews.get('demo-before', identifier)['claims'][0]
    save(reviews, identifier)
    with pytest.raises(InputError, match='已被更新'):
        save(reviews, identifier, status='conflict', expected_revision=original['review']['revision'])
    again = save(reviews, identifier)
    assert again['claims'][0]['event_count'] == 1 and again['claims'][0]['review']['revision'] == 1
    result = save(reviews, identifier, status='insufficient', note='缺少测试执行结果。')
    assert result['claims'][0]['events'][0]['previous_status'] == 'supported'
    assert result['claims'][0]['event_count'] == 2


def test_unicode_position_check_does_not_accept_wrong_repeated_sentence_offset(records):
    service, reviews, identifier = records
    replace_answer(service, identifier, lambda a: a['model_explanation']['claims'][0]['quotes'][0].update(source_start=1))
    result = reviews.get('demo-before', identifier)['claims'][0]
    assert result['literal_check']['status'] == 'mismatch'
    assert result['review']['status'] == 'pending'


def test_unquoted_legacy_claim_has_no_false_literal_approval(records):
    service, reviews, identifier = records
    replace_answer(service, identifier, lambda a: a['model_explanation']['claims'][0].update(quotes=[]))
    assert reviews.get('demo-before', identifier)['claims'][0]['literal_check']['status'] == 'no_quotes'


@pytest.mark.parametrize('kwargs', [
    {'status': 'verified'}, {'status': ['supported']}, {'note': 'x' * 1001}, {'note': None},
    {'claim_index': True}, {'claim_index': -1}, {'claim_index': 10},
    {'expected_fingerprint': None}, {'expected_fingerprint': 'bad'}, {'expected_revision': True},
])
def test_invalid_review_input_is_rejected_without_creating_events(records, kwargs):
    _, reviews, identifier = records
    fingerprint = reviews.get('demo-before', identifier)['claims'][0]['fingerprint']
    args = {'snapshot_id': 'demo-before', 'answer_id': identifier, 'claim_index': 0,
            'status': 'supported', 'note': 'review', 'expected_fingerprint': fingerprint}
    args.update(kwargs)
    with pytest.raises(InputError):
        reviews.save(**args)
    assert reviews.get('demo-before', identifier)['claims'][0]['event_count'] == 0


def test_notes_are_parameterized_and_audit_preserves_changes(records):
    service, reviews, identifier = records
    malicious = "'); DROP TABLE history; -- <img src=x onerror=alert(1)>"
    result = save(reviews, identifier, status='conflict', note=malicious)
    assert result['claims'][0]['review']['note'] == malicious
    assert service.store.history_item('demo-before', identifier)
    reset = save(reviews, identifier, status='pending', note='撤回判断，等待补充。')
    assert reset['claims'][0]['review']['status'] == 'pending'
    assert reset['claims'][0]['events'][1]['note'] == malicious


def test_local_template_answer_needs_no_fake_semantic_review(records):
    service, reviews, _ = records
    answer = service.ask('demo-before', '漏洞路径？', 'GHSA-29mw-wpgm-hmr9')
    assert reviews.get('demo-before', answer['id'])['claims'] == []
