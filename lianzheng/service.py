import hashlib
import json
import time
from pathlib import Path
from uuid import uuid4

from .domain import InputError, parse_bom, reachable_nodes, representative_paths
from .osv import OSVClient, evidence_documents, findings_for
from .retrieval import Retriever, model_explanation
from .knowledge import prepare_document, document_summary
from .store import Store, now
from .settings import ModelSettings


class Service:
    def __init__(self, database, fixtures):
        self.store = Store(database)
        self.fixtures = Path(fixtures)
        self.osv = OSVClient(self.store,self.fixtures)
        self.retriever = Retriever()
        self.models=ModelSettings(Path(database).parent/'model-settings.json',self.fixtures.parent/'.env')

    def import_bom(self, raw, project=None, label=None, identifier=None, demo=False):
        graph=parse_bom(raw)
        canonical=json.dumps(raw,sort_keys=True,ensure_ascii=False).encode()
        item={'id':identifier or uuid4().hex,'project':project or graph['nodes'][0]['name'],
              'label':label or '导入快照','created':now(),'hash':hashlib.sha256(canonical).hexdigest(),
              'demo':demo,'raw':raw,'graph':graph}
        self.store.add_snapshot(item)
        self.scan(item['id'],live=False)
        return self.analyze(item['id'])

    def seed(self):
        for filename,identifier,label in [('before','demo-before','初始快照'),('partial','demo-partial','仅升级报表路径'),('resolved','demo-resolved','两条路径均已升级')]:
            try:self.store.get(identifier)
            except KeyError:
                raw=json.loads((self.fixtures/f'{filename}.cdx.json').read_text(encoding='utf-8'))
                self.import_bom(raw,project='商城运营工作台',label=label,identifier=identifier,demo=True)

    def scan(self,identifier,live=False):
        item=self.store.get(identifier)
        nodes=item['graph']['nodes']
        eligible=[x for x in nodes if x.get('package_name')]
        if live and len({(x['package_name'],x['package_version']) for x in eligible})>100:
            raise InputError('在线扫描单次最多支持 100 个精确包版本，请先拆分清单。')
        memo,scans,documents={},{},[]
        for node in nodes:
            if node['root']:
                continue
            # Synthetic demo components are explicitly disclosed and never sent to OSV.
            if item['demo'] and node['name'].startswith('@demo/'):
                scans[node['id']]={'status':'demo-component','source':'demo','fetched_at':None,
                                    'data':{},'error':'演示业务组件，不代表真实 npm 包。'}
                continue
            if not node.get('package_name'):
                scans[node['id']]={'status':'unsupported','source':'none','fetched_at':None,'data':{},
                                    'error':node['identity_error']}
                continue
            key=(node['package_name'],node['package_version'])
            if key not in memo:memo[key]=self.osv.query(*key,live=live)
            scans[node['id']]=memo[key]
            documents.extend(evidence_documents(identifier,node,memo[key]))
        self.store.save_scans(identifier,scans,documents)
        return {'snapshot_id':identifier,'live_requested':live,
                'checked':sum(x['status']=='checked' for x in scans.values()),
                'failed':sum(x['status']=='failed' for x in scans.values())}

    def analyze(self,identifier,focus=None,include_documents=True,include_paths=True):
        item=self.store.get(identifier)
        graph=item['graph']
        scans=self.store.scans(identifier)
        reachable=reachable_nodes(graph['root'],graph['edges'])
        findings=[]
        nodes=[]
        for node in graph['nodes']:
            result=scans.get(node['id'])
            hits=findings_for(node,result) if result and result['status']=='checked' else []
            findings.extend({**hit,'reachable':node['id'] in reachable} for hit in hits)
            nodes.append({**node,'reachable':node['id'] in reachable,
                          'scan_status':result['status'] if result else ('project' if node['root'] else 'unscanned'),
                          'scan_error':result.get('error') if result else None,
                          'findings':[x['id'] for x in hits], 'source':result.get('source') if result else None,
                          'fetched_at':result.get('fetched_at') if result else None})
        findings.sort(key=lambda v:({'CRITICAL':0,'HIGH':1,'MODERATE':2,'LOW':3}.get(v['severity'],4),v['id'],v['ref']))
        unique={v['id']:v for v in findings}
        focus=focus if focus in unique else ('GHSA-29mw-wpgm-hmr9' if 'GHSA-29mw-wpgm-hmr9' in unique else next(iter(unique),None))
        focus_refs={v['ref'] for v in findings if v['id']==focus}
        path_results=[representative_paths(graph,ref) for ref in sorted(focus_refs)] if include_paths else []
        paths=[path for result in path_results for path in result['paths']][:5]
        unknown=[n for n in nodes if not n['root'] and n['scan_status'] not in ('checked','demo-component')]
        checked=[n for n in nodes if n['scan_status']=='checked']
        return {'snapshot':{k:item[k] for k in ('id','project','label','created','hash','demo')},
                'root':graph['root'],'nodes':nodes,'edges':graph['edges'],'issues':graph['issues'],
                'complete':graph['complete'],'findings':findings,'vulnerabilities':list(unique.values()),
                'focus':focus,'paths':paths,'paths_truncated':any(r['truncated'] for r in path_results) or sum(len(r['paths']) for r in path_results)>5,
                'stats':{'components':len(nodes)-1,'edges':len(graph['edges']),'vulnerabilities':len(unique),
                         'affected_occurrences':len({v['ref'] for v in findings}),
                         'reachable_affected':len({v['ref'] for v in findings if v['reachable']}),
                         'checked':len(checked),'unknown':len(unknown)},
                'sources':sorted({r['source'] for r in scans.values()}),
                'can_confirm_absence':graph['complete'] and not unknown,
                'documents':self.store.documents(identifier) if include_documents else []}

    def list_snapshots(self):
        rows=[]
        for snapshot in self.store.list():
            result=self.analyze(snapshot['id'],include_documents=False,include_paths=False)
            rows.append({**snapshot,'stats':result['stats'],'complete':result['complete']})
        return rows

    def import_document(self,identifier,payload):
        item=self.store.get(identifier)
        document=prepare_document(identifier,item['graph'],payload)
        existing=self.store.knowledge_documents(identifier)
        if not any(d['id']==document['id'] for d in existing):
            if len(existing)>=50 or sum(len(d['chunks']) for d in existing)+len(document['chunks'])>2000:
                raise InputError('当前快照最多保存 50 份文档和 2000 个片段，请先整理文档。')
        return document_summary(self.store.add_document(document))

    def list_documents(self,identifier):
        self.store.get(identifier)
        return [document_summary(d) for d in self.store.knowledge_documents(identifier)]

    def compare(self,before,after):
        left=self.analyze(before,include_documents=False,include_paths=False)
        right=self.analyze(after,include_documents=False,include_paths=False)
        if left['snapshot']['project'] != right['snapshot']['project']:
            raise InputError('请选择同一项目的两个快照。')
        old={v['id'] for v in left['findings'] if v['reachable']}
        new={v['id'] for v in right['findings'] if v['reachable']}
        left_times={n['fetched_at'] for n in left['nodes'] if n['scan_status']=='checked'}
        right_times={n['fetched_at'] for n in right['nodes'] if n['scan_status']=='checked'}
        same_knowledge_snapshot=bool(left_times) and left_times==right_times
        complete=right['can_confirm_absence'] and same_knowledge_snapshot
        removed=sorted(old-new)
        left_nodes={n['id']:n for n in left['nodes']}
        right_nodes={n['id']:n for n in right['nodes']}
        # ref is an occurrence ID, not guaranteed stable across generated SBOMs.
        changes=[{'ref':ref,'name':right_nodes[ref]['name'],'from':left_nodes[ref]['version'],
                  'to':right_nodes[ref]['version']}
                 for ref in left_nodes.keys() & right_nodes.keys()
                 if left_nodes[ref]['name']==right_nodes[ref]['name'] and left_nodes[ref]['version']!=right_nodes[ref]['version']]
        finding_key=lambda v:(v['ref'],v['id'],v['version'])
        old_hits={finding_key(v):v for v in left['findings'] if v['reachable']}
        new_hits={finding_key(v):v for v in right['findings'] if v['reachable']}
        return {'before':left['snapshot'],'after':right['snapshot'],
                'resolved':removed if complete else [],'not_observed':removed if not complete else [],
                'remaining':sorted(old & new),'introduced':sorted(new-old),
                'component_changes':changes,
                'occurrences_no_longer_observed':[old_hits[k] for k in old_hits.keys()-new_hits.keys()],
                'before_stats':left['stats'],'after_stats':right['stats'],'comparison_complete':complete,
                'same_knowledge_snapshot':same_knowledge_snapshot,
                'note':'仅针对选定公告快照与清单；未证明运行时可利用性或升级兼容性。'+
                       ('新清单存在缺失或未扫描项，消失项仅标记为未观察到。' if not right['can_confirm_absence'] else '')+
                       ('两侧公告获取时间不同，差异可能来自知识库更新，消失项仅标记为未观察到。' if not same_knowledge_snapshot else '')}

    def ask(self,identifier,question,focus=None,mode='graph',use_model=False,parent_id=None):
        started=time.perf_counter()
        conversation=[]
        parent=None
        if parent_id:
            parent=self.store.history_item(identifier,parent_id)
            if parent['answer']['mode']!=mode:raise InputError('追问不能跨检索模式，请开启新对话。')
            prior_focus=parent['answer'].get('facts',{}).get('focus')
            if focus and prior_focus and focus!=prior_focus:raise InputError('追问的漏洞与当前选择不同，请开启新对话。')
            focus=focus or prior_focus
            cursor=parent
            for _ in range(3):
                conversation.append({'question':cursor['question'],
                                     'conclusion':cursor['answer']['conclusion'],
                                     'target_version':cursor['answer'].get('facts',{}).get('target_version')})
                previous=cursor['answer'].get('parent_id')
                if not previous:break
                cursor=self.store.history_item(identifier,previous)
            conversation.reverse()
        analysis=self.analyze(identifier,focus,include_documents=False,include_paths=False)
        graph=self.store.get(identifier)['graph']
        # Bind question entities rather than silently answering about the currently selected card.
        import re
        explicit_ids=re.findall(r'(?:GHSA-[A-Za-z0-9-]+|CVE-\d{4}-\d+)',question,re.I)
        explicit_unmatched=False
        multiple=False
        if explicit_ids:
            candidates=[v for v in analysis['vulnerabilities'] if any(q.lower() in [v['id'].lower()]+[a.lower() for a in v['aliases']] for q in explicit_ids)]
            explicit_unmatched=any(not any(q.lower() in [v['id'].lower()]+[a.lower() for a in v['aliases']] for v in candidates) for q in explicit_ids)
            multiple=len({v['id'] for v in candidates})>1
            if candidates and not explicit_unmatched and not multiple:focus=candidates[0]['id']
            else:focus=None
        elif focus and focus not in {v['id'] for v in analysis['vulnerabilities']}:
            explicit_unmatched=True
            focus=None
        else:
            focus=analysis['focus']
        relevant=[v for v in analysis['findings'] if v['id']==focus] if focus else []
        available={(n['package_name'],n['package_version']) for n in analysis['nodes']
                   if n.get('package_name') and n['scan_status']!='demo-component'}
        named={package for package,version in available if re.search(r'(?<![\w@/.-])'+re.escape(package)+r'(?![\w/.-])',question,re.I)}
        bindings={(v['package'],v['version']) for v in relevant}
        package_conflict=bool(named and bindings and not named & {package for package,version in bindings})
        if not bindings and not explicit_unmatched and not multiple:
            if named:bindings={(p,v) for p,v in available if p in named}
            elif len({p for p,v in available})==1:bindings=available
        if explicit_unmatched or multiple or package_conflict:
            bindings=set();relevant=[];focus=None
        if parent and focus!=parent['answer'].get('facts',{}).get('focus'):
            conversation=[];parent_id=None
        target_match=re.search(r'(?:升级(?:到|至)?|目标版本(?:为|是)?|target\s*[:=]?|\bto)\s*v?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?)',question,re.I)
        target=target_match.group(1) if target_match else None
        if not target and conversation:target=conversation[-1].get('target_version')
        migration_request=any(t in question.lower() for t in ('迁移','升级','注意事项','变更','测试','migration','upgrade'))
        paths=[];paths_truncated=False
        for hit in relevant if mode!='text' else []:
            result=representative_paths(graph,hit['ref'])
            paths.extend(result['paths']);paths_truncated=paths_truncated or result['truncated']
        paths_truncated=paths_truncated or len(paths)>5
        node_map={n['id']:n for n in analysis['nodes']}
        readable=[' → '.join(f"{node_map[x]['name']}@{node_map[x]['version']}" for x in path) for path in paths[:5]]
        # A baseline receives the same documents but cannot use graph facts in the explanation.
        retrieval_question=question+('\n上文问题：'+conversation[-1]['question'] if conversation else '')
        if conversation and any(t in question for t in ('那','这些','这个','还有','继续')):
            migration_request=migration_request or any(t in conversation[-1]['question'] for t in ('升级','迁移','测试','检查'))
        docs,method,warning=self.retriever.retrieve(retrieval_question,self.store.documents(identifier),
                                                   focus=focus,bindings=bindings,target_version=target,
                                                   prefer_knowledge=migration_request)
        knowledge=[d for d in docs if d.get('source')=='user-document']
        fixed=sorted({v for hit in relevant for v in hit['fixed_versions']})
        insufficient = explicit_unmatched or multiple or package_conflict or (not relevant and not knowledge)
        limits=['公告命中不等于漏洞实际可利用；修复候选需要构建与业务测试。']
        if knowledge:limits.append('导入文档的适用范围由导入者声明，内容真实性未自动验证；文档要求不能代替项目测试。')
        else:limits.append('未检索到当前包、来源版本及目标版本适用的项目文档，无法确认业务兼容性。')
        if not analysis['complete']:limits.append('依赖结构不完整，路径与消除判断仅覆盖已知关系。')
        if analysis['stats']['unknown']:limits.append(f"存在 {analysis['stats']['unknown']} 个组件未完成漏洞查询。")
        if warning:limits.append(warning)
        if any(term in question for term in ('可利用','攻击成功','一定安全','一定兼容','保证兼容','兼容吗','是否兼容','能上线','可以上线')):
            insufficient=True
            conclusion='证据不足，无法确认实际可利用性、升级兼容性或是否可以上线。'
        elif multiple:
            conclusion='当前一次问答仅分析一个漏洞，请按漏洞编号拆分问题；未将多个漏洞合并为同一结论。'
        elif package_conflict:
            conclusion='问题中的组件与已选公告不一致，请选择对应公告或明确要分析的组件。'
        elif explicit_unmatched:
            conclusion='当前快照没有匹配到问题中的漏洞证据，无法作出该漏洞的影响判断。'
        elif migration_request and knowledge:
            conclusion=f'已检索到 {len(knowledge)} 个与当前包及精确来源版本绑定的文档片段，以下要求需要结合项目测试核实。'
        elif not relevant:
            conclusion='所选数据中未检索到匹配漏洞证据；这不等于项目绝对安全。'
        elif mode=='text':
            conclusion=f"已检索到 {focus} 的公告证据；普通文本检索模式不提供依赖路径判断。"
        else:
            conclusion=f"当前快照中 {len(relevant)} 个组件出现位置命中 {focus}，其中 {sum(v['reachable'] for v in relevant)} 个从项目根节点可达。"
        statements=[]
        if mode!='text' and relevant:
            statements.extend(readable)
            if len(readable)>1:
                statements.append('存在多条引入路径；仅升级一条路径不能据此确认目标漏洞已消除。请导入新清单复核。')
        if fixed and relevant:
            statements.append('该包公告列出的修复边界：'+', '.join(fixed)+'。这不是依赖可解析或业务兼容性的保证。')
        if migration_request:
            for document in knowledge:
                scope=f"{document['package']} {document['version']}"
                if document.get('target_version'):scope+=' → '+document['target_version']
                excerpt=document['text'][:360]
                statements.append(f"导入文档 {document['id']}（声明适用 {scope}）：{excerpt}"+
                                  ('…完整片段见引用。' if len(document['text'])>360 else ''))
        citations=[{'id':d['id'],'title':d['title'],'text':d['text'],'url':d['url'],
                    'locator':d['locator'],'ref':d['ref'],'version':d['version'],'source':d['source'],
                    'fetched_at':d['fetched_at'],'target_version':d.get('target_version'),
                    'kind':d.get('kind','advisory'),'document_id':d.get('document_id'),
                    'snapshot_id':identifier,'trust':d.get('trust')} for d in docs]
        if use_model and mode!='text' and self.models.public()['configured']:
            edge_locations={(e['source'],e['target']):e['locator'] for e in graph['edges']}
            for index,path in enumerate(paths[:3]):
                text=' → '.join(f"{node_map[ref]['name']}@{node_map[ref]['version']}" for ref in path)
                locations=[edge_locations[(left,right)] for left,right in zip(path,path[1:])]
                text+='\n原始依赖位置：'+'；'.join(locations)
                evidence_id='path-'+hashlib.sha256((identifier+json.dumps(path)).encode()).hexdigest()[:20]
                citations.append({'id':evidence_id,'title':f'清单中的代表依赖路径 {index+1}',
                                  'text':text,'url':'','locator':'；'.join(locations),'ref':path[-1],
                                  'version':node_map[path[-1]]['version'],'source':'graph-evidence',
                                  'fetched_at':analysis['snapshot']['created'],'target_version':None,
                                  'kind':'dependency-path','document_id':None,'snapshot_id':identifier,
                                  'trust':'由当前清单中已声明的依赖边计算；代表路径不保证枚举全部路径。'})
        answer={'question':question,'conclusion':conclusion,'statements':statements,'limits':limits,
                'paths':paths[:5] if mode!='text' else [],'citations':citations,'insufficient':insufficient,
                'retrieval':method,'mode':mode,'generation':'evidence-template','model_explanation':None,
                'parent_id':parent_id,'conversation_depth':len(conversation),
                'facts':{'focus':focus,'fixed_versions':fixed,'target_version':target,'insufficient':insufficient,
                         'snapshot_id':identifier,'document_count':len(docs)},'created':now()}
        if mode!='text':
            answer['facts'].update(matched_occurrences=len(relevant),graph_complete=analysis['complete'],
                                   displayed_paths=len(readable),paths_truncated=paths_truncated)
        if use_model and citations:
            context={'facts':answer['facts'],'evidence':citations,'paths':readable if mode!='text' else [],
                     'conversation':conversation,'limitations':limits}
            if self.models.public()['configured']:
                generated,model_warning=model_explanation(question,context,config=self.models.current())
            else:
                generated,model_warning=model_explanation(question,context)
                if not generated and not model_warning:model_warning='尚未连接真实模型，本次显示本地证据解释。'
            answer['model_explanation']=generated
            if generated:answer['generation']='model-assisted'
            if model_warning:
                answer['limits'].append(str(model_warning))
                if getattr(model_warning,'metadata',None):answer['model_attempt']=model_warning.metadata
        answer['elapsed_ms']=round((time.perf_counter()-started)*1000)
        self.store.add_history(identifier,question,answer)
        return answer
