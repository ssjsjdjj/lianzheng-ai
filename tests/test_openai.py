"""Offline OpenAI Responses protocol checks; no supplier acceptance is claimed."""
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from lianzheng.domain import InputError
from lianzheng.providers import ChatClient, ModelError, parse_json_content
from lianzheng.retrieval import model_explanation
from lianzheng.settings import ModelSettings


ROOT = Path(__file__).resolve().parent.parent
KEY = 'openai-unit-test-placeholder-not-a-real-key'
MESSAGES = [{'role': 'system', 'content': 'Return JSON only.'},
            {'role': 'user', 'content': 'Explain the supplied evidence.'}]


@pytest.fixture(autouse=True)
def isolated_provider_environment(monkeypatch):
    # Fixed names only: never inspect or print credentials from the host.
    for name in ('LZ_LLM_PROVIDER', 'LZ_LLM_BASE_URL', 'LZ_LLM_MODEL',
                 'LZ_LLM_API_KEY', 'OPENAI_API_KEY', 'DEEPSEEK_API_KEY',
                 'LZ_LLM_MAX_OUTPUT_TOKENS'):
        monkeypatch.delenv(name, raising=False)


def configuration(model='gpt-6-luna', **changes):
    return {'provider': 'openai', 'base_url': 'https://api.openai.com/v1',
            'model': model, 'api_key': KEY, 'json_mode': True,
            'remember_key': False, 'strict_citations': True, **changes}


def usage():
    return {'input_tokens': 1000, 'output_tokens': 200, 'total_tokens': 1200,
            'input_tokens_details': {'cached_tokens': 300, 'cache_write_tokens': 200,
                                     'cache_write_tokens_details': {'ttl_30m_tokens': 100, 'ttl_12h_tokens': 100}},
            'output_tokens_details': {'reasoning_tokens': 50}}


def message(text):
    return {'type': 'message', 'role': 'assistant', 'status': 'completed',
            'content': [{'type': 'output_text', 'text': text}]}


def response_body(content=None, **changes):
    if content is None:
        content = {'ok': True}
    return {'id': 'resp_unit_protocol', 'model': 'gpt-6-luna', 'status': 'completed',
            'error': None, 'service_tier': 'default', 'usage': usage(),
            'output': [message(json.dumps(content, ensure_ascii=False))], **changes}


def mock_client(monkeypatch, handler):
    original = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))


def test_openai_uses_responses_and_strict_evidence_schema(monkeypatch):
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=response_body())
    mock_client(monkeypatch, handler)
    _, metadata = ChatClient(configuration()).complete(MESSAGES)
    assert len(seen) == 1
    assert str(seen[0].url) == 'https://api.openai.com/v1/responses'
    body = json.loads(seen[0].content)
    assert body['input'] == MESSAGES and body['store'] is False and body['stream'] is False
    assert body['service_tier'] == 'default'
    assert body['reasoning'] == {'effort': 'none'} and body['max_output_tokens'] == 2400
    assert not {'temperature', 'top_p', 'messages', 'response_format'} & body.keys()
    assert seen[0].headers['authorization'] == 'Bearer ' + KEY
    assert KEY not in json.dumps(body)
    format_ = body['text']['format']
    assert format_['type'] == 'json_schema' and format_['strict'] is True
    schema = format_['schema']
    assert set(schema['required']) == {'claims', 'follow_up_questions'}
    assert schema['additionalProperties'] is False
    claim = schema['properties']['claims']['items']
    assert set(claim['required']) == {'text', 'evidence_ids', 'quotes'}
    assert claim['additionalProperties'] is False
    quote = claim['properties']['quotes']['items']
    assert set(quote['required']) == {'evidence_id', 'quote'} and quote['additionalProperties'] is False
    assert metadata['api_family'] == 'responses' and metadata['provider'] == 'openai'


@pytest.mark.parametrize('model,effort,limit', [
    ('gpt-6-luna', 'none', 128), ('gpt-6.1-sol', 'low', 1024), ('gpt-6-astra', 'low', 1024),
])
def test_openai_connection_probe_respects_reasoning_budget(monkeypatch, model, effort, limit):
    bodies = []
    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=response_body(model=model))
    mock_client(monkeypatch, handler)
    metadata = ChatClient(configuration(model)).probe()
    assert len(bodies) == 1
    assert bodies[0]['reasoning'] == {'effort': effort}
    assert bodies[0]['max_output_tokens'] == limit
    assert bodies[0]['text']['format']['schema']['properties']['ok']['enum'] == [True]
    assert 'temperature' not in bodies[0] and metadata['reasoning_effort'] == effort


def test_responses_output_walks_past_reasoning_and_concatenates_text(monkeypatch):
    body = response_body(output=[{'type': 'reasoning', 'summary': []},
                                 message('{"ok":'), message('true}')])
    mock_client(monkeypatch, lambda request: httpx.Response(200, json=body))
    content, metadata = ChatClient(configuration()).complete(MESSAGES)
    assert parse_json_content(content) == {'ok': True}
    counts = metadata['usage']
    assert counts['input_tokens'] == counts['prompt_tokens'] == 1000
    assert counts['output_tokens'] == counts['completion_tokens'] == 200
    assert counts['total_tokens'] == 1200
    assert counts['cached_tokens'] == counts['input_tokens_details']['cached_tokens'] == 300
    assert counts['cache_write_tokens'] == 200
    assert counts['reasoning_tokens'] == counts['output_tokens_details']['reasoning_tokens'] == 50
    assert counts['input_tokens_details']['cache_write_tokens_details']['ttl_12h_tokens'] == 100


@pytest.mark.parametrize('changes', [
    {'status': 'incomplete', 'incomplete_details': {'reason': 'max_output_tokens'}},
    {'status': 'incomplete', 'incomplete_details': {'reason': 'content_filter'}},
    {'status': 'incomplete', 'incomplete_details': 'malformed-details'},
    {'status': 'failed', 'error': {'message': KEY}},
    {'status': 'queued'}, {'status': 'cancelled'}, {'status': None},
    {'output': []}, {'output': {}}, {'output': [None]},
    {'output': [message('')]},
    {'output': [{'type': 'message', 'role': 'assistant', 'status': 'incomplete', 'content': []}]},
    {'output': [{'type': 'message', 'role': 'assistant', 'content': {'text': 'invalid'}}]},
    {'output': [{'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': 123}]}]},
    {'output': [message('{"ok":true}'), {'type': 'message', 'role': 'assistant',
                                       'content': [{'type': 'refusal', 'refusal': KEY}]}]},
])
def test_rejected_responses_keep_usage_without_echoing_provider_text(monkeypatch, changes):
    mock_client(monkeypatch, lambda request: httpx.Response(200, json=response_body(**changes)))
    with pytest.raises(ModelError) as caught:
        ChatClient(configuration()).complete(MESSAGES)
    assert KEY not in str(caught.value)
    assert caught.value.metadata['usage']['input_tokens'] == 1000
    assert caught.value.metadata['usage']['output_tokens'] == 200


def test_luna_cost_uses_cache_write_lifetimes_and_counts_reasoning_only_once(monkeypatch):
    mock_client(monkeypatch, lambda request: httpx.Response(200, json=response_body()))
    _, metadata = ChatClient(configuration()).complete(MESSAGES)
    estimate = metadata['cost_estimate']
    # 500 ordinary, 300 cached, 100 30m writes, 100 12h writes, 200 total output.
    assert estimate['amount'] == pytest.approx(0.0001905)
    assert estimate['currency'] == 'USD' and estimate['estimated'] is True


def test_luna_long_context_uses_full_request_multiplier(monkeypatch):
    counts = {'input_tokens': 300000, 'output_tokens': 1000, 'total_tokens': 301000,
              'input_tokens_details': {'cached_tokens': 100000, 'cache_write_tokens': 100000,
                                       'cache_write_tokens_details': {'ttl_30m_tokens': 100000, 'ttl_12h_tokens': 0}},
              'output_tokens_details': {'reasoning_tokens': 100}}
    mock_client(monkeypatch, lambda request: httpx.Response(200, json=response_body(usage=counts)))
    _, metadata = ChatClient(configuration()).complete(MESSAGES)
    assert metadata['cost_estimate']['amount'] == pytest.approx(0.04775)


@pytest.mark.parametrize('change', [
    'unknown-model', 'unknown-tier', 'missing-usage', 'missing-cached', 'missing-writes',
    'missing-write-breakdown', 'wrong-write-sum', 'impossible-input', 'invalid-output-count',
])
def test_unknown_or_inconsistent_billing_data_is_not_reported_as_zero(monkeypatch, change):
    body = response_body()
    if change == 'unknown-model': body['model'] = 'custom-model'
    elif change == 'unknown-tier': body['service_tier'] = 'priority'
    elif change == 'missing-usage': body.pop('usage')
    elif change == 'missing-cached': body['usage']['input_tokens_details'].pop('cached_tokens')
    elif change == 'missing-writes': body['usage']['input_tokens_details'].pop('cache_write_tokens')
    elif change == 'missing-write-breakdown': body['usage']['input_tokens_details'].pop('cache_write_tokens_details')
    elif change == 'wrong-write-sum': body['usage']['input_tokens_details']['cache_write_tokens_details']['ttl_30m_tokens'] = 5
    elif change == 'impossible-input': body['usage']['input_tokens'] = 100
    elif change == 'invalid-output-count': body['usage']['output_tokens'] = True
    mock_client(monkeypatch, lambda request: httpx.Response(200, json=body))
    _, metadata = ChatClient(configuration()).complete(MESSAGES)
    assert metadata.get('cost_estimate') is None


@pytest.mark.parametrize('status', [401, 402, 403, 404, 429, 500, 302])
def test_openai_http_errors_are_redacted_and_not_retried(monkeypatch, status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, text='provider error echoes ' + KEY)
    mock_client(monkeypatch, handler)
    with pytest.raises(ModelError) as caught:
        ChatClient(configuration()).probe()
    assert len(calls) == 1 and KEY not in str(caught.value)


def evidence_context():
    return {'facts': {'fixed_versions': ['4.17.21'], 'target_version': '4.18.1'},
            'paths': [], 'evidence': [{'id': 'source-1', 'text': '迁移后执行报表与导出入口的回归测试。',
                                      'version': '4.17.20', 'target_version': '4.18.1'}]}


def supported_answer():
    return {'claims': [{'text': '升级到 4.18.1 后需要执行报表与导出入口回归测试。',
                        'evidence_ids': ['source-1'],
                        'quotes': [{'evidence_id': 'source-1', 'quote': '迁移后执行报表与导出入口的回归测试。'}]}],
            'follow_up_questions': ['还缺哪些验证结果？']}


def test_openai_explanation_retains_existing_citation_validation(monkeypatch):
    mock_client(monkeypatch, lambda request: httpx.Response(200, json=response_body(supported_answer())))
    result, warning = model_explanation('迁移要求？', evidence_context(), config=configuration())
    assert warning is None and result['claims'][0]['evidence_ids'] == ['source-1']
    assert result['metadata']['api_family'] == 'responses'


@pytest.mark.parametrize('mutation', ['invented-id', 'invented-quote', 'unscoped-version', 'malformed-json'])
def test_schema_output_cannot_bypass_application_evidence_checks(monkeypatch, mutation):
    answer = supported_answer()
    if mutation == 'invented-id': answer['claims'][0]['evidence_ids'] = ['invented']
    elif mutation == 'invented-quote': answer['claims'][0]['quotes'][0]['quote'] = '这段文字没有出现在证据当中。'
    elif mutation == 'unscoped-version': answer['claims'][0]['text'] = '升级到 99.99.99 保证兼容。'
    body = response_body(answer)
    if mutation == 'malformed-json': body['output'] = [message('{"claims":')]
    mock_client(monkeypatch, lambda request: httpx.Response(200, json=body))
    result, warning = model_explanation('迁移要求？', evidence_context(), config=configuration())
    assert result is None and warning
    assert warning.metadata['usage']['total_tokens'] == 1200


@pytest.mark.parametrize('changes', [
    {'status': 'incomplete', 'incomplete_details': {'reason': 'max_output_tokens'}},
    {'output': [{'type': 'message', 'role': 'assistant', 'content': [{'type': 'refusal', 'refusal': KEY}]}]},
])
def test_provider_failure_falls_back_with_billable_attempt_usage(monkeypatch, changes):
    mock_client(monkeypatch, lambda request: httpx.Response(200, json=response_body(**changes)))
    result, warning = model_explanation('迁移要求？', evidence_context(), config=configuration())
    assert result is None and warning and KEY not in str(warning)
    assert warning.metadata['provider'] == 'openai'
    assert warning.metadata['usage']['output_tokens'] == 200


def test_runtime_openai_endpoint_guard_blocks_requests_before_transport(monkeypatch):
    def handler(request):
        pytest.fail('Invalid official endpoint must never reach the transport.')
    mock_client(monkeypatch, handler)
    with pytest.raises(InputError):
        ChatClient(configuration(base_url='https://provider.invalid/v1')).complete(MESSAGES)


@pytest.mark.parametrize('url', [
    'https://api.openai.com', 'https://provider.invalid/v1', 'http://127.0.0.1:9000/v1',
    'https://api.openai.com.evil.invalid/v1', 'https://api.openai.com/v1/responses',
    'https://user:password@api.openai.com/v1', 'https://api.openai.com/v1?api_key=' + KEY,
])
def test_official_openai_settings_reject_other_endpoints_without_key_leak(tmp_path, url):
    settings = ModelSettings(tmp_path/'model.json')
    with pytest.raises(InputError) as caught:
        settings.candidate(configuration(base_url=url))
    assert KEY not in str(caught.value)


def test_openai_dotenv_infers_official_luna_without_claiming_verification(tmp_path):
    dotenv = tmp_path/'.env'
    dotenv.write_text('OPENAI_API_KEY=' + KEY + '\n', encoding='utf-8')
    settings = ModelSettings(tmp_path/'model.json', dotenv)
    current = settings.current()
    assert current['provider'] == 'openai' and current['base_url'] == 'https://api.openai.com/v1'
    assert current['model'] == 'gpt-6-luna' and current['api_key'] == KEY
    public = settings.public()
    assert public['configured'] and public['has_key'] and not public['verified']
    assert KEY not in json.dumps(public)


def test_openai_missing_key_is_pending_and_cannot_be_saved(tmp_path):
    settings = ModelSettings(tmp_path/'model.json')
    with pytest.raises(InputError):
        settings.candidate(configuration(api_key=''))
    assert not settings.public()['configured'] and not settings.public()['verified']
    assert not (tmp_path/'model.json').exists()


def test_unconfigured_default_prefers_gpt_without_claiming_a_connection(tmp_path):
    public = ModelSettings(tmp_path/'model.json').public()
    assert public['provider'] == 'openai'
    assert public['base_url'] == 'https://api.openai.com/v1' and public['model'] == 'gpt-6-luna'
    assert not public['configured'] and not public['verified'] and not public['has_key']


@pytest.mark.parametrize('code,expected', [('credit_balance_exhausted','额度不足'),
                                         ('insufficient_quota','额度不足'),('rate_limit_exceeded','限流')])
def test_quota_errors_are_distinguished_without_echoing_the_provider_body(monkeypatch,code,expected):
    mock_client(monkeypatch,lambda request:httpx.Response(429,json={'error':{'code':code,'message':KEY}}))
    with pytest.raises(ModelError) as caught:
        ChatClient(configuration()).probe()
    assert expected in str(caught.value) and KEY not in str(caught.value)


def test_openai_probe_save_redacts_metadata_and_memory_only_credentials(tmp_path, monkeypatch):
    body = response_body(id='response-' + KEY, model='model-' + KEY)
    mock_client(monkeypatch, lambda request: httpx.Response(200, json=body))
    settings = ModelSettings(tmp_path/'model.json')
    public = settings.test_and_save(configuration())
    assert public['provider'] == 'openai' and public['verified'] and public['has_key']
    assert KEY not in json.dumps(public)
    assert KEY not in (tmp_path/'model.json').read_text(encoding='utf-8')
    reloaded = ModelSettings(tmp_path/'model.json')
    assert not reloaded.public()['verified'] and not reloaded.public()['has_key']


def load_acceptance_script():
    spec = importlib.util.spec_from_file_location('openai_acceptance_unit', ROOT/'scripts/verify_live_model.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('model', [
    {'provider': 'openai', 'base_url': 'https://api.openai.com/v1'},
    {'provider': 'openai', 'base_url': 'http://127.0.0.1:9000/v1'},
])
def test_unverified_live_acceptance_never_posts(monkeypatch, model):
    methods = []
    def handler(request):
        methods.append(request.method)
        assert request.method == 'GET'
        return httpx.Response(200, json={'llm_verified': False, 'model': model})
    mock_client(monkeypatch, handler)
    assert load_acceptance_script().run('http://127.0.0.1:8765') == 2
    assert methods == ['GET']


def test_official_acceptance_rejects_a_local_stub_before_posts(monkeypatch):
    methods = []
    def handler(request):
        methods.append(request.method)
        return httpx.Response(200, json={'llm_verified': True, 'model': {
            'provider': 'openai', 'base_url': 'http://127.0.0.1:9000/v1',
            'verification': {'provider': 'openai', 'transport': 'http-request', 'api_family': 'responses'}}})
    mock_client(monkeypatch, handler)
    assert load_acceptance_script().run('http://127.0.0.1:8765') == 2
    assert methods == ['GET']


@pytest.mark.parametrize('metadata', [
    None,
    {'provider': 'openai', 'transport': 'http-request', 'api_family': 'chat-completions',
     'requested_model': 'gpt-6-luna', 'returned_model': 'gpt-6-luna'},
    {'provider': 'openai', 'transport': 'http-request', 'api_family': 'responses',
     'requested_model': 'contract-test-stub', 'returned_model': 'gpt-6-luna'},
    {'provider': 'openai', 'transport': 'http-request', 'api_family': 'responses',
     'requested_model': 'gpt-6-luna', 'returned_model': 'mock-gpt'},
    {'provider': 'openai', 'transport': 'http-request', 'api_family': 'responses'},
])
def test_acceptance_requires_official_nonstub_response_metadata(metadata):
    assert not load_acceptance_script().official_metadata(metadata, 'openai')


def test_acceptance_script_handles_official_openai_metadata_offline(tmp_path, monkeypatch):
    """Exercise the report contract with mock HTTP, never a real-provider result."""
    module = load_acceptance_script()
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    (tmp_path/'evaluation').mkdir()
    metadata = {'provider': 'openai', 'transport': 'http-request', 'api_family': 'responses',
                'requested_model': 'gpt-6-luna', 'returned_model': 'gpt-6-luna', 'usage': {'total_tokens': 20}}
    questions = []
    def handler(request):
        if request.url.path == '/api/health':
            return httpx.Response(200, json={'llm_verified': True, 'model': {
                'provider': 'openai', 'base_url': 'https://api.openai.com/v1', 'verification': metadata}})
        if request.url.path == '/api/demo/prepare':
            return httpx.Response(200, json={'initial': 'demo-before', 'focus': 'GHSA-unit-test', 'target_version': '4.18.1'})
        assert request.url.path == '/api/snapshots/demo-before/ask'
        payload = json.loads(request.content)
        questions.append(payload)
        return httpx.Response(200, json={'id': len(questions), 'generation': 'model-assisted',
                                        'parent_id': payload['parent_id'], 'facts': {'target_version': '4.18.1'},
                                        'model_explanation': {'metadata': metadata, 'claims': supported_answer()['claims']},
                                        'elapsed_ms': 1, 'limits': []})
    mock_client(monkeypatch, handler)
    assert module.run('http://127.0.0.1:8765') == 0
    assert len(questions) == 3 and [q['parent_id'] for q in questions] == [None, 1, 2]
    report = json.loads((tmp_path/'evaluation/live-model-results.json').read_text(encoding='utf-8'))
    assert report['provider'] == 'openai' and report['passed'] == report['total'] == 3
