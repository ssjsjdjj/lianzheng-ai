import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from lianzheng.app import ROOT, create_app
from lianzheng.domain import InputError
from lianzheng.real_case import RealCase
from lianzheng.service import Service

TARGET='GHSA-29mw-wpgm-hmr9'


def write_bundle(tmp_path):
    folder=tmp_path/'cases'/'test-fixture';folder.mkdir(parents=True)
    def lock(version):
        return {'name':'case-test-fixture','version':'1.0.0','lockfileVersion':3,'packages':{
            '':{'name':'case-test-fixture','version':'1.0.0','dependencies':{'lodash':'^4.17.20'}},
            'node_modules/lodash':{'version':version,'resolved':f'https://registry.npmjs.org/lodash/-/lodash-{version}.tgz'}}}
    blobs={'before.json':lock('4.17.20'),'after.json':lock('4.17.21'),
           'osv.json':{'fetched_at':'2026-01-01T00:00:00Z','records':{
               'npm:lodash:4.17.20':{'vulns':[{'id':TARGET,'summary':'Test fixture only','details':'Synthetic API fixture','affected':[]}]},
               'npm:lodash:4.17.21':{'vulns':[]}}},'test-log.txt':'Synthetic API test fixture, not a real upstream run.'}
    files=[]
    for name,value in blobs.items():
        raw=(json.dumps(value) if not isinstance(value,str) else value).encode()
        (folder/name).write_bytes(raw);files.append({'name':name,'label':name,'sha256':hashlib.sha256(raw).hexdigest()})
    case={'id':'test-fixture','title':'Explicit synthetic API fixture','project':'API fixture',
          'source':{'url':'https://example.test/source','commit':'a'*40,'license':'test-only'},
          'target':{'advisory_id':TARGET,'package':'lodash','before_version':'4.17.20','after_version':'4.17.21'},
          'before_lockfile':'before.json','after_lockfile':'after.json','osv_snapshot':'osv.json',
          'tests':{'before':{'command':'synthetic-fixture','exit_code':0,'summary':'Fixture only','log_file':'test-log.txt'},
                   'after':{'command':'synthetic-fixture','exit_code':0,'summary':'Fixture only','log_file':'test-log.txt'}},
          'limitations':['Synthetic test input, not real project validation.'],'files':files}
    (folder/'case.json').write_text(json.dumps(case),encoding='utf-8')
    return folder.parent,folder


def update_bundle_file(folder,name,value):
    path=folder/name
    raw=value if isinstance(value,bytes) else json.dumps(value).encode('utf-8')
    path.write_bytes(raw)
    manifest=folder/'case.json';definition=json.loads(manifest.read_text(encoding='utf-8'))
    existing=next((entry for entry in definition['files'] if entry['name']==name),None)
    if existing:existing['sha256']=hashlib.sha256(raw).hexdigest()
    else:definition['files'].append({'name':name,'label':name,'sha256':hashlib.sha256(raw).hexdigest()})
    manifest.write_text(json.dumps(definition),encoding='utf-8')
    return definition


def test_case_preparation_preserves_originals_and_never_mutates_existing_scans(tmp_path):
    directory,folder=write_bundle(tmp_path)
    service=Service(tmp_path/'db.sqlite3',ROOT/'fixtures');case=RealCase(service,directory)
    assert not case.status()['prepared'] and service.store.list()==[]
    first=case.prepare();second=case.prepare()
    assert first['before_snapshot_id']==second['before_snapshot_id'] and len(service.store.list())==2
    assert first['verification']['target_before_count']==1 and first['verification']['target_after_count']==0
    assert first['current']['basis_matches_recorded'] is True
    for item in service.store.list():assert not item['demo']
    with service.store.connect() as db:
        raw=json.loads(db.execute('SELECT source FROM lockfile_sources WHERE snapshot_id=?',(first['before_snapshot_id'],)).fetchone()['source'])
    assert raw==json.loads((folder/'before.json').read_text())
    service.store.save_scans(first['before_snapshot_id'],{},[])
    changed=case.prepare()
    assert changed['current']['basis_matches_recorded'] is False
    assert service.store.scans(first['before_snapshot_id'])=={}
    assert changed['verification']['target_before_count']==1


def test_case_hash_failure_prevents_any_import_or_download(tmp_path):
    directory,folder=write_bundle(tmp_path);service=Service(tmp_path/'db.sqlite3',ROOT/'fixtures');case=RealCase(service,directory)
    (folder/'test-log.txt').write_text('Modified after manifest was written')
    with pytest.raises(InputError,match='校验失败'):case.prepare()
    with pytest.raises(InputError):case.file('before.json')
    assert service.store.list()==[]


@pytest.mark.parametrize('name',['../secret','/absolute','C:/secret','a\\b','a/../b'])
def test_case_download_rejects_path_escape(tmp_path,name):
    directory,folder=write_bundle(tmp_path);case=RealCase(Service(tmp_path/'db.sqlite3',ROOT/'fixtures'),directory)
    with pytest.raises(InputError):case.file(name)


def test_case_prepare_rolls_back_both_snapshots_on_conflict(tmp_path):
    directory,folder=write_bundle(tmp_path);service=Service(tmp_path/'db.sqlite3',ROOT/'fixtures');case=RealCase(service,directory)
    definition,files,digest,_=case._bundle();plans=case._plans(definition,files,digest)
    service.import_bom(json.loads((ROOT/'fixtures/before.cdx.json').read_text(encoding='utf-8')),identifier=plans[-1]['id'])
    with pytest.raises(InputError,match='冲突'):case.prepare()
    assert len(service.store.list())==1
    with pytest.raises(KeyError):service.store.get(plans[0]['id'])


def test_case_partial_phase_is_imported_and_counted_without_overwriting_scans(tmp_path):
    directory,folder=write_bundle(tmp_path)
    definition=update_bundle_file(folder,'partial.json',(folder/'before.json').read_bytes())
    definition['partial_lockfile']='partial.json'
    definition['tests']['partial']={'command':'synthetic partial fixture','exit_code':0,'log_file':'test-log.txt'}
    (folder/'case.json').write_text(json.dumps(definition),encoding='utf-8')
    service=Service(tmp_path/'db.sqlite3',ROOT/'fixtures');case=RealCase(service,directory)
    initial=case.status();assert initial['verification']['target_partial_count']==1
    prepared=case.prepare();assert len(service.store.list())==3 and prepared['partial_snapshot_id']
    assert prepared['verification']['target_before_count']==1 and prepared['verification']['target_after_count']==0
    service.store.save_scans(prepared['partial_snapshot_id'],{},[])
    repeated=case.prepare()
    assert service.store.scans(prepared['partial_snapshot_id'])=={}
    assert repeated['current']['basis_matches_recorded'] is False


def test_case_unlisted_partial_file_is_rejected_before_any_write_or_download(tmp_path):
    directory,folder=write_bundle(tmp_path)
    manifest=folder/'case.json';definition=json.loads(manifest.read_text(encoding='utf-8'))
    definition['partial_lockfile']='not-listed.json';manifest.write_text(json.dumps(definition),encoding='utf-8')
    service=Service(tmp_path/'db.sqlite3',ROOT/'fixtures');case=RealCase(service,directory)
    with pytest.raises(InputError):case.status()
    with pytest.raises(InputError):case.prepare()
    with pytest.raises(InputError):case.file_bytes('before.json')
    assert service.store.list()==[]


def test_case_plan_uses_exact_bytes_already_hashed_instead_of_reopening_path(tmp_path):
    directory,folder=write_bundle(tmp_path)
    case=RealCase(Service(tmp_path/'db.sqlite3',ROOT/'fixtures'),directory)
    definition,files,digest,_=case._bundle()
    (folder/'before.json').write_text('{"modified_after_verification":true}',encoding='utf-8')
    plans=case._plans(definition,files,digest)
    assert plans[0]['raw_lockfile']['packages']['node_modules/lodash']['version']=='4.17.20'
    assert plans[0]['target_count']==1


@pytest.mark.parametrize('name',['before.json','case.json'])
def test_case_download_bytes_are_the_same_bytes_checked_by_bundle(tmp_path,monkeypatch,name):
    directory,folder=write_bundle(tmp_path)
    case=RealCase(Service(tmp_path/'db.sqlite3',ROOT/'fixtures'),directory)
    original=(folder/name).read_bytes();read_bundle=case._bundle
    def changed_after_validation():
        result=read_bundle()
        (folder/name).write_bytes(b'changed after validation')
        return result
    monkeypatch.setattr(case,'_bundle',changed_after_validation)
    filename,payload=case.file_bytes(name)
    assert filename==name and payload==original


@pytest.mark.parametrize('value',[None,[],{}, {'files':[]}])
def test_malformed_case_manifest_does_not_look_like_an_uninstalled_case(tmp_path,value):
    directory,folder=write_bundle(tmp_path)
    (folder/'case.json').write_text(json.dumps(value),encoding='utf-8')
    case=RealCase(Service(tmp_path/'db.sqlite3',ROOT/'fixtures'),directory)
    with pytest.raises(InputError):case.status()


def test_case_evidence_invalid_json_is_rejected_atomically(tmp_path):
    directory,folder=write_bundle(tmp_path);update_bundle_file(folder,'after.json',b'not valid JSON')
    service=Service(tmp_path/'db.sqlite3',ROOT/'fixtures');case=RealCase(service,directory)
    with pytest.raises(InputError,match='JSON'):case.prepare()
    assert service.store.list()==[]


def test_case_file_case_collisions_and_control_characters_are_rejected(tmp_path):
    directory,folder=write_bundle(tmp_path);case=RealCase(Service(tmp_path/'db.sqlite3',ROOT/'fixtures'),directory)
    for name in ('bad\x00name','line\nname','tab\tname','bad\x7fname','before.json.','before.json ','folder /before.json'):
        with pytest.raises(InputError):case.file_bytes(name)
    definition=json.loads((folder/'case.json').read_text(encoding='utf-8'))
    definition['files'].append({**definition['files'][0],'name':definition['files'][0]['name'].upper()})
    (folder/'case.json').write_text(json.dumps(definition),encoding='utf-8')
    with pytest.raises(InputError,match='重复'):case.prepare()


@pytest.mark.parametrize('vulns',[[{}],[{'id':TARGET},{'id':TARGET}],[{'id':['invalid']}],[None]])
def test_invalid_frozen_vulnerability_identity_is_rejected_before_import(tmp_path,vulns):
    directory,folder=write_bundle(tmp_path)
    frozen=json.loads((folder/'osv.json').read_text(encoding='utf-8'))
    frozen['records']['npm:lodash:4.17.20']={'vulns':vulns};update_bundle_file(folder,'osv.json',frozen)
    service=Service(tmp_path/'db.sqlite3',ROOT/'fixtures');case=RealCase(service,directory)
    with pytest.raises(InputError,match='公告标识'):case.prepare()
    assert service.store.list()==[]


def test_incomplete_osv_page_is_unknown_instead_of_a_zero_risk_success(tmp_path):
    directory,folder=write_bundle(tmp_path)
    frozen=json.loads((folder/'osv.json').read_text(encoding='utf-8'))
    frozen['records']['npm:lodash:4.17.21']={'vulns':[],'next_page_token':'more-data'}
    update_bundle_file(folder,'osv.json',frozen)
    case=RealCase(Service(tmp_path/'db.sqlite3',ROOT/'fixtures'),directory)
    result=case.prepare()
    assert result['verification']['after_unknown']==1 and result['verification']['comparison_complete'] is False


def test_partial_case_import_rolls_back_all_new_phases_on_late_conflict(tmp_path):
    directory,folder=write_bundle(tmp_path)
    definition=update_bundle_file(folder,'partial.json',(folder/'before.json').read_bytes())
    definition['partial_lockfile']='partial.json';(folder/'case.json').write_text(json.dumps(definition),encoding='utf-8')
    service=Service(tmp_path/'db.sqlite3',ROOT/'fixtures');case=RealCase(service,directory)
    definition,files,digest,_=case._bundle();plans=case._plans(definition,files,digest)
    service.import_bom(json.loads((ROOT/'fixtures/before.cdx.json').read_text(encoding='utf-8')),identifier=plans[-1]['id'])
    existing_scans=service.store.scans(plans[-1]['id'])
    with pytest.raises(InputError,match='冲突'):case.prepare()
    assert len(service.store.list())==1 and service.store.scans(plans[-1]['id'])==existing_scans
    for plan in plans[:-1]:
        with pytest.raises(KeyError):service.store.get(plan['id'])


def test_case_api_uses_allowlisted_files_and_origin_guard(tmp_path,monkeypatch):
    directory,folder=write_bundle(tmp_path)
    monkeypatch.setattr('lianzheng.app.RealCase',lambda service,unused:RealCase(service,directory))
    with TestClient(create_app(tmp_path/'db.sqlite3')) as client:
        assert client.get('/api/real-case').json()['prepared'] is False
        assert client.post('/api/real-case/prepare',headers={'Origin':'https://foreign.invalid'}).status_code==403
        result=client.post('/api/real-case/prepare').json()
        assert result['prepared'] is True
        response=client.get('/api/real-case/files/before.json')
        assert response.status_code==200 and 'attachment' in response.headers['content-disposition']
        assert client.get('/api/real-case/files/model-settings.json').status_code==404
        assert client.get('/api/snapshots/'+result['before_snapshot_id']+'/lockfile').json()==response.json()


def test_simulation_route_is_read_only_and_validates_scope(tmp_path):
    app=create_app(tmp_path/'db.sqlite3');service=app.state.service
    before=service.store.get('demo-before');scans=service.store.scans('demo-before');history=service.store.history('demo-before')
    with TestClient(app) as client:
        path='/api/snapshots/demo-before/simulation'
        result=client.post(path,json={'focus':TARGET,'selected_refs':[]})
        assert result.status_code==200 and result.json()['kind']=='hypothetical'
        refs=[x['ref'] for x in result.json()['occurrences']]
        result=client.post(path,json={'focus':TARGET,'selected_refs':refs})
        assert result.status_code==200 and result.json()['counts']['remaining']==0
        assert client.post(path,json={'focus':'missing','selected_refs':[]}).status_code==400
        assert client.post(path,json={'focus':TARGET,'selected_refs':['not-a-target']}).status_code==400
        assert client.post(path,json={'focus':TARGET,'selected_refs':[1]}).status_code==422
        assert client.post(path,json={'focus':TARGET,'selected_refs':[]},headers={'Origin':'https://foreign.invalid'}).status_code==403
    assert service.store.get('demo-before')==before
    assert service.store.scans('demo-before')==scans and service.store.history('demo-before')==history
    assert service.call_control.public()['calls_today']==0
