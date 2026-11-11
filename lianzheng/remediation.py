"""Persist evidence-bound remediation tasks; verification never calls an external API."""
import hashlib
import json
from datetime import datetime
from uuid import uuid4

from .domain import InputError
from .store import now


MANUAL_STATUSES = {'todo', 'in_progress', 'needs_review'}
STATUS_LABELS = {'todo': '待处理', 'in_progress': '处理中', 'needs_review': '待复核',
                 'verified': '目标漏洞复核通过'}
CHECKS = (
    ('inventory', '核对全部已知受影响位置与依赖路径'),
    ('candidate', '核对候选版本与上游依赖约束'),
    ('build', '完成安装、构建与业务回归，并保存结果'),
    ('rollback', '准备回滚方案并记录审批'),
    ('snapshot', '提交修复后的实际依赖清单'),
)
LIMITATION = ('候选版本仅是公告中的修复边界，不代表依赖可解析或业务兼容。'
              '复核通过仅针对所选公告、清单与知识快照，不代表全部漏洞消除或可以上线。'
              '检查项由使用者自行勾选，不替代测试证据。')


def _text(value, name, maximum, allow_empty=True):
    if not isinstance(value, str):
        raise InputError(f'{name}必须是文本。')
    value = value.strip()
    if len(value) > maximum or (not value and not allow_empty):
        raise InputError(f'{name}长度必须为 {0 if allow_empty else 1} 至 {maximum} 个字符。')
    return value


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


class RemediationTasks:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        # Additive schema: old snapshots, settings, evidence and histories are untouched.
        with self.store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS remediation_tasks (
                    id TEXT PRIMARY KEY,
                    snapshot_id TEXT NOT NULL REFERENCES snapshots(id),
                    focus TEXT NOT NULL,
                    created TEXT NOT NULL,
                    updated TEXT NOT NULL,
                    body TEXT NOT NULL,
                    UNIQUE(snapshot_id, focus));
                CREATE INDEX IF NOT EXISTS ix_remediation_snapshot
                    ON remediation_tasks(snapshot_id, created, id);
            ''')

    def list(self, snapshot_id):
        self.store.get(snapshot_id)
        with self.store.connect() as db:
            rows = db.execute('SELECT body FROM remediation_tasks WHERE snapshot_id=? '
                              'ORDER BY created DESC,id', (snapshot_id,)).fetchall()
        return [self._decode(row['body']) for row in rows]

    @staticmethod
    def _decode(body):
        task = json.loads(body)
        # Tasks created before optimistic locking are revision 1 without rewriting their history.
        task.setdefault('revision', 1)
        return task

    @staticmethod
    def _get(db, task_id):
        row = db.execute('SELECT body FROM remediation_tasks WHERE id=?', (task_id,)).fetchone()
        if row is None:
            raise KeyError('修复任务不存在')
        return RemediationTasks._decode(row['body'])

    @staticmethod
    def _check_revision(task, expected_revision):
        if expected_revision is None:
            return
        if type(expected_revision) is not int or expected_revision < 1:
            raise InputError('修复任务版本必须为大于等于 1 的整数。')
        if expected_revision != task['revision']:
            raise InputError('这条任务已被其他操作更新，请点击“刷新任务”核对最新记录后再提交；本次未覆盖已有内容。')

    def get(self, task_id):
        with self.store.connect() as db:
            return self._get(db, task_id)

    def report(self, task_id):
        """Return a portable evidence receipt, with no settings or credential fields."""
        task = self.get(task_id)
        verification = task['verification']
        current_basis_matches = None
        if verification:
            before = self.store.get(task['snapshot_id'])
            after = self.store.get(verification['after_snapshot']['id'])
            current_basis_matches = (
                before['hash'] == task['source_basis']['snapshot_hash'] and
                _fingerprint(self.store.scans(task['snapshot_id'])) == task['source_basis']['scans_sha256'] and
                after['hash'] == verification['after_snapshot']['hash'] and
                _fingerprint(self.store.scans(after['id'])) == verification['after_scans_sha256'])
        return {'kind': 'remediation-task-evidence-report', 'schema_version': 1,
                'exported_at': now(), 'task': task,
                'current_basis_matches': current_basis_matches,
                'verification_scope': LIMITATION,
                'freshness_note': '验收记录描述当时的清单与公告证据。当前证据变化后需要重新复核。'}

    @staticmethod
    def _event(task, event, details):
        if len(task['events']) >= 500:
            raise InputError('该任务已达到 500 条审计记录上限，请保留记录并在新的来源快照上创建任务。')
        stamp = now()
        task['updated'] = stamp
        if event != 'created':
            task['revision'] += 1
        task['events'].append({'id': len(task['events']) + 1, 'created': stamp,
                               'type': event, 'details': details, 'revision': task['revision']})

    @staticmethod
    def _save(db, task):
        task['status_label'] = STATUS_LABELS[task['status']]
        db.execute('UPDATE remediation_tasks SET updated=?,body=? WHERE id=?',
                   (task['updated'], json.dumps(task, ensure_ascii=False), task['id']))
        return task

    def create(self, snapshot_id, focus, title=None, owner=''):
        focus = _text(focus, '公告编号', 160, False)
        owner = _text(owner, '负责人', 100)
        if title is not None:
            title = _text(title, '任务标题', 160, False)
        with self.store.connect() as db:
            # Serialize concurrent creations and keep source scans stable while reading them.
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT body FROM remediation_tasks WHERE snapshot_id=? AND focus=?',
                             (snapshot_id, focus)).fetchone()
            if row:
                return self._decode(row['body'])
            analysis = self.service.analyze(snapshot_id, focus, include_documents=False)
            hits = [hit for hit in analysis['findings'] if hit['id'] == focus]
            if not hits:
                raise InputError('当前快照没有该公告的已知命中，不能据此创建修复任务。')
            if db.execute('SELECT COUNT(*) FROM remediation_tasks WHERE snapshot_id=?',
                          (snapshot_id,)).fetchone()[0] >= 200:
                raise InputError('每份快照最多保存 200 个修复任务。')
            nodes = {node['id']: node for node in analysis['nodes']}
            occurrences = [dict(ref=hit['ref'], package=hit['package'], version=hit['version'],
                                reachable=hit['reachable'], locator=nodes[hit['ref']]['locator'],
                                fixed_versions=hit['fixed_versions'], source=hit['source'],
                                fetched_at=hit['fetched_at'], url=hit['url'])
                           for hit in hits]
            edge_locations = {(e['source'], e['target']): e['locator'] for e in analysis['edges']}
            paths = [{'nodes': path,
                      'label': ' → '.join(nodes[ref]['name']+'@'+nodes[ref]['version'] for ref in path),
                      'edges': [{'source': left, 'target': right, 'locator': edge_locations[left, right]}
                                for left, right in zip(path, path[1:])]}
                     for path in analysis['paths']]
            stamp = now()
            task = {'id': uuid4().hex, 'schema_version': 1, 'revision': 1, 'snapshot_id': snapshot_id,
                    'project': analysis['snapshot']['project'], 'source_snapshot': analysis['snapshot'],
                    'focus': focus, 'title': title or f'复核并处理 {focus}', 'owner': owner,
                    'status': 'todo', 'status_label': STATUS_LABELS['todo'],
                    'affected_occurrences': occurrences,
                    'candidate_versions': sorted({version for hit in hits for version in hit['fixed_versions']}),
                    'paths': paths, 'paths_truncated': analysis['paths_truncated'],
                    'coverage_complete': analysis['can_confirm_absence'],
                    'source_basis': {'snapshot_hash': analysis['snapshot']['hash'],
                                     'scans_sha256': _fingerprint(self.store.scans(snapshot_id)),
                                     'knowledge_times': sorted({n['fetched_at'] for n in analysis['nodes']
                                                               if n['scan_status'] == 'checked' and n['fetched_at']})},
                    'checks': [{'id': identifier, 'label': label, 'done': False} for identifier, label in CHECKS],
                    'limitations': LIMITATION, 'verification': None, 'events': [],
                    'created': stamp, 'updated': stamp}
            self._event(task, 'created', {'focus': focus, 'known_occurrences': len(occurrences),
                                         'coverage_complete': task['coverage_complete']})
            db.execute('INSERT INTO remediation_tasks VALUES(?,?,?,?,?,?)',
                       (task['id'], snapshot_id, focus, task['created'], task['updated'],
                        json.dumps(task, ensure_ascii=False)))
            return task

    def update(self, task_id, fields, expected_revision=None):
        if not isinstance(fields, dict) or not fields or set(fields) - {'title', 'owner', 'status', 'checks', 'note'}:
            raise InputError('仅可修改任务标题、负责人、人工处理状态、检查项或添加备注。')
        changes = {}
        for key, name, maximum, allow_empty in (('title', '任务标题', 160, False),
                                               ('owner', '负责人', 100, True),
                                               ('note', '备注', 2000, False)):
            if key in fields:
                changes[key] = _text(fields[key], name, maximum, allow_empty)
        if 'status' in fields:
            if not isinstance(fields['status'], str) or fields['status'] not in MANUAL_STATUSES:
                raise InputError('人工状态仅支持 todo、in_progress、needs_review；复核通过必须提交新清单验证。')
            changes['status'] = fields['status']
        if 'checks' in fields:
            checks = fields['checks']
            if not isinstance(checks, dict) or not checks or set(checks) - {i for i, _ in CHECKS}:
                raise InputError('检查项必须是已声明检查编号与布尔值的映射。')
            if any(type(value) is not bool for value in checks.values()):
                raise InputError('检查项只能填写 true 或 false。')
            changes['checks'] = dict(checks)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            task = self._get(db, task_id)
            self._check_revision(task, expected_revision)
            applied = {}
            for key in ('title', 'owner', 'status'):
                if key in changes and task[key] != changes[key]:
                    applied[key] = {'before': task[key], 'after': changes[key]}
                    task[key] = changes[key]
            if 'checks' in changes:
                changed_checks = {}
                for check in task['checks']:
                    if check['id'] in changes['checks'] and check['done'] != changes['checks'][check['id']]:
                        changed_checks[check['id']] = changes['checks'][check['id']]
                        check['done'] = changes['checks'][check['id']]
                if changed_checks:
                    applied['checks'] = changed_checks
            if 'note' in changes:
                applied['note'] = changes['note']
            if not applied:
                return task
            self._event(task, 'updated', applied)
            return self._save(db, task)

    def verify(self, task_id, after_snapshot_id, expected_revision=None):
        after_snapshot_id = _text(after_snapshot_id, '修复后快照编号', 200, False)
        with self.store.connect() as db:
            # A scan replacement cannot race between comparison and saving the receipt.
            db.execute('BEGIN IMMEDIATE')
            task = self._get(db, task_id)
            self._check_revision(task, expected_revision)
            if after_snapshot_id == task['snapshot_id']:
                raise InputError('请提交不同于来源快照的修复后清单。')
            before = self.service.analyze(task['snapshot_id'], include_documents=False, include_paths=False)
            after = self.service.analyze(after_snapshot_id, include_documents=False, include_paths=False)
            if before['snapshot']['project'] != after['snapshot']['project']:
                raise InputError('修复后清单必须属于同一项目。')
            if datetime.fromisoformat(after['snapshot']['created']) < datetime.fromisoformat(before['snapshot']['created']):
                raise InputError('请选择来源快照之后创建的修复后清单。')
            comparison = self.service.compare(task['snapshot_id'], after_snapshot_id)
            remaining = [hit for hit in after['findings'] if hit['id'] == task['focus']]
            source_unchanged = (task['source_basis']['snapshot_hash'] == before['snapshot']['hash'] and
                                task['source_basis']['scans_sha256'] == _fingerprint(self.store.scans(task['snapshot_id'])))
            reasons = []
            if not source_unchanged:
                reasons.append({'code': 'source_evidence_changed', 'message': '来源清单或公告证据在任务创建后发生变化，需要重新建立复核基线。'})
            if not before['can_confirm_absence']:
                reasons.append({'code': 'source_coverage_incomplete', 'message': '来源快照存在未扫描项或结构缺失，原始风险覆盖范围不完整。'})
            if not after['can_confirm_absence']:
                reasons.append({'code': 'after_coverage_incomplete', 'message': '修复后清单存在未扫描项或结构缺失，不能确认目标漏洞消除。'})
            if not comparison['same_knowledge_snapshot']:
                reasons.append({'code': 'knowledge_changed', 'message': '两份清单的公告获取时间不同，消失项只能记为未观察到。'})
            if remaining:
                reasons.append({'code': 'target_remains', 'message': f'修复后清单仍有 {len(remaining)} 个位置命中该公告。'})
            if task['focus'] not in comparison['resolved'] and not reasons:
                reasons.append({'code': 'not_confirmed_resolved', 'message': '对比结果未确认该目标公告消除。'})
            passed = not reasons and comparison['comparison_complete'] and task['focus'] in comparison['resolved']
            verification = {'created': now(), 'passed': passed, 'after_snapshot': after['snapshot'],
                            'source_unchanged': source_unchanged,
                            'comparison_complete': comparison['comparison_complete'],
                            'same_knowledge_snapshot': comparison['same_knowledge_snapshot'],
                            'resolved': task['focus'] in comparison['resolved'],
                            'not_observed': task['focus'] in comparison['not_observed'],
                            'remaining_occurrences': [{'ref': hit['ref'], 'package': hit['package'],
                                                       'version': hit['version'], 'reachable': hit['reachable']}
                                                      for hit in remaining],
                            'after_scans_sha256': _fingerprint(self.store.scans(after_snapshot_id)),
                            'reasons': reasons, 'scope': LIMITATION,
                            'note': '已确认目标公告在选定完整清单与同一知识快照下无命中。' if passed else '尚不能确认该任务的目标公告已消除。'}
            task['verification'] = verification
            task['status'] = 'verified' if passed else 'needs_review'
            self._event(task, 'verified' if passed else 'verification_failed', verification)
            return self._save(db, task)
