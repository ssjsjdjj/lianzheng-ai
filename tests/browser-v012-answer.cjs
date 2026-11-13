/* v0.12 item/source linkage, recorded retrieval replay and readonly capture protocol in a minimal DOM. No server, secret or network.
 * Real browser layout and downloaded source bytes are separate acceptance checks.
 */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const code=fs.readFileSync(path.join(__dirname,'../static/task-compare.js'),'utf8');
const hashes={A:'a'.repeat(64),B:'b'.repeat(64),updated:'c'.repeat(64)};
const caseSource={case_bundle_sha256:'fixed-bundle',commit:'fixed-commit',lockfile:'before.package-lock.json'};
const caseCatalog={available:true,model_configured:true,source:caseSource,tasks:[{id:'before-occurrences',question:'固定案例问题',phase:'before'}],protocol:{statement:'same fixed sources'}};
const clone=value=>JSON.parse(JSON.stringify(value));
const decode=value=>value.replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&amp;/g,'&');
function harness(){
  const nodes=[],jobs=[],calls=[],timers=[],downloads=[],events=[],listeners=new Map();
  class Element{
    constructor(tag='div'){this.tagName=tag.toUpperCase();this._html='';this.attrs={};this.fields=null;this.listeners={};this.dataset={};this.classList={add(){},toggle(){}};this.hidden=false;nodes.push(this);}
    set innerHTML(value){this._html=value;this.fields=null;}get innerHTML(){return this._html;}
    setAttribute(name,value){this.attrs[name]=value;}getAttribute(name){return this.attrs[name]??null;}hasAttribute(name){return name in this.attrs;}
    append(){}replaceChildren(){this.innerHTML='';}scrollIntoView(){this.scrolls=(this.scrolls||0)+1;}focus(){document.activeElement=this;}setSelectionRange(){}
    contains(node){return (this.fields||[]).includes(node);}addEventListener(name,fn){this.listeners[name]=fn;}
    querySelectorAll(selector){
      const attr=selector.match(/^\[([^\]]+)\]$/)?.[1];if(!attr)return [];
      if(!this.fields){this.fields=[];for(const match of this.innerHTML.matchAll(/<(button|input|textarea|select|small|details|a)\b([^>]*)>/g)){
        const element=new Element(match[1]);for(const attribute of match[2].matchAll(/([\w-]+)(?:="([^"]*)")?/g)){const name=attribute[1],value=decode(attribute[2]||'');element.attrs[name]=value;if(name.startsWith('data-'))element.dataset[name.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=value;}
        element.open=element.hasAttribute('open');element.disabled=element.hasAttribute('disabled');element.checked=element.hasAttribute('checked');this.fields.push(element);
      }}
      return this.fields.filter(e=>e.hasAttribute(attr));
    }
    querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
    click(){return this.disabled?undefined:this.listeners.click?.({target:this,preventDefault:()=>{this.prevented=true;}});}
  }
  const heading=new Element(),main=new Element(),selector={value:'A'};
  const document={activeElement:null,querySelector:s=>s==='.heading-actions'?heading:s==='main'?main:null,getElementById:id=>id==='snapshot-select'?selector:null,createElement:tag=>new Element(tag)};
  const window={addEventListener:(name,fn)=>{if(!listeners.has(name))listeners.set(name,[]);listeners.get(name).push(fn);},dispatchEvent:event=>{events.push(event);for(const fn of listeners.get(event.type)||[])fn(event);}};
  const context=vm.createContext({document,window,AbortController,Blob,URL:{createObjectURL:blob=>{downloads.push(blob);return 'blob:test';},revokeObjectURL(){}},CustomEvent:class{constructor(type,init){this.type=type;this.detail=init.detail;}},console,
    escapeHTML:value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
    setTimeout:(fn,ms)=>{const timer={fn,ms,active:true};timers.push(timer);return timer;},clearTimeout:timer=>{if(timer)timer.active=false;},
    fetch:(url,options)=>{
      const call={url,body:options.body?JSON.parse(options.body):null,signal:options.signal};calls.push(call);
      if(url.endsWith('/tasks'))return Promise.resolve({ok:true,json:async()=>clone(caseCatalog)});
      return new Promise((resolve,reject)=>{const job={...call,ignoreAbort:false,resolve:(data,status=200)=>resolve({ok:status<400,status,json:async()=>data}),reject};jobs.push(job);options.signal.addEventListener('abort',()=>{if(!job.ignoreAbort){const error=new Error('aborted');error.name='AbortError';reject(error);}});});
    }});
  vm.runInContext(code,context);
  const panel=nodes.find(n=>n.id==='task-comparison-panel');
  return {api:window.lianzhengTaskCompare,panel,calls,timers,jobs,downloads,events,host:()=>new Element(),event:(name,detail)=>window.dispatchEvent({type:name,detail}),
    click(name){return panel.querySelector('[data-tc-'+name+']')?.click();},
    clickValue(name,value,column){return panel.querySelectorAll('[data-tc-'+name+']').find(e=>e.getAttribute('data-tc-'+name)===value&&(column===undefined||e.dataset.tcColumn===String(column)))?.click();},
    input(value){const e=panel.querySelector('[data-tc-question]');assert.ok(e);e.value=value;e.selectionStart=value.length;e.listeners.input({target:e});},
    model(value){const e=panel.querySelector('[data-tc-model]');e.checked=value;e.listeners.change({target:e});},
    last:()=>jobs.at(-1),posts:()=>calls.filter(c=>c.body),
  };
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const binding=(id='A',hash=hashes[id])=>({scope:'snapshot',snapshot_id:id,context_sha256:hash});
const url=(id='A',hash=hashes[id],source='manifest')=>`/api/snapshots/${id}/task-comparison/sources/${source}?context_sha256=${hash}`;
function context(id='A',hash=hashes[id]){return {available:true,model_configured:null,source:{...binding(id,hash),project:'同名项目',label:'同名快照',filename:'package-lock.json',url:url(id,hash)},protocol:{statement:'current snapshot only'}};}
function answer(question='shared 路径',id='A',hash=hashes[id]){
  const source=context(id,hash).source,b= binding(id,hash);
  const document={...b,id:'same-evidence-id',title:'shared@1.0.0 同名组件',phase:'snapshot',text:'shared 由项目根引入。',filename:'package-lock.json',url:url(id,hash),locator:'/packages/node_modules~1shared',ref:'shared-ref',relations:[{...b,source:'root',target:'shared-ref'}],source_sha256:'f'.repeat(64),source_excerpt:'{"version":"1.0.0"}',source_excerpt_kind:'saved-source-content',kind:'occurrence'};
  const linkedPath={...b,id:'same-path-id',label:'root → shared',nodes:[{...b,ref:'root',name:'same-root',version:'1.0.0',url:url(id,hash)},{...b,ref:'shared-ref',name:'shared',version:'1.0.0',url:url(id,hash)}],edges:[{...b,source:'root',target:'shared-ref',evidence_ids:[document.id],url:url(id,hash)}]};
  const column=method=>({id:method,method,generation:'offline-evidence',answer:'项目证据摘要',evidence:[clone(document)],paths:['root → shared'],metrics:{retrieved:1,connected_target_occurrences:1,retrieval_ms:1,evidence_bytes:100},evidence_links:{source:clone(source),paths:[clone(linkedPath)],facts:[{...b,id:'same-fact-id',text:'shared 从项目根引入。',evidence_ids:[document.id],path_ids:[linkedPath.id],kind:'retrieved-fact'}]}});
  return {release:'0.10.0',task:{id:'project-question-hash',question,phase:'snapshot',kind:'project-question'},source,fairness:{},columns:[column('bm25'),column('bm25+graph')],comparison:{result:'unscored',note:'当前项目自由题，无预设答案'},limitations:[],model_calls_attempted:0};
}
async function ready(h,id='A',hash=hashes[id]){h.api.configure({scope:'snapshot',snapshot_id:id,mode:'free',reset:true});if(!h.api.state().loading)h.api.refresh().catch(()=>{});await tick();h.last().resolve(context(id,hash));await tick();}
async function ask(h,question,data){h.input(question);const running=h.click('run');await tick();h.last().resolve(data);await running;}
function v11Answer(question='shared 路径',id='A',hash=hashes[id],specs=[{key:'root',hash:'1'}]){
  const data=answer(question,id,hash),b=binding(id,hash);
  for(const c of data.columns){
    const base=c.evidence[0];
    c.evidence=specs.map(s=>({...clone(base),id:hash.slice(0,5)+'-'+s.key,stable_key:id+':'+s.key,content_sha256:(s.hash||'1').repeat(64),title:s.title||'依据 '+s.key,source_excerpt:s.excerpt||'保存片段 '+s.key}));
    c.evidence_links.paths=[];
    c.evidence_links.facts=c.evidence.map(e=>({...b,id:'fact-'+e.id,kind:'retrieved-fact',text:e.title,evidence_ids:[e.id],path_ids:[]}));
    c.answer_card={...b,generation:c.generation,conclusion:{text:'取回 '+c.evidence.length+' 份材料，结论仍需复核。',evidence_ids:c.evidence.map(e=>e.id)},reasons:c.evidence.map(e=>({id:'reason-'+e.id,text:e.title,evidence_ids:[e.id]})),unknowns:[{text:'尚无运行测试，状态仍待确认。',evidence_ids:[]}],next_steps:[{text:'补充实际测试日志后复核。',evidence_ids:[]}],note:'仅依据本侧已取回材料。'};
  }
  return data;
}
async function updateContext(h,hash=hashes.updated){h.event('lianzheng-project-evidence-changed',{snapshot_id:'A'});await tick();h.last().resolve(context('A',hash));await tick();}
async function rerun(h,data,control='run'){const waiting=h.click(control);await tick();h.last().resolve(data);await waiting;}
function changeCount(html,key){return Number(html.match(new RegExp('tc-change-'+key+'"><summary>[^<]+<b>(\\d+)</b>'))?.[1]);}
function traced(data=v11Answer()){
  const b=binding(data.source.snapshot_id,data.source.context_sha256),common={...b,filename:'package-lock.json',source_sha256:'f'.repeat(64)};
  for(const c of data.columns){
    for(const e of c.evidence)e.relations=[{...b,source:'root',target:e.ref,locator:'/packages/root/dependencies/shared'}];
    const e=c.evidence[0],used=c.id==='bm25+graph';
    const target=e?{...common,ref:e.ref,name:'shared',version:'1.0.0',locator:e.locator,evidence_ids:[e.id],evidence_id:e.id}:null;
    const root={...common,ref:'root',name:'project-root',version:'1.0.0',locator:'/packages/root',evidence_ids:[]};
    const edge=e?{...common,source:'root',target:e.ref,locator:'/packages/root/dependencies/shared',source_locator:root.locator,target_locator:e.locator,evidence_ids:[e.id],declaration_excerpt:'"^1.0.0"',declaration_excerpt_kind:'saved-source-content',declaration_excerpt_truncated:false}:null;
    c.retrieval_trace={...b,schema:'lianzheng-retrieval-trace-v1',status:'ready',method:c.id,
      graph:{...b,status:used&&e?'applied':used?'no-matched-targets':'text-only',matched_targets:used&&target?[target]:[],matched_target_count:used&&target?1:0,targets_truncated:false,paths:used&&e?[{...b,id:'path-one',nodes:[root,target],edges:[edge],complete:true,truncated:false,node_count:2}]:[],path_count:used&&e?1:0,paths_truncated:false},
      candidates:[...c.evidence.map((d,i)=>({...b,id:'candidate-'+i,title:d.title,final_rank:i+1,lexical_rank:i+1,graph_priority_rank:used?i+1:null,status:'selected',evidence_id:d.id})),{...b,id:'candidate-unselected',title:'未取回候选 UNIQUE_CANDIDATE',final_rank:c.evidence.length+1,lexical_rank:c.evidence.length+1,graph_priority_rank:null,status:'not-considered-limit'}],candidate_count:c.evidence.length+1,candidates_truncated:false,selected_evidence_ids:c.evidence.map(d=>d.id),
      selection:{limit:8,max_bytes:28000,used_bytes:100,selected_count:c.evidence.length,skipped_budget_count:0,not_considered_count:1},
      steps:['lexical','entity-match','graph-priority','budget'].map((id,i)=>({...b,id,label:['文本召回','目标匹配','图优先排序','证据入选'][i],detail:'真实记录步骤 '+i,count:i===3?c.evidence.length:1}))};
  }return data;
}
const graph=data=>data.columns[1];
const allItems=card=>[card.conclusion,...card.reasons,...card.unknowns,...card.next_steps];
async function compare(h,before,after){await ready(h,'A',before.source.context_sha256);await ask(h,before.task.question,before);h.click('retain');await updateContext(h,after.source.context_sha256);await rerun(h,after);h.click('download-change');return JSON.parse(await h.downloads.at(-1).text());}
(async()=>{
  let passed=0;const check=(name,fn)=>{fn();passed++;console.log('PASS '+name);};
  const h=harness();await tick();
  const before=v11Answer(),after=v11Answer('shared 路径','A',hashes.updated);
  for(const data of [before,after])for(const item of allItems(graph(data).answer_card))item.evidence_ids=[graph(data).evidence[0].id];
  for(const [i,item] of allItems(graph(after).answer_card).entries())item.text='改写条目 '+i;
  let exported=await compare(h,before,after);
  check('all four sections compare by stable citation identity across transient IDs',()=>{assert.equal(exported.answer_changes.length,4);assert.ok(exported.answer_changes.every(x=>x.status==='changed'));assert.deepEqual(exported.answer_changes.map(x=>x.section),['conclusion','reasons','unknowns','next_steps']);assert.ok(h.panel.innerHTML.includes('引用材料及内容指纹相同，仅回答文字变化'));});
  h.clickValue('change-item','answer-change-3');
  check('selection links next-step text to historical/current source locators and hashes',()=>{assert.ok(h.panel.innerHTML.includes('下一步 · 文字变化'));assert.ok(h.panel.innerHTML.includes('行号 / JSON 定位'));assert.ok(h.panel.innerHTML.includes('来源 SHA-256 '+ 'f'.repeat(64)));assert.ok(!h.panel.innerHTML.includes(url('A',hashes.A)));assert.ok(h.panel.innerHTML.includes(url('A',hashes.updated)));});
  check('item export retains original excerpts and omits live history/current URLs',()=>{assert.equal(exported.format,'lianzheng-answer-change-v2');assert.ok(exported.historical.evidence[0].source_excerpt);assert.ok(!JSON.stringify(exported).includes('/api/'));assert.ok(exported.note.includes('不构成因果'));});
  const contentOnly=v11Answer('shared 路径','A',hashes.updated,[{key:'root',hash:'2',excerpt:'changed original line 42'}]);
  exported=await compare(h,v11Answer(),contentOnly);
  check('unchanged answer text with edited material is labeled separately from text changes',()=>{assert.equal(exported.answer_changes.find(x=>x.section==='conclusion').status,'unchanged');assert.deepEqual(exported.answer_changes[0].changed_source_keys,['A:root']);assert.ok(h.panel.innerHTML.includes('条目文字未变；部分引用原文内容有变化'));assert.ok(h.panel.innerHTML.includes('changed original line 42'));});
  const newSet=v11Answer('shared 路径','A',hashes.updated,[{key:'other',hash:'2'}]);graph(newSet).answer_card.conclusion.text=graph(v11Answer()).answer_card.conclusion.text;
  exported=await compare(h,v11Answer(),newSet);
  check('changed citation sets are unpaired even when conclusion wording matches',()=>{const items=exported.answer_changes.filter(x=>x.section==='conclusion');assert.equal(items.length,2);assert.deepEqual(items.map(x=>x.status),['removed','added']);assert.ok(h.panel.innerHTML.includes('不推断它们互相替代'));});
  const uncited=v11Answer('shared 路径','A',hashes.updated);graph(uncited).answer_card.unknowns[0].text='新待确认事项';
  exported=await compare(h,v11Answer(),uncited);
  check('uncited changed items are not paired by list position',()=>{assert.deepEqual(exported.answer_changes.filter(x=>x.section==='unknowns').map(x=>x.status),['removed','added']);assert.equal(exported.answer_changes.find(x=>x.section==='next_steps').status,'unchanged');});
  const duplicateBefore=v11Answer(),duplicateAfter=v11Answer('shared 路径','A',hashes.updated);
  for(const data of [duplicateBefore,duplicateAfter]){const c=graph(data);c.answer_card.reasons=[{text:'first sentence',evidence_ids:[c.evidence[0].id]},{text:'second sentence',evidence_ids:[c.evidence[0].id]}];}
  graph(duplicateAfter).answer_card.reasons.reverse();exported=await compare(h,duplicateBefore,duplicateAfter);
  check('reordered exact items sharing citations match deterministically',()=>assert.ok(exported.answer_changes.filter(x=>x.section==='reasons').every(x=>x.status==='unchanged')));
  graph(duplicateAfter).answer_card.reasons.forEach((item,i)=>item.text='different '+i);exported=await compare(h,duplicateBefore,duplicateAfter);
  check('ambiguous repeated citation groups remain additions/removals instead of false rewrites',()=>{const items=exported.answer_changes.filter(x=>x.section==='reasons');assert.equal(items.length,4);assert.equal(items.filter(x=>x.status==='changed').length,0);});
  for(const [name,mutate] of [['duplicate stable identities',d=>{const c=graph(d);c.evidence.push({...clone(c.evidence[0]),id:'different-id'});}],['missing stable identity',d=>delete graph(d).evidence[0].stable_key]]){
    const old=v11Answer(),fresh=v11Answer('shared 路径','A',hashes.updated);mutate(old);exported=await compare(h,old,fresh);
    check(name+' cannot create a paired cited item',()=>assert.deepEqual(exported.answer_changes.filter(x=>x.section==='conclusion').map(x=>x.status),['removed','added']));
  }
  const crossSection=v11Answer('shared 路径','A',hashes.updated);const moved=graph(crossSection).answer_card.reasons.pop();graph(crossSection).answer_card.next_steps.push(moved);exported=await compare(h,v11Answer(),crossSection);
  check('items never pair across sections',()=>{assert.equal(exported.answer_changes.find(x=>x.section==='reasons').status,'removed');assert.ok(exported.answer_changes.some(x=>x.section==='next_steps'&&x.status==='added'));});
  await ready(h);await ask(h,'shared 路径',traced());const posts=h.posts().length;
  check('validated trace renders recorded steps plus actual retrieved-set overlap',()=>{assert.ok(h.panel.innerHTML.includes('已记录的检索过程回放'));assert.equal(h.panel.innerHTML.includes('本侧没有可验证'),false);assert.ok(h.panel.innerHTML.includes('两侧共同取回 <b>1</b>'));assert.ok(h.panel.innerHTML.includes('不是模型思维过程'));});
  h.clickValue('trace-step','2',1);
  check('graph step shows recorded source path with evidence-bound relationship links',()=>{assert.ok(h.panel.innerHTML.includes('实际用于排序的路径'));assert.ok(h.panel.innerHTML.includes('/packages/root/dependencies/shared'));assert.ok(h.panel.innerHTML.includes('查看本侧关系证据片段'));assert.ok(h.panel.innerHTML.includes('保存的关系声明值（JSON 显示）'));assert.ok(h.panel.innerHTML.includes('&quot;^1.0.0&quot;'));assert.equal(h.posts().length,posts);});
  h.clickValue('trace-step','3',0);h.clickValue('trace-step','1',1);h.clickValue('trace-step','3',1);
  check('replay controls never issue retrieval or model requests and distinguish candidates',()=>{assert.equal(h.posts().length,posts);assert.ok(h.panel.innerHTML.includes('候选 · 达到数量上限'));assert.ok(h.panel.innerHTML.includes('已取回'));assert.ok(h.panel.innerHTML.includes('实际取回 1 / 8'));assert.equal(h.panel.querySelectorAll('[data-tc-trace-evidence]').some(e=>e.getAttribute('data-tc-trace-evidence')==='candidate-unselected'),false);});
  h.clickValue('trace-evidence','aaaaa-root',1);
  check('trace evidence selection opens only that column actual selected source',()=>{assert.equal(h.panel.querySelector('[data-tc-technical]').open,true);assert.equal(h.posts().length,posts);});
  const poisonCases=[
    ['trace binding',t=>t.snapshot_id='B'],['graph binding',t=>t.graph.context_sha256=hashes.B],['candidate binding',t=>t.candidates[0].snapshot_id='B'],['step binding',t=>t.steps[0].snapshot_id='B'],
    ['selected evidence list',t=>t.selected_evidence_ids=['foreign']],['selected candidate citation',t=>t.candidates[0].evidence_id='foreign'],['unselected candidate citation',t=>t.candidates[1].evidence_id='aaaaa-root'],['candidate URL',t=>t.candidates[1].url='javascript:evil()'],
    ['target evidence IDs',t=>t.graph.matched_targets[0].evidence_ids=['foreign']],['target binding',t=>t.graph.matched_targets[0].snapshot_id='B'],['path binding',t=>t.graph.paths[0].snapshot_id='B'],['path node binding',t=>t.graph.paths[0].nodes[0].snapshot_id='B'],
    ['path edge binding',t=>t.graph.paths[0].edges[0].snapshot_id='B'],['path continuity',t=>t.graph.paths[0].edges[0].target='fabricated'],['path citation',t=>t.graph.paths[0].edges[0].evidence_ids=['foreign']],['path relation locator',t=>t.graph.paths[0].edges[0].locator='/wrong'],['path source hash',t=>t.graph.paths[0].edges[0].source_sha256='0'.repeat(64)],['trace method',t=>t.method='bm25'],['declaration type',t=>t.graph.paths[0].edges[0].declaration_excerpt={}],['declaration kind',t=>t.graph.paths[0].edges[0].declaration_excerpt_kind='guessed'],['declaration truncation',t=>delete t.graph.paths[0].edges[0].declaration_excerpt_truncated],
  ];
  for(const [label,poison] of poisonCases){const data=traced();poison(graph(data).retrieval_trace);await ready(h);await ask(h,'shared 路径',data);check('invalid '+label+' disables trace without discarding bound answer',()=>{assert.ok(h.api.state().result);assert.equal((h.panel.innerHTML.match(/本侧没有可验证/g)||[]).length,1);assert.equal(h.panel.querySelectorAll('[data-tc-trace-step]').some(e=>e.dataset.tcColumn==='1'),false);});}
  const legacyTrace=traced();for(const edge of graph(legacyTrace).retrieval_trace.graph.paths[0].edges)for(const field of ['declaration_excerpt','declaration_excerpt_kind','declaration_excerpt_truncated'])delete edge[field];
  await ready(h);await ask(h,'shared 路径',legacyTrace);h.clickValue('trace-step','2',1);
  check('older trace without declaration excerpt retains replay with an explicit source-pointer fallback',()=>{assert.ok(h.panel.innerHTML.includes('旧记录未保存声明值'));assert.ok(h.panel.innerHTML.includes('实际用于排序的路径'));});
  const escapedDeclaration=traced();graph(escapedDeclaration).retrieval_trace.graph.paths[0].edges[0].declaration_excerpt='<svg onload=evil()>DECLARATION';graph(escapedDeclaration).retrieval_trace.graph.paths[0].edges[0].declaration_excerpt_truncated=true;
  await ready(h);await ask(h,'shared 路径',escapedDeclaration);h.clickValue('trace-step','2',1);
  check('saved declaration JSON is escaped and clipping is disclosed alongside the locator',()=>{assert.ok(h.panel.innerHTML.includes('&lt;svg onload=evil()&gt;DECLARATION'));assert.ok(!h.panel.innerHTML.includes('<svg onload'));assert.ok(h.panel.innerHTML.includes('声明片段已截断'));});
  await ready(h);await ask(h,'shared 路径',v11Answer());
  check('legacy or unavailable trace degrades without fabricated steps or automatic request',()=>{assert.equal((h.panel.innerHTML.match(/本侧没有可验证/g)||[]).length,2);assert.equal(h.panel.querySelectorAll('[data-tc-trace-step]').length,0);});
  const dangerous=traced();graph(dangerous).retrieval_trace.candidates[0].title='<img onerror=evil()>TRACE';graph(dangerous).retrieval_trace.steps[0].detail='<script>TRACE</script>';graph(dangerous).answer_card.conclusion.text='<svg onload=evil()>ANSWER';graph(dangerous).evidence[0].source_excerpt='<iframe src=javascript:evil()>SOURCE';
  const xssExport=await compare(h,v11Answer(),{...dangerous,source:dangerous.source});
  check('answer changes and replay escape hostile text as inert markup',()=>{assert.ok(!h.panel.innerHTML.includes('<script>TRACE'));assert.ok(!h.panel.innerHTML.includes('<img onerror'));assert.ok(!h.panel.innerHTML.includes('<svg onload'));assert.ok(!h.panel.innerHTML.includes('<iframe src='));assert.ok(h.panel.innerHTML.includes('&lt;script&gt;TRACE'));});
  const captured=h.api.state().result,old=h.api.state().baseline,host=h.host(),preState=JSON.stringify(h.api.state()),calls=h.calls.length;let live=true;
  const mounted=h.api.mountReadonly(host,{result:captured,baseline:old,context:context(),view:'answer',isCurrent:()=>live});
  check('readonly presentation clones a validated answer and includes trace without requests or shared state mutation',()=>{assert.ok(host.innerHTML.includes('已锁定项目答案卡'));assert.ok(host.innerHTML.includes('已记录的检索过程回放'));assert.equal(h.calls.length,calls);assert.equal(JSON.stringify(h.api.state()),preState);});
  captured.columns[1].answer_card.conclusion.text='MUTATED OUTSIDE CAPTURE';host.querySelector('[data-tc-readonly-evidence]').click();
  check('readonly source clicks use an independent capture after caller mutation',()=>{assert.ok(!host.innerHTML.includes('MUTATED OUTSIDE CAPTURE'));assert.ok(host.innerHTML.includes('&lt;iframe'));assert.ok(host.querySelector('[data-tc-current-source]'));assert.equal(h.calls.length,calls);});
  const sourceLink=host.querySelector('[data-tc-current-source]');live=false;sourceLink.click();
  check('readonly link checks freshness again at click and removes stale download targets',()=>{assert.equal(sourceLink.prevented,true);assert.equal(host.querySelector('[data-tc-current-source]'),null);assert.ok(!host.innerHTML.includes('/api/snapshots/'));assert.ok(host.innerHTML.includes('历史原文副本'));});
  const staleControl=host.querySelector('[data-tc-trace-step]');mounted.destroy();staleControl.click();
  check('destroyed readonly mounts cannot repaint via retained event callbacks',()=>assert.equal(host.innerHTML,''));
  const historyHost=h.host();const historyMount=h.api.mountReadonly(historyHost,{result:captured,baseline:old,context:context(),view:'changes',historical:true,isCurrent:()=>true});
  check('readonly historical comparison exposes selected old/new originals without active URLs',()=>{assert.ok(historyHost.innerHTML.includes('答案条目变化与原文联动'));assert.ok(!historyHost.innerHTML.includes('/api/snapshots/'));assert.equal(h.calls.length,calls);});historyMount.destroy();
  const foreign=traced();foreign.source.snapshot_id='B';const foreignHost=h.host();h.api.mountReadonly(foreignHost,{result:foreign,context:context(),view:'answer',isCurrent:()=>true});
  check('foreign readonly captures do not fall back to global current results',()=>{assert.ok(foreignHost.innerHTML.includes('尚无可核验'));assert.ok(!foreignHost.innerHTML.includes('shared@'));assert.equal(h.calls.length,calls);});
  const oldOnly=h.host();h.api.mountReadonly(oldOnly,{baseline:old,context:context(),view:'changes',historical:true});
  check('history-only readonly capture cannot invent a current counterpart',()=>{assert.ok(oldOnly.innerHTML.includes('尚无同题新回答'));assert.ok(!oldOnly.innerHTML.includes('data-tc-change-item'));assert.ok(!oldOnly.innerHTML.includes('/api/'));});
  await ready(h);const oversized=v11Answer();graph(oversized).evidence[0].source_excerpt='z'.repeat(500001);await ask(h,'shared 路径',oversized);h.click('retain');
  check('history capture has a bounded RAM size and reports refusal instead of silently truncating',()=>{assert.equal(h.api.state().baseline,null);assert.ok(h.api.state().notice.includes('保存上限'));});
  await ready(h);await ask(h,'shared 路径',traced());h.click('retain');h.input('different question');
  check('question change synchronously removes baseline, selected diff, and replay state',()=>{assert.equal(h.api.state().baseline,null);assert.equal(h.api.state().result,null);assert.equal(h.panel.querySelectorAll('[data-tc-trace-step]').length,0);assert.equal(h.panel.querySelectorAll('[data-tc-change-item]').length,0);});
  check('new interaction flow keeps all captures in page memory',()=>assert.ok(!/localStorage|sessionStorage|indexedDB/.test(code)));
  if(process.env.LIANZHENG_V012_TRACE_CONTRACT){
    const real=JSON.parse(fs.readFileSync(process.env.LIANZHENG_V012_TRACE_CONTRACT,'utf8')),contractHost=h.host(),previousCalls=h.calls.length;
    const contractMount=h.api.mountReadonly(contractHost,{result:real,context:real.source,view:'trace',historical:true,isCurrent:()=>false});
    contractHost.querySelectorAll('[data-tc-trace-step]').find(e=>e.dataset.tcColumn==='1'&&e.dataset.tcTraceStep==='2')?.click();
    check('actual isolated backend trace contract renders both scoped columns and saved declarations offline',()=>{
      assert.ok(!contractHost.innerHTML.includes('本侧没有可验证'));assert.ok(!contractHost.innerHTML.includes('尚无可核验'));
      assert.ok(contractHost.innerHTML.includes('实际用于排序的路径'));assert.ok(contractHost.innerHTML.includes('保存的关系声明值（JSON 显示）'));
      assert.ok(!contractHost.innerHTML.includes('/api/snapshots/'));assert.equal(h.calls.length,previousCalls);
    });contractMount.destroy();
  }
  console.log(JSON.stringify({suite:'v0.12 answer source linkage and recorded retrieval UI',passed,network_calls:0,real_model_calls:0,browser_layout_verified:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
