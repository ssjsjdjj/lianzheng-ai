"""Read-only local presentation checks. Never tests or contacts a model provider."""
import sqlite3

from .domain import InputError
from .store import now


class DemoReadiness:
    def __init__(self, service, real_case, comparison, decisions):
        self.service = service
        self.real_case = real_case
        self.comparison = comparison
        self.decisions = decisions

    def report(self):
        checks = [{'id': 'service', 'label': '本机服务', 'status': 'pass',
                   'detail': '服务已响应；此项不表示模型接口在线。'}]
        failures = (InputError, KeyError, OSError, ValueError, TypeError, sqlite3.Error)
        case = {'available': False, 'id': None, 'title': '固定真实案例',
                'bundle_sha256': None, 'source_commit': None, 'prepared': False,
                'basis_matches_recorded': None}
        blocked = False
        try:
            status = self.real_case.status()
            if not status.get('available'):
                raise InputError('missing case')
            case.update({key: status.get(key) for key in ('available', 'id', 'title', 'bundle_sha256', 'prepared')})
            case['source_commit'] = status['source'].get('commit')
            case['basis_matches_recorded'] = (status.get('current') or {}).get('basis_matches_recorded')
            checks.append({'id': 'case-files', 'label': '案例来源与文件', 'status': 'pass',
                           'detail': '冻结案例文件哈希与清单已核对；没有重新查询公告或执行上游测试。'})
            if case['prepared'] and case['basis_matches_recorded'] is not True:
                blocked = True
                checks.append({'id': 'workspace', 'label': '工作空间案例依据', 'status': 'fail',
                               'detail': '已载入案例的查询依据与冻结记录不同。请核对案例详情；不会覆盖已有数据。'})
            else:
                checks.append({'id': 'workspace', 'label': '工作空间案例依据',
                               'status': 'pass' if case['prepared'] else 'warn',
                               'detail': '已载入依据与冻结案例一致。' if case['prepared'] else
                                         '尚未载入；点击开始后会添加缺少的案例快照，不覆盖已有记录。'})
        except failures:
            blocked = True
            checks.append({'id': 'case-files', 'label': '案例来源与文件', 'status': 'fail',
                           'detail': '案例缺失、损坏或与工作空间冲突。请恢复发布包中的案例材料，再重新预检。'})
        try:
            catalog = self.comparison.tasks()
            if (not case['available'] or catalog['source']['case_bundle_sha256'] != case['bundle_sha256']):
                raise InputError('case changed')
            checks.append({'id': 'task-set', 'label': '对照任务与案例绑定', 'status': 'pass',
                           'detail': f"{len(catalog['tasks'])} 个固定开发任务与当前案例一致；现场新问题不使用参考评分。"})
        except failures:
            blocked = True
            checks.append({'id': 'task-set', 'label': '对照任务与案例绑定', 'status': 'fail',
                           'detail': '任务集无法读取或案例校验值不一致，请恢复匹配的发布材料后重试。'})
        try:
            decisions = self.decisions.report()
            if decisions.get('bundle_sha256') != case['bundle_sha256'] or not case['available']:
                raise InputError('case changed')
            checks.append({'id': 'decisions', 'label': '方案、时间线与下载材料', 'status': 'pass',
                           'detail': '实际方案与保存的成功、失败日志已核对；可离线导出证据包。'})
        except failures:
            blocked = True
            checks.append({'id': 'decisions', 'label': '方案、时间线与下载材料', 'status': 'fail',
                           'detail': '方案或测试记录无法核对。请恢复案例材料后重试，不能用旧结果代替。'})
        try:
            public = self.service.models.public()
            model = {'configured': bool(public.get('configured')), 'verified': bool(public.get('verified')),
                     'remote_checked': False, 'model': public.get('model')}
            checks.append({'id': 'model', 'label': '可选模型配置',
                           'status': 'pass' if model['configured'] else 'warn',
                           'detail': '本机已配置；历史连接状态不代表当前可用额度或在线情况。' if model['configured'] else
                                     '尚未配置模型，可完成离线主线。预检不会发送模型请求。'})
        except failures:
            model = {'configured': False, 'verified': False, 'remote_checked': False, 'model': None}
            checks.append({'id': 'model', 'label': '可选模型配置', 'status': 'warn',
                           'detail': '本机模型配置暂时无法读取；可先使用离线证据。'})
        try:
            current = self.service.call_control.public()
            policy = current['policy']
            remaining = max(0, policy['daily_calls'] - current['calls_today']) if policy['enabled'] else None
            budget = policy.get('daily_budget_usd')
            budget_blocked = (policy['enabled'] and budget is not None and
                              (current['unreserved_calls'] > 0 or current['budget_accounted_usd'] >= budget))
            allowed = bool(model['configured'] and not current['in_flight'] and
                           (remaining is None or remaining >= 2) and not budget_blocked)
            usage = {key: current[key] for key in ('policy', 'day_utc', 'calls_today', 'in_flight',
                                                 'budget_accounted_usd', 'unknown_cost_calls')}
            usage.update({'remaining_calls': remaining, 'model_pair_locally_allowed': allowed})
            checks.append({'id': 'usage', 'label': '本地聊天调用限制', 'status': 'pass' if allowed else 'warn',
                           'detail': '本地检查未发现阻挡；实际请求仍需通过当次预算与服务商校验。' if allowed else
                                     '可选双侧模型暂未就绪，请核对配置、进行中请求或本地限制；离线模式不受影响。'})
        except failures:
            usage = {'calls_today': None, 'in_flight': None, 'remaining_calls': None,
                     'policy': None, 'model_pair_locally_allowed': False}
            checks.append({'id': 'usage', 'label': '本地聊天调用限制', 'status': 'warn',
                           'detail': '调用账本暂时无法读取，先使用离线证据，不据此判断余额。'})
        return {'release': '0.10.0', 'checked_at': now(), 'offline_ready': not blocked,
                'case': case, 'checks': checks, 'model': model, 'usage': usage,
                'model_calls': 0, 'network_calls': 0, 'workspace_modified': False,
                'note': '预检仅核对本地资料和设置，不验证服务商余额、接口在线状态或真实模型问答效果。'}
