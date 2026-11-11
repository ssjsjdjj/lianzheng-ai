"""Verify frozen, public lockfile imports locally. Never install, scan, or call a model.

The default exit status checks source-file integrity, not universal importer
coverage. Unsupported projects remain visible in the report. Pass
--require-supported to fail when any input cannot be converted.
"""
import argparse
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from lianzheng.domain import InputError,parse_bom,representative_paths
from lianzheng.lockfiles import convert_package_lock,ROOT_REF


def read_project(source,root=ROOT):
    result={key:source.get(key) for key in ('repository','commit','url','path','sha256','license','license_url','license_path')}
    result.update(status='invalid-source',supported=False,source_integrity_verified=False,
                  advisory_scan_performed=False,model_calls=0,dependency_scripts_executed=False)
    try:
        path=Path(source['path']);path=path if path.is_absolute() else root/path
        license_path=Path(source.get('license_path',str(path.parent/'LICENSE')))
        license_path=license_path if license_path.is_absolute() else root/license_path
        content=path.read_bytes()
        digest=hashlib.sha256(content).hexdigest()
        result['actual_sha256']=digest
        if digest!=source.get('sha256'):raise ValueError('冻结锁文件 SHA-256 与来源清单不一致。')
        commit=source.get('commit','')
        if not re.fullmatch('[0-9a-f]{40}',commit):raise ValueError('来源清单缺少完整 commit。')
        repository=source.get('repository','')
        expected_prefix=f'https://github.com/{repository}/blob/{commit}/'
        if not str(source.get('url','')).startswith(expected_prefix):raise ValueError('锁文件来源 URL 未固定到声明的 commit。')
        if not str(source.get('license_url','')).startswith(expected_prefix):raise ValueError('许可证来源 URL 未固定到声明的 commit。')
        license_bytes=license_path.read_bytes()
        if not license_bytes.strip():raise ValueError('许可证文件为空。')
        license_sha=hashlib.sha256(license_bytes).hexdigest()
        result['license_sha256']=license_sha
        if source.get('license_sha256') and license_sha!=source['license_sha256']:
            raise ValueError('许可证 SHA-256 与来源清单不一致。')
        result['source_integrity_verified']=True
        raw=json.loads(content.decode('utf-8-sig'))
        if not isinstance(raw,dict):raise ValueError('锁文件顶层必须是 JSON 对象。')
        result['lockfile_version']=raw.get('lockfileVersion')
        result['package_entries']=len(raw.get('packages',{}))
    except (OSError,ValueError,TypeError,UnicodeError,KeyError) as error:
        result['error']=str(error)
        return result
    try:
        bom=convert_package_lock(raw)
        graph=parse_bom(bom)
    except InputError as error:
        result.update(status='unsupported',error=str(error))
        return result
    properties=bom['metadata'].get('properties',[])
    warnings=[p['value'] for p in properties if p['name']=='lianzheng:import:warning']
    refs={n['id'] for n in graph['nodes']}
    expected_refs={ROOT_REF}|{'npm:'+location for location in raw['packages'] if location}
    checks={'all_installation_positions_preserved':refs==expected_refs,
            'unique_node_ids':len(refs)==len(graph['nodes']),
            'exact_npm_identities':all(n['root'] or n['identity_error'] is None for n in graph['nodes']),
            'all_emitted_edges_reference_known_positions':all(d['ref'] in refs and all(t in refs for t in d['dependsOn']) for d in bom['dependencies'])}
    samples=[]
    for node in graph['nodes'][1:]:
        if len(samples)>=3:break
        paths=representative_paths(graph,node['id'],limit=1)['paths']
        if paths and len(paths[0])>=3:samples.append(paths[0])
    result.update(supported=True,status='supported-complete' if graph['complete'] else 'supported-incomplete',
                  components=len(graph['nodes'])-1,edges=len(graph['edges']),graph_complete=graph['complete'],
                  alias_occurrences=sum(any(p['name']=='lianzheng:npm:alias' for p in c.get('properties',[])) for c in bom['components']),
                  structure_checks=checks,structure_checks_passed=all(checks.values()),
                  import_warning_count=int(next(p['value'] for p in properties if p['name']=='lianzheng:import:warning-count')),
                  import_warnings=warnings,issue_counts=dict(Counter(i['code'] for i in graph['issues'])),sample_paths=samples)
    return result


def run(manifest,output,root=ROOT):
    sources=json.loads(manifest.read_text(encoding='utf-8'))
    if isinstance(sources,dict):sources=sources['projects']
    results=[read_project(source,root) for source in sources]
    report={'kind':'frozen-public-project-import-compatibility','generated_at':datetime.now(timezone.utc).isoformat(),
            'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),
            'project_count':len(results),'supported':sum(r['supported'] for r in results),
            'unsupported':sum(r['status']=='unsupported' for r in results),
            'invalid_sources':sum(r['status']=='invalid-source' for r in results),
            'model_calls':0,'network_calls':0,'dependency_scripts_executed':False,'independent_expert_labels':False,
            'limitations':['真实公开项目的冻结输入只验证导入结构与兼容性；不是客户试用或生产效果评测。',
                           'SHA-256 核对的是本地来源清单记录，脚本不联网重新核实上游。',
                           '未执行漏洞查询、实际安装、构建、运行时检查或语义问答；未扫描不能解释为安全。',
                           '不支持的输入保留原因，不修改原始文件来提高通过数量。',
                           '自动结构检查不替代独立专家标注，也不能证明 GraphRAG 优于其他检索方法。'],
            'results':results}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,default=ROOT/'fixtures/public-projects/sources.json')
    parser.add_argument('--root',type=Path,default=ROOT,help='Base for repository-relative paths in the source manifest')
    parser.add_argument('--output',type=Path,default=ROOT/'evaluation/public-project-results.json')
    parser.add_argument('--require-supported',action='store_true')
    args=parser.parse_args();report=run(args.manifest,args.output,args.root)
    print(json.dumps({key:report[key] for key in ('project_count','supported','unsupported','invalid_sources','model_calls')},ensure_ascii=False))
    print('Report:',args.output)
    failures=report['invalid_sources'] or any(r.get('supported') and not r.get('structure_checks_passed') for r in report['results'])
    if args.require_supported:failures=failures or report['unsupported']
    raise SystemExit(1 if failures else 0)
