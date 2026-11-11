"""Read-only, explicit what-if handling of known advisory occurrences.

This module never changes graph edges, versions, scan results or stored snapshots.
The selected occurrence is assumed to stop matching one advisory; it is not an
upgrade resolver and does not establish that an actual repair is feasible.
"""
import hashlib
import json

from .domain import InputError, representative_paths


MAX_SELECTED = 2000
MAX_PATHS = 24
MAX_PATH_TARGETS = 12
PATHS_PER_TARGET = 3


class RepairSimulation:
    def __init__(self, service):
        self.service = service

    def preview(self, snapshot_id, focus, selected_refs):
        if not isinstance(focus, str) or not focus or len(focus) > 200:
            raise InputError('请选择有效的目标公告。')
        if not isinstance(selected_refs, list) or len(selected_refs) > MAX_SELECTED:
            raise InputError(f'推演位置必须为数组，单次最多选择 {MAX_SELECTED} 个位置。')
        if any(not isinstance(ref, str) or not ref for ref in selected_refs):
            raise InputError('推演位置必须是非空的精确组件标识。')
        if len(selected_refs) != len(set(selected_refs)):
            raise InputError('推演位置不能重复，请按精确出现位置选择。')

        analysis = self.service.analyze(snapshot_id, focus, include_documents=False, include_paths=False)
        # analyze() has a display fallback for unknown advisory IDs. Never use it
        # to silently substitute a different target in a what-if request.
        findings = [item for item in analysis['findings'] if item['id'] == focus]
        if not findings:
            raise InputError('当前快照没有该公告的已知命中位置，不能建立此推演。')
        nodes = {node['id']: node for node in analysis['nodes']}
        affected = sorted({item['ref'] for item in findings})
        allowed = set(affected)
        if any(ref not in allowed or nodes[ref]['root'] for ref in selected_refs):
            raise InputError('只能选择当前公告实际命中的组件出现位置；根节点、其他组件和未知位置不可选。')
        selected = set(selected_refs)
        remaining = allowed - selected
        occurrences = [
            {'ref': ref, 'name': nodes[ref]['name'], 'version': nodes[ref]['version'],
             'locator': nodes[ref]['locator'], 'reachable': nodes[ref]['reachable'],
             'selected': ref in selected}
            for ref in affected
        ]
        unknown = [node for node in analysis['nodes'] if not node['root'] and
                   node['scan_status'] not in ('checked', 'demo-component')]
        basis = {
            'snapshot_hash': analysis['snapshot']['hash'], 'focus': focus,
            'graph': {'root': analysis['root'], 'edges': analysis['edges'], 'complete': analysis['complete']},
            'scan_coverage': [
                {'ref': n['id'], 'status': n['scan_status'], 'source': n.get('source'),
                 'fetched_at': n.get('fetched_at'), 'findings': n['findings']}
                for n in analysis['nodes']
            ],
            'target_findings': findings,
        }
        fingerprint = hashlib.sha256(json.dumps(basis, sort_keys=True, ensure_ascii=False,
                                                separators=(',', ':')).encode('utf-8')).hexdigest()

        graph = {'root': analysis['root'], 'edges': analysis['edges']}
        edge_locators = {(e['source'], e['target']): e['locator'] for e in analysis['edges']}
        # Display enumeration is bounded independently of the complete set of
        # known occurrences. Unselected occurrences are shown first.
        ordered = sorted(affected, key=lambda ref: (ref in selected, ref))
        reachable = [ref for ref in ordered if nodes[ref]['reachable']]
        paths, path_targets = [], []
        truncated = len(reachable) > MAX_PATH_TARGETS
        for ref in reachable[:MAX_PATH_TARGETS]:
            result = representative_paths(graph, ref, limit=PATHS_PER_TARGET)
            path_targets.append(ref)
            truncated = truncated or result['truncated']
            for refs in result['paths']:
                if len(paths) >= MAX_PATHS:
                    truncated = True
                    break
                paths.append({
                    'target_ref': ref, 'selected': ref in selected,
                    'nodes': [{'ref': r, 'name': nodes[r]['name'], 'version': nodes[r]['version'],
                               'locator': nodes[r]['locator']} for r in refs],
                    'edge_locators': [edge_locators[a, b] for a, b in zip(refs, refs[1:])],
                })
            if len(paths) >= MAX_PATHS:
                truncated = truncated or len(path_targets) < len(reachable)
                break
        coverage = {
            'graph_complete': analysis['complete'], 'unknown_scan_count': len(unknown),
            'can_confirm_absence': analysis['can_confirm_absence'],
            'meaning': '仅表示原清单和原查询的覆盖情况，不是推演结果的实际修复证明。',
        }
        remaining_reachable = sum(nodes[ref]['reachable'] for ref in remaining)
        limitations = [
            '这是假设推演：只假设勾选位置不再命中目标公告，没有修改依赖版本、依赖边或实际扫描结果。',
            '候选升级能否安装、是否满足约束及业务兼容性尚未验证；实际修复须导入新清单并核对测试记录。',
            '选择一个位置不会连带消除其下游或同名组件的其他命中位置；其他公告不在本次推演范围内。',
        ]
        if not analysis['complete']:
            limitations.append('原清单结构存在缺失或不可达位置，剩余数量只覆盖已知命中；未知关系仍需核对。')
        if unknown:
            limitations.append(f'原清单有 {len(unknown)} 个组件尚未完成精确版本查询；勾选全部已知位置也不能确认整体已消除。')
        if truncated:
            limitations.append('路径图仅展示有界的代表性路径，已截断；全部已知命中位置仍参与计数和选择。')
        conclusion = f'在已知清单内，假设处理 {len(selected)} 个位置后，剩余目标命中预览为 {len(remaining)} 个位置。'
        return {
            'kind': 'hypothetical', 'persisted': False, 'model_calls': 0,
            'snapshot': analysis['snapshot'], 'focus': focus, 'basis_fingerprint': fingerprint,
            'selected_refs': sorted(selected), 'occurrences': occurrences,
            'counts': {'known_affected': len(affected), 'assumed_handled': len(selected),
                       'remaining': len(remaining), 'remaining_reachable': remaining_reachable,
                       'remaining_unreachable': len(remaining) - remaining_reachable},
            'coverage': coverage, 'paths': paths, 'paths_truncated': truncated,
            'path_display_limit': MAX_PATHS, 'path_targets_considered': len(path_targets),
            'selection_limit': MAX_SELECTED, 'conclusion': conclusion, 'limitations': limitations,
        }
