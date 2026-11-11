"""Paired retrieval over the same frozen real-project evidence, with optional paid explanation.

Reference labels are used only after retrieval. The default run never changes the
workspace or calls an external service. This is a single-project development task
set, not a held-out benchmark or an answer-accuracy claim.
"""
import hashlib
import json
import math
import re
import time
from collections import Counter, deque
from pathlib import Path

from .domain import InputError
from .retrieval import tokens, model_explanation
from .budget import MAX_INPUT_BYTES
from .providers import validate_provider_endpoint
from .store import now


K = 8
EVIDENCE_BYTES = 28000
METHODS = ('bm25', 'bm25+graph')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def node_id(ref):
    return 'node-' + hashlib.sha256(ref.encode()).hexdigest()[:16]


def pointer(path):
    return '/packages/' + path.replace('~', '~0').replace('/', '~1')


def lexical_rank(question, documents):
    """No task id, labels, phase-specific answer, or embedding service enters ranking."""
    counts = [Counter(tokens(d['title'] + '\n' + d['text'])) for d in documents]
    lengths = [sum(c.values()) for c in counts]
    average = sum(lengths) / max(len(lengths), 1) or 1
    query = set(tokens(question))
    frequencies = Counter(t for c in counts for t in query if t in c)
    scores = []
    for index, count in enumerate(counts):
        score = sum(math.log(1 + (len(counts) - frequencies[t] + .5) / (frequencies[t] + .5)) *
                    count[t] * 2.5 / (count[t] + 1.5 * (.25 + .75 * lengths[index] / average))
                    for t in query if count[t])
        scores.append(score)
    return [documents[i]['id'] for i in sorted(range(len(documents)), key=lambda i: (-scores[i], documents[i]['id']))
            if scores[i] > 0]


def entities(question, graph):
    names = {n['name'] for n in graph['nodes'] if not n['root']}
    found = {name for name in names if re.search(r'(?<![\w@/.-])' + re.escape(name) + r'(?![\w/.-])', question, re.I)}
    versions = set(re.findall(r'\b\d+\.\d+\.\d+(?:-[\w.-]+)?\b', question))
    return [n['id'] for n in graph['nodes'] if n['name'] in found and (not versions or n['version'] in versions)]


def shortest_paths(graph, targets):
    root = graph['root']
    adjacency = {}
    for edge in graph['edges']:
        adjacency.setdefault(edge['source'], []).append(edge['target'])
    parent = {root: None}; queue = deque([root])
    while queue:
        current = queue.popleft()
        for child in sorted(adjacency.get(current, [])):
            if child not in parent:
                parent[child] = current; queue.append(child)
    result = []
    for target in targets:
        if target not in parent:
            continue
        path = [target]
        while parent[path[-1]] is not None:
            path.append(parent[path[-1]])
        result.append(list(reversed(path)))
    return result


def rank(question, documents, graph, method):
    ranked = lexical_rank(question, documents)
    if method == 'bm25':
        return ranked
    if method != 'bm25+graph':
        raise InputError('不支持的对照方法。')
    # Query names, not answer labels, choose graph traversal endpoints. Both
    # columns can read the same incoming-edge text in the same node documents.
    targets = entities(question, graph)
    if not targets or not re.search('路径|引入|位置|依赖|残留|间接|直接', question):
        return ranked
    promoted = [node_id(ref) for ref in targets]
    for path in shortest_paths(graph, targets):
        promoted.extend(node_id(ref) for ref in reversed(path[:-1]) if ref != graph['root'])
    available = {d['id'] for d in documents}
    return list(dict.fromkeys(i for i in promoted + ranked if i in available))


def select_evidence(ids, documents):
    lookup = {d['id']: d for d in documents}; selected = []; used = 0
    for identifier in ids:
        doc = lookup[identifier]
        size = len(json.dumps(doc, ensure_ascii=False).encode())
        if len(selected) >= K:
            break
        if used + size > EVIDENCE_BYTES:
            continue
        selected.append(doc); used += size
    return selected, used


def selected_paths(question, selected, graph):
    """The same postprocessor for both sides; only visible selected edges count."""
    actual = {(edge['source'], edge['target']) for edge in graph['edges']}
    edges = {(edge['source'], edge['target']) for d in selected for edge in d.get('relations', [])
             if (edge['source'], edge['target']) in actual}
    reduced = {**graph, 'edges': [{'source': a, 'target': b} for a, b in edges]}
    return shortest_paths(reduced, entities(question, graph))[:3]


def linked_evidence(selected, paths, graph, case, case_hash, phase, model=None):
    """Bind display links to selected documents and verified graph edges only.

    A link says where a claim cites material; it is not a semantic support verdict.
    Neither model prose nor a source filename can introduce a graph relationship.
    """
    nodes = {node['id']: node for node in graph['nodes']}
    actual = {(edge['source'], edge['target']) for edge in graph['edges']}
    lockfile = case[phase + '_lockfile']
    lock_hash = next(row['sha256'] for row in case['files'] if row['name'] == lockfile)
    documents = {document['id']: document for document in selected}
    bindings = {}
    for document in selected:
        if document['filename'] != lockfile or document['source_sha256'] != lock_hash:
            continue
        for relation in document.get('relations', []):
            edge = (relation['source'], relation['target'])
            if edge in actual and all(ref in nodes for ref in edge):
                bindings.setdefault(edge, []).append(document['id'])

    def locator(ref):
        return pointer('' if ref == graph['root'] else ref.removeprefix('npm:'))

    linked_paths = []
    for path in paths:
        edges = list(zip(path, path[1:]))
        if (len(path) < 2 or path[0] != graph['root'] or len(set(path)) != len(path) or
                not all(ref in nodes for ref in path) or not all(edge in bindings for edge in edges)):
            continue
        linked_paths.append({
            'id': 'path-' + digest([phase, path])[:20],
            'label': ' → '.join(nodes[ref]['name'] + '@' + nodes[ref]['version'] for ref in path),
            'nodes': [{'ref': ref, 'name': nodes[ref]['name'], 'version': nodes[ref]['version'],
                       'locator': locator(ref), 'filename': lockfile, 'source_sha256': lock_hash}
                      for ref in path],
            'edges': [{'source': source, 'target': target,
                       'evidence_ids': sorted(set(bindings[(source, target)])),
                       'source_locator': locator(source), 'target_locator': locator(target),
                       'filename': lockfile, 'source_sha256': lock_hash}
                      for source, target in edges]})

    def path_ids(evidence_ids):
        identifiers = set(evidence_ids)
        return [path['id'] for path in linked_paths
                if any(identifiers.intersection(edge['evidence_ids']) for edge in path['edges'])]

    facts = []
    for document in selected:
        text = document['text'].splitlines()[0]
        identifiers = [document['id']]
        facts.append({'id': 'fact-' + digest([phase, document['id'], text])[:20], 'text': text,
                      'evidence_ids': identifiers, 'path_ids': path_ids(identifiers),
                      'kind': 'retrieved-fact'})
    for index, claim in enumerate((model or {}).get('claims', [])):
        if not isinstance(claim, dict) or not isinstance(claim.get('text'), str) or not claim['text'].strip():
            continue
        quotes = claim.get('quotes')
        if not isinstance(quotes, list) or not quotes:
            continue
        if not all(isinstance(quote, dict) and isinstance(quote.get('evidence_id'), str) and
                   quote['evidence_id'] in documents and isinstance(quote.get('quote'), str) and
                   quote['quote'].strip() and quote['quote'] in documents[quote['evidence_id']]['text']
                   for quote in quotes):
            continue
        identifiers = list(dict.fromkeys(quote['evidence_id'] for quote in quotes))
        facts.append({'id': 'claim-' + str(index), 'text': claim['text'],
                      'evidence_ids': identifiers, 'path_ids': path_ids(identifiers), 'kind': 'model-claim'})
    return {'paths': linked_paths, 'facts': facts,
            'source': {'case_bundle_sha256': case_hash, 'phase': phase,
                       'lockfile': lockfile, 'lockfile_sha256': lock_hash},
            'semantic_support': 'pending-human-review',
            'note': '联动仅表示本侧检索材料中的引用与依赖关系。模型摘录针对规范化事实，不是上游文件逐字引用；是否支持结论仍需人工复核。'}


class TaskComparison:
    def __init__(self, service, real_case, fixture_path):
        self.service = service; self.real_case = real_case; self.fixture_path = Path(fixture_path)

    def _fixture(self):
        if self.fixture_path.is_symlink():
            raise InputError('任务集不能是符号链接。')
        try:
            if self.fixture_path.stat().st_size > 200000:
                raise InputError('真实任务集过大。')
            raw = self.fixture_path.read_bytes(); fixture = json.loads(raw)
        except (OSError, ValueError, UnicodeError) as error:
            raise InputError('真实任务集无法读取。') from error
        tasks = fixture.get('tasks') if isinstance(fixture, dict) else None
        if not isinstance(tasks, list) or not 1 <= len(tasks) <= 50:
            raise InputError('真实任务集格式不正确。')
        identifiers = set()
        for task in tasks:
            if (not isinstance(task, dict) or not isinstance(task.get('id'), str) or task['id'] in identifiers or
                not isinstance(task.get('question'), str) or not 1 <= len(task['question']) <= 1000 or
                not isinstance(task.get('category'), str) or not task['category'] or
                task.get('phase') not in ('before', 'partial', 'after') or
                not isinstance(task.get('expected_evidence_ids'), list) or
                not all(isinstance(i, str) for i in task['expected_evidence_ids'])):
                raise InputError('真实任务条目格式不正确。')
            identifiers.add(task['id'])
        return fixture, hashlib.sha256(raw).hexdigest()

    def _load(self):
        fixture, fixture_hash = self._fixture()
        case, files, case_hash, _ = self.real_case._bundle()
        if fixture.get('case_bundle_sha256') != case_hash:
            raise InputError('任务集与冻结案例不一致，请恢复匹配的来源文件。')
        return fixture, fixture_hash, case, files, case_hash

    def tasks(self):
        fixture, fixture_hash, case, files, case_hash = self._load()
        return {'available': True, 'tasks': [{key: task[key] for key in ('id', 'question', 'phase', 'category')}
                                           for task in fixture['tasks']],
                'source': {'case_id': case['id'], 'commit': case['source']['commit'], 'url': case['source']['url'],
                           'case_bundle_sha256': case_hash, 'task_fixture_sha256': fixture_hash},
                'protocol': self.protocol(), 'model_configured': self.service.models.public()['configured']}

    @staticmethod
    def protocol():
        return {'project_count': 1, 'task_authorship': '开发者依据冻结真实项目整理，非真实用户提问记录',
                'independent_test': False, 'human_reviewed': False, 'semantic_accuracy': None,
                'k': K, 'evidence_max_bytes': EVIDENCE_BYTES, 'model_max_input_bytes': MAX_INPUT_BYTES,
                'shared_postprocessing': '两侧均从各自取回片段的明确入边连接代表路径；并非完全禁止文本侧的关系推理。',
                'statement': '两侧使用同一候选语料、相同 k 和字节上限，仅检索排序不同。实际片段和输入字节可以不同；结构命中不等于回答正确率。'}

    def _corpus(self, case, files, plan):
        graph = plan['graph']; phase = plan['phase']; lock_name = case[phase + '_lockfile']
        hashes = {f['name']: f['sha256'] for f in case['files']}
        nodes = {n['id']: n for n in graph['nodes']}; incoming = {}
        for edge in graph['edges']:
            incoming.setdefault(edge['target'], []).append(edge)
        documents = []

        def add(identifier, title, text, filename, locator, **extra):
            if extra.get('kind') == 'test':
                lines = files.contents[filename].decode('utf-8').splitlines(keepends=True)
                position = next((i for i, line in enumerate(lines) if re.match(r'^\s*\d+ passing\b', line)), 0)
                start = max(position - 1, 0)
                excerpt = ''.join(lines[start:start + 14])
                extra.update(source_excerpt=excerpt[:2400], source_excerpt_kind='raw-log',
                             source_excerpt_truncated=start > 0 or start + 14 < len(lines) or len(excerpt) > 2400,
                             source_line_start=start + 1, source_line_end=min(start + 14, len(lines)))
            documents.append({'id': identifier, 'title': title, 'text': text,
                              'source': 'frozen-case-normalized-fact', 'filename': filename, 'locator': locator,
                              'url': '/api/real-case/files/' + filename, 'source_sha256': hashes.get(filename),
                              'phase': phase, 'version': '', **extra})

        for node in graph['nodes']:
            if node['root']:
                continue
            ref = node['id']; path = ref.removeprefix('npm:'); raw = plan['raw_lockfile']['packages'][path]
            relations = [{**edge, 'source_lock_locator': pointer('' if edge['source'] == graph['root'] else edge['source'].removeprefix('npm:')),
                          'target_lock_locator': pointer(path)}
                         for edge in sorted(incoming.get(ref, []), key=lambda e: (e['source'], e['target']))[:12]]
            relation_text = '\n'.join(f"依赖关系：{nodes[e['source']]['name']}@{nodes[e['source']]['version']} [{e['source']}] → {node['name']}@{node['version']} [{ref}]。" for e in relations)
            scan = plan['scans'][ref]
            # Source scan records describe this exact npm version; actual target
            # matching is delegated to findings_for, same as the case importer.
            from .osv import findings_for
            target_hit = any(v['id'] == case['target']['advisory_id'] for v in findings_for(node, scan))
            match_label = str(target_hit) if scan['status'] == 'checked' else '未知（未完成查询）'
            text = (f"组件 {node['name']}@{node['version']}，精确安装位置 {ref}。\n"
                    f"锁文件 dev 标记：{raw.get('dev', False)}；此标记不证明生产运行时暴露。\n"
                    f"冻结查询状态：{scan['status']}。目标公告 {case['target']['advisory_id']} 匹配：{match_label}。\n" + relation_text)
            if len(incoming.get(ref, [])) > len(relations):
                text += '\n本片段仅列出前 12 个入边；原始锁文件保留全部声明。'
            source_json = json.dumps(raw, ensure_ascii=False, sort_keys=True)
            add(node_id(ref), f"{node['name']} {node['version']} 安装位置与直接引入关系", text,
                lock_name, pointer(path), ref=ref, version=node['version'], relations=relations,
                source_excerpt=source_json[:1200], source_excerpt_truncated=len(source_json) > 1200,
                derived_from=[lock_name, case['osv_snapshot']], kind='occurrence')

        target_refs = [d['ref'] for d in documents if d.get('ref') and '匹配：True' in d['text']]
        add('target-summary', 'minimist 目标公告匹配位置汇总',
            f"目标公告 {case['target']['advisory_id']}；minimist 已观察匹配位置数：{plan['target_count']}。\n"
            f"匹配位置：{', '.join(target_refs) or '当前冻结记录未观察到目标匹配'}。\n"
            '汇总来自当前阶段全部已解析位置及冻结 OSV；零命中不等于全项目安全。',
            case['osv_snapshot'], '/records', derived_from=[lock_name, case['osv_snapshot']], kind='summary')
        issue_text = '\n'.join(i['message'] for i in graph['issues'])
        add('coverage', '依赖覆盖、未知与生产可利用性边界',
            f"依赖图完整：{graph['complete']}。尚未查询位置：{plan['unknown']}。\n{issue_text}\n"
            '没有本项目生产环境调用轨迹、部署记录或实际攻击记录，不能断言生产可利用或可安全上线。',
            lock_name, '/packages', derived_from=[lock_name, case['osv_snapshot']], kind='coverage')
        test = case['tests'][phase]
        add('tests', '实际测试命令、通过、跳过与覆盖范围',
            f"{test['summary']}\n命令：{test['command']}。退出码：{test['exit_code']}。\n"
            f"coverage_enabled={test['coverage_enabled']}；这是保存的实验记录，当前任务未重跑测试。", test['log_file'],
            'recorded test summary; original log download', kind='test')
        add('source', '项目来源与固定版本', f"项目 http-server；固定提交 {case['source']['commit']}；"
            f"许可证 {case['source']['license']}；该实验不是上游已合并修复或客户生产验证。",
            'source-files.json', '/', kind='source')
        if phase == 'after':
            failure = case['migration_failure']
            add('migration-failure', 'tap 测试 API 迁移前失败', failure['summary'] + '\n命令：' + failure['command'] +
                '。这是升级后的中间失败，不是最终成功测试。', failure['log_file'], 'recorded failure log', kind='test')
            patch = files.contents['test-api-migration.patch'].decode('utf-8')
            add('migration-patch', '两条字符串包含断言的等意图 API 迁移',
                '升级 tap 后保留原检查意图，将两处 t.includes 迁移为 t.ok(res.body.includes(...))。\n' + patch,
                'test-api-migration.patch', 'unified diff', source_excerpt=patch, kind='migration')
        return sorted(documents, key=lambda d: d['id'])

    def run(self, task_id, use_model=False):
        if not isinstance(task_id, str) or type(use_model) is not bool:
            raise InputError('任务标识或模型选项无效。')
        fixture, fixture_hash, case, files, case_hash = self._load()
        task = next((t for t in fixture['tasks'] if t['id'] == task_id), None)
        if task is None:
            raise KeyError('真实任务不存在。')
        return self._run(task, case, files, case_hash, fixture_hash, use_model)

    def ask(self, question, phase='before', use_model=False):
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= 1000 or len(question) > 2000:
            raise InputError('请输入 1 至 1000 字的问题。')
        if not isinstance(phase, str) or phase not in ('before', 'partial', 'after'):
            raise InputError('案例阶段必须为 before、partial 或 after。')
        if type(use_model) is not bool:
            raise InputError('模型选项必须为布尔值。')
        question = question.strip()
        case, files, case_hash, _ = self.real_case._bundle()
        task = {'id': 'free-' + hashlib.sha256((phase + '\n' + question).encode()).hexdigest()[:20],
                'question': question, 'phase': phase, 'category': '现场自由提问'}
        return self._run(task, case, files, case_hash, None, use_model)

    def _run(self, task, case, files, case_hash, fixture_hash, use_model):
        scored = 'expected_evidence_ids' in task
        plans = self.real_case._plans(case, files, case_hash)
        plan = next(p for p in plans if p['phase'] == task['phase'])
        documents = self._corpus(case, files, plan)
        corpus_hash = digest(documents); expected = set(task.get('expected_evidence_ids', []))
        if not expected.issubset({d['id'] for d in documents}):
            raise InputError('任务参考证据与来源不一致。')
        config = None
        if use_model:
            config = dict(self.service.models.current())
            _, local = validate_provider_endpoint(config.get('base_url', ''), config.get('provider'))
            if not config.get('model') or not (config.get('api_key') or local):
                raise InputError('尚未配置可用模型；可先运行离线证据对照。')
        columns = []; attempts = 0
        for method in METHODS:
            started = time.perf_counter()
            ranked = rank(task['question'], documents, plan['graph'], method)
            selected, used_bytes = select_evidence(ranked, documents)
            paths = selected_paths(task['question'], selected, plan['graph'])
            lookup = {n['id']: n for n in plan['graph']['nodes']}
            connected_targets = sorted({path[-1] for path in paths if lookup[path[-1]]['name'] == case['target']['package']})
            readable = [' → '.join(lookup[ref]['name'] + '@' + lookup[ref]['version'] + ' [' + ref + ']' for ref in path) for path in paths]
            hits = expected.intersection(d['id'] for d in selected)
            local_answer = ('本侧检索到 ' + str(len(selected)) + ' 份证据。前列规范化事实摘要：\n' +
                            '\n'.join(str(i + 1) + '. ' + d['text'].splitlines()[0] for i, d in enumerate(selected[:3])) +
                            '\n以上仅摘要已取回材料，完整依据与适用范围见下方。' if selected else
                            '未检索到适用片段，当前方法不能回答；不等于来源中不存在证据。')
            column = {'id': method, 'method': method, 'generation': 'offline-evidence', 'answer': local_answer,
                      'evidence': selected, 'paths': readable, 'warning': None, 'model': None,
                      'metrics': {'retrieved': len(selected), 'reference_found': len(hits) if scored else None,
                                  'reference_total': len(expected) if scored else None,
                                  'reference_coverage': round(len(hits) / len(expected), 4) if expected else None,
                                  'expected_evidence_ids': sorted(expected), 'missing_evidence_ids': sorted(expected - hits),
                                  'retrieval_ms': round((time.perf_counter() - started) * 1000, 3),
                                  'evidence_bytes': used_bytes, 'semantic_support': 'pending-human-review',
                                  'connected_representative_paths': len(readable),
                                  'connected_target_occurrences': len(connected_targets),
                                  'connected_target_refs': connected_targets,
                                  'connected_target_package': case['target']['package'],
                                  'connected_target_scope': '由已取回关系片段连通到的目标包位置，包含无目标公告命中的版本；不是全图路径数或受影响位置数。',
                                  'semantic_accuracy': None}}
            if use_model:
                # Capture configuration once for the pair. Shared source data, budgets,
                # formatting and postprocessing; reference labels never reach the LLM.
                attempts += 1
                evidence = [{key: d[key] for key in ('id', 'title', 'text', 'version', 'source', 'locator')} for d in selected]
                context = {'facts': {'insufficient': not bool(selected), 'fixed_versions': [], 'target_version': None,
                                    'graph_complete': plan['graph']['complete'], 'scope': 'retrieved evidence only'},
                           'evidence': evidence, 'paths': readable, 'conversation': [],
                           'limitations': ['仅使用本侧检索片段，不得以参考标签或另一侧答案补充缺项。',
                                           '路径由两侧相同的片段入边后处理生成；不能新增未提供关系。',
                                           '无生产部署或运行时攻击证据；命中不等于可利用。']}
                # Permit only exact source versions through existing citation guard;
                # these are observed versions, not proposed fixed-version claims.
                for d in evidence:
                    d['target_version'] = d['version'] or None
                result, warning = model_explanation(task['question'], context, config=config,
                                                    usage_guard=self.service.call_control)
                column['model'] = result
                column['warning'] = str(warning) if warning else None
                column['attempt_metadata'] = getattr(warning, 'metadata', None)
                if result:
                    column['generation'] = 'model-assisted'; column['answer'] = result['text']
                else:
                    column['generation'] = 'model-fallback'
            column['evidence_links'] = linked_evidence(selected, paths, plan['graph'], case, case_hash,
                                                       task['phase'], column['model'])
            columns.append(column)
        delta = columns[1]['metrics']['reference_found'] - columns[0]['metrics']['reference_found'] if scored else None
        model_names = [((c.get('model') or {}).get('metadata') or {}).get('returned_model') for c in columns]
        comparable = (not use_model) or (all(c['generation'] == 'model-assisted' for c in columns) and
                                        all(model_names) and model_names[0] == model_names[1])
        return {'release': '0.9.0', 'generated_at': now(),
                'task': {**{k: task[k] for k in ('id', 'question', 'phase', 'category')},
                         'kind': 'curated-task' if scored else 'free-question'},
                'source': {'case_id': case['id'], 'commit': case['source']['commit'], 'url': case['source']['url'],
                           'case_bundle_sha256': case_hash, 'task_fixture_sha256': fixture_hash,
                           'lockfile': case[task['phase'] + '_lockfile'], 'basis': 'frozen-case; not current workspace scans'},
                'fairness': {**self.protocol(), 'corpus_sha256': corpus_hash, 'candidate_documents': len(documents),
                             'reference_scored': scored,
                             'task_authorship': '开发者依据冻结真实项目整理，非真实用户提问记录' if scored else '本次操作者现场输入；没有预设参考答案',
                             'same_raw_materials': True, 'same_candidate_corpus': True, 'same_requested_model': True,
                             'requested_model': config.get('model') if config else None, 'returned_models': model_names,
                             'model_pair_comparable': comparable if use_model else None},
                'columns': columns, 'comparison': {'metric': 'reference-evidence-found' if scored else None, 'graph_minus_text': delta,
                                                  'result': ('tie' if delta == 0 else 'graph-more' if delta > 0 else 'text-more') if scored else 'unscored',
                                                  'semantic_winner': None,
                                                  'note': '仅比较参考结构证据覆盖；不能据此宣布回答更准确。' if scored else
                                                          '现场自由提问没有预设参考答案，不计算覆盖得分或方法胜负。'},
                'model_calls_attempted': attempts, 'embedding_calls': 0, 'workspace_modified': False,
                'limitations': ['16 个任务来自同一个固定真实项目，由开发者整理；非用户试用、独立专家标注或留出测试集。' if scored else
                                '问题仅检索所选阶段的冻结项目材料；无预设答案，不能据此报告准确率、方法胜负或跨项目效果。',
                                '检索用时是单次本机观察；字节不是 token，实际模型输入预算以各侧返回元数据为准。',
                                '原始锁文件关系仅作可解析范围内的图事实；optional / peer 缺口不会自动消失。',
                                '两侧生成失败、回退或返回模型不同均不能作为语义优劣判断。']}
