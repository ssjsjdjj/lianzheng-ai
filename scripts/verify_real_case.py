"""Verify the recorded real-case artifacts offline; do not rerun upstream code.

The recorded install/test/OSV collection used network access. This verifier only
checks bundled hashes, frozen query coverage, target observations and test logs.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys

ROOT=Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from lianzheng.domain import parse_bom
from lianzheng.lockfiles import convert_package_lock


def sha(data):return hashlib.sha256(data).hexdigest()


def checked_path(directory,name):
    if not isinstance(name,str) or not name or '\\' in name or ':' in name:
        raise ValueError('Invalid case artifact path')
    relative=PurePosixPath(name)
    if relative.is_absolute() or '..' in relative.parts or str(relative)!=name:
        raise ValueError('Case artifact escapes its directory')
    path=directory/name
    if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):
        raise ValueError('Missing or linked case artifact: '+name)
    return path


def verify_case(directory):
    directory=Path(directory);manifest_path=checked_path(directory,'case.json')
    manifest_bytes=manifest_path.read_bytes();case=json.loads(manifest_bytes)
    entries=case['files'];names=[entry['name'] for entry in entries]
    if len(set(names))!=len(names) or 'case.json' in names:raise ValueError('Duplicate/self-referencing case manifest')
    verified_contents={}
    for entry in entries:
        raw=checked_path(directory,entry['name']).read_bytes()
        if sha(raw)!=entry['sha256']:raise ValueError('Hash mismatch: '+entry['name'])
        verified_contents[entry['name']]=raw
    def data(name):
        if name not in verified_contents:raise ValueError('Unlisted case artifact: '+name)
        return verified_contents[name]
    scans=json.loads(data(case['osv_snapshot']));records=scans['records']
    errors=scans.get('errors',{});target=case['target']['advisory_id']
    if set(records)&set(errors):raise ValueError('Query cannot be both successful and failed')
    stages=[];query_keys=set()
    for stage in ('before','partial','after'):
        lockfile=case[stage+'_lockfile'];lock_raw=data(lockfile);lock=json.loads(lock_raw)
        bom=convert_package_lock(lock);graph=parse_bom(bom)
        observed=[];unknown=[]
        for component in bom['components']:
            key=f"npm:{component['name']}:{component['version']}";query_keys.add(key)
            if key not in records:
                unknown.append(component['bom-ref']);continue
            record=records[key]
            if not isinstance(record,dict) or not isinstance(record.get('vulns'),list):
                raise ValueError('Malformed frozen query: '+key)
            matches=[v for v in record['vulns'] if v.get('id')==target and not v.get('withdrawn')]
            if matches:
                loc=component['bom-ref'].removeprefix('npm:')
                observed.append({'ref':component['bom-ref'],'package':component['name'],'version':component['version'],
                                 'dev':bool(lock['packages'].get(loc,{}).get('dev'))})
        if unknown:raise ValueError(f'{stage}: frozen query coverage is incomplete')
        if len(observed)!=case['expected_target_occurrences'][stage]:
            raise ValueError(f'{stage}: target observation count differs from the record')
        run=case['tests'][stage];log=data(run['log_file']).decode('utf-8')
        if run['log_sha256']!=sha(data(run['log_file'])) or run['lockfile_sha256']!=sha(lock_raw):
            raise ValueError(f'{stage}: test run does not bind to its log and lockfile')
        if run['exit_code']!=0 or run['failing']!=0 or run['passing']<1:
            raise ValueError(f'{stage}: successful upstream test run not recorded')
        passed=re.search(r'\b(\d+) passing \(',log);pending=re.search(r'\b(\d+) pending\b',log)
        if not passed or not pending or int(passed.group(1))!=run['passing'] or int(pending.group(1))!=run['pending']:
            raise ValueError(f'{stage}: log summary does not match test metadata')
        if re.search(r'\b[1-9]\d* failing\b',log):raise ValueError(f'{stage}: failing test points in success log')
        if run['test_files']!=31 or '--jobs=1' not in run['command'] or run['environment'].get('TZ')!='UTC0':
            raise ValueError(f'{stage}: recorded test environment changed')
        stages.append({'stage':stage,'component_occurrences':len(bom['components']),'dependency_edges':len(graph['edges']),
                       'graph_complete':graph['complete'],'import_warnings':sum(p['name']=='lianzheng:import:warning' for p in bom['metadata']['properties']),
                       'target_occurrences':observed,'target_count':len(observed),'unqueried_occurrences':len(unknown),
                       'tests':{'exit_code':run['exit_code'],'passing':run['passing'],'pending':run['pending'],'test_files':run['test_files'],
                                'modified_assertions':run['modified_assertions'],'command':run['command'],'log_file':run['log_file']}})
    if not query_keys.issubset(set(records)|set(errors)) or len(query_keys)!=scans['unique_package_versions']:
        raise ValueError('Frozen query union differs from the three lockfiles')
    original=data('before.main.test.js').decode('utf-8');migrated=data('after.main.test.js').decode('utf-8')
    expected=original
    for text in ('./file','./canYouSeeMe'):
        old=f"t.includes(res.body, '{text}');"
        new=f"t.ok(res.body.includes('{text}'), 'directory listing includes {text}');"
        if expected.count(old)!=1:raise ValueError('Unexpected original assertion')
        expected=expected.replace(old,new)
    if expected!=migrated:raise ValueError('Test API migration includes other source changes')
    if case['tests']['after']['modified_assertions']!=2:raise ValueError('Test API migration not disclosed')
    failure=case['migration_failure'];failure_log=data(failure['log_file']).decode('utf-8')
    if failure['log_sha256']!=sha(data(failure['log_file'])) or failure['lockfile_sha256']!=sha(data(case['after_lockfile'])):
        raise ValueError('Original migration failure does not bind to its log and lockfile')
    if failure['exit_code']==0 or failure['failing']!=2 or not re.search(r'\b2 failing\b',failure_log):
        raise ValueError('Original migration failure evidence is missing')
    if sha(data(case['before_lockfile']))!=case['source']['before_lockfile_sha256']:
        raise ValueError('Original source lockfile hash changed')
    source_files=json.loads(data('source-files.json'))
    if set(source_files['modified_upstream_files'])!={'package.json','package-lock.json','test/main.test.js'}:
        raise ValueError('Unexpected upstream source modification scope')
    return {'release':'0.7.0','case_id':case['id'],'verification':'offline artifact consistency and frozen target observations',
            'artifact_checks_passed':True,'case_manifest_sha256':sha(manifest_bytes),'verified_file_count':len(entries),
            'source_commit':case['source']['commit'],'target_advisory':target,'stages':stages,
            'frozen_query_count':len(records),'failed_query_count':len(errors),'collection_window':scans['collection_window'],
            'model_calls':0,'network_calls':0,'upstream_tests_rerun':False,
            'recorded_upstream_test_runs':3,'recorded_upstream_tests_passed':True,
            'scope':'This verifier did not install dependencies, rerun upstream tests, or query current OSV. The recorded experiment did perform real npm installations, tests and OSV network requests. Import incompleteness and other vulnerabilities remain outside a target-only absence observation.',
            'limitations':case['limitations']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case-dir',type=Path,default=ROOT/'fixtures/real-case/http-server-minimist')
    parser.add_argument('--output',type=Path,default=ROOT/'evaluation/real-case-results.json')
    parser.add_argument('--require-passed',action='store_true',help='Compatibility flag; any failed verification already exits nonzero.')
    args=parser.parse_args()
    try:result=verify_case(args.case_dir)
    except (ValueError,KeyError,TypeError,OSError) as exc:
        print(f'Real case verification failed: {exc}',file=sys.stderr);return 1
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'case_id':result['case_id'],'files_verified':result['verified_file_count'],
                      'target_observations':[s['target_count'] for s in result['stages']],
                      'recorded_tests':[s['tests']['passing'] for s in result['stages']],
                      'network_calls_this_check':0}))
    return 0


if __name__=='__main__':raise SystemExit(main())
