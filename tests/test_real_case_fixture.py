"""Check the case evidence contract, not claimed runtime exploitability."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import pytest

ROOT=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('verify_real_case',ROOT/'scripts/verify_real_case.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
CASE=ROOT/'fixtures/real-case/http-server-minimist'


def copied(tmp_path):
    target=tmp_path/'case';shutil.copytree(CASE,target);return target


def write_manifest(path,case):
    (path/'case.json').write_text(json.dumps(case,ensure_ascii=False,indent=2),encoding='utf-8')


def replace_artifact(path,name,value):
    (path/name).write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
    case=json.loads((path/'case.json').read_text(encoding='utf-8'))
    next(e for e in case['files'] if e['name']==name)['sha256']=hashlib.sha256((path/name).read_bytes()).hexdigest()
    write_manifest(path,case)


def test_real_case_observations_and_test_migration_are_transparent():
    report=module.verify_case(CASE)
    assert [x['target_count'] for x in report['stages']]==[2,1,0]
    assert [x['tests']['passing'] for x in report['stages']]==[395]*3
    assert [x['tests']['pending'] for x in report['stages']]==[1]*3
    assert [x['tests']['modified_assertions'] for x in report['stages']]==[0,0,2]
    assert all(not x['graph_complete'] for x in report['stages'])
    assert report['network_calls']==0 and report['upstream_tests_rerun'] is False
    assert report['frozen_query_count']==731 and report['failed_query_count']==0
    assert report['stages'][0]['target_occurrences'][0]['dev'] is False
    assert report['stages'][1]['target_occurrences'][0]['dev'] is True


def test_original_lock_is_the_pinned_upstream_bytes():
    assert hashlib.sha256((CASE/'before.package-lock.json').read_bytes()).hexdigest()=='c2c49899baad1056455227f90108caa8bf358da24719e9074f6e77b32754c398'


def test_reject_changed_artifact_bytes(tmp_path):
    path=copied(tmp_path);(path/'after.package-lock.json').write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError,match='Hash mismatch'):module.verify_case(path)


@pytest.mark.parametrize('name',['../outside.json','C:/secret.json','..\\outside.json','/absolute.json'])
def test_reject_path_escape_before_reading(tmp_path,name):
    with pytest.raises(ValueError):module.checked_path(tmp_path,name)


def test_unknown_query_cannot_be_treated_as_zero_target_hits(tmp_path):
    path=copied(tmp_path);snapshot=json.loads((path/'osv-snapshot.json').read_text(encoding='utf-8'))
    snapshot['records'].pop('npm:minimist:1.2.8')
    replace_artifact(path,'osv-snapshot.json',snapshot)
    with pytest.raises(ValueError,match='coverage is incomplete'):module.verify_case(path)


def test_changed_target_count_is_not_a_valid_record(tmp_path):
    path=copied(tmp_path);case=json.loads((path/'case.json').read_text(encoding='utf-8'))
    case['expected_target_occurrences']['partial']=0;write_manifest(path,case)
    with pytest.raises(ValueError,match='observation count'):module.verify_case(path)


def test_cannot_hide_upstream_platform_skip(tmp_path):
    path=copied(tmp_path);case=json.loads((path/'case.json').read_text(encoding='utf-8'))
    case['tests']['after']['pending']=0;write_manifest(path,case)
    with pytest.raises(ValueError,match='log summary'):module.verify_case(path)


def test_cannot_omit_test_api_migration_disclosure(tmp_path):
    path=copied(tmp_path);case=json.loads((path/'case.json').read_text(encoding='utf-8'))
    case['tests']['after']['modified_assertions']=0;write_manifest(path,case)
    with pytest.raises(ValueError,match='not disclosed'):module.verify_case(path)


def test_cannot_claim_success_for_the_migration_failure(tmp_path):
    path=copied(tmp_path);case=json.loads((path/'case.json').read_text(encoding='utf-8'))
    case['migration_failure']['exit_code']=0;write_manifest(path,case)
    with pytest.raises(ValueError,match='failure evidence'):module.verify_case(path)


def test_failure_run_hash_must_match_its_artifact(tmp_path):
    path=copied(tmp_path);case=json.loads((path/'case.json').read_text(encoding='utf-8'))
    case['migration_failure']['log_sha256']='0'*64;write_manifest(path,case)
    with pytest.raises(ValueError,match='failure does not bind'):module.verify_case(path)
