import copy
import json

import pytest

from lianzheng.domain import InputError,parse_bom,representative_paths
from lianzheng.lockfiles import convert_package_lock,ROOT_REF


def lock(packages=None,version=3):
    return {'name':'fixture-app','version':'1.0.0','lockfileVersion':version,
            'packages':{'':{'name':'fixture-app','version':'1.0.0','dependencies':{'adapter':'^2.0.0'}},
                        'node_modules/adapter':{'version':'2.0.0','dependencies':{'shared':'^1.0.0'}},
                        'node_modules/shared':{'version':'1.2.3'},**(packages or {})}}


def edges(bom):
    return {(e['source'],e['target']) for e in parse_bom(bom)['edges']}


def properties(bom,name):
    return [p['value'] for p in bom['metadata']['properties'] if p['name']==name]


@pytest.mark.parametrize('version',[2,3])
def test_root_dependencies_and_hoisting_are_distinct_from_all_packages(version):
    raw=lock(version=version);before=copy.deepcopy(raw)
    bom=convert_package_lock(raw)
    assert raw==before
    assert edges(bom)=={(ROOT_REF,'npm:node_modules/adapter'),
                        ('npm:node_modules/adapter','npm:node_modules/shared')}
    graph=parse_bom(bom)
    assert graph['complete'] and not graph['issues']
    assert graph['nodes'][1]['package_name']=='adapter'
    assert representative_paths(graph,'npm:node_modules/shared')['paths']==[[ROOT_REF,'npm:node_modules/adapter','npm:node_modules/shared']]


def test_nested_versions_are_resolved_by_installation_location():
    raw=lock({'node_modules/adapter/node_modules/shared':{'version':'1.0.1'},
              'node_modules/other':{'version':'3.0.0','dependencies':{'shared':'1.2.3'}}})
    raw['packages']['']['dependencies']['other']='3.0.0'
    bom=convert_package_lock(raw)
    assert ('npm:node_modules/adapter','npm:node_modules/adapter/node_modules/shared') in edges(bom)
    assert ('npm:node_modules/other','npm:node_modules/shared') in edges(bom)
    assert ('npm:node_modules/adapter','npm:node_modules/shared') not in edges(bom)
    assert len([n for n in parse_bom(bom)['nodes'] if n['name']=='shared'])==2


def test_same_version_at_two_locations_is_not_merged():
    raw=lock({'node_modules/adapter/node_modules/shared':{'version':'1.2.3'}})
    raw['packages']['']['dependencies']['shared']='1.2.3'
    graph=parse_bom(convert_package_lock(raw))
    assert len([n for n in graph['nodes'] if n['name']=='shared' and n['version']=='1.2.3'])==2
    assert graph['complete']


def test_scoped_paths_purls_and_original_pointers_are_preserved():
    raw={'name':'scoped-app','lockfileVersion':3,'packages':{
        '':{'name':'scoped-app','dependencies':{'@scope/adapter':'2.0.0'}},
        'node_modules/@scope/adapter':{'name':'@scope/adapter','version':'2.0.0','dependencies':{'@other/util':'1.2.3'}},
        'node_modules/@other/util':{'version':'1.2.3'}}}
    bom=convert_package_lock(raw);graph=parse_bom(bom)
    assert graph['complete'] and all(n['identity_error'] is None for n in graph['nodes'])
    util=next(n for n in graph['nodes'] if n['name']=='@other/util')
    assert util['purl']=='pkg:npm/%40other/util@1.2.3'
    relations=json.loads(properties(bom,'lianzheng:import:relationships')[0])
    assert any(r['source_pointer']=='/packages/node_modules~1@scope~1adapter/dependencies/@other~1util' for r in relations)


def test_missing_optional_dev_and_required_records_remain_explicitly_incomplete():
    raw=lock()
    raw['packages']['']['optionalDependencies']={'platform-addon':'^1.0.0'}
    raw['packages']['']['devDependencies']={'test-tool':'^1.0.0'}
    raw['packages']['node_modules/adapter']['dependencies']['missing-runtime']='1.0.0'
    bom=convert_package_lock(raw)
    assert len(properties(bom,'lianzheng:import:warning'))==3
    assert properties(bom,'lianzheng:import:warning-count')==['3']
    assert not parse_bom(bom)['complete']
    assert len(parse_bom(bom)['nodes'])==3
    assert all('missing' not in target and 'test-tool' not in target and 'platform-addon' not in target for _,target in edges(bom))


def test_flags_and_root_dev_dependencies_are_retained_without_runtime_claims():
    raw=lock({'node_modules/devtool':{'version':'1.0.0','dev':True},
              'node_modules/platform-addon':{'version':'2.0.0','optional':True,'devOptional':True}})
    raw['packages']['']['devDependencies']={'devtool':'1.0.0'}
    raw['packages']['']['optionalDependencies']={'platform-addon':'2.0.0'}
    raw['packages']['node_modules/adapter']['devDependencies']={'not-installed-for-consumers':'1.0.0'}
    bom=convert_package_lock(raw)
    assert (ROOT_REF,'npm:node_modules/devtool') in edges(bom)
    addon=next(c for c in bom['components'] if c['name']=='platform-addon')
    assert addon['scope']=='optional'
    assert {'name':'lianzheng:npm:devOptional','value':'true'} in addon['properties']
    assert parse_bom(bom)['complete']


def test_optional_declaration_overrides_regular_dependency_and_is_deduplicated():
    raw=lock()
    raw['packages']['']['optionalDependencies']={'adapter':'2.0.0'}
    raw['packages']['']['devDependencies']={'adapter':'2.0.0'}
    bom=convert_package_lock(raw)
    relations=json.loads(properties(bom,'lianzheng:import:relationships')[0])
    root_relations=[r for r in relations if r['source']==ROOT_REF]
    assert len(root_relations)==1 and root_relations[0]['kind']=='optionalDependencies'


def test_peer_resolution_uses_sibling_or_ancestor_and_not_private_nested_copy():
    raw=lock({'node_modules/peer':{'version':'1.0.0'},
              'node_modules/adapter/node_modules/peer':{'version':'2.0.0'}})
    raw['packages']['']['dependencies']['peer']='1.0.0'
    raw['packages']['node_modules/adapter']['peerDependencies']={'peer':'^1.0.0'}
    bom=convert_package_lock(raw)
    assert ('npm:node_modules/adapter','npm:node_modules/peer') in edges(bom)
    assert ('npm:node_modules/adapter','npm:node_modules/adapter/node_modules/peer') not in edges(bom)
    assert not parse_bom(bom)['complete']  # The unrelated private record is visibly unreachable.


def test_absent_optional_peer_is_reported_without_a_fake_node():
    raw=lock()
    raw['packages']['node_modules/adapter']['peerDependencies']={'optional-peer':'*'}
    raw['packages']['node_modules/adapter']['peerDependenciesMeta']={'optional-peer':{'optional':True}}
    bom=convert_package_lock(raw)
    relation=next(r for r in json.loads(properties(bom,'lianzheng:import:relationships')[0]) if r['dependency']=='optional-peer')
    assert relation['optional'] and relation['target'] is None
    assert not parse_bom(bom)['complete']


@pytest.mark.parametrize('location',['../evil','/node_modules/a','C:/node_modules/a','node_modules/../a',
                                    'node_modules/a\\b','node_modules/a/../../b','node_modules/@scope',
                                    'node_modules/a/','node_modules/a/node_modules/..','packages/workspace',
                                    'node_modules/a\u0000b'])
def test_unsafe_and_workspace_locations_are_rejected(location):
    raw=lock({location:{'version':'1.0.0'}})
    with pytest.raises(InputError):convert_package_lock(raw)


@pytest.mark.parametrize('version',[1,4,'3',True,None])
def test_unsupported_lockfile_version_is_actionable(version):
    with pytest.raises(InputError,match='v2/v3'):convert_package_lock(lock(version=version))


@pytest.mark.parametrize('version',['^1.0.0','latest','git+ssh://example/x','file:../x','1.2','01.2.3','1.2.3-01',1,None])
def test_package_identity_requires_exact_semver(version):
    raw=lock();raw['packages']['node_modules/shared']['version']=version
    with pytest.raises(InputError,match='精确'):convert_package_lock(raw)


@pytest.mark.parametrize('spec',['npm:real-package@1.0.0','file:../local','workspace:*','link:../a','git+ssh://host/repo',
                               'https://token@host/package.tgz',None,{},'', 'x\n injected'])
def test_unsupported_dependency_identity_never_becomes_a_guessed_registry_package(spec):
    raw=lock();raw['packages']['']['dependencies']['adapter']=spec
    with pytest.raises(InputError):convert_package_lock(raw)


def test_alias_workspace_and_link_records_are_rejected():
    raw=lock();raw['packages']['node_modules/adapter']['name']='real-adapter'
    with pytest.raises(InputError,match='别名'):convert_package_lock(raw)
    raw=lock();raw['packages']['node_modules/adapter']['link']=True
    with pytest.raises(InputError,match='link'):convert_package_lock(raw)
    raw=lock();raw['packages']['']['workspaces']=['packages/*']
    with pytest.raises(InputError,match='workspace'):convert_package_lock(raw)


def test_explicit_alias_keeps_install_position_and_uses_real_registry_identity():
    raw=lock({'node_modules/old-util':{'name':'@actual/util','version':'1.2.3'}})
    raw['packages']['']['dependencies']['old-util']='npm:@actual/util@^1.2.0'
    bom=convert_package_lock(raw);graph=parse_bom(bom)
    node=next(n for n in graph['nodes'] if n['id']=='npm:node_modules/old-util')
    assert node['name']=='@actual/util' and node['package_name']=='@actual/util'
    assert node['purl']=='pkg:npm/%40actual/util@1.2.3'
    assert (ROOT_REF,node['id']) in edges(bom)
    component=next(c for c in bom['components'] if c['bom-ref']==node['id'])
    assert {'name':'lianzheng:npm:alias','value':'old-util'} in component['properties']
    relation=next(r for r in json.loads(properties(bom,'lianzheng:import:relationships')[0]) if r['dependency']=='old-util')
    assert relation['alias_target']=='@actual/util' and relation['declared_spec']=='npm:@actual/util@^1.2.0'


def test_alias_resolves_scoped_install_names_and_multiple_consistent_parents():
    raw=lock({'node_modules/@test/react-18':{'name':'react','version':'18.3.1'}})
    raw['packages']['']['dependencies']['@test/react-18']='npm:react@^18.0.0'
    raw['packages']['node_modules/adapter']['dependencies']['@test/react-18']='npm:react@18.3.1'
    bom=convert_package_lock(raw)
    assert (ROOT_REF,'npm:node_modules/@test/react-18') in edges(bom)
    assert ('npm:node_modules/adapter','npm:node_modules/@test/react-18') in edges(bom)
    assert parse_bom(bom)['complete']


@pytest.mark.parametrize('descriptor_name',[None,'not-the-declared-target'])
def test_alias_requires_matching_explicit_descriptor_name(descriptor_name):
    raw=lock({'node_modules/alias':{'version':'1.2.3'}})
    if descriptor_name is not None:raw['packages']['node_modules/alias']['name']=descriptor_name
    raw['packages']['']['dependencies']['alias']='npm:real-name@1.2.3'
    with pytest.raises(InputError,match='显式 name'):convert_package_lock(raw)


def test_alias_conflicting_declarations_are_rejected():
    raw=lock({'node_modules/alias':{'name':'real-name','version':'1.2.3'}})
    raw['packages']['']['dependencies']['alias']='npm:real-name@1.2.3'
    raw['packages']['node_modules/adapter']['dependencies']['alias']='npm:different-name@1.2.3'
    with pytest.raises(InputError,match='显式 name'):convert_package_lock(raw)
    raw['packages']['node_modules/adapter']['dependencies']['alias']='1.2.3'
    with pytest.raises(InputError,match='冲突'):convert_package_lock(raw)


@pytest.mark.parametrize('spec',['npm:real-name','npm:@scope/pkg','npm:real-name@','npm:../../evil@1.0.0',
                               'npm:real-name@file:../local','npm:npm:other@1.0.0'])
def test_ambiguous_alias_specifications_remain_unsupported(spec):
    raw=lock();raw['packages']['']['dependencies']['adapter']=spec
    with pytest.raises(InputError,match='别名'):convert_package_lock(raw)


def test_two_nested_alias_locations_may_have_different_explicit_identities():
    raw=lock({'node_modules/alias':{'name':'first-real','version':'1.2.3'},
              'node_modules/adapter/node_modules/alias':{'name':'second-real','version':'2.0.0'}})
    raw['packages']['']['dependencies']['alias']='npm:first-real@1.2.3'
    raw['packages']['node_modules/adapter']['dependencies']['alias']='npm:second-real@2.0.0'
    graph=parse_bom(convert_package_lock(raw))
    assert graph['complete']
    assert {n['name'] for n in graph['nodes'] if n['id'].endswith('/alias')}=={'first-real','second-real'}


def test_registry_package_workspace_metadata_does_not_declare_project_workspaces():
    raw=lock();raw['packages']['node_modules/adapter']['workspaces']=['docs','tests/*']
    bom=convert_package_lock(raw)
    assert parse_bom(bom)['complete'] and len(bom['components'])==2
    assert 'workspaces' not in json.dumps(bom)


@pytest.mark.parametrize('change',[
    lambda r:r.update(packages=[]),lambda r:r['packages'].pop(''),
    lambda r:r['packages'].update({'node_modules/invalid':None}),
    lambda r:r['packages'][''].update(dependencies=[]),
    lambda r:r['packages']['node_modules/adapter'].update(dev='true'),
    lambda r:r['packages']['node_modules/adapter'].update(peerDependenciesMeta={'peer':{'optional':'yes'}}),
    lambda r:r['packages'][''].update(version=0),lambda r:r.update(version='9.0.0'),
])
def test_malformed_maps_flags_and_root_identity_are_input_errors(change):
    raw=lock();change(raw)
    with pytest.raises(InputError):convert_package_lock(raw)


def test_limits_bound_packages_declarations_paths_and_input_size(monkeypatch):
    monkeypatch.setattr('lianzheng.lockfiles.MAX_PACKAGES',2)
    with pytest.raises(InputError,match='安装位置'):convert_package_lock(lock())
    monkeypatch.setattr('lianzheng.lockfiles.MAX_PACKAGES',10000)
    monkeypatch.setattr('lianzheng.lockfiles.MAX_DECLARATIONS',1)
    with pytest.raises(InputError,match='依赖声明'):convert_package_lock(lock())
    monkeypatch.setattr('lianzheng.lockfiles.MAX_DECLARATIONS',50000)
    monkeypatch.setattr('lianzheng.lockfiles.MAX_INPUT_BYTES',100)
    with pytest.raises(InputError,match='5 MB'):convert_package_lock(lock())


def test_deep_paths_and_non_json_payloads_are_rejected():
    raw=lock({'/'.join(['node_modules/a']*31):{'version':'1.0.0'}})
    with pytest.raises(InputError,match='层'):convert_package_lock(raw)
    raw=lock();raw['cycle']=raw
    with pytest.raises(InputError,match='JSON'):convert_package_lock(raw)


def test_unreferenced_installed_packages_are_not_promoted_to_direct_dependencies():
    bom=convert_package_lock(lock({'node_modules/orphan':{'version':'1.0.0'}}))
    assert (ROOT_REF,'npm:node_modules/orphan') not in edges(bom)
    assert any(i['code']=='unreachable' for i in parse_bom(bom)['issues'])


def test_v2_legacy_tree_and_scripts_are_not_used_or_copied():
    raw=lock(version=2);raw['dependencies']={'invented':{'version':'9.9.9'}}
    raw['packages']['node_modules/adapter']['scripts']={'postinstall':'do-not-execute-this'}
    raw['packages']['node_modules/adapter']['resolved']='https://secret:password@registry.example/adapter.tgz'
    result=json.dumps(convert_package_lock(raw))
    assert 'invented' not in result and 'do-not-execute-this' not in result and 'password' not in result


def test_warning_output_is_bounded_but_full_missing_relationships_are_retained():
    raw=lock();raw['packages']['']['optionalDependencies']={f'missing-{i}':'1.0.0' for i in range(120)}
    bom=convert_package_lock(raw)
    assert properties(bom,'lianzheng:import:warning-count')==['120']
    assert len(properties(bom,'lianzheng:import:warning'))==101
    missing=[r for r in json.loads(properties(bom,'lianzheng:import:relationships')[0]) if r['target'] is None]
    assert len(missing)==120


def _public_verifier():
    import importlib.util
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('public_project_verifier',Path(__file__).resolve().parent.parent/'scripts/verify_public_projects.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_public_project_report_checks_integrity_and_keeps_unsupported_reason(tmp_path):
    import hashlib
    verifier=_public_verifier();source=tmp_path/'package-lock.json';license_file=tmp_path/'LICENSE'
    source.write_text(json.dumps(lock(version=1)),encoding='utf-8');license_file.write_text('Test license fixture',encoding='utf-8')
    commit='a'*40
    manifest={'repository':'fixture/project','commit':commit,'path':str(source),'license_path':str(license_file),
              'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'url':f'https://github.com/fixture/project/blob/{commit}/package-lock.json',
              'license_url':f'https://github.com/fixture/project/blob/{commit}/LICENSE'}
    result=verifier.read_project(manifest)
    assert result['status']=='unsupported' and result['source_integrity_verified']
    assert 'v2/v3' in result['error'] and not result['supported'] and result['model_calls']==0
    source.write_text(json.dumps(lock()),encoding='utf-8')
    assert verifier.read_project(manifest)['status']=='invalid-source'


def test_frozen_public_inputs_keep_all_occurrences_and_expose_missing_peers():
    from pathlib import Path
    verifier=_public_verifier();root=Path(__file__).resolve().parent.parent
    manifest=json.loads((root/'fixtures/public-projects/sources.json').read_text(encoding='utf-8'))
    for source in manifest:
        result=verifier.read_project(source)
        assert result['source_integrity_verified'] and result['supported']
        assert result['structure_checks_passed'] and result['alias_occurrences']>0
        assert result['status']=='supported-incomplete' and result['import_warning_count']>0
        assert not result['advisory_scan_performed'] and not result['dependency_scripts_executed']
