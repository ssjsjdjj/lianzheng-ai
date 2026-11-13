/* Imported-project UI state protocol in a minimal DOM. No server, secret or network.
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
  const nodes=[],jobs=[],calls=[],timers=[],listeners=new Map();
  class Element{
    constructor(tag='div'){this.tagName=tag.toUpperCase();this._html='';this.attrs={};this.fields=null;this.listeners={};this.dataset={};this.classList={add(){},toggle(){}};this.hidden=false;nodes.push(this);}
    set innerHTML(value){this._html=value;this.fields=null;}get innerHTML(){return this._html;}
    setAttribute(name,value){this.attrs[name]=value;}getAttribute(name){return this.attrs[name]??null;}hasAttribute(name){return name in this.attrs;}
    append(){}replaceChildren(){this.innerHTML='';}scrollIntoView(){}focus(){document.activeElement=this;}setSelectionRange(){}
    contains(node){return (this.fields||[]).includes(node);}addEventListener(name,fn){this.listeners[name]=fn;}
    querySelectorAll(selector){
      const attr=selector.match(/^\[([^\]]+)\]$/)?.[1];if(!attr)return [];
      if(!this.fields){this.fields=[];for(const match of this.innerHTML.matchAll(/<(button|input|textarea|select|small)\b([^>]*)>/g)){
        const element=new Element(match[1]);for(const attribute of match[2].matchAll(/([\w-]+)(?:="([^"]*)")?/g)){const name=attribute[1],value=decode(attribute[2]||'');element.attrs[name]=value;if(name.startsWith('data-'))element.dataset[name.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=value;}
        element.disabled=element.hasAttribute('disabled');element.checked=element.hasAttribute('checked');this.fields.push(element);
      }}
      return this.fields.filter(e=>e.hasAttribute(attr));
    }
    querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
    click(){return this.disabled?undefined:this.listeners.click?.({target:this});}
  }
  const heading=new Element(),main=new Element(),selector={value:'A'};
  const document={activeElement:null,querySelector:s=>s==='.heading-actions'?heading:s==='main'?main:null,getElementById:id=>id==='snapshot-select'?selector:null,createElement:tag=>new Element(tag)};
  const window={addEventListener:(name,fn)=>{if(!listeners.has(name))listeners.set(name,[]);listeners.get(name).push(fn);},dispatchEvent:event=>{for(const fn of listeners.get(event.type)||[])fn(event);}};
  const context=vm.createContext({document,window,AbortController,Blob,URL,CustomEvent:class{constructor(type,init){this.type=type;this.detail=init.detail;}},console,
    escapeHTML:value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
    setTimeout:(fn,ms)=>{const timer={fn,ms,active:true};timers.push(timer);return timer;},clearTimeout:timer=>{if(timer)timer.active=false;},
    fetch:(url,options)=>{
      const call={url,body:options.body?JSON.parse(options.body):null,signal:options.signal};calls.push(call);
      if(url.endsWith('/tasks'))return Promise.resolve({ok:true,json:async()=>clone(caseCatalog)});
      return new Promise((resolve,reject)=>{const job={...call,ignoreAbort:false,resolve:(data,status=200)=>resolve({ok:status<400,status,json:async()=>data}),reject};jobs.push(job);options.signal.addEventListener('abort',()=>{if(!job.ignoreAbort){const error=new Error('aborted');error.name='AbortError';reject(error);}});});
    }});
  vm.runInContext(code,context);
  const panel=nodes.find(n=>n.id==='task-comparison-panel');
  return {api:window.lianzhengTaskCompare,panel,calls,timers,jobs,host:()=>new Element(),event:(name,detail)=>window.dispatchEvent({type:name,detail}),
    click(name){return panel.querySelector('[data-tc-'+name+']')?.click();},
    clickValue(name,value,column){return panel.querySelectorAll('[data-tc-'+name+']').find(e=>e.getAttribute('data-tc-'+name)===value&&(column===undefined||e.dataset.tcColumn===String(column)))?.click();},
    input(value){const e=panel.querySelector('[data-tc-question]');assert.ok(e);e.value=value;e.selectionStart=value.length;e.listeners.input({target:e});},
    model(value){const e=panel.querySelector('[data-tc-model]');e.checked=value;e.listeners.change({target:e});},
    last:()=>jobs.at(-1),posts:()=>calls.filter(c=>c.body),
  };
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function workspaceHarness(){
  const source=fs.readFileSync(path.join(__dirname,'../static/app.js'),'utf8'),nodes=new Map(),jobs=[],events=[],rendered=[];
  const state={id:'A',request:0,analysis:null,switchingSnapshot:false,documents:[{title:'old document'}],history:[{question:'old history'}],parentId:9,turns:[{question:'old conversation'}],pendingQuestion:null};
  class Node{
    constructor(){this._html='';this._text='';this.buttons=[];this.dataset={};this.listeners={};this.classList={toggle(){}};}
    set textContent(value){this._text=String(value);this._html='';this.buttons=[];}get textContent(){return this._text;}
    set innerHTML(value){this._html=value;this._text='';this.buttons=[...value.matchAll(/data-history="([^"]+)"/g)].map(match=>{const button=new Node();button.dataset.history=match[1];return button;});}get innerHTML(){return this._html;}
    addEventListener(name,fn){this.listeners[name]=fn;}click(){return this.listeners.click?.();}
  }
  const get=id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);};
  get('#document-list').innerHTML='old document';get('#history-list').innerHTML='old history';
  const scope=vm.createContext({state,$:get,$$:selector=>selector==='#history-list [data-history]'?get('#history-list').buttons:[],
    api:url=>new Promise((resolve,reject)=>jobs.push({url,resolve,reject})),window:{dispatchEvent:event=>events.push(event)},CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail;}},
    renderConversation(){},renderAnalysis(){},renderAnswer:answer=>rendered.push(answer),renderEvidence(){if(!state.analysis)throw Error('analysis has not loaded');},changeView(){},toast(){},escapeHTML:value=>String(value??''),dateLabel:value=>value,busy:(_button,_text,action)=>action(),console});
  for(const name of ['stopWaiting','selectSnapshot','refreshKnowledge','refreshHistory']){
    const start=source.search(new RegExp('(?:async )?function '+name+'\\('));assert.ok(start>=0,'root function '+name+' exists');
    const end=source.slice(start+1).search(/\n(?:async )?function \w+\(/);assert.ok(end>=0,'root function '+name+' has a source boundary');
    vm.runInContext(source.slice(start,start+1+end),scope);
  }
  return {state,jobs,events,rendered,get,select:scope.selectSnapshot,history:scope.refreshHistory,last:()=>jobs.at(-1)};
}
const workspaceAnalysis=()=>({focus:'current-focus',vulnerabilities:[{id:'different-focus'}]});
const historyItem=(focus=null)=>({id:7,question:'A private historical question',created:'saved date',answer:{mode:'graph',citations:[],facts:{focus},conclusion:'A private historical answer'}});
async function finishSelection(h,pending){h.last().resolve(workspaceAnalysis());await tick();for(const job of h.jobs.slice(-2))job.resolve([]);await pending;}
async function workspaceTests(check){
  const initial=workspaceHarness(),selection=initial.select('B');
  check('workspace initial load with analysis null clears old lists and conversation synchronously',()=>{assert.equal(initial.jobs.length,1);assert.equal(initial.state.analysis,null);assert.equal(initial.state.documents.length,0);assert.equal(initial.state.history.length,0);assert.equal(initial.state.turns.length,0);assert.equal(initial.state.parentId,null);assert.ok(!initial.get('#document-list').innerHTML.includes('old document'));assert.ok(!initial.get('#history-list').innerHTML.includes('old history'));assert.equal(initial.events[0].type,'lianzheng-snapshot-changing');});
  initial.last().resolve(workspaceAnalysis());await tick();for(const job of initial.jobs.slice(-2))job.reject(Error('side panel unavailable'));await selection;
  const delayed=initial.history('B',initial.state.request),oldRead=initial.last(),next=initial.select('A');oldRead.resolve([historyItem()]);await delayed;await finishSelection(initial,next);
  check('failed side-panel loads and delayed old history never restore former project items',()=>{assert.equal(initial.state.id,'A');assert.equal(initial.state.documents.length,0);assert.equal(initial.state.history.length,0);assert.ok(!initial.get('#history-list').innerHTML.includes('A private historical'));assert.ok(!initial.get('#document-list').innerHTML.includes('old document'));});
  const stale=workspaceHarness();stale.state.analysis=workspaceAnalysis();const load=stale.history('A',0);stale.last().resolve([historyItem()]);await load;const button=stale.get('#history-list').buttons[0],switching=stale.select('B'),serial=stale.state.request;await button.click();await finishSelection(stale,switching);await button.click();
  check('a detached old history button cannot invalidate an in-flight or completed snapshot switch',()=>{assert.equal(stale.state.id,'B');assert.equal(stale.state.request,serial);assert.equal(stale.rendered.length,0);assert.equal(stale.state.parentId,null);});
  const focused=workspaceHarness();focused.state.analysis=workspaceAnalysis();const read=focused.history('A',0);focused.last().resolve([historyItem('different-focus')]);await read;const replay=focused.get('#history-list').buttons[0].click(),lateFocus=focused.last();const newProject=focused.select('B'),expected=focused.state.request;await finishSelection(focused,newProject);lateFocus.resolve(workspaceAnalysis());await replay;
  check('history focus lookup arriving after another project cannot replay or cancel that project',()=>{assert.equal(focused.state.id,'B');assert.equal(focused.state.request,expected);assert.equal(focused.rendered.length,0);assert.equal(focused.state.history.length,0);assert.equal(focused.state.turns.length,0);});
}
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
async function ready(h,id='A',hash=hashes[id]){h.api.configure({scope:'snapshot',snapshot_id:id,mode:'free',reset:true});await tick();h.last().resolve(context(id,hash));await tick();}
async function ask(h,question,data){h.input(question);const running=h.click('run');await tick();h.last().resolve(data);await running;}
(async()=>{
  let passed=0;const check=(name,fn)=>{fn();passed++;console.log('PASS '+name);};
  const h=harness();await tick();await ready(h);
  check('choosing current project reads only its context',()=>{assert.equal(h.last().url,'/api/snapshots/A/task-comparison/context');assert.equal(h.posts().length,0);assert.equal(h.api.state().mode,'free');assert.ok(h.panel.innerHTML.includes('当前项目'));assert.ok(h.panel.innerHTML.includes('固定参赛案例'));});
  check('unknown public model status keeps offline available without claiming unconfigured',()=>{assert.ok(h.panel.innerHTML.includes('模型状态尚未确认'));assert.ok(h.panel.querySelector('[data-tc-model]').disabled);});
  h.input('shared 路径');const run=h.click('run');await tick();
  check('project question sends only its current id and fingerprint, defaults offline',()=>{assert.equal(h.last().url,'/api/snapshots/A/task-comparison/ask');assert.deepEqual(h.last().body,{question:'shared 路径',expected_context_sha256:hashes.A,use_model:false});});
  h.click('run');check('pending project question cannot be submitted twice',()=>assert.equal(h.posts().length,1));
  h.last().resolve(answer());await run;
  check('project fact links to its actual path and saved original excerpt',()=>{assert.ok(h.panel.innerHTML.includes('class="tc-path-chain"'));assert.ok(h.panel.innerHTML.includes('root → shared'));assert.ok(h.panel.innerHTML.includes('/packages/node_modules~1shared'));assert.ok(h.panel.innerHTML.includes('&quot;version&quot;'));assert.ok(h.panel.innerHTML.includes(url()));assert.ok(h.panel.innerHTML.includes('未评分'));});
  h.clickValue('fact','same-fact-id',0);
  check('clicking a fact retains its matching source and path',()=>{assert.ok(h.panel.innerHTML.includes('当前依据摘要'));assert.ok(h.panel.innerHTML.includes('shared 从项目根引入'));assert.ok(h.panel.innerHTML.includes('package-lock.json'));});
  h.event('lianzheng-model-updated',{configured:true});h.model(true);
  check('public model metadata enables explicit opt-in only',()=>assert.equal(h.api.state().use_model,true));
  h.input('late A');const slow=h.click('run');await tick();const old=h.last();old.ignoreAbort=true;
  h.event('lianzheng-snapshot-changing',{snapshot_id:'B',request:2});
  check('switch immediately aborts and clears question, model, response before workspace GET ends',()=>{assert.ok(old.signal.aborted);assert.equal(h.api.state().question,'');assert.equal(h.api.state().use_model,false);assert.equal(h.api.state().result,null);assert.equal(h.api.state().context,null);assert.ok(h.panel.querySelector('[data-tc-run]').disabled);});
  const count=h.posts().length;h.input('B draft while changing');h.click('run');
  check('project cannot submit while workspace is still loading',()=>assert.equal(h.posts().length,count));
  h.event('lianzheng-snapshot-changed',{snapshot:'B',analysis:{}});await tick();h.last().resolve(context('B'));await tick();
  await ask(h,'shared 路径',answer('shared 路径','B'));
  old.resolve(answer('late A'));await slow;
  check('late A with identical project names, refs and evidence ids cannot replace B',()=>{assert.equal(h.api.state().result.source.snapshot_id,'B');assert.ok(!h.panel.innerHTML.includes(url('A')));});
  const oldContextHash=h.api.state().context.source.context_sha256;
  h.event('lianzheng-project-evidence-changed',{snapshot_id:'B'});await tick();
  check('same-project document change immediately discards previous sources',()=>{assert.equal(h.api.state().context,null);assert.equal(h.api.state().result,null);assert.equal(h.api.state().use_model,false);assert.ok(h.panel.querySelector('[data-tc-run]').disabled);});
  h.last().resolve(context('B',hashes.updated));await tick();await ask(h,'new document question',answer('new document question','B',hashes.updated));
  check('new questions use the refreshed material fingerprint',()=>{assert.notEqual(h.api.state().context.source.context_sha256,oldContextHash);assert.equal(h.posts().at(-1).body.expected_context_sha256,hashes.updated);});
  h.input('stale server context');const conflict=h.click('run');await tick();h.last().resolve({detail:'项目证据已更新，请刷新上下文后重新提问。'},409);await conflict;
  check('409 invalidates context and exposes refresh without an automatic retry',()=>{assert.equal(h.api.state().context,null);assert.equal(h.api.state().question,'stale server context');assert.ok(!h.panel.innerHTML.includes('data-tc-offline'));assert.ok(h.panel.querySelector('[data-tc-run]').disabled);});
  const beforeRefresh=h.posts().length;const refresh=h.api.refresh();await tick();h.last().resolve(context('B'));await refresh;
  check('refresh only fetches context and preserves draft without paid retry',()=>{assert.equal(h.posts().length,beforeRefresh);assert.equal(h.api.state().question,'stale server context');});
  for(const [name,poison] of [
    ['different snapshot source',r=>r.source.snapshot_id='A'],
    ['stale context fingerprint',r=>r.source.context_sha256=hashes.updated],
    ['foreign evidence binding',r=>r.columns[0].evidence[0].snapshot_id='A'],
    ['case-scoped evidence with matching project ids',r=>r.columns[0].evidence[0].scope='case'],
    ['foreign fact binding',r=>r.columns[0].evidence_links.facts[0].snapshot_id='A'],
    ['foreign path binding',r=>r.columns[0].evidence_links.paths[0].snapshot_id='A'],
    ['foreign node binding',r=>r.columns[0].evidence_links.paths[0].nodes[0].context_sha256=hashes.A],
    ['foreign edge binding',r=>r.columns[0].evidence_links.paths[0].edges[0].snapshot_id='A'],
    ['foreign declared relation',r=>r.columns[0].evidence[0].relations[0].snapshot_id='A'],
    ['foreign path id',r=>r.columns[0].evidence_links.facts[0].path_ids=['other-project-path']],
    ['foreign links source',r=>r.columns[0].evidence_links.source.snapshot_id='A'],
    ['foreign evidence download URL',r=>r.columns[0].evidence[0].url=url('A')],
    ['external evidence download URL',r=>r.columns[0].evidence[0].url='https://example.com/source'],
    ['download URL with extra query',r=>r.columns[0].evidence[0].url+='&other=1'],
    ['foreign node download URL',r=>r.columns[0].evidence_links.paths[0].nodes[0].url=url('A')],
    ['foreign links-source download URL',r=>r.columns[0].evidence_links.source.url=url('A')],
  ]){
    const question='reject '+name,r=answer(question,'B');poison(r);await ask(h,question,r);
    check(name+' is rejected before rendering or export',()=>{assert.equal(h.api.state().result,null);assert.ok(h.api.state().error.includes('拒绝'));assert.ok(!h.panel.innerHTML.includes('data-tc-download'));});
  }
  const invented=answer('unsupported edge','B');for(const column of invented.columns)column.evidence_links.paths[0].edges[0].target='fabricated-ref';
  await ask(h,'unsupported edge',invented);
  check('correct project binding cannot make an undeclared edge appear as an actual path',()=>{assert.ok(h.api.state().result);assert.ok(!h.panel.innerHTML.includes('class="tc-path-chain"'));});
  h.api.configure({scope:'snapshot',snapshot_id:'A'});await tick();const delayedContext=h.last();delayedContext.ignoreAbort=true;
  h.event('lianzheng-snapshot-changing',{snapshot_id:'B',request:3});h.event('lianzheng-snapshot-changed',{snapshot:'B'});await tick();const newest=h.last();newest.resolve(context('B'));await tick();delayedContext.resolve(context('A'));await tick();
  check('late context A cannot overwrite ready context B',()=>{assert.equal(h.api.state().snapshot_id,'B');assert.equal(h.api.state().context.source.snapshot_id,'B');assert.equal(h.api.state().loading,false);assert.ok(delayedContext.signal.aborted);});
  h.event('lianzheng-snapshot-changing',{snapshot_id:'A',request:4});h.event('lianzheng-snapshot-change-failed',{snapshot_id:'A',request:4});h.input('unavailable A');const reads=h.calls.length;await h.api.refresh();h.click('run');
  check('failed workspace selection cannot restore stale context or ask',()=>{assert.equal(h.api.state().result,null);assert.equal(h.api.state().context,null);assert.equal(h.calls.length,reads);assert.ok(h.panel.querySelector('[data-tc-run]').disabled);});
  h.api.configure({scope:'case',mode:'fixed',phase:'before',expected_case_hash:'fixed-bundle',reset:true});const presenter=h.host();h.api.mount(presenter,{compact:true,lockScope:true});
  h.event('lianzheng-snapshot-changing',{snapshot_id:'B',request:5});h.event('lianzheng-snapshot-changed',{snapshot:'B'});h.event('lianzheng-project-evidence-changed',{snapshot_id:'B'});
  check('fixed case presentation remains fixed and hides project source selector',()=>{assert.equal(h.api.state().scope,'case');assert.equal(h.api.state().phase,'before');assert.equal(h.api.state().expected_case_hash,'fixed-bundle');assert.ok(!presenter.innerHTML.includes('data-tc-scope'));assert.ok(presenter.innerHTML.includes('固定 http-server'));});
  h.api.reset();check('reset safely restores offline fixed case',()=>{assert.equal(h.api.state().scope,'case');assert.equal(h.api.state().mode,'fixed');assert.equal(h.api.state().question,'固定案例问题');assert.equal(h.api.state().use_model,false);});
  const h2=harness();await tick();await ready(h2);h2.input('waiting');const loading=h2.api.refresh();await tick();h2.click('run');
  check('context refresh blocks submission despite preserved question',()=>assert.equal(h2.posts().length,0));
  h2.last().resolve(context());await loading;
  check('project questions are not persisted to browser storage',()=>{assert.ok(!/localStorage|sessionStorage|indexedDB/.test(code));});
  await workspaceTests(check);
  if(process.argv[2]){
    const fixture=JSON.parse(fs.readFileSync(process.argv[2],'utf8')),real=harness();await tick();
    real.api.configure({scope:'snapshot',snapshot_id:fixture.context.source.snapshot_id,mode:'free'});await tick();real.last().resolve(fixture.context);await tick();
    await ask(real,fixture.result.task.question,fixture.result);
    const linkedFact=fixture.result.columns[1].evidence_links.facts.find(f=>f.path_ids.length);
    assert.ok(linkedFact,'backend fixture must contain a fact with a real dependency path');real.clickValue('fact',linkedFact.id,1);
    check('actual backend offline response satisfies project UI contract',()=>{assert.equal(real.api.state().error,'');assert.ok(real.api.state().result);assert.ok(real.panel.innerHTML.includes('class="tc-path-chain"'));assert.ok(real.panel.innerHTML.includes('保存的来源原文片段'));});
  }
  console.log(JSON.stringify({suite:'v0.10 project UI state protocol',passed,network_calls:0,real_model_calls:0,browser_layout_verified:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
