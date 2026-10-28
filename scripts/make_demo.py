"""Create explicitly synthetic business topology over frozen, genuine OSV results."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
fixture=ROOT/'fixtures'
cache=json.loads((fixture/'osv-cache.json').read_text(encoding='utf-8'))
resolved=cache['demo_resolved_version']

for name,versions in [('before',('4.17.20','4.17.20')),('partial',('4.17.21','4.17.20')),('resolved',(resolved,resolved))]:
    components=[
        {'type':'library','bom-ref':'report','name':'@demo/report-kit','version':'1.0.0','purl':'pkg:npm/%40demo/report-kit@1.0.0'},
        {'type':'library','bom-ref':'export','name':'@demo/export-kit','version':'1.0.0','purl':'pkg:npm/%40demo/export-kit@1.0.0'},
        {'type':'library','bom-ref':'lodash-report','name':'lodash','version':versions[0],'purl':'pkg:npm/lodash@'+versions[0]},
        {'type':'library','bom-ref':'lodash-export','name':'lodash','version':versions[1],'purl':'pkg:npm/lodash@'+versions[1]},
    ]
    raw={'bomFormat':'CycloneDX','specVersion':'1.6','version':1,
         'metadata':{'component':{'type':'application','bom-ref':'shop','name':'商城运营工作台','version':'1.0.0'},
                     'properties':[{'name':'lianzheng:demo','value':'业务组件和依赖拓扑为演示构造；OSV 查询数据是真实冻结快照。'}]},
         'components':components,'dependencies':[{'ref':'shop','dependsOn':['report','export']},
           {'ref':'report','dependsOn':['lodash-report']},{'ref':'export','dependsOn':['lodash-export']},
           {'ref':'lodash-report','dependsOn':[]},{'ref':'lodash-export','dependsOn':[]}],
         'compositions':[{'aggregate':'complete'}]}
    (fixture/f'{name}.cdx.json').write_text(json.dumps(raw,ensure_ascii=False,indent=2),encoding='utf-8')
print('Demo fixtures created; resolved version:',resolved)
