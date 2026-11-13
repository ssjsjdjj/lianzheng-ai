"""Frozen multi-project retrieval evaluation. No model, network, or main database.

References are read only AFTER retrieval and never passed to the ranker. An exit
failure means source/protocol failure, not a low retrieval score. Misses remain
visible. All answer correctness and semantic support fields require human review.
"""
import argparse
from contextlib import ExitStack
import hashlib
from html import escape
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from lianzheng.project_query import ProjectContextChanged, ProjectQuery
from lianzheng.service import Service
from lianzheng.store import now
from lianzheng.task_compare import EVIDENCE_BYTES, K, METHODS


def checked_file(root, relative, expected):
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Source path escapes fixture root')
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('Frozen source hash mismatch: ' + relative)
    return data


def load_fixture(path=ROOT / 'fixtures/project-questions.json', root=ROOT):
    fixture = json.loads(path.read_bytes())
    projects = fixture['projects']
    if len(projects) != 3 or [p['split'] for p in projects] != ['dev', 'validation', 'validation']:
        raise ValueError('Expected one development and two validation projects')
    if len({p['source']['repository'] for p in projects}) != 3:
        raise ValueError('Project splits overlap')
    ids = [t['id'] for p in projects for t in p['tasks']]
    if len(ids) != 24 or len(set(ids)) != 24 or any(len(p['tasks']) != 8 for p in projects):
        raise ValueError('Expected 24 unique questions')
    for project in projects:
        source = project['source']
        checked_file(root, source['path'], source['sha256'])
        checked_file(root, source['license_path'], source['license_sha256'])
    return fixture


def matches(reference, document):
    # Only frozen source identity fields; no generated ID or answer-text matching.
    return all(document.get(key) == value for key, value in reference.items())


def score_references(references, evidence):
    found = [ref for ref in references if any(matches(ref, doc) for doc in evidence)]
    return {'found': len(found), 'total': len(references),
            'coverage': len(found) / len(references) if references else None,
            'missing': [ref for ref in references if ref not in found]}


def protocol_checks(result, snapshot_id, context_hash, graph):
    actual_edges = {(e['source'], e['target']) for e in graph['edges']}
    source = result['source']
    checks = {'context_bound': source['snapshot_id'] == snapshot_id and source['context_sha256'] == context_hash,
              'no_model_calls': result['model_calls_attempted'] == 0,
              'two_methods': [c['id'] for c in result['columns']] == list(METHODS)}
    for column in result['columns']:
        prefix = column['id'] + ':'
        docs = column['evidence']; ids = {d['id'] for d in docs}
        checks[prefix+'budget'] = len(docs) <= K and column['metrics']['evidence_bytes'] <= EVIDENCE_BYTES
        checks[prefix+'evidence_binding'] = all(
            d['snapshot_id'] == snapshot_id and d['context_sha256'] == context_hash for d in docs)
        card = column['answer_card']
        checks[prefix+'card_citations'] = all(set(item['evidence_ids']) <= ids for item in
            [card['conclusion'], *card['reasons'], *card['unknowns'], *card['next_steps']])
        paths = column['evidence_links']['paths']
        by_id={d['id']:d for d in docs}
        checks[prefix+'actual_edges'] = all((e['source'], e['target']) in actual_edges and
            bool(e['evidence_ids']) and set(e['evidence_ids']) <= ids and all(
                any(r['source']==e['source'] and r['target']==e['target'] and r['locator']==e['locator']
                    for r in by_id[identifier].get('relations',[])) for identifier in e['evidence_ids'])
            for path in paths for e in path['edges'])
        trace = column.get('retrieval_trace')
        checks[prefix+'trace_selected'] = bool(trace) and trace.get('selected_evidence_ids') == [d['id'] for d in docs]
        checks[prefix+'trace_binding'] = bool(trace) and trace.get('snapshot_id') == snapshot_id and trace.get('context_sha256') == context_hash
    return checks


def _blocked(*args, **kwargs):
    raise AssertionError('Evaluation attempted external HTTP or private model settings')


def frozen(value):
    """Discard temporary local URLs; frozen source paths remain in project metadata."""
    if isinstance(value,dict):
        return {key:frozen(item) for key,item in value.items() if key!='url'}
    if isinstance(value,list):
        return [frozen(item) for item in value]
    return value


def evaluate(fixture, root=ROOT, split='all'):
    import httpx
    import urllib.request
    rows = []; workflow = []; project_rows = []
    with tempfile.TemporaryDirectory(prefix='lianzheng-project-eval-') as folder, ExitStack() as stack:
        stack.enter_context(patch.object(httpx.Client, 'request', _blocked))
        stack.enter_context(patch.object(httpx.AsyncClient, 'request', _blocked))
        stack.enter_context(patch.object(urllib.request, 'urlopen', _blocked))
        service = Service(Path(folder) / 'isolated.sqlite3', root / 'fixtures')
        stack.enter_context(patch.object(service.models, 'current', _blocked))
        query = ProjectQuery(service)
        previous_ids = set()
        for project in fixture['projects']:
            if split != 'all' and project['split'] != split:
                continue
            source = project['source']
            raw = json.loads(checked_file(root, source['path'], source['sha256']))
            imported = service.import_lockfile(raw, project=source['repository'], label='Frozen evaluation input')
            identifier = imported['snapshot']['id']
            ctx = query.context(identifier); graph = service.store.get(identifier)['graph']
            project_rows.append({'id':project['id'], 'split':project['split'], 'source':source,
                                 'coverage':ctx['coverage'], 'supplement_origin':'synthetic evaluation requirement, not upstream testimony'})
            project_evidence_ids = set()
            for task in project['tasks']:
                baseline = None
                if task['supplement']:
                    before_hash = ctx['source']['context_sha256']
                    baseline = query.ask(identifier, task['question'], before_hash, use_model=False)
                    service.import_document(identifier, task['supplement'])
                    ctx = query.context(identifier)
                    try:
                        query.ask(identifier, task['question'], before_hash, use_model=False)
                        rejected = False
                    except ProjectContextChanged:
                        rejected = True
                    workflow.append({'project_id':project['id'], 'check':'old-context-rejected-after-supplement', 'passed':rejected})
                result = query.ask(identifier, task['question'], ctx['source']['context_sha256'], use_model=False)
                checks = protocol_checks(result, identifier, ctx['source']['context_sha256'], graph)
                columns = []
                for column in result['columns']:
                    evidence = column['evidence']
                    project_evidence_ids.update(d['id'] for d in evidence)
                    # This is the first use of task references; they never enter ask().
                    score = score_references(task['references'], evidence)
                    columns.append({'method':column['id'], 'reference_evidence':score,
                                    'evidence_bytes':column['metrics']['evidence_bytes'],
                                    'retrieval_ms':column['metrics']['retrieval_ms'],
                                    'selected':[ {k:d.get(k) for k in ('id','stable_key','kind','ref','source','title','locator','source_sha256','content_sha256','source_excerpt','source_excerpt_kind','source_excerpt_truncated')} for d in evidence],
                                    'answer_card':column['answer_card'],
                                    'connected_paths':frozen(column['evidence_links']['paths']),
                                    'semantic_correctness':None, 'citation_semantic_support':None,
                                    'human_review':{'status':'pending','reviewer':None,'note':None}})
                if baseline:
                    old = {d['stable_key'] for col in baseline['columns'] for d in col['evidence']}
                    new = {d['stable_key'] for col in result['columns'] for d in col['evidence']}
                    workflow.append({'project_id':project['id'], 'check':'supplement-context-changed',
                                     'passed':baseline['source']['context_sha256'] != result['source']['context_sha256'],
                                     'added_selected_items':len(new-old), 'no_longer_selected_items':len(old-new),
                                     'meaning':'selection-set difference; not causal or semantic answer improvement'})
                rows.append({'id':task['id'], 'project_id':project['id'], 'split':project['split'],
                             'type':task['type'], 'question':task['question'], 'references':task['references'],
                             'source':frozen(result['source']), 'protocol_checks':checks, 'columns':columns})
            workflow.append({'project_id':project['id'], 'check':'no-selected-evidence-id-shared-between-projects',
                             'passed':not bool(previous_ids & project_evidence_ids)})
            previous_ids.update(project_evidence_ids)
    summaries=[]
    for group in ('dev','validation'):
        for method in METHODS:
            scores=[col['reference_evidence'] for row in rows if row['split']==group for col in row['columns'] if col['method']==method]
            if not scores:continue
            total=sum(s['total'] for s in scores); found=sum(s['found'] for s in scores)
            summaries.append({'split':group, 'method':method, 'question_count':len(scores),
                              'scored_questions':sum(s['total']>0 for s in scores),
                              'reference_found':found, 'reference_total':total,
                              'micro_reference_coverage':found/total if total else None,
                              'answer_accuracy':None,'semantic_support':None})
    checks=[v for row in rows for v in row['protocol_checks'].values()]+[r['passed'] for r in workflow]
    return {'release':'0.12.0','generated_at':now(),'kind':'project-separated-offline-retrieval-evaluation',
            'question_count':len(rows),'project_count':len(project_rows),'split':split,
            'model_calls':0,'network_calls':0,'dependency_scripts_executed':False,
            'passed':sum(checks),'total':len(checks),
            'limitations':fixture['limitations']+[
                '自动通过数仅表示协议与隔离检查，不是答案准确率。',
                '在临时数据库运行；导出已移除临时来源链接，复核请使用 projects.source 内的冻结文件路径和固定提交链接。',
                '两侧共享候选语料和路径后处理，只比较 BM25 与 BM25 加图优先排序。',
                '引用覆盖不等于语义支持；路径合法不等于覆盖全部依赖，真实模型问答未运行。'],
            'projects':project_rows,'summary':summaries,'workflow_checks':workflow,'results':rows}


def render_html(report):
    e=lambda value:escape(str(value),quote=True)
    percent=lambda n:'不计分' if n is None else f'{n:.1%}'
    summary=''.join(f"<tr><td>{e(r['split'])}</td><td>{e(r['method'])}</td><td>{r['scored_questions']}/{r['question_count']}</td><td>{r['reference_found']}/{r['reference_total']}</td><td>{percent(r['micro_reference_coverage'])}</td></tr>" for r in report['summary'])
    tasks=[]
    for row in report['results']:
        cols=[]
        for col in row['columns']:
            score=col['reference_evidence']
            docs=''.join(f"<li><b>{e(d['title'])}</b><br><code>{e(d['locator'])}</code><br><small>{e(d['source_sha256'])}</small></li>" for d in col['selected'])
            cols.append(f"<section><h3>{e(col['method'])}</h3><p>参考证据 {score['found']}/{score['total']} · {percent(score['coverage'])}</p><p>{e(col['answer_card']['conclusion']['text'])}</p><details><summary>未命中参考与已选证据</summary><pre>{e(json.dumps(score['missing'],ensure_ascii=False,indent=2))}</pre><ul>{docs}</ul></details></section>")
        tasks.append(f"<article><h2>{e(row['id'])} · {e(row['question'])}</h2><p>{e(row['split'])} · {e(row['project_id'])} · 语义正确性与引用支持：待人工复核</p><div class='cols'>{''.join(cols)}</div></article>")
    limitations=''.join('<li>'+e(t)+'</li>' for t in report['limitations'])
    return f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>链证 AI · 多项目问答评测</title><style>body{{font:16px/1.65 system-ui,sans-serif;background:#f4f7fa;color:#173044;margin:auto;max-width:1200px;padding:28px}}h1{{font-size:32px}}article,.intro{{background:white;border:1px solid #d7e2ea;border-radius:16px;padding:24px;margin:20px 0}}h2{{font-size:19px}}.cols{{display:grid;grid-template-columns:1fr 1fr;gap:24px}}section{{min-width:0}}pre,code,small{{overflow-wrap:anywhere;white-space:pre-wrap}}table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;padding:12px;border-bottom:1px solid #ddd}}a{{color:#176e74}}@media(max-width:720px){{.cols{{grid-template-columns:1fr}}body{{padding:12px}}table{{font-size:12px}}}}</style><main><a href="/">← 返回工作台</a><h1>多项目问答评测 · v0.12</h1><p>{report['project_count']} 个冻结项目 · {report['question_count']} 个问题 · {report['model_calls']} 次模型调用</p><div class="intro"><h2>先看评测边界</h2><ul>{limitations}</ul><p>协议检查 {report['passed']}/{report['total']}；答案准确率与引用语义支持暂不评分。</p><a href="/api/project-evaluation/report">下载完整 JSON 与人工复核空栏</a></div><table><thead><tr><th>数据分组</th><th>方法</th><th>有参考问题</th><th>命中/参考</th><th>微平均覆盖</th></tr></thead><tbody>{summary}</tbody></table>{''.join(tasks)}</main></html>"""


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--split',choices=('dev','validation','all'),default='all')
    parser.add_argument('--output',type=Path,default=ROOT/'evaluation/project-question-results.json')
    args=parser.parse_args(); path=ROOT/'fixtures/project-questions.json'
    report=evaluate(load_fixture(path),split=args.split)
    report['fixture_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    args.output.with_suffix('.html').write_text(render_html(report),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('question_count','project_count','passed','total','summary')},ensure_ascii=False))
    return 0 if report['passed']==report['total'] else 1


if __name__=='__main__':
    raise SystemExit(main())
