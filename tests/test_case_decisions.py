"""Recorded decisions remain derived, bounded and separate from live scans."""
import copy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from lianzheng.case_decisions import CaseDecisions
from lianzheng.domain import InputError
from lianzheng.real_case import RealCase


ROOT=Path(__file__).resolve().parent.parent
CASE=ROOT/'fixtures/real-case/http-server-minimist'


@pytest.fixture(scope='module')
def report():
    # No service or store exists: every result must come from the frozen files.
    return CaseDecisions(RealCase(None,CASE.parent)).report()


def copied(tmp_path):
    target=tmp_path/'cases/http-server-minimist';shutil.copytree(CASE,target)
    return target,CaseDecisions(RealCase(None,target.parent))


def rewrite(path,case):
    (path/'case.json').write_text(json.dumps(case,ensure_ascii=False),encoding='utf-8')


def mutate_file(path,name,callback):
    data=json.loads((path/name).read_text(encoding='utf-8'));callback(data)
    raw=json.dumps(data,ensure_ascii=False).encode();(path/name).write_bytes(raw)
    case=json.loads((path/'case.json').read_text(encoding='utf-8'))
    next(e for e in case['files'] if e['name']==name)['sha256']=hashlib.sha256(raw).hexdigest();rewrite(path,case)


def test_actual_three_phase_counts_and_boundaries(report):
    assert [p['target_count'] for p in report['plans']]==[2,1,0]
    assert [p['test']['passing'] for p in report['plans']]==[395]*3
    assert [p['test']['modified_assertions'] for p in report['plans']]==[0,0,2]
    assert all(p['test']['pending']==1 and not p['graph_complete'] for p in report['plans'])
    assert report['model_calls']==report['network_calls']==0
    assert report['persisted'] is report['upstream_tests_rerun'] is False
    assert report['kind']=='recorded-experiment'


def test_direct_and_bundled_target_occurrences_are_not_merged(report):
    a,b=report['plans'][:2]
    assert {x['ref'] for x in a['target_occurrences']}=={'npm:node_modules/minimist','npm:node_modules/tap/node_modules/minimist'}
    remaining=b['target_occurrences'][0]
    assert remaining['dev'] is True and remaining['dependency_kind']=='transitive'
    assert remaining['locator']=='/packages/node_modules~1tap~1node_modules~1minimist'


def test_diff_counts_derive_from_exact_positions_and_include_all_changes(report):
    c=report['selected_comparison'];rows=c['changes'];counts=c['counts']
    assert counts['total_changed']==len(rows)==381
    assert counts['total_changed']==sum(counts[x] for x in ('added','removed','updated'))
    assert counts['total_changed']==sum(counts[x] for x in ('direct','transitive','unknown'))
    assert counts['version_changed']==sum('version' in r['changed_fields'] for r in rows)==123
    assert len({r['ref'] for r in rows})==len(rows)
    tap=next(r for r in rows if r['ref']=='npm:node_modules/tap')
    assert tap['before']['version']=='14.11.0' and tap['after']['version']=='16.3.10'
    assert tap['dependency_kind']=='direct' and tap['after']['dev'] is True
    assert next(r for r in rows if r['ref']=='npm:node_modules/tap/node_modules/minimist')['change']=='removed'


def test_other_advisories_remain_explicitly_unconfirmed(report):
    c=report['selected_comparison'];other=c['other_advisories']
    assert not c['coverage']['complete']
    assert other['new'] and other['retained'] and other['no_longer_observed']
    assert 'resolved' not in other and 'eliminated' not in other
    assert not (set(other['new'])&set(other['retained']))
    assert report['target']['advisory_id'] not in set(sum(other.values(),[]))


def test_failed_run_and_migration_remain_in_timeline(report):
    timeline=report['timeline'];failure=timeline[2];migration=timeline[3];final=timeline[4]
    assert failure['test']['passing']==393 and failure['test']['failing']==2
    assert failure['test']['exit_code']==1 and failure['target_count']==0
    assert failure['test']['modified_assertions']==0
    assert final['test']['passing']==395 and final['test']['modified_assertions']==2
    assert migration['started_at'] is None and migration['finished_at'] is None
    assert '未单独记录' in migration['time_note']
    assert migration['migration']['files']['patch_file']['name']=='test-api-migration.patch'
    assert all(event['recorded'] and not event['rerun'] for event in timeline)


def test_recorded_commands_times_and_hashes_are_traceable(report):
    original=json.loads((CASE/'case.json').read_text(encoding='utf-8'))
    for p in report['plans']:
        assert p['test']['started_at']==original['tests'][p['id']]['started_at']
        assert p['lockfile']['sha256']==p['test']['lockfile_sha256']
        assert p['test']['log']['sha256']==p['test']['log_sha256']
    assert report['timeline'][1]['updates'][0]['command'].find('minimist@1.2.8')>=0
    assert report['timeline'][2]['updates'][0]['command'].find('tap@16.3.10')>=0


@pytest.mark.parametrize('left,right',[('after','partial'),('partial','after'),('before','before')])
def test_user_selected_comparison_including_reverse_and_equal(left,right):
    r=CaseDecisions(RealCase(None,CASE.parent)).report(left,right)
    c=r['selected_comparison'];assert (c['from_phase'],c['to_phase'])==(left,right)
    if left==right:
        assert c['changes']==[] and c['counts']['total_changed']==0
        assert not c['other_advisories']['new'] and not c['other_advisories']['no_longer_observed']
    elif left=='after':
        minimist=next(x for x in c['changes'] if x['ref']=='npm:node_modules/tap/node_modules/minimist')
        assert minimist['change']=='added' and c['target']['after_count']==1


@pytest.mark.parametrize('left,right',[('unknown','after'),('before',''),('../after','partial'),('before',None)])
def test_invalid_phase_is_rejected(left,right):
    with pytest.raises(InputError):CaseDecisions(RealCase(None,CASE.parent)).report(left,right)


def test_missing_case_returns_unavailable_without_fake_data(tmp_path):
    r=CaseDecisions(RealCase(None,tmp_path)).report()
    assert r['available'] is False and 'plans' not in r


def test_changed_file_bytes_are_rejected(tmp_path):
    path,decisions=copied(tmp_path);(path/'partial.package-lock.json').write_text('{}',encoding='utf-8')
    with pytest.raises(InputError,match='校验失败'):decisions.report()


@pytest.mark.parametrize('field,value',[('passing',999),('pending',0),('log_sha256','0'*64),('lockfile_sha256','0'*64)])
def test_test_metadata_cannot_claim_changed_success_or_binding(tmp_path,field,value):
    path,decisions=copied(tmp_path);case=json.loads((path/'case.json').read_text(encoding='utf-8'))
    case['tests']['after'][field]=value;rewrite(path,case)
    with pytest.raises(InputError):decisions.report()


def test_original_failure_cannot_be_hidden(tmp_path):
    path,decisions=copied(tmp_path);case=json.loads((path/'case.json').read_text(encoding='utf-8'))
    case['migration_failure']['failing']=0;case['migration_failure']['exit_code']=0;rewrite(path,case)
    with pytest.raises(InputError):decisions.report()


def test_unsupported_case_cannot_reuse_fixed_narrative(tmp_path):
    path,decisions=copied(tmp_path);case=json.loads((path/'case.json').read_text(encoding='utf-8'))
    case['target']['advisory_id']='GHSA-unrelated';rewrite(path,case)
    with pytest.raises(InputError,match='仅支持固定'):decisions.report()


def test_original_source_hash_must_match_downloaded_lock(tmp_path):
    path,decisions=copied(tmp_path);case=json.loads((path/'case.json').read_text(encoding='utf-8'))
    case['source']['before_lockfile_sha256']='0'*64;rewrite(path,case)
    with pytest.raises(InputError,match='上游来源哈希'):decisions.report()


def test_command_record_disagreement_is_rejected_even_when_file_hash_is_valid(tmp_path):
    path,decisions=copied(tmp_path)
    mutate_file(path,'commands.json',lambda d:d['test_runs']['after'].update({'passing':394}))
    with pytest.raises(InputError,match='命令过程'):decisions.report()


def test_migration_cannot_link_outside_verified_files(tmp_path):
    path,decisions=copied(tmp_path)
    mutate_file(path,'migration-notes.json',lambda d:d.update({'patch_file':'../secret.txt'}))
    with pytest.raises(InputError,match='已校验案例'):decisions.report()


def test_verified_bytes_are_used_even_if_paths_change_after_verification(tmp_path,monkeypatch):
    path,decisions=copied(tmp_path);original=decisions.real_case._bundle
    def checked_then_changed():
        result=original();(path/'after.package-lock.json').write_text('{}',encoding='utf-8');return result
    monkeypatch.setattr(decisions.real_case,'_bundle',checked_then_changed)
    r=decisions.report();assert r['plans'][2]['target_count']==0 and r['plans'][2]['components']==697


def test_frozen_comparison_does_not_access_current_database_or_network(monkeypatch):
    import httpx
    def forbidden(*args,**kwargs):raise AssertionError('Unexpected external operation')
    class NoService:
        @property
        def store(self):return forbidden()
    monkeypatch.setattr(httpx.Client,'request',forbidden)
    r=CaseDecisions(RealCase(NoService(),CASE.parent)).report()
    assert r['available'] and not r['persisted']


def test_unknown_scan_and_unreachable_scope_are_retained(monkeypatch):
    real_case=RealCase(None,CASE.parent);original=real_case._plans
    def with_unknown(*args):
        plans=original(*args);p=plans[2];ref='npm:node_modules/minimist'
        p['scans'][ref]={'status':'unscanned','source':'none','data':{},'error':'missing','fetched_at':None};p['unknown']+=1
        p['graph']['edges']=[e for e in p['graph']['edges'] if e['target']!=ref]
        p['graph']['complete']=False
        return plans
    monkeypatch.setattr(real_case,'_plans',with_unknown)
    r=CaseDecisions(real_case).report();c=r['selected_comparison']
    assert c['coverage']['to_unqueried']==1 and not c['coverage']['complete']
    assert next(x for x in c['changes'] if x['ref']=='npm:node_modules/minimist')['dependency_kind']=='unknown'
