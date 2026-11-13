"""Read-only presentation of captured project evidence, without model or I/O.

Cards describe what the selected material supports and what remains unknown.
Retrieval paths are structural evidence, not proof of exploitability or a fix.
"""
import json
import re

from .task_compare import digest


def evidence_identity(snapshot_id, identifier, title, text, locator, excerpt, extra):
    """Fingerprint one item, not its context-dependent download wrapper.

    A document addition changes every public evidence id and URL. It must not
    make an unchanged component or advisory appear edited in a before/after
    comparison. Keep full (untruncated) source content in this fingerprint.
    """
    try:
        content = json.loads(excerpt)
    except (TypeError, ValueError):
        content = excerpt
    if extra.get('kind') == 'scan' and isinstance(content, dict):
        content = {key: value for key, value in content.items() if key != 'fetched_at'}
    semantic = {key: extra[key] for key in (
        'kind', 'ref', 'version', 'package', 'target_version', 'vulnerability', 'source',
        'trust', 'line_start', 'column_start', 'line_end', 'column_end') if key in extra}
    if 'relations' in extra:
        semantic['relations'] = [{key: edge[key] for key in (
            'source', 'target', 'locator', 'source_lock_locator', 'target_lock_locator') if key in edge}
            for edge in extra['relations']]
    return {'stable_key': 'item-' + digest([snapshot_id, identifier])[:32],
            'content_sha256': digest({'title': title, 'text': text, 'locator': locator,
                                      'source_content': content, 'semantic': semantic})}


def project_brief(state):
    """Use only the already captured read transaction, including empty imports."""
    source = state['source']; coverage = state['coverage']
    components = sorted((n for n in state['graph']['nodes'] if not n['root']),
                        key=lambda n: (n['name'], n['version'], n['id']))
    notes = ['本简报来自当前保存的清单、查询记录与项目文档；生成简报不会发起模型或漏洞查询。',
             '依赖图连通、公告查询完成或导入的测试说明，都不等于本系统已经验证修复或运行测试。']
    if not coverage['graph_complete']:
        notes.append('清单存在依赖关系或身份信息缺口；无法确认完整路径，缺失部分继续标记为未知。')
    if coverage['unknown_components']:
        notes.append(f"{coverage['unknown_components']} 个组件尚未取得完整查询结论；不能把未知当作无风险。")
    suggestions = []
    if components:
        # Prefer a package with actual supplementary material for a useful
        # question, then one with saved advisories, finally a declared package.
        documented = {(d['package'], d['version']) for d in state['knowledge']}
        node = next((n for n in components if (n.get('package_name'), n.get('package_version')) in documented), None)
        if node is None:
            node = next((n for n in components if state['scans'].get(n['id'], {}).get('data', {}).get('vulns')), components[0])
        package = node['name'] + ('@' + node['version'] if node['version'] else '')
        suggestions.append({'id': 'paths', 'label': '解释引入路径',
                            'question': f'{package} 是通过哪些依赖路径引入当前项目的？'})
        suggestions.append({'id': 'coverage', 'label': '核对查询与缺口',
                            'question': f'关于 {package}，当前保存了哪些漏洞查询证据，还有哪些信息未知？'})
        suggestions.append({'id': 'documents', 'label': '核对处理依据' if documented else '准备补充资料',
                            'question': (f'现有 {package} 项目文档支持哪些处理建议，哪些仍需验证？' if documented else
                                         f'如果处理 {package}，还需要补充哪些项目说明和验证记录？')})
    else:
        notes.append('当前清单没有非根组件；先补充带组件和依赖声明的清单，再回答具体包的问题。')
        suggestions.append({'id': 'empty-coverage', 'label': '查看清单缺口',
                            'question': '当前项目清单的覆盖情况是什么，还需要补充哪些组件和依赖信息？'})
    return {**state['binding'], 'project': source['project'], 'label': source['label'],
            'format': source['format'], **{key: coverage[key] for key in (
                'component_count', 'checked_components', 'unknown_components', 'graph_complete', 'knowledge_documents')},
            'issue_count': len(coverage['issues']), 'suggestions': suggestions, 'notes': notes}


def _compact(text, limit=300):
    text = ' '.join(str(text).split())
    return text if len(text) <= limit else text[:limit] + '…'


def answer_card(state, question, column):
    """Only this column's selected evidence may back a card claim.

    Exact quote validation happens in ProjectQuery._links. Even a validated
    quote proves its source, not semantic correctness: expose that limitation.
    """
    selected = column['evidence']; lookup = {d['id']: d for d in selected}
    kinds = {}
    for doc in selected:
        kinds.setdefault(doc['kind'], []).append(doc)
    documents = kinds.get('project', []) + kinds.get('migration', [])
    coverage = kinds.get('coverage', [])
    scans = kinds.get('scan', []); advisories = kinds.get('advisory', [])
    occurrences = kinds.get('occurrence', [])
    paths = column['evidence_links']['paths']
    model_claims = [f for f in column['evidence_links']['facts']
                    if f['kind'] == 'model-claim' and f.get('evidence_ids') and
                    all(identifier in lookup for identifier in f['evidence_ids'])]
    wants_path = bool(re.search(r'路径|引入|依赖|位置|间接|直接|残留', question))
    wants_action = bool(re.search(r'升级|修复|迁移|替换|处理|方案|兼容|测试|验证', question))

    def ids(items):
        return list(dict.fromkeys(item['id'] for item in items))

    def row(text, evidence_ids=()):
        return {'text': text, 'evidence_ids': list(dict.fromkeys(evidence_ids))}

    path_ids = list(dict.fromkeys(identifier for path in paths for edge in path['edges']
                                 for identifier in edge['evidence_ids'] if identifier in lookup))
    if not selected:
        conclusion = row('本侧没有检索到可引用的当前项目片段，暂时无法回答这个问题。')
    elif wants_action and documents:
        first = documents[0]
        conclusion = row('导入文档提供了处理线索：“' + _compact(first['text'], 180) +
                         '”。这些是文档记载，尚不能据此确认兼容、测试通过或修复成功。', [first['id']])
    elif wants_path and paths:
        conclusion = row(f'本侧取回的清单声明可连通 {len(paths)} 条代表性引入路径：' +
                         _compact(paths[0]['label'], 230) + '。这说明依赖关系，不代表运行时可利用性。', path_ids)
    elif advisories:
        conclusion = row('本侧找到已保存的公告材料：' +
                         '、'.join(d.get('vulnerability') or d['title'] for d in advisories[:3]) +
                         '；是否影响本项目运行、如何处理，仍需结合适用条件与验证记录判断。', ids(advisories[:3]))
    elif scans:
        conclusion = row(_compact(scans[0]['text']) + ' 查询状态不等于修复验证结果。', ids(scans[:1]))
    elif documents:
        conclusion = row('导入文档记载：“' + _compact(documents[0]['text'], 180) +
                         '”。其内容真实性和项目适用性仍需核对。', ids(documents[:1]))
    elif occurrences:
        conclusion = row(_compact(occurrences[0]['text'].splitlines()[0]) +
                         ' 当前片段仅能说明清单中的组件记录，尚不足以得出问题所需的风险或处理结论。', ids(occurrences[:1]))
    else:
        conclusion = row(_compact(coverage[0]['text']) if coverage else '本侧材料尚不足以回答该问题。', ids(coverage[:1]))

    reasons = []
    prioritized = (documents if wants_action else []) + selected
    seen = set()
    for doc in prioritized:
        if doc['id'] in seen:
            continue
        seen.add(doc['id'])
        if doc['kind'] in ('project', 'migration'):
            text = '导入文档记载（未验证）：' + _compact(doc['text'])
        elif doc['kind'] == 'advisory':
            text = '已保存公告 ' + doc.get('vulnerability', '') + '：' + _compact(doc['text'])
        else:
            text = _compact(doc['text'])
        reasons.append({'id': 'reason-' + doc['stable_key'], **row(text, [doc['id']])})
    generation = column['generation']
    if model_claims:
        conclusion = row(model_claims[0]['text'], model_claims[0]['evidence_ids'])
        reasons = [{'id': f['id'], **row(f['text'], f['evidence_ids'])} for f in model_claims] + reasons
    elif generation == 'model-assisted':
        generation = 'model-fallback'

    unknowns = [row('本次问答未运行项目测试或攻击验证，不能确认测试通过、兼容性或实际修复效果。')]
    if not selected:
        unknowns.insert(0, row('没有取回片段不代表项目不存在证据或风险；可换用清单中的包名和精确版本再问。'))
    if wants_path and not paths:
        unknowns.append(row('本侧没有取回可从项目根连通的完整路径；缺失关系不能补造，也不代表该包没有被引入。', ids(occurrences)))
    if not scans and not advisories:
        unknowns.append(row('本侧未取回可用于核对的组件漏洞查询记录或公告；不能据此判断无漏洞。'))
    if coverage:
        if not state['coverage']['graph_complete']:
            unknowns.append(row('当前清单存在关系或身份缺口，无法保证路径与组件信息完整。', ids(coverage)))
        if state['coverage']['unknown_components']:
            unknowns.append(row(f"当前记录中有 {state['coverage']['unknown_components']} 个组件尚未取得完整查询结论。", ids(coverage)))
    if wants_action and not documents:
        unknowns.append(row('本侧没有取回适用的项目或迁移文档；不能据此推荐具体升级版本或断言处理方案可行。'))
    if documents:
        unknowns.append(row('导入文档由提供者声明，包含的建议或测试结论尚未由本系统独立验证。', ids(documents)))
    if column['generation'] == 'model-fallback':
        unknowns.append(row('本次模型解释未成功，答案卡保留离线取证结果。'))
    elif column['generation'] == 'model-assisted' and not model_claims:
        unknowns.append(row('模型输出没有可核对原文摘录的结论，答案卡改用离线取证结果。'))
    next_steps = []
    if paths:
        next_steps.append(row('打开路径与对应原文，核对组件位置和每条依赖声明。', path_ids))
    if advisories or scans:
        next_steps.append(row('核对查询时间、公告适用条件及修复边界，再选择待验证的处理方案。', ids(advisories + scans)))
    else:
        next_steps.append(row('补充当前精确版本的查询记录与公告，再核对风险判断。'))
    if documents:
        next_steps.append(row('核对导入文档对应的包与版本，并补充实际测试命令、输出和执行环境。', ids(documents)))
    else:
        next_steps.append(row('补充与当前包和精确版本绑定的项目说明或迁移文档，再以同一个问题对照回答变化。'))
    return {**state['binding'], 'generation': generation, 'conclusion': conclusion,
            'reasons': reasons, 'unknowns': unknowns, 'next_steps': next_steps[:3],
            'note': '每个引用仅指向本侧当前项目片段；原文摘录核对与路径连通不等于结论语义已通过审核。'}
