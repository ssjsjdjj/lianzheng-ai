import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from lianzheng.domain import InputError
from lianzheng.remediation import RemediationTasks
from lianzheng.service import Service


ROOT = Path(__file__).resolve().parent.parent
TARGET = 'GHSA-29mw-wpgm-hmr9'


@pytest.fixture
def tasks(tmp_path):
    service = Service(tmp_path/'tasks.sqlite3', ROOT/'fixtures')
    service.seed()
    return RemediationTasks(service)


def test_task_captures_all_occurrences_and_literal_declared_edges(tasks):
    task = tasks.create('demo-before', TARGET, owner='发布负责人')
    assert task['status'] == 'todo' and task['owner'] == '发布负责人'
    assert {o['ref'] for o in task['affected_occurrences']} == {'lodash-report', 'lodash-export'}
    assert {o['version'] for o in task['affected_occurrences']} == {'4.17.20'}
    assert task['candidate_versions'] == ['4.17.21']
    assert len(task['paths']) == 2 and not task['paths_truncated']
    actual = {(e['source'], e['target']): e['locator'] for e in tasks.service.analyze('demo-before')['edges']}
    for path in task['paths']:
        for edge in path['edges']:
            assert edge['locator'] == actual[edge['source'], edge['target']]
    assert '不代表' in task['limitations']
    assert len(task['events']) == 1 and all(not c['done'] for c in task['checks'])


def test_unknown_focus_does_not_use_service_default_vulnerability(tasks):
    with pytest.raises(InputError, match='没有该公告'):
        tasks.create('demo-before', 'CVE-2099-999999')
    assert tasks.list('demo-before') == []


def test_creation_is_idempotent_and_serialized(tasks):
    with ThreadPoolExecutor(max_workers=4) as pool:
        created = list(pool.map(lambda _: tasks.create('demo-before', TARGET), range(4)))
    assert len({t['id'] for t in created}) == 1
    assert len(tasks.list('demo-before')) == 1
    assert tasks.create('demo-before', TARGET, owner='different')['owner'] == ''


def test_revision_tracks_only_written_task_changes_and_verification_attempts(tasks):
    task = tasks.create('demo-before', TARGET)
    assert task['revision'] == 1
    changed = tasks.update(task['id'], {'owner': 'Alice'}, expected_revision=1)
    assert changed['revision'] == 2
    assert tasks.update(task['id'], {'owner': 'Alice'}, expected_revision=2)['revision'] == 2
    failed = tasks.verify(task['id'], 'demo-partial', expected_revision=2)
    assert failed['revision'] == 3 and not failed['verification']['passed']
    passed = tasks.verify(task['id'], 'demo-resolved', expected_revision=3)
    assert passed['revision'] == 4 and passed['verification']['passed']
    assert [e['revision'] for e in passed['events']] == [1, 2, 3, 4]


def test_stale_update_cannot_erase_other_tabs_changes(tasks):
    task = tasks.create('demo-before', TARGET)
    saved = tasks.update(task['id'], {'owner': 'Alice'}, expected_revision=1)
    with pytest.raises(InputError, match='已被其他操作更新'):
        tasks.update(task['id'], {'title': '另一标签的标题', 'owner': ''}, expected_revision=1)
    assert tasks.get(task['id']) == saved


def test_stale_verification_cannot_replace_new_task_state_or_append_a_receipt(tasks):
    task = tasks.create('demo-before', TARGET)
    saved = tasks.verify(task['id'], 'demo-resolved', expected_revision=1)
    with pytest.raises(InputError, match='已被其他操作更新'):
        tasks.verify(task['id'], 'demo-partial', expected_revision=1)
    assert tasks.get(task['id']) == saved


def test_concurrent_updates_with_same_revision_allow_only_one_writer(tasks):
    task = tasks.create('demo-before', TARGET)
    def edit(owner):
        try:
            return tasks.update(task['id'], {'owner': owner}, expected_revision=1)['owner']
        except InputError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(edit, ['Alice', 'Bob']))
    assert sum(owner is not None for owner in outcomes) == 1
    current = tasks.get(task['id'])
    assert current['owner'] == next(owner for owner in outcomes if owner)
    assert current['revision'] == 2 and len(current['events']) == 2


def test_concurrent_verifications_cannot_both_consume_same_revision(tasks):
    task = tasks.create('demo-before', TARGET)
    def verify(after):
        try:
            return tasks.verify(task['id'], after, expected_revision=1)['verification']['after_snapshot']['id']
        except InputError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(verify, ['demo-partial', 'demo-resolved']))
    assert sum(after is not None for after in outcomes) == 1
    current = tasks.get(task['id'])
    assert current['verification']['after_snapshot']['id'] == next(after for after in outcomes if after)
    assert current['revision'] == 2 and len(current['events']) == 2


def test_legacy_task_without_revision_is_read_as_revision_one(tasks):
    task = tasks.create('demo-before', TARGET)
    del task['revision']
    for event in task['events']:
        event.pop('revision', None)
    with tasks.store.connect() as db:
        db.execute('UPDATE remediation_tasks SET body=? WHERE id=?', (json.dumps(task), task['id']))
    assert tasks.get(task['id'])['revision'] == 1
    assert tasks.list('demo-before')[0]['revision'] == 1
    assert tasks.create('demo-before', TARGET)['revision'] == 1
    assert tasks.update(task['id'], {'owner': 'Alice'}, expected_revision=1)['revision'] == 2


@pytest.mark.parametrize('revision', [True, 0, -1, 1.5, '1'])
def test_invalid_expected_revisions_are_rejected_without_changes(tasks, revision):
    task = tasks.create('demo-before', TARGET)
    with pytest.raises(InputError, match='版本必须'):
        tasks.update(task['id'], {'owner': 'Alice'}, expected_revision=revision)
    with pytest.raises(InputError, match='版本必须'):
        tasks.verify(task['id'], 'demo-resolved', expected_revision=revision)
    assert tasks.get(task['id']) == task


def test_tasks_and_audit_persist_without_changing_original_history(tasks):
    service = tasks.service
    old_snapshots = service.store.list()
    old_scans = service.store.scans('demo-before')
    task = tasks.create('demo-before', TARGET)
    updated = tasks.update(task['id'], {'title': '升级验证', 'owner': '研发同学', 'status': 'in_progress',
                                      'checks': {'inventory': True}, 'note': '已核对两处引入位置。'})
    assert updated['checks'][0]['done']
    assert updated['events'][-1]['details']['note'] == '已核对两处引入位置。'
    reopened = RemediationTasks(Service(service.store.path, ROOT/'fixtures'))
    assert reopened.get(task['id']) == updated
    assert service.store.list() == old_snapshots and service.store.scans('demo-before') == old_scans
    assert service.store.history('demo-before') == []


@pytest.mark.parametrize('fields', [
    {'status': 'verified'}, {'verification': {'passed': True}}, {'focus': 'fake'},
    {'checks': {'invented': True}}, {'checks': {'build': 'true'}}, {'checks': {'build': 1}},
    {'owner': ['somebody']}, {'owner': 'x'*101}, {'title': ''}, {'note': 'x'*2001},
    {'status': []}, {}, None,
])
def test_client_cannot_forge_verification_or_immutable_evidence(tasks, fields):
    task = tasks.create('demo-before', TARGET)
    with pytest.raises(InputError):
        tasks.update(task['id'], fields)
    assert tasks.get(task['id']) == task


def test_partial_fix_stays_open_and_preserves_failed_attempt(tasks):
    task = tasks.create('demo-before', TARGET)
    result = tasks.verify(task['id'], 'demo-partial')
    assert result['status'] == 'needs_review' and not result['verification']['passed']
    assert [o['ref'] for o in result['verification']['remaining_occurrences']] == ['lodash-export']
    assert {r['code'] for r in result['verification']['reasons']} == {'target_remains'}
    success = tasks.verify(task['id'], 'demo-resolved')
    assert success['status'] == 'verified' and success['verification']['passed']
    assert [e['type'] for e in success['events']] == ['created', 'verification_failed', 'verified']
    assert success['events'][1]['details']['after_snapshot']['id'] == 'demo-partial'
    assert not any(c['done'] for c in success['checks'])  # Graph verification never invents business test results.


def test_different_knowledge_snapshot_never_proves_fix(tasks):
    task = tasks.create('demo-before', TARGET)
    scans = tasks.store.scans('demo-resolved')
    for scan in scans.values():
        if scan['status'] == 'checked':
            scan['fetched_at'] = '2099-01-01T00:00:00+00:00'
    tasks.store.save_scans('demo-resolved', scans, [])
    result = tasks.verify(task['id'], 'demo-resolved')
    assert result['status'] == 'needs_review'
    assert result['verification']['not_observed']
    assert 'knowledge_changed' in {r['code'] for r in result['verification']['reasons']}


@pytest.mark.parametrize('status', ['unscanned', 'failed', 'unsupported'])
def test_missing_or_failed_scan_never_proves_fix(tasks, status):
    task = tasks.create('demo-before', TARGET)
    scans = tasks.store.scans('demo-resolved')
    scans['lodash-export']['status'] = status
    tasks.store.save_scans('demo-resolved', scans, [])
    result = tasks.verify(task['id'], 'demo-resolved')
    assert result['status'] == 'needs_review'
    assert 'after_coverage_incomplete' in {r['code'] for r in result['verification']['reasons']}


def test_incomplete_graph_never_proves_fix(tasks):
    task = tasks.create('demo-before', TARGET)
    raw = json.loads((ROOT/'fixtures/resolved.cdx.json').read_text(encoding='utf-8'))
    raw['dependencies'].pop()
    tasks.service.import_bom(raw, project=task['project'], identifier='incomplete-after', demo=True)
    result = tasks.verify(task['id'], 'incomplete-after')
    assert result['status'] == 'needs_review' and not result['verification']['comparison_complete']


def test_unreachable_remaining_occurrence_is_not_ignored(tasks):
    task = tasks.create('demo-before', TARGET)
    raw = json.loads((ROOT/'fixtures/resolved.cdx.json').read_text(encoding='utf-8'))
    raw['components'].append({'type': 'library', 'name': 'lodash', 'version': '4.17.20',
                              'purl': 'pkg:npm/lodash@4.17.20', 'bom-ref': 'disconnected-vulnerable'})
    raw['dependencies'].append({'ref': 'disconnected-vulnerable', 'dependsOn': []})
    tasks.service.import_bom(raw, project=task['project'], identifier='disconnected-after', demo=True)
    result = tasks.verify(task['id'], 'disconnected-after')
    assert result['status'] == 'needs_review'
    assert result['verification']['remaining_occurrences'][0]['ref'] == 'disconnected-vulnerable'
    assert result['verification']['remaining_occurrences'][0]['reachable'] is False
    assert {'target_remains', 'after_coverage_incomplete'} <= {r['code'] for r in result['verification']['reasons']}


def test_source_rescan_cannot_silently_replace_task_basis(tasks):
    task = tasks.create('demo-before', TARGET)
    scans = tasks.store.scans('demo-before')
    scans['lodash-export']['data']['vulns'][0]['summary'] += ' changed'
    tasks.store.save_scans('demo-before', scans, [])
    result = tasks.verify(task['id'], 'demo-resolved')
    assert result['status'] == 'needs_review'
    assert result['verification']['resolved']  # compare alone would confirm it, but source basis changed.
    assert 'source_evidence_changed' in {r['code'] for r in result['verification']['reasons']}


def test_cross_project_and_same_snapshot_are_rejected(tasks):
    task = tasks.create('demo-before', TARGET)
    raw = json.loads((ROOT/'fixtures/resolved.cdx.json').read_text(encoding='utf-8'))
    tasks.service.import_bom(raw, project='another-project', identifier='other-project', demo=True)
    for after in ('demo-before', 'other-project'):
        with pytest.raises(InputError):
            tasks.verify(task['id'], after)
    assert tasks.get(task['id'])['events'] == task['events']


def test_task_reopens_after_new_failed_verification_and_keeps_passed_receipt(tasks):
    task = tasks.create('demo-before', TARGET)
    passed = tasks.verify(task['id'], 'demo-resolved')
    assert passed['status'] == 'verified'
    reopened = tasks.verify(task['id'], 'demo-partial')
    assert reopened['status'] == 'needs_review'
    assert reopened['events'][1]['type'] == 'verified'
    assert reopened['events'][1]['details']['passed'] is True


def test_tasks_are_snapshot_scoped_and_unknown_resources_raise_key_error(tasks):
    task = tasks.create('demo-before', TARGET)
    assert tasks.list('demo-partial') == []
    for operation in (lambda: tasks.list('missing'), lambda: tasks.get('missing'),
                      lambda: tasks.update('missing', {'owner': 'reader'}),
                      lambda: tasks.verify(task['id'], 'missing')):
        with pytest.raises(KeyError):
            operation()


def test_report_retains_original_receipt_and_exposes_changed_scan_basis(tasks):
    task = tasks.create('demo-before', TARGET)
    assert tasks.report(task['id'])['current_basis_matches'] is None
    verified = tasks.verify(task['id'], 'demo-resolved')
    report = tasks.report(task['id'])
    assert report['current_basis_matches'] is True
    assert report['task'] == verified
    assert report['kind'] == 'remediation-task-evidence-report'
    scans = tasks.store.scans('demo-resolved')
    scans['lodash-export']['fetched_at'] = '2099-01-01T00:00:00+00:00'
    tasks.store.save_scans('demo-resolved', scans, [])
    changed = tasks.report(task['id'])
    assert changed['current_basis_matches'] is False
    assert changed['task']['verification']['passed']  # Keep history instead of rewriting a past result.
    assert 'api_key' not in json.dumps(changed)


def test_occurrences_are_not_limited_to_five_display_paths(tasks):
    raw = json.loads((ROOT/'fixtures/before.cdx.json').read_text(encoding='utf-8'))
    root_ref = raw['metadata']['component']['bom-ref']
    template = next(c for c in raw['components'] if c['name'] == 'lodash')
    for i in range(8):
        ref = f'extra-lodash-{i}'
        component = copy.deepcopy(template); component['bom-ref'] = ref
        raw['components'].append(component)
        raw['dependencies'].append({'ref': ref, 'dependsOn': []})
        next(d for d in raw['dependencies'] if d['ref'] == root_ref)['dependsOn'].append(ref)
    tasks.service.import_bom(raw, project='many-paths', identifier='many-paths', demo=True)
    task = tasks.create('many-paths', TARGET)
    assert len(task['affected_occurrences']) == 10
    assert len(task['paths']) == 5 and task['paths_truncated']
