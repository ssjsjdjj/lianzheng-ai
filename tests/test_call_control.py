"""Local admission-control tests. All provider transport is replaced or forbidden."""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from lianzheng.call_control import CallControl
from lianzheng.domain import InputError
from lianzheng.providers import ChatClient, ModelError
from lianzheng.service import Service
from lianzheng.store import Store


ROOT = Path(__file__).resolve().parent.parent
KEY = 'test-call-control-placeholder-not-a-real-key'


@pytest.fixture(autouse=True)
def no_external_http(monkeypatch):
    for key in ('LZ_LLM_PROVIDER', 'LZ_LLM_BASE_URL', 'LZ_LLM_MODEL', 'LZ_LLM_API_KEY',
                'OPENAI_API_KEY', 'DEEPSEEK_API_KEY', 'LZ_EMBEDDING_BASE_URL', 'LZ_EMBEDDING_MODEL'):
        monkeypatch.delenv(key, raising=False)
    def forbidden(*args, **kwargs):
        raise AssertionError('Call-control tests must never access an external API')
    monkeypatch.setattr('httpx.Client.request', forbidden)


@pytest.fixture
def guard(tmp_path):
    return CallControl(Store(tmp_path / 'guard.sqlite3'))


def configuration(**changes):
    return {'provider': 'openai', 'base_url': 'https://api.openai.com/v1', 'model': 'gpt-6-luna',
            'api_key': KEY, 'remember_key': False, 'json_mode': True, 'strict_citations': True, **changes}


def payload(question='为什么？', **changes):
    return {'model': 'gpt-6-luna', 'service_tier': 'default', 'input': [{'role': 'user', 'content': question}],
            'max_output_tokens': 2400, **changes}


def measured(amount=.0001, **usage):
    return {'cost_estimate': {'currency': 'USD', 'amount': amount},
            'usage': {'input_tokens': 100, 'output_tokens': 20, **usage}}


def test_daily_limit_counts_failed_attempts_and_rejections_make_no_new_ticket(guard):
    guard.update({'daily_calls': 1})
    ticket = guard.reserve(configuration(), payload())
    guard.finish(ticket, None, 'failed')
    with pytest.raises(ModelError, match='次数上限'):
        guard.reserve(configuration(), payload('另一个问题'))
    public = guard.public()
    assert public['calls_today'] == 1 and public['unknown_cost_calls'] == 1
    assert public['budget_accounted_usd'] > 0 and public['recent'][0]['status'] == 'failed'


def test_two_service_instances_admit_only_one_concurrent_ticket(guard):
    other = CallControl(guard.store)
    guard.update({'daily_calls': 1})
    barrier = threading.Barrier(8)
    def reserve(index):
        barrier.wait(timeout=5)
        try:
            return (guard if index % 2 else other).reserve(configuration(), payload(str(index)))
        except ModelError:
            return None
    with ThreadPoolExecutor(max_workers=8) as executor:
        tickets = list(executor.map(reserve, range(8)))
    accepted = [ticket for ticket in tickets if ticket]
    assert len(accepted) == 1 and guard.public()['calls_today'] == 1
    guard.finish(accepted[0], measured(), 'returned')
    with pytest.raises(ModelError, match='次数上限'):
        other.reserve(configuration(), payload('after finish'))


def test_identical_in_flight_request_is_rejected_even_if_limits_disabled(guard):
    guard.update({'enabled': False})
    ticket = guard.reserve(configuration(), payload())
    with pytest.raises(ModelError, match='相同请求'):
        guard.reserve(configuration(), payload())
    assert guard.public()['calls_today'] == 1
    guard.finish(ticket, measured(), 'returned')
    assert guard.reserve(configuration(), payload())


def test_old_in_flight_ticket_is_not_assumed_free_or_silently_reissued(guard):
    ticket = guard.reserve(configuration(), payload())
    reservation = guard.public()['budget_accounted_usd']
    with guard.store.connect() as db:
        db.execute('UPDATE chat_calls SET started=? WHERE id=?', (time.time() - 1000, ticket))
    with pytest.raises(ModelError):
        guard.reserve(configuration(), payload())
    public = guard.public()
    assert public['calls_today'] == 1 and public['in_flight'] == 1
    assert public['budget_accounted_usd'] == reservation and public['unknown_cost_calls'] == 1


def test_known_model_reservation_is_applied_before_network(guard):
    guard.update({'daily_budget_usd': .001})
    with pytest.raises(ModelError, match='超过'):
        guard.reserve(configuration(), payload())
    assert guard.public()['calls_today'] == 0


def test_unknown_model_is_blocked_when_money_threshold_is_enabled(guard):
    guard.update({'daily_budget_usd': .1})
    with pytest.raises(ModelError, match='无法保守预估'):
        guard.reserve(configuration(model='unpriced-model'), payload(model='unpriced-model'))
    assert guard.public()['calls_today'] == 0


def test_unknown_unreserved_past_cost_blocks_later_budgeted_calls(guard):
    ticket = guard.reserve(configuration(model='unpriced-model'), payload(model='unpriced-model'))
    guard.finish(ticket, {'usage': {'input_tokens': 50}}, 'failed')
    guard.update({'daily_budget_usd': .1})
    with pytest.raises(ModelError, match='无法估算的历史调用'):
        guard.reserve(configuration(), payload())
    public = guard.public()
    assert public['unknown_cost_calls'] == public['unreserved_calls'] == 1
    assert public['calls_today'] == 1 and public['known_estimated_usd'] == 0


@pytest.mark.parametrize('cost', [
    {}, {'currency': 'EUR', 'amount': 0}, {'currency': 'USD', 'amount': -1},
    {'currency': 'USD', 'amount': float('nan')}, {'currency': 'USD', 'amount': float('inf')},
    {'currency': 'USD', 'amount': True}, {'currency': 'USD', 'amount': '0.01'},
])
def test_missing_or_invalid_cost_keeps_the_reservation_and_unknown_flag(guard, cost):
    ticket = guard.reserve(configuration(), payload())
    before = guard.public()['budget_accounted_usd']
    guard.finish(ticket, {'cost_estimate': cost}, 'returned')
    public = guard.public()
    assert public['unknown_cost_calls'] == 1 and public['budget_accounted_usd'] == before
    assert public['recent'][0]['cost_estimate'] is None


def test_valid_cost_replaces_reservation_and_zero_token_counts_survive(guard):
    ticket = guard.reserve(configuration(), payload())
    guard.finish(ticket, measured(.0001, input_tokens=0, output_tokens=0), 'returned')
    public = guard.public()
    assert public['unknown_cost_calls'] == 0 and public['budget_accounted_usd'] == .0001
    assert public['recent'][0]['input_tokens'] == public['recent'][0]['output_tokens'] == 0


def test_parallel_partial_policy_updates_do_not_overwrite_each_other(guard, monkeypatch):
    original = guard.public
    barrier = threading.Barrier(2)
    seen = threading.local()
    def coordinated_public():
        result = original()
        if not getattr(seen, 'called', False):
            seen.called = True
            barrier.wait(timeout=5)
        return result
    monkeypatch.setattr(guard, 'public', coordinated_public)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(guard.update, values) for values in
                   ({'daily_calls': 3}, {'daily_budget_usd': .1})]
        for future in futures:
            future.result(timeout=8)
    policy = original()['policy']
    assert policy['daily_calls'] == 3 and policy['daily_budget_usd'] == .1


def test_utc_day_reset_applies_to_completed_calls(guard, monkeypatch):
    class Clock:
        value = datetime(2026, 11, 11, 23, 59, tzinfo=timezone.utc)
        @classmethod
        def now(cls, tz):
            return cls.value
    monkeypatch.setattr('lianzheng.call_control.datetime', Clock)
    guard.update({'daily_calls': 1})
    ticket = guard.reserve(configuration(), payload())
    guard.finish(ticket, measured(), 'returned')
    Clock.value += timedelta(minutes=2)
    assert guard.public()['calls_today'] == 0
    assert guard.reserve(configuration(), payload())


def test_previous_day_unfinished_request_stays_visible_and_blocks_new_requests(guard, monkeypatch):
    class Clock:
        value = datetime(2026, 11, 11, 23, 59, tzinfo=timezone.utc)
        @classmethod
        def now(cls, tz):
            return cls.value
    monkeypatch.setattr('lianzheng.call_control.datetime', Clock)
    ticket = guard.reserve(configuration(), payload())
    Clock.value += timedelta(minutes=2)
    public = guard.public()
    assert public['calls_today'] == 0 and public['in_flight'] == 1
    assert len(public['outstanding']) == 1 and public['outstanding'][0]['id'] == ticket
    assert KEY not in json.dumps(public)
    with pytest.raises(ModelError):
        guard.reserve(configuration(), payload('新一天的问题'))
    guard.finish(ticket, None, 'failed')
    assert guard.public()['in_flight'] == 0 and guard.public()['outstanding'] == []
    assert guard.reserve(configuration(), payload('旧请求结束后可继续'))


@pytest.mark.parametrize('values', [
    {'daily_calls': 0}, {'daily_calls': 1001}, {'daily_calls': True}, {'daily_calls': 1.2},
    {'daily_budget_usd': 0}, {'daily_budget_usd': -1}, {'daily_budget_usd': True},
    {'daily_budget_usd': float('nan')}, {'daily_budget_usd': float('inf')},
    {'enabled': 'false'}, {'unexpected': 3},
])
def test_invalid_policy_is_rejected_without_modifying_current_policy(guard, values):
    before = guard.public()['policy']
    with pytest.raises(InputError):
        guard.update(values)
    assert guard.public()['policy'] == before


def test_provider_failure_finishes_ticket_and_does_not_automatically_retry(guard, monkeypatch):
    calls = []
    def fail(*args, **kwargs):
        calls.append(1)
        raise ModelError('simulated supplier failure', measured(.0002))
    monkeypatch.setattr(ChatClient, '_request', fail)
    with pytest.raises(ModelError):
        ChatClient(configuration(usage_guard=guard)).probe()
    public = guard.public()
    assert len(calls) == public['calls_today'] == 1
    assert public['in_flight'] == 0 and public['recent'][0]['status'] == 'failed'
    assert public['budget_accounted_usd'] == .0002


def test_connection_probe_and_question_share_the_same_application_limit(tmp_path, monkeypatch):
    service = Service(tmp_path / 'integration.sqlite3', ROOT / 'fixtures')
    service.seed()
    service.models.dotenv = None
    service.call_control.update({'daily_calls': 1})
    calls = []
    def fake_request(self, *args, **kwargs):
        calls.append(1)
        return '{"ok":true}', measured()
    monkeypatch.setattr(ChatClient, '_request', fake_request)
    service.models.test_and_save(configuration())
    answer = service.ask('demo-before', '漏洞从哪里来？', 'GHSA-29mw-wpgm-hmr9', use_model=True)
    assert answer['generation'] == 'evidence-template'
    assert any('次数上限' in limit for limit in answer['limits'])
    assert len(calls) == service.call_control.public()['calls_today'] == 1
    assert KEY not in json.dumps(service.call_control.public())


def test_bad_model_citation_still_counts_as_a_billable_request(tmp_path, monkeypatch):
    service = Service(tmp_path / 'bad-citation.sqlite3', ROOT / 'fixtures')
    service.seed(); service.models.dotenv = None; service.models.saved = configuration()
    calls = []
    def invalid_citation(self, *args, **kwargs):
        calls.append(1)
        return json.dumps({'claims': [{'text': '无法支持的结论', 'quote_ids': ['made-up']}],
                           'follow_up_questions': []}), measured()
    monkeypatch.setattr(ChatClient, '_request', invalid_citation)
    answer = service.ask('demo-before', '漏洞路径？', 'GHSA-29mw-wpgm-hmr9', use_model=True)
    assert answer['generation'] == 'evidence-template' and answer['model_attempt']['cost_estimate']['amount'] > 0
    assert service.call_control.public()['calls_today'] == len(calls) == 1
    assert service.call_control.public()['budget_accounted_usd'] > 0
