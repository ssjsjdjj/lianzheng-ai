import copy
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from lianzheng.domain import InputError
from lianzheng.providers import ModelWarning
from lianzheng.real_case import RealCase
from lianzheng.service import Service
from lianzheng.task_compare import TaskComparison, K, EVIDENCE_BYTES, node_id, rank, selected_paths

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def comparison(tmp_path):
    service = Service(tmp_path / 'work.sqlite3', ROOT / 'fixtures')
    return TaskComparison(service, RealCase(service, ROOT / 'fixtures/real-case'), ROOT / 'fixtures/task-comparison.json')


def test_catalog_source_and_task_scope(comparison):
    result = comparison.tasks()
    assert len(result['tasks']) == 16
    assert {t['phase'] for t in result['tasks']} == {'before', 'partial', 'after'}
    assert len({t['id'] for t in result['tasks']}) == 16
    assert result['protocol']['project_count'] == 1
    assert not result['protocol']['human_reviewed']
    assert not result['protocol']['independent_test']
    assert result['protocol']['semantic_accuracy'] is None
    assert result['source']['case_bundle_sha256'] == 'a737ddf3a515dee53f77a1d5394ca1a7a47ebf07a7bea124470e6968a62e3975'
    assert all('expected_evidence_ids' not in t for t in result['tasks'])


def test_offline_is_read_only_and_no_external_clients(comparison):
    before = comparison.service.store.list()
    with patch('httpx.Client.request', side_effect=AssertionError('network forbidden')), \
         patch('lianzheng.task_compare.model_explanation', side_effect=AssertionError('model forbidden')):
        result = comparison.run('before-occurrences')
    assert comparison.service.store.list() == before
    assert not result['workspace_modified']
    assert result['model_calls_attempted'] == result['embedding_calls'] == 0
    assert result['fairness']['same_candidate_corpus']
    assert result['fairness']['model_pair_comparable'] is None
    assert result['comparison']['result'] == 'tie'
    assert result['comparison']['semantic_winner'] is None
    for column in result['columns']:
        assert column['generation'] == 'offline-evidence'
        assert column['metrics']['semantic_accuracy'] is None
        assert column['metrics']['retrieved'] <= K
        assert column['metrics']['evidence_bytes'] <= EVIDENCE_BYTES


def test_text_baseline_receives_explicit_edge_material(comparison):
    result = comparison.run('before-occurrences')
    a, b = result['columns']
    assert any('依赖关系：' in d['text'] for d in a['evidence'])
    assert a['paths']  # text side is not forbidden from connecting its own edges
    assert a['metrics']['connected_target_occurrences'] == 1
    assert b['metrics']['connected_target_occurrences'] == 2
    assert len(set(b['metrics']['connected_target_refs'])) == 2
    assert a['metrics']['reference_coverage'] == b['metrics']['reference_coverage'] == 1


def test_reference_labels_cannot_change_ranking(comparison, tmp_path):
    original = comparison.run('before-occurrences')
    fixture = json.loads(comparison.fixture_path.read_text(encoding='utf-8'))
    fixture['tasks'][0]['expected_evidence_ids'] = ['coverage']
    path = tmp_path / 'modified-labels.json'; path.write_text(json.dumps(fixture), encoding='utf-8')
    comparison.fixture_path = path
    changed = comparison.run('before-occurrences')
    assert changed['fairness']['corpus_sha256'] == original['fairness']['corpus_sha256']
    assert [[d['id'] for d in c['evidence']] for c in original['columns']] == [[d['id'] for d in c['evidence']] for c in changed['columns']]
    assert [c['paths'] for c in original['columns']] == [c['paths'] for c in changed['columns']]
    assert changed['columns'][0]['metrics']['expected_evidence_ids'] == ['coverage']


@pytest.mark.parametrize('bad', [None, [], 12])
def test_invalid_identifier(comparison, bad):
    with pytest.raises(InputError): comparison.run(bad)


def test_unknown_task(comparison):
    with pytest.raises(KeyError): comparison.run('not-a-task')


@pytest.mark.parametrize('value', [1, 'false', None])
def test_model_flag_is_strict(comparison, value):
    with pytest.raises(InputError): comparison.run('before-tests', value)


def test_case_manifest_binding(comparison, tmp_path):
    fixture = json.loads(comparison.fixture_path.read_text(encoding='utf-8'))
    fixture['case_bundle_sha256'] = '0' * 64
    path = tmp_path / 'wrong-case.json'; path.write_text(json.dumps(fixture), encoding='utf-8'); comparison.fixture_path = path
    with pytest.raises(InputError, match='冻结案例'): comparison.run('before-tests')


def test_bad_category_and_reference(comparison, tmp_path):
    fixture = json.loads(comparison.fixture_path.read_text(encoding='utf-8')); fixture['tasks'][0].pop('category')
    path = tmp_path / 'bad.json'; path.write_text(json.dumps(fixture), encoding='utf-8'); comparison.fixture_path = path
    with pytest.raises(InputError): comparison.tasks()
    fixture['tasks'][0]['category'] = 'example'; fixture['tasks'][0]['expected_evidence_ids'] = ['missing']
    path.write_text(json.dumps(fixture), encoding='utf-8')
    with pytest.raises(InputError, match='参考证据'): comparison.run('before-occurrences')


def test_coverage_boundary_and_intermediate_failure_remain(comparison):
    result = comparison.run('after-failure')
    for c in result['columns']:
        failure = next(d for d in c['evidence'] if d['id'] == 'migration-failure')
        assert '2 项失败' in failure['text']
        assert '中间失败' in failure['text']
    result = comparison.run('after-target')
    for c in result['columns']:
        assert any('零命中不等于全项目安全' in d['text'] for d in c['evidence'])
        assert any('依赖图完整：False' in d['text'] for d in c['evidence'])


def test_paths_only_use_selected_visible_relations():
    graph = {'root': 'root', 'nodes': [{'id':'root','name':'project','version':'1','root':True},
             {'id':'a','name':'minimist','version':'1.2.5','root':False}],
             'edges': [{'source':'root','target':'a'}]}
    assert selected_paths('minimist 路径', [], graph) == []
    assert selected_paths('minimist 路径', [{'relations':[{'source':'root','target':'a'}]}], graph) == [['root','a']]


def test_config_unavailable_never_calls_model(comparison):
    comparison.service.models.current = Mock(return_value={'provider':'openai','base_url':'https://api.openai.com/v1','model':'test','api_key':''})
    with patch('lianzheng.task_compare.model_explanation') as call:
        with pytest.raises(InputError): comparison.run('before-tests', True)
        call.assert_not_called()
    comparison.service.models.current.assert_called_once()


def configured(comparison):
    comparison.service.models.current = Mock(return_value={'provider':'local','base_url':'http://127.0.0.1:9/v1','model':'unit-model','api_key':'test-only-value'})


def answer(model='unit-model'):
    return {'text':'unit fixture explanation', 'claims':[], 'metadata':{'returned_model':model,'usage':{'total_tokens':15}}}


def test_pair_uses_one_config_and_labels_never_enter_context(comparison):
    configured(comparison); captured = []
    def explain(question, context, config, usage_guard):
        captured.append((copy.deepcopy(context), config, usage_guard))
        return answer(), None
    with patch('lianzheng.task_compare.model_explanation', side_effect=explain):
        result = comparison.run('before-occurrences', True)
    comparison.service.models.current.assert_called_once()
    assert len(captured) == result['model_calls_attempted'] == 2
    assert captured[0][1] is captured[1][1]
    assert captured[0][2] is captured[1][2] is comparison.service.call_control
    assert captured[0][0]['facts'] == captured[1][0]['facts']
    assert all('expected_evidence_ids' not in json.dumps(c[0]) for c in captured)
    assert result['fairness']['model_pair_comparable']
    assert 'api_key' not in json.dumps(result)
    assert result['comparison']['semantic_winner'] is None


@pytest.mark.parametrize('second', [(None, ModelWarning('budget blocked')), (answer('different-model'), None)])
def test_failed_or_different_model_pair_is_not_comparable(comparison, second):
    configured(comparison)
    with patch('lianzheng.task_compare.model_explanation', side_effect=[(answer(), None), second]) as call:
        result = comparison.run('before-tests', True)
    assert call.call_count == 2
    assert not result['fairness']['model_pair_comparable']
    assert result['comparison']['semantic_winner'] is None
    if second[0] is None:
        assert result['columns'][1]['generation'] == 'model-fallback'
        assert result['columns'][1]['warning'] == 'budget blocked'


def test_missing_returned_model_is_unknown(comparison):
    configured(comparison)
    with patch('lianzheng.task_compare.model_explanation', return_value=({'text':'mock','metadata':{}}, None)):
        result = comparison.run('before-tests', True)
    assert not result['fairness']['model_pair_comparable']


def test_same_question_same_corpus_has_reproducible_selection(comparison):
    a = comparison.run('partial-remaining'); b = comparison.run('partial-remaining')
    assert a['fairness']['corpus_sha256'] == b['fairness']['corpus_sha256']
    assert [[d['id'] for d in c['evidence']] for c in a['columns']] == [[d['id'] for d in c['evidence']] for c in b['columns']]
