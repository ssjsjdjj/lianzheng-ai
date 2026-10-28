from __future__ import annotations

from collections import defaultdict, deque
from urllib.parse import unquote


class InputError(ValueError):
    pass


def npm_identity(component: dict) -> tuple[str | None, str | None, str | None]:
    """Never compare or guess semver ranges. The OSV service resolves versions."""
    name, version = component.get('name'), component.get('version')
    purl = component.get('purl', '')
    if not isinstance(purl, str):
        return None, None, 'purl 必须是字符串'
    if not purl.startswith('pkg:npm/'):
        return None, None, '只支持带 npm purl 的组件'
    locator = purl.split('?', 1)[0].split('#', 1)[0][8:]
    if '@' not in locator[1:]:
        return None, None, 'npm purl 缺少精确版本'
    pname, pversion = locator.rsplit('@', 1)
    pname, pversion = unquote(pname), unquote(pversion)
    declared_name = f"{component.get('group')}/{name}" if component.get('group') else name
    if name and declared_name != pname:
        return None, None, '组件名称与 purl 不一致'
    if version and version != pversion:
        return None, None, '组件版本与 purl 不一致'
    if not pname or not pversion or any(c in pversion for c in '^~*<>=| '):
        return None, None, '必须提供精确的 npm 版本'
    return pname, pversion, None


def parse_bom(raw: dict) -> dict:
    if not isinstance(raw, dict) or raw.get('bomFormat') != 'CycloneDX':
        raise InputError('请导入 CycloneDX JSON 文件，bomFormat 必须为 CycloneDX。')
    if raw.get('specVersion') not in ('1.4', '1.5', '1.6', '1.7'):
        raise InputError('目前支持 CycloneDX 1.4–1.7 JSON。')
    if not isinstance(raw.get('components', []), list):
        raise InputError('components 必须是数组。')
    root = raw.get('metadata', {}).get('component', {})
    if not isinstance(root, dict) or not root.get('bom-ref'):
        raise InputError('metadata.component.bom-ref 必须明确声明项目根节点。')
    nodes, issues, refs = [], [], set()

    def add(c, locator, root_node=False, depth=0):
        if depth > 20 or len(nodes) >= 10000:
            raise InputError('最多支持 10000 个组件及 20 层嵌套。')
        if not isinstance(c, dict) or not isinstance(c.get('bom-ref'), str) or not c['bom-ref']:
            raise InputError(f'{locator} 缺少有效的 bom-ref。')
        ref = c['bom-ref']
        if ref in refs:
            raise InputError(f'bom-ref 重复：{ref}')
        refs.add(ref)
        name, version, error = npm_identity(c) if not root_node else (None, None, None)
        nodes.append({'id': ref, 'name': str(c.get('name') or ref), 'version': str(c.get('version') or ''),
                      'purl': str(c.get('purl') or ''), 'root': root_node,
                      'package_name': name, 'package_version': version, 'identity_error': error,
                      'locator': locator, 'scope': c.get('scope', 'unknown')})
        if error:
            issues.append({'code': 'identity', 'message': f'{ref}：{error}', 'ref': ref})
        nested = c.get('components', [])
        if not isinstance(nested, list):
            raise InputError('嵌套 components 必须是数组。')
        for i, child in enumerate(nested):
            add(child, f'{locator}/components/{i}', depth=depth+1)

    add(root, '/metadata/component', True)
    for i, c in enumerate(raw.get('components', [])):
        add(c, f'/components/{i}')
    deps = raw.get('dependencies', [])
    if not isinstance(deps, list):
        raise InputError('dependencies 必须是数组。')
    edges, declared, unique = [], set(), set()
    for i, dep in enumerate(deps):
        if not isinstance(dep, dict) or not isinstance(dep.get('dependsOn', []), list):
            raise InputError('依赖记录必须包含有效的 dependsOn 数组。')
        source = dep.get('ref')
        if not isinstance(source, str) or source not in refs:
            issues.append({'code': 'dangling', 'message': f'依赖来源不存在：{source}'})
            continue
        if source in declared:
            issues.append({'code': 'duplicate_dependency', 'message': f'重复的依赖声明：{source}'})
        declared.add(source)
        for j, target in enumerate(dep.get('dependsOn', [])):
            if not isinstance(target, str) or target not in refs:
                issues.append({'code': 'dangling', 'message': f'{source} 引用了不存在的组件：{target}'})
            elif (source, target) not in unique:
                unique.add((source, target))
                edges.append({'source': source, 'target': target, 'locator': f'/dependencies/{i}/dependsOn/{j}'})
    for missing in refs-declared:
        issues.append({'code': 'missing_dependencies', 'message': f'{missing} 未声明依赖列表，无法确认是否为叶节点。', 'ref': missing})
    for composition in raw.get('compositions', []):
        if composition.get('aggregate') != 'complete':
            issues.append({'code': 'composition', 'message': '清单声明其组成信息并不完整。'})
    reachable = reachable_nodes(root['bom-ref'], edges)
    for ref in refs-reachable:
        issues.append({'code': 'unreachable', 'message': f'{ref} 未从项目根节点可达，单独列出其风险。', 'ref': ref})
    structure_codes = {'dangling', 'missing_dependencies', 'duplicate_dependency', 'composition', 'unreachable'}
    return {'root': root['bom-ref'], 'nodes': nodes, 'edges': edges, 'issues': issues,
            'complete': not any(x['code'] in structure_codes for x in issues)}


def reachable_nodes(root: str, edges: list[dict]) -> set[str]:
    adjacency = defaultdict(list)
    for edge in edges:
        adjacency[edge['source']].append(edge['target'])
    seen, queue = {root}, deque([root])
    while queue:
        for child in adjacency[queue.popleft()]:
            if child not in seen:
                seen.add(child)
                queue.append(child)
    return seen


def representative_paths(graph: dict, target: str, limit: int = 5, max_depth: int = 12) -> dict:
    """Bound display enumeration; full reachability is computed independently."""
    adjacency = defaultdict(list)
    reverse = defaultdict(list)
    for edge in graph['edges']:
        adjacency[edge['source']].append(edge['target'])
        reverse[edge['target']].append(edge['source'])
    ancestors, queue = {target}, deque([target])
    while queue:
        for parent in reverse[queue.popleft()]:
            if parent not in ancestors:
                ancestors.add(parent); queue.append(parent)
    queue = deque([[graph['root']]])
    paths, truncated, expansions = [], False, 0
    while queue:
        path = queue.popleft(); expansions += 1
        if expansions > 3000:
            truncated = True; break
        if path[-1] == target:
            paths.append(path)
            if len(paths) >= limit:
                truncated = bool(queue); break
            continue
        children = [x for x in adjacency[path[-1]] if x in ancestors and x not in path]
        if len(path)-1 >= max_depth:
            truncated = truncated or bool(children)
            continue
        queue.extend(path+[child] for child in children)
    return {'paths': paths, 'truncated': truncated, 'reachable': graph['root'] in ancestors,
            'display_limit': limit, 'max_display_depth': max_depth}


def affected_fixed_versions(record: dict, name: str) -> list[str]:
    # Only read the matched package's events; do not mix lodash subpackages.
    fixed = []
    for item in record.get('affected', []):
        package = item.get('package', {})
        if package.get('ecosystem') == 'npm' and package.get('name') == name:
            for span in item.get('ranges', []):
                for event in span.get('events', []):
                    if event.get('fixed') and event['fixed'] not in fixed:
                        fixed.append(event['fixed'])
    return fixed
