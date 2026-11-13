"""Read-only, snapshot-bound paired retrieval for imported projects.

One SQLite read transaction captures every input. Downloads and answers require
that exact context hash; no mutable cache or fixed demonstration case is used.
"""
import hashlib
import json
import re
import time
from urllib.parse import quote

from .domain import InputError, parse_bom
from .knowledge import prepare_document
from .lockfiles import convert_package_lock
from .osv import evidence_documents
from .providers import validate_provider_endpoint
from .project_answer import answer_card, evidence_identity, project_brief
from .retrieval import model_explanation
from .store import now
from .task_compare import (METHODS, TaskComparison, digest, node_id,
                           rank, select_evidence, selected_paths)


class ProjectContextChanged(InputError):
    """The requested version is no longer the current snapshot context."""


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode('utf-8')


def _resolve(raw, pointer):
    value = raw
    for part in pointer.lstrip('/').split('/') if pointer else []:
        part = part.replace('~1', '/').replace('~0', '~')
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def _properties(value):
    return {item['name']: item['value'] for item in value.get('properties', [])}


def _expected(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise InputError('请先获取当前项目上下文，再提交有效的上下文校验值。')


def _question(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 1000 or len(value) > 2000:
        raise InputError('请输入 1 至 1000 字的问题。')
    if any(ord(c) < 32 and c not in '\n\r\t' for c in value):
        raise InputError('问题包含无效控制字符。')
    return value.strip()


class ProjectQuery:
    def __init__(self, service):
        self.service = service

    @staticmethod
    def protocol():
        return {**TaskComparison.protocol(), 'task_authorship': '操作者针对当前导入项目提问；无预设参考答案',
                'scope': 'snapshot', 'context_binding': 'snapshot + source + graph + scans + project documents'}

    def _capture(self, identifier):
        if not isinstance(identifier, str) or not identifier or len(identifier) > 200:
            raise InputError('项目快照标识无效。')
        # Store methods open separate connections. Do not substitute get/scans/
        # documents here: BEGIN pins one generation before the first read.
        with self.service.store.connect() as db:
            db.execute('BEGIN')
            row = db.execute('SELECT * FROM snapshots WHERE id=?', (identifier,)).fetchone()
            if row is None:
                raise KeyError('项目快照不存在。')
            snapshot = dict(row)
            scans = {r['ref']: json.loads(r['result']) for r in db.execute(
                'SELECT ref,result FROM scans WHERE snapshot_id=? ORDER BY ref', (identifier,))}
            stored_documents = [dict(r) for r in db.execute(
                'SELECT id,body FROM documents WHERE snapshot_id=? ORDER BY id', (identifier,))]
            rows = list(db.execute('SELECT id,body FROM knowledge_documents WHERE snapshot_id=? ORDER BY id', (identifier,)))
            table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lockfile_sources'").fetchone()
            lock = db.execute('SELECT source FROM lockfile_sources WHERE snapshot_id=?', (identifier,)).fetchone() if table else None
        try:
            raw = json.loads(snapshot['raw']); graph = json.loads(snapshot['graph'])
            parsed = parse_bom(raw)
            properties = _properties(raw.get('metadata', {}))
            for prop in raw.get('metadata', {}).get('properties', []):
                if prop.get('name') == 'lianzheng:import:warning':
                    parsed['issues'].append({'code': 'import_warning', 'message': prop['value'][:1500]})
            # parse_bom reports set-derived issue lists; order may differ after
            # a Python process restart without any change in graph semantics.
            def normalized(value):
                return {**value, 'issues': sorted(value['issues'], key=digest)}
            if normalized(parsed) != normalized(graph):
                raise InputError('项目依赖图与保存的清单不一致，请重新导入。')
            is_lock = properties.get('lianzheng:import:format') == 'npm-package-lock'
            if is_lock and lock is None:
                raise InputError('原始锁文件尚未保存完整，请等待导入完成后刷新。')
            origin = json.loads(lock['source']) if is_lock else raw
            if is_lock and convert_package_lock(origin) != raw:
                raise InputError('原始锁文件与当前项目清单不一致，请重新导入。')
            knowledge = []
            for row in rows:
                doc = json.loads(row['body'])
                # Rebuild every chunk from the scoped document. Stored chunk
                # URLs, IDs, ref fields and quote spans are not trusted.
                if doc.get('snapshot_id') != identifier:
                    raise InputError('项目文档的快照归属不一致，请移除后重新导入。')
                rebuilt = prepare_document(identifier, graph, doc)
                if row['id'] != rebuilt['id'] or doc.get('id') != rebuilt['id'] or doc.get('hash') != rebuilt['hash']:
                    raise InputError('项目文档内容校验失败，请移除后重新导入。')
                rebuilt['created'] = doc.get('created')
                for chunk in rebuilt['chunks']:
                    chunk['fetched_at'] = doc.get('created')
                knowledge.append(rebuilt)
        except (KeyError, TypeError, ValueError) as error:
            if isinstance(error, InputError):
                raise
            raise InputError('当前项目证据格式损坏，请重新导入。') from error
        source_bytes = _json_bytes(origin)
        fingerprint = digest({'snapshot_id': identifier, 'project': snapshot['project'], 'label': snapshot['label'],
                              'raw_source_sha256': _sha(source_bytes), 'bom': raw, 'graph': graph,
                              'scans': scans, 'stored_documents': stored_documents, 'knowledge': knowledge})
        binding = {'scope': 'snapshot', 'snapshot_id': identifier, 'context_sha256': fingerprint}
        source = {**binding, 'project': snapshot['project'], 'label': snapshot['label'],
                  'format': 'npm-package-lock' if is_lock else 'cyclonedx',
                  'filename': 'package-lock.json' if is_lock else 'snapshot.cdx.json',
                  'raw_source_sha256': _sha(source_bytes), 'source_sha256': _sha(source_bytes),
                  'basis': 'current snapshot; saved JSON serialization, not original upload bytes',
                  'serialization': '保存的 JSON 内容重新序列化；哈希校验下载字节，不代表上传文件原始字节。'}
        components = [n for n in graph['nodes'] if not n['root']]
        unknown = sum(scans.get(n['id'], {}).get('status') not in ('checked', 'demo-component') for n in components)
        coverage = {'graph_complete': graph['complete'], 'component_count': len(components),
                    'checked_components': sum(scans.get(n['id'], {}).get('status') == 'checked' for n in components),
                    'unknown_components': unknown, 'issues': graph['issues'],
                    'can_confirm_absence': False, 'knowledge_documents': len(knowledge)}
        artifacts = {'manifest': (source['filename'], source_bytes, 'application/json')}
        state = {'source': source, 'binding': binding, 'raw': raw, 'origin': origin, 'is_lock': is_lock,
                 'graph': graph, 'scans': scans, 'knowledge': knowledge, 'coverage': coverage,
                 'artifacts': artifacts, 'properties': properties}
        source['url'] = self._url(state, 'manifest')
        # Include all valid current documents in source downloads; query-specific
        # applicability still controls which chunks enter the retrieval corpus.
        for doc in knowledge:
            artifacts[doc['id']] = (doc['id'] + '.txt', doc['text'].encode(), 'text/plain; charset=utf-8')
        artifacts['scans'] = ('snapshot-scans.json', _json_bytes(scans), 'application/json')
        artifacts['coverage'] = ('snapshot-coverage.json', _json_bytes(coverage), 'application/json')
        return state

    @staticmethod
    def _url(state, source_id):
        source = state['source']
        return ('/api/snapshots/' + quote(source['snapshot_id'], safe='') + '/task-comparison/sources/' +
                quote(source_id, safe='') + '?context_sha256=' + source['context_sha256'])

    def _check(self, identifier, expected):
        _expected(expected)
        state = self._capture(identifier)
        if state['source']['context_sha256'] != expected:
            raise ProjectContextChanged('项目证据已更新，请刷新上下文后重新提问。')
        return state

    def context(self, identifier):
        state = self._capture(identifier)
        return {'available': True, 'source': state['source'], 'coverage': state['coverage'], 'brief': project_brief(state),
                'protocol': self.protocol(), 'model_configured': None, 'model_status': 'not-inspected-offline'}

    def source(self, identifier, source_id, expected_context_sha256):
        state = self._check(identifier, expected_context_sha256)
        if not isinstance(source_id, str) or source_id not in state['artifacts']:
            raise KeyError('当前项目证据源不存在。')
        return state['artifacts'][source_id]

    def _corpus(self, state, question):
        graph = state['graph']; nodes = {n['id']: n for n in graph['nodes']}
        documents = []; incoming = {}; locators = {}
        for n in graph['nodes']:
            component = _resolve(state['raw'], n['locator'])
            locators[n['id']] = (_properties(component).get('lianzheng:npm:source-pointer')
                                 if state['is_lock'] else n['locator'])
            if not locators[n['id']]:
                raise InputError('清单组件缺少可验证的原文定位。')
        declared = json.loads(state['properties'].get('lianzheng:import:relationships', '[]')) if state['is_lock'] else []
        declarations = {}
        for relation in declared:
            declarations.setdefault((relation['source'], relation.get('target')), relation)
        for edge in graph['edges']:
            pointer = edge['locator']
            if state['is_lock']:
                relation = declarations.get((edge['source'], edge['target']))
                if relation is None:
                    raise InputError('依赖关系缺少原始声明，不能生成联动路径。')
                pointer = relation['source_pointer']
            _resolve(state['origin'], pointer)  # Verify every displayed declaration pointer.
            incoming.setdefault(edge['target'], []).append({**edge, 'locator': pointer,
                'source_lock_locator': locators[edge['source']], 'target_lock_locator': locators[edge['target']],
                **state['binding']})

        def add(identifier, title, text, source_id, locator, excerpt, **extra):
            filename, data, _ = state['artifacts'][source_id]
            documents.append({'id': identifier, 'title': title, 'text': text, 'source': 'snapshot-normalized-fact',
                              'filename': filename, 'locator': locator, 'url': self._url(state, source_id),
                              'source_sha256': _sha(data), 'phase': 'snapshot', 'version': '',
                              'source_excerpt': excerpt[:1600], 'source_excerpt_truncated': len(excerpt) > 1600,
                              'source_excerpt_kind': 'saved-source-content', **extra, **state['binding'],
                              **evidence_identity(state['source']['snapshot_id'], identifier, title, text, locator, excerpt, extra)})

        for node in graph['nodes']:
            if node['root']:
                continue
            ref = node['id']; relations = sorted(incoming.get(ref, []), key=lambda e: (e['source'], e['target']))[:12]
            text = f"组件 {node['name']}@{node['version']}，清单位置 {ref}。\n" + '\n'.join(
                f"依赖关系：{nodes[e['source']]['name']}@{nodes[e['source']]['version']} [{e['source']}] → {node['name']}@{node['version']} [{ref}]。" for e in relations)
            if len(incoming.get(ref, [])) > len(relations):
                text += '\n本片段只展示前 12 条入边，完整声明见来源文件。'
            raw_excerpt = json.dumps(_resolve(state['origin'], locators[ref]), ensure_ascii=False, sort_keys=True)
            add(node_id(ref), f"{node['name']} {node['version']} 安装位置与依赖关系", text, 'manifest',
                locators[ref], raw_excerpt, kind='occurrence', ref=ref, version=node['version'], relations=relations)
            scan = state['scans'].get(ref, {'status': 'unscanned', 'source': 'none', 'data': {}, 'fetched_at': None})
            scan_pointer = '/' + ref.replace('~', '~0').replace('/', '~1')
            status_label = {'checked': '查询完成', 'unscanned': '尚未查询', 'failed': '查询失败',
                            'unsupported': '暂不支持此组件身份', 'demo-component': '演示组件，未执行真实查询'}.get(scan['status'], '未知')
            scan_text = f"组件 {node['name']}@{node['version']}，当前扫描状态：{status_label}。\n"
            scan_text += ('当前保存记录中的公告数量：' + str(len(scan.get('data', {}).get('vulns', []))) + '；零命中不等于项目安全。'
                          if scan['status'] == 'checked' else '未取得完整漏洞查询结论，不能判断无风险。')
            # Missing scan records have no original JSON location; coverage is
            # their auditable source rather than an invented /ref entry.
            if ref in state['scans']:
                add('scan-' + node_id(ref), node['name'] + ' 漏洞查询状态', scan_text, 'scans', scan_pointer,
                    json.dumps(scan, ensure_ascii=False), kind='scan', ref=ref, version=node['version'])
            if scan['status'] == 'checked' and node.get('package_name'):
                for doc in evidence_documents(state['source']['snapshot_id'], node, scan):
                    vuln_index = next(i for i, v in enumerate(scan['data'].get('vulns', [])) if v['id'] == doc['vulnerability'])
                    add('advisory-' + doc['id'], doc['title'], doc['text'], 'scans',
                        scan_pointer + '/data/vulns/' + str(vuln_index),
                        json.dumps(scan['data']['vulns'][vuln_index], ensure_ascii=False), kind='advisory',
                        ref=ref, version=node['version'], package=node['package_name'], vulnerability=doc['vulnerability'],
                        source=doc['source'], fetched_at=doc['fetched_at'])
        coverage = state['coverage']
        add('coverage', '项目覆盖、扫描未知与生产风险边界',
            f"依赖图覆盖：{'完整' if coverage['graph_complete'] else '有缺口'}；尚未完成查询的组件：{coverage['unknown_components']}。\n" +
            '\n'.join(i['message'] for i in graph['issues']) +
            '\n当前清单与查询结果不包含生产运行轨迹或实际攻击验证，不能据此宣称项目无风险或可安全上线。',
            'coverage', '', _json_bytes(coverage).decode(), kind='coverage')
        target = re.search(r'(?:升级(?:到|至)?|目标版本(?:为|是)?|target\s*[:=]?|\bto)\s*v?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?)', question, re.I)
        target = target.group(1) if target else None
        for doc in state['knowledge']:
            if doc.get('target_version') and doc['target_version'] != target:
                continue
            for chunk in doc['chunks']:
                add(chunk['id'], chunk['title'], chunk['text'], doc['id'], chunk['locator'], chunk['text'],
                    kind=doc['kind'], package=doc['package'], version=doc['version'], target_version=doc.get('target_version'),
                    source='user-document', trust=doc['trust'], line_start=chunk['line_start'],
                    column_start=chunk['column_start'], line_end=chunk['line_end'], column_end=chunk['column_end'])
        return sorted(documents, key=lambda d: d['id']), locators

    def _links(self, state, selected, paths, locators, model):
        binding = state['binding']; nodes = {n['id']: n for n in state['graph']['nodes']}
        actual = {(e['source'], e['target']) for e in state['graph']['edges']}
        edge_docs = {}; relations = {}
        for doc in selected:
            for edge in doc.get('relations', []):
                key = (edge['source'], edge['target'])
                if key in actual and doc['source_sha256'] == state['source']['raw_source_sha256']:
                    edge_docs.setdefault(key, []).append(doc['id']); relations[key] = edge
        linked = []
        common = {**binding, 'filename': state['source']['filename'], 'url': state['source']['url'],
                  'source_sha256': state['source']['raw_source_sha256']}
        for path in paths:
            pairs = list(zip(path, path[1:]))
            if len(path) < 2 or path[0] != state['graph']['root'] or not all(pair in edge_docs for pair in pairs):
                continue
            linked.append({**binding, 'id': 'path-' + digest([binding, path])[:24],
                           'label': ' → '.join(nodes[ref]['name'] + '@' + nodes[ref]['version'] for ref in path),
                           'nodes': [{**common, 'ref': ref, 'name': nodes[ref]['name'], 'version': nodes[ref]['version'],
                                      'locator': locators[ref]} for ref in path],
                           'edges': [{**common, 'source': a, 'target': b, 'evidence_ids': sorted(edge_docs[(a, b)]),
                                      'locator': relations[(a, b)]['locator'], 'source_locator': locators[a],
                                      'target_locator': locators[b]} for a, b in pairs]})
        def fact(identifier, text, ids, kind):
            return {**binding, 'id': identifier, 'text': text, 'evidence_ids': ids, 'kind': kind,
                    'path_ids': [p['id'] for p in linked if any(set(ids).intersection(e['evidence_ids']) for e in p['edges'])]}
        facts = [fact('fact-' + digest([binding, d['id']])[:24],
                      next((line for line in d['text'].splitlines() if line.strip()), d['text']),
                      [d['id']], 'retrieved-fact') for d in selected]
        lookup = {d['id']: d for d in selected}
        for index, claim in enumerate((model or {}).get('claims', [])):
            if not isinstance(claim, dict) or not isinstance(claim.get('text'), str) or not claim['text'].strip():
                continue
            quotes = claim.get('quotes')
            if not isinstance(quotes, list) or not quotes or not all(
                isinstance(q, dict) and isinstance(q.get('evidence_id'), str) and q['evidence_id'] in lookup and
                isinstance(q.get('quote'), str) and q['quote'].strip() and q['quote'] in lookup[q['evidence_id']]['text'] for q in quotes):
                continue
            facts.append(fact('claim-' + digest([binding, index, claim])[:24], claim['text'],
                              list(dict.fromkeys(q['evidence_id'] for q in quotes)), 'model-claim'))
        return {'paths': linked, 'facts': facts, 'source': state['source'], 'semantic_support': 'pending-human-review',
                'note': '联动只表示本侧材料中的引用和已声明依赖关系。规范化摘要不是原文逐字引用；语义是否支持结论仍需人工复核。'}

    def ask(self, identifier, question, expected_context_sha256, use_model=False):
        question = _question(question)
        if type(use_model) is not bool:
            raise InputError('模型选项必须为布尔值。')
        state = self._check(identifier, expected_context_sha256)
        documents, locators = self._corpus(state, question)
        config = None
        if use_model:
            config = dict(self.service.models.current())
            _, local = validate_provider_endpoint(config.get('base_url', ''), config.get('provider'))
            if not config.get('model') or not (config.get('api_key') or local):
                raise InputError('尚未配置可用模型；可先运行离线证据对照。')
        columns = []; attempts = 0
        identifiers = {d['id']: 'ev-' + digest([state['binding'], d['id']])[:32] for d in documents}
        public_documents = [{**d, 'id': identifiers[d['id']]} for d in documents]
        graph = state['graph']; nodes = {n['id']: n for n in graph['nodes']}
        for method in METHODS:
            started = time.perf_counter()
            ranked = rank(question, documents, graph, method)
            selected, used = select_evidence([identifiers[i] for i in ranked], public_documents)
            paths = selected_paths(question, selected, graph)
            # Rank with stable internal IDs; namespaced public IDs are never shared
            # by two snapshots, including identical package refs and versions.
            readable = [' → '.join(nodes[r]['name'] + '@' + nodes[r]['version'] + ' [' + r + ']' for r in path) for path in paths]
            answer = ('本侧检索到 ' + str(len(selected)) + ' 份当前项目证据。\n' +
                      '\n'.join(str(i + 1) + '. ' + d['text'].splitlines()[0] for i, d in enumerate(selected[:3])) +
                      '\n结论范围以所列证据为限；未查询或缺失关系仍为未知。' if selected else
                      '未检索到适用片段，当前方法不能回答；不等于项目不存在风险或证据。')
            connected = sorted({p[-1] for p in paths})
            column = {'id': method, 'method': method, 'generation': 'offline-evidence', 'answer': answer,
                      'evidence': selected, 'paths': readable, 'model': None, 'warning': None,
                      'metrics': {'retrieved': len(selected), 'reference_found': None, 'reference_total': None,
                                  'reference_coverage': None, 'expected_evidence_ids': [], 'missing_evidence_ids': [],
                                  'retrieval_ms': round((time.perf_counter() - started) * 1000, 3), 'evidence_bytes': used,
                                  'semantic_support': 'pending-human-review', 'semantic_accuracy': None,
                                  'connected_representative_paths': len(paths), 'connected_target_occurrences': len(connected),
                                  'connected_target_refs': connected, 'connected_target_package': '问题所指组件',
                                  'connected_target_scope': '仅计本侧已取回明确关系连通的目标位置，不是全图路径或受影响位置数。'}}
            if use_model:
                self._check(identifier, expected_context_sha256)
                evidence = [{key: d[key] for key in ('id', 'title', 'text', 'version', 'source', 'locator')} for d in selected]
                for d, full in zip(evidence, selected):
                    d.update(state['binding']); d['target_version'] = full.get('target_version') or d['version'] or None
                model_context = {'facts': {'insufficient': not bool(selected), 'fixed_versions': [], 'target_version': None,
                                          'graph_complete': graph['complete'], 'scope': 'retrieved evidence only', **state['binding']},
                                 'evidence': evidence, 'paths': readable, 'conversation': [],
                                 'limitations': ['只使用本侧当前快照材料，不得引用其他项目或固定演示案例。',
                                                 '未知扫描、未声明依赖和缺失版本依据均不能当作无风险或推荐升级的证据。',
                                                 '文档为导入者声明，尚未验证真实性；本次没有运行项目测试。']}
                attempts += 1
                result, warning = model_explanation(question, model_context, config=config, usage_guard=self.service.call_control)
                column.update(model=result, warning=str(warning) if warning else None,
                              attempt_metadata=getattr(warning, 'metadata', None),
                              generation='model-assisted' if result else 'model-fallback')
                if result:
                    column['answer'] = result['text']
            column['evidence_links'] = self._links(state, selected, paths, locators, column['model'])
            column['answer_card'] = answer_card(state, question, column)
            columns.append(column)
        # A long model call may overlap a rescan or document edit. Never publish
        # that old answer as if it described the current project generation.
        self._check(identifier, expected_context_sha256)
        model_names = [((c.get('model') or {}).get('metadata') or {}).get('returned_model') for c in columns]
        return {'release': '0.11.0', 'generated_at': now(), 'source': state['source'], 'coverage': state['coverage'],
                'task': {'id': 'question-' + digest([state['binding'], question])[:24], 'question': question,
                         'phase': 'snapshot', 'kind': 'project-question', 'category': '当前项目自由提问'},
                'fairness': {**self.protocol(), 'corpus_sha256': digest(documents), 'candidate_documents': len(documents),
                             'reference_scored': False, 'same_raw_materials': True, 'same_candidate_corpus': True,
                             'same_requested_model': True, 'requested_model': config.get('model') if config else None,
                             'returned_models': model_names, 'model_pair_comparable':
                             (all(c['generation'] == 'model-assisted' for c in columns) and all(model_names) and model_names[0] == model_names[1]) if use_model else None},
                'columns': columns, 'comparison': {'metric': None, 'graph_minus_text': None, 'result': 'unscored',
                                                 'semantic_winner': None, 'note': '自由提问没有参考答案，不计算准确率或方法胜负。'},
                'model_calls_attempted': attempts, 'embedding_calls': 0, 'workspace_modified': False,
                'limitations': ['证据仅属于所选快照及该上下文版本；重扫或改动文档后须重新提问。',
                                '路径只使用清单明确声明且本侧取回的关系；缺失边不补造。',
                                '没有当前项目的运行时攻击验证或测试执行，未知不等于无风险。',
                                '模型摘录与来源联动不等于语义支持已通过审核；需人工复核。']}
