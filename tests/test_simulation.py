import copy
from pathlib import Path

import pytest

from lianzheng.domain import InputError
from lianzheng.service import Service
from lianzheng.simulation import RepairSimulation, MAX_SELECTED, MAX_PATHS, MAX_PATH_TARGETS


ROOT=Path(__file__).resolve().parent.parent
TARGET='GHSA-29mw-wpgm-hmr9'


@pytest.fixture
def sim(tmp_path):
    service=Service(tmp_path/'simulation.sqlite3', ROOT/'fixtures')
    service.seed()
    return RepairSimulation(service)


def make_bom(components, edges):
    refs=['root']+[item['bom-ref'] for item in components]
    return {'bomFormat':'CycloneDX','specVersion':'1.6',
            'metadata':{'component':{'bom-ref':'root','name':'推演边界测试','version':'1'}},
            'components':components,
            'dependencies':[{'ref':ref,'dependsOn':[target for source,target in edges if source==ref]} for ref in refs]}


def lodash(ref, version='4.17.20'):
    return {'bom-ref':ref,'name':'lodash','version':version,'purl':'pkg:npm/lodash@'+version}


def demo_component(ref):
    return {'bom-ref':ref,'group':'@demo','name':ref,'version':'1','purl':'pkg:npm/@demo/'+ref+'@1'}


def import_test(sim, bom, identifier='case'):
    return sim.service.import_bom(bom,identifier=identifier,project='边界测试',demo=True)


def dump_database(service):
    with service.store.connect() as db:return '\n'.join(db.iterdump())


def test_preview_counts_exact_occurrences_and_does_not_claim_actual_repair(sim):
    result=sim.preview('demo-before',TARGET,[])
    assert result['kind']=='hypothetical' and result['persisted'] is False
    assert result['counts']=={'known_affected':2,'assumed_handled':0,'remaining':2,
                             'remaining_reachable':2,'remaining_unreachable':0}
    assert {o['ref'] for o in result['occurrences']}=={'lodash-report','lodash-export'}
    assert {o['version'] for o in result['occurrences']}=={'4.17.20'}
    assert result['model_calls']==0 and len(result['paths'])==2
    assert '假设' in result['conclusion'] and '预览' in result['conclusion']
    assert '实际修复' in ' '.join(result['limitations'])
    assert not any(key in result for key in ('verified','resolved','new_snapshot','fixed_version'))


def test_one_selected_position_leaves_other_path_and_all_select_is_only_preview(sim):
    one=sim.preview('demo-before',TARGET,['lodash-report'])
    assert one['counts']['assumed_handled']==1 and one['counts']['remaining']==1
    assert next(o for o in one['occurrences'] if o['ref']=='lodash-export')['selected'] is False
    assert next(p for p in one['paths'] if p['target_ref']=='lodash-export')['selected'] is False
    both=sim.preview('demo-before',TARGET,['lodash-report','lodash-export'])
    assert both['counts']['remaining']==0 and all(p['selected'] for p in both['paths'])
    assert '已知清单' in both['conclusion'] and '假设' in both['conclusion']
    assert sim.service.analyze('demo-before')['stats']['affected_occurrences']==2


def test_preview_is_read_only_and_never_calls_model_or_scanner(sim, monkeypatch):
    before=dump_database(sim.service)
    def unexpected(*args,**kwargs):raise AssertionError('Preview performed an external or mutable operation')
    monkeypatch.setattr(sim.service,'ask',unexpected)
    monkeypatch.setattr(sim.service.osv,'query',unexpected)
    monkeypatch.setattr(sim.service.store,'add_snapshot',unexpected)
    for refs in ([],['lodash-export'],['lodash-export','lodash-report'],[]):
        sim.preview('demo-before',TARGET,refs)
    assert dump_database(sim.service)==before


def test_scope_never_silently_falls_back_to_service_default_advisory(sim):
    with pytest.raises(InputError,match='没有该公告'):
        sim.preview('demo-before','CVE-2099-NOT-PRESENT',[])
    with pytest.raises(InputError,match='没有该公告'):
        sim.preview('demo-resolved',TARGET,[])


@pytest.mark.parametrize('refs',[
    ['root'],['shop-app'],['report-kit'],['absent'],['lodash-report','absent'],
    ['lodash-report','lodash-report'],[None],[True],[2],[{}],[''],
])
def test_invalid_or_non_target_occurrence_rejected(sim, refs):
    with pytest.raises(InputError):sim.preview('demo-before',TARGET,refs)


@pytest.mark.parametrize('refs',[None,{},'lodash-report',('lodash-report',),False])
def test_selection_requires_array(sim, refs):
    with pytest.raises(InputError):sim.preview('demo-before',TARGET,refs)


@pytest.mark.parametrize('focus',[None,'',True,{},'a'*201])
def test_invalid_focus_rejected(sim, focus):
    with pytest.raises(InputError):sim.preview('demo-before',focus,[])


def test_selection_limit_rejected_before_reading_snapshot(sim, monkeypatch):
    def unexpected(*args,**kwargs):raise AssertionError('Should reject input before reading graph')
    monkeypatch.setattr(sim.service,'analyze',unexpected)
    with pytest.raises(InputError,match='最多选择'):
        sim.preview('demo-before',TARGET,[str(i) for i in range(MAX_SELECTED+1)])


def test_missing_snapshot_remains_not_found(sim):
    with pytest.raises(KeyError):sim.preview('not-found',TARGET,[])


def test_returned_paths_only_use_original_edges_and_preserve_locators(sim):
    analysis=sim.service.analyze('demo-before')
    edges={(e['source'],e['target']):e['locator'] for e in analysis['edges']}
    for path in sim.preview('demo-before',TARGET,['lodash-report'])['paths']:
        refs=[n['ref'] for n in path['nodes']]
        assert refs[0]==analysis['root'] and refs[-1]==path['target_ref']
        assert path['edge_locators']==[edges[a,b] for a,b in zip(refs,refs[1:])]
        assert all(n['locator'] for n in path['nodes'])


def test_selecting_upstream_affected_position_does_not_remove_downstream_hit_or_edge(sim):
    import_test(sim,make_bom([lodash('upstream'),lodash('downstream')],
                            [('root','upstream'),('upstream','downstream')]))
    result=sim.preview('case',TARGET,['upstream'])
    assert result['counts']['remaining']==result['counts']['remaining_reachable']==1
    downstream=next(p for p in result['paths'] if p['target_ref']=='downstream')
    assert [n['ref'] for n in downstream['nodes']]==['root','upstream','downstream']
    assert downstream['selected'] is False


def test_unreachable_hits_are_counted_even_when_path_display_is_empty(sim):
    import_test(sim,make_bom([lodash('reached'),lodash('orphan')],[('root','reached')]))
    result=sim.preview('case',TARGET,['reached'])
    assert result['counts']['known_affected']==2 and result['counts']['remaining']==1
    assert result['counts']['remaining_reachable']==0 and result['counts']['remaining_unreachable']==1
    assert not result['coverage']['graph_complete']
    assert {p['target_ref'] for p in result['paths']}=={'reached'}
    both=sim.preview('case',TARGET,['reached','orphan'])
    assert both['counts']['remaining']==0 and not both['coverage']['can_confirm_absence']


def test_unknown_scan_coverage_does_not_disappear_after_selecting_all_known_hits(sim):
    import_test(sim,make_bom([lodash('known'),lodash('unknown','999.1.0')],
                            [('root','known'),('root','unknown')]))
    result=sim.preview('case',TARGET,['known'])
    assert result['counts']['remaining']==0 and result['coverage']['unknown_scan_count']==1
    assert not result['coverage']['can_confirm_absence']
    assert any('不能确认整体已消除' in text for text in result['limitations'])
    with pytest.raises(InputError):sim.preview('case',TARGET,['unknown'])


def test_incomplete_composition_remains_explicit_with_zero_preview(sim):
    bom=make_bom([lodash('known')],[('root','known')]);bom['compositions']=[{'aggregate':'incomplete'}]
    import_test(sim,bom)
    result=sim.preview('case',TARGET,['known'])
    assert result['counts']['remaining']==0 and not result['coverage']['graph_complete']
    assert any('结构存在缺失' in text for text in result['limitations'])


def test_path_display_truncation_never_truncates_known_occurrence_counts(sim):
    refs=[f'position-{i:02}' for i in range(MAX_PATH_TARGETS+5)]
    import_test(sim,make_bom([lodash(ref) for ref in refs],[('root',ref) for ref in refs]))
    result=sim.preview('case',TARGET,refs[:2])
    assert result['counts']['known_affected']==len(refs) and result['counts']['remaining']==len(refs)-2
    assert len(result['occurrences'])==len(refs) and result['paths_truncated']
    assert len(result['paths'])<=MAX_PATHS and result['path_targets_considered']<=MAX_PATH_TARGETS
    assert all(not p['selected'] for p in result['paths'])
    all_selected=sim.preview('case',TARGET,refs)
    assert all_selected['counts']['remaining']==0 and all_selected['paths_truncated']


def test_multiple_paths_to_same_occurrence_do_not_inflate_counts(sim):
    parents=[f'parent-{i}' for i in range(7)]
    bom=make_bom([demo_component(r) for r in parents]+[lodash('target')],
                 [('root',r) for r in parents]+[(r,'target') for r in parents])
    import_test(sim,bom)
    result=sim.preview('case',TARGET,[])
    assert len(result['paths'])==3 and result['paths_truncated']
    assert result['counts']['known_affected']==1 and result['counts']['remaining']==1
    assert sim.preview('case',TARGET,['target'])['counts']['remaining']==0


def test_deep_reachable_target_still_counted_when_no_short_path_displayed(sim):
    middle=[f'middle-{i}' for i in range(13)];chain=['root']+middle+['target']
    import_test(sim,make_bom([demo_component(r) for r in middle]+[lodash('target')],list(zip(chain,chain[1:]))))
    result=sim.preview('case',TARGET,[])
    assert result['counts']['remaining_reachable']==1
    assert result['paths']==[] and result['paths_truncated']


def test_basis_fingerprint_is_order_independent_of_selection_but_tracks_scan_changes(sim):
    baseline=sim.preview('demo-before',TARGET,[])
    left=sim.preview('demo-before',TARGET,['lodash-report','lodash-export'])
    right=sim.preview('demo-before',TARGET,['lodash-export','lodash-report'])
    assert left==right
    assert baseline['basis_fingerprint']==left['basis_fingerprint']
    scans=sim.service.store.scans('demo-before');scans['lodash-report']['fetched_at']='2099-01-01T00:00:00Z'
    docs=sim.service.store.documents('demo-before',include_knowledge=False)
    sim.service.store.save_scans('demo-before',scans,docs)
    changed=sim.preview('demo-before',TARGET,[])
    assert changed['basis_fingerprint']!=baseline['basis_fingerprint']


def test_preview_does_not_mutate_input_selection_or_shared_analysis(sim, monkeypatch):
    analysis=sim.service.analyze('demo-before',include_documents=False,include_paths=False)
    original=copy.deepcopy(analysis);refs=['lodash-report'];original_refs=refs.copy()
    monkeypatch.setattr(sim.service,'analyze',lambda *a,**k:analysis)
    sim.preview('demo-before',TARGET,refs)
    assert analysis==original and refs==original_refs


def test_other_advisories_on_selected_positions_are_not_removed_from_real_findings(sim):
    before=sim.service.analyze('demo-before')['findings']
    assert len({f['id'] for f in before})>1
    sim.preview('demo-before',TARGET,['lodash-report','lodash-export'])
    assert sim.service.analyze('demo-before')['findings']==before
