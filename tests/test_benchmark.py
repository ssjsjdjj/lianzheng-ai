import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('benchmark',ROOT/'scripts/benchmark.py')
benchmark=importlib.util.module_from_spec(spec);spec.loader.exec_module(benchmark)


def test_metrics_separate_unknown_cases_and_penalize_short_returns():
    assert benchmark.metrics(['a'],['a','b'],5)=={'recall_at_k':.5,'precision_at_k':.2,'mrr':1,'abstained':None}
    assert benchmark.metrics([],[],5)['abstained'] is True
    assert benchmark.metrics(['a'],[],5)['abstained'] is False
    assert benchmark.metrics(['x','a'],['a'],5)['mrr']==.5


def test_fixture_is_disjoint_and_annotations_resolve_to_literal_sources():
    data=json.loads((ROOT/'evaluation/benchmark-fixture.json').read_text(encoding='utf-8'))
    projects={'dev':set(),'test':set()};cases=set()
    for scenario in data['scenarios']:
        projects[scenario['split']].add(scenario['id'])
        ids={d['id'] for d in scenario['documents']}
        for case in scenario['questions']:
            assert set(case['relevant_ids'])<=ids and case['id'] not in cases
            cases.add(case['id'])
        for case in scenario['excerpt_questions']:
            assert case['expected_quote'] in scenario['long_document']
    assert projects['dev'].isdisjoint(projects['test']) and len(cases)==60


def test_benchmark_cannot_call_remote_embeddings(monkeypatch):
    monkeypatch.setenv('LZ_EMBEDDING_BASE_URL','https://must-not-call.invalid')
    monkeypatch.setenv('LZ_EMBEDDING_MODEL','must-not-call')
    def forbidden(*args,**kwargs):raise AssertionError('External API must not be called')
    monkeypatch.setattr('httpx.Client',forbidden)
    report=benchmark.run(ROOT/'evaluation/benchmark-fixture.json','dev',5)
    assert report['model_calls']==report['embedding_api_calls']==0
    assert len(report['results'])==150
