"""Reproduce the real-project development task comparison without model/network calls."""
import argparse
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from lianzheng.real_case import RealCase
from lianzheng.service import Service
from lianzheng.task_compare import TaskComparison
from lianzheng.store import now


def verify(output):
    with tempfile.TemporaryDirectory() as directory:
        service = Service(Path(directory) / 'comparison.sqlite3', ROOT / 'fixtures')
        comparison = TaskComparison(service, RealCase(service, ROOT / 'fixtures/real-case'), ROOT / 'fixtures/task-comparison.json')
        with patch('httpx.Client.request', side_effect=AssertionError('Offline comparison cannot access a network')), \
             patch('lianzheng.task_compare.model_explanation', side_effect=AssertionError('Offline comparison cannot call a model')):
            catalog = comparison.tasks()
            runs = [comparison.run(t['id']) for t in catalog['tasks']]
    invariant = all(r['model_calls_attempted'] == r['embedding_calls'] == 0 and not r['workspace_modified'] and
                    r['fairness']['same_candidate_corpus'] and r['fairness']['same_raw_materials'] and
                    r['comparison']['semantic_winner'] is None and
                    all(c['metrics']['semantic_accuracy'] is None for c in r['columns']) for r in runs)
    result = {'release': '0.9.0', 'generated_at': now(), 'kind': 'real-project-development-retrieval-comparison',
              **catalog['source'], 'task_count': len(runs), 'project_count': 1, 'phase_count': 3,
              'human_reviewed': False, 'independent_test': False, 'semantic_accuracy': None,
              'model_calls': 0, 'embedding_calls': 0, 'network_calls': 0,
              'protocol_checks_passed': invariant, 'protocol': catalog['protocol'],
              'outcomes': {key: sum(r['comparison']['result'] == key for r in runs)
                           for key in ('tie', 'graph-more', 'text-more')},
              'runs': runs,
              'limitations': ['Pass means protocol invariants passed, not all reference evidence retrieved.',
                              'A single real project supplies all 16 developer-curated tasks; no independent answer-accuracy claim.',
                              'Frozen source parsing and retrieval only; does not rerun upstream tests or paid explanations.']}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--require-passed', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / 'evaluation/task-comparison-results.json')
    args = parser.parse_args(); report = verify(args.output)
    print(json.dumps({key: report[key] for key in ('task_count', 'project_count', 'outcomes', 'protocol_checks_passed', 'model_calls')}, ensure_ascii=False))
    raise SystemExit(0 if report['protocol_checks_passed'] else 1)
