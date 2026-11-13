/* v0.11 answer-card and material-change protocol in a minimal DOM. No server, secret or network.
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
      if(!this.fields){this.fields=[];for(const match of this.innerHTML.matchAll(/<(button|input|textarea|select|small|details)\b([^>]*)>/g)){
        const element=new Element(match[1]);for(const attribute of match[2].matchAll(/([\w-]+)(?:="([^"]*)")?/g)){const name=attribute[1],value=decode(attribute[2]||'');element.attrs[name]=value;if(name.startsWith('data-'))element.dataset[name.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=value;}
        element.open=element.hasAttribute('open');element.disabled=element.hasAttribute('disabled');element.checked=element.hasAttribute('checked');this.fields.push(element);
      }}
      return this.fields.filter(e=>e.hasAttribute(attr));
    }
    querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
    click(){return this.disabled?undefined:this.listeners.click?.({target:this});}
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
async function ready(h,id='A',hash=hashes[id]){h.api.configure({scope:'snapshot',snapshot_id:id,mode:'free',reset:true});await tick();h.last().resolve(context(id,hash));await tick();}
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
(async()=>{
  let passed=0;const check=(name,fn)=>{fn();passed++;console.log('PASS '+name);};
  const h=harness();await tick();
  const opening=h.api.open({scope:'snapshot',snapshot_id:'A',mode:'free',question:'shared 路径'});await tick();h.last().resolve(context());await opening;
  check('brief question API fills only and never submits',()=>{assert.equal(h.api.state().question,'shared 路径');assert.equal(h.posts().length,0);assert.equal(h.api.state().use_model,false);});
  await rerun(h,v11Answer());
  check('snapshot leads with bounded answer card and collapsed technical columns',()=>{assert.ok(h.panel.innerHTML.includes('当前项目答案卡'));assert.ok(h.panel.innerHTML.indexOf('当前项目答案卡')<h.panel.innerHTML.indexOf('class="tc-columns"'));assert.equal(h.panel.querySelector('[data-tc-technical]').open,false);assert.ok(h.panel.innerHTML.includes('未绑定检索证据 · 提示或待确认项'));assert.ok(h.panel.innerHTML.includes('两侧使用同一模型解释（最多两次请求，可能计费）'));});
  h.clickValue('card-evidence','aaaaa-root',1);
  check('answer citation expands technical view and selects its own column evidence',()=>{assert.equal(h.panel.querySelector('[data-tc-technical]').open,true);assert.ok(h.panel.innerHTML.includes('保存片段 root'));assert.equal(h.api.state().result.columns[1].evidence[0].id,'aaaaa-root');});
  h.click('retain');const saved=h.api.state().baseline;
  check('explicit retention clones same-question history without live source URLs',()=>{assert.equal(saved.status,'historical-not-current');assert.equal(saved.question,'shared 路径');assert.equal(saved.source.context_sha256,hashes.A);assert.ok(saved.answered_at);assert.ok(saved.retained_at);assert.ok(saved.evidence[0].source_excerpt);assert.ok(!JSON.stringify(saved).includes('/api/'));assert.ok(h.panel.innerHTML.includes('历史记录，非当前状态'));});
  saved.answer_card.conclusion.text='changed through public state';h.api.state().result.columns[1].answer_card.conclusion.text='changed current response';
  check('historical copy cannot be changed through public state or original response mutation',()=>assert.ok(!h.api.state().baseline.answer_card.conclusion.text.includes('changed')));
  const beforeSupplement=h.posts().length;h.click('supplement');
  check('supplement action opens only the bound project document flow',()=>{const event=h.events.find(e=>e.type==='lianzheng-open-project-document');assert.equal(event.detail.snapshot_id,'A');assert.equal(event.detail.context_sha256,hashes.A);assert.equal(h.posts().length,beforeSupplement);});
  await updateContext(h);
  check('document update clears active sources but keeps clearly historical excerpts',()=>{assert.equal(h.api.state().result,null);assert.equal(h.api.state().baseline.source.context_sha256,hashes.A);assert.ok(!h.panel.innerHTML.includes(url()));assert.ok(h.panel.innerHTML.includes('保存片段 root'));assert.ok(h.panel.innerHTML.includes('资料已更新'));assert.equal(h.panel.querySelector('[data-tc-reask]').disabled,false);assert.equal(h.posts().length,beforeSupplement);assert.equal(h.api.state().use_model,false);});
  await rerun(h,v11Answer('shared 路径','A',hashes.updated,[{key:'root',hash:'1'},{key:'new-log',hash:'2'}]),'reask');
  check('explicit same-question rerun uses fresh context and records added evidence',()=>{assert.equal(h.last().body.expected_context_sha256,hashes.updated);assert.equal(h.last().body.use_model,false);assert.equal(changeCount(h.panel.innerHTML,'added'),1);assert.equal(changeCount(h.panel.innerHTML,'unchanged'),1);assert.equal(changeCount(h.panel.innerHTML,'removed'),0);assert.equal(changeCount(h.panel.innerHTML,'changed'),0);assert.ok(h.panel.innerHTML.includes('不证明回答更正确或修复已完成'));assert.ok(h.panel.innerHTML.includes('本次未取回依据'));assert.ok(h.panel.innerHTML.includes('不含全文逐句差异'));assert.ok(h.panel.innerHTML.includes('不代表资料已删除'));});
  h.click('download-change');const exported=JSON.parse(await h.downloads.at(-1).text());
  check('comparison export keeps frozen quotes and marks historical/current sources without URLs',()=>{assert.equal(exported.historical.status,'historical-not-current');assert.equal(exported.current.status,'current-at-export');assert.equal(exported.historical.source.context_sha256,hashes.A);assert.equal(exported.current.source.context_sha256,hashes.updated);assert.equal(exported.historical.evidence[0].source_excerpt,'保存片段 root');assert.equal(exported.changes.added.length,1);assert.ok(!JSON.stringify(exported).includes('/api/'));});
  h.click('retain');await updateContext(h,'d'.repeat(64));
  await rerun(h,v11Answer('shared 路径','A','d'.repeat(64),[{key:'root',hash:'3'},{key:'other',hash:'4'}]),'reask');
  check('stable identities distinguish content edits, removals and additions across context IDs',()=>{assert.equal(changeCount(h.panel.innerHTML,'added'),1);assert.equal(changeCount(h.panel.innerHTML,'removed'),1);assert.equal(changeCount(h.panel.innerHTML,'changed'),1);assert.equal(changeCount(h.panel.innerHTML,'unchanged'),0);});
  h.click('retain');await updateContext(h,'e'.repeat(64));
  await rerun(h,v11Answer('shared 路径','A','e'.repeat(64),[{key:'root',hash:'3'},{key:'other',hash:'4'}]),'reask');
  check('context and transient evidence IDs changing alone do not manufacture evidence changes',()=>{assert.equal(changeCount(h.panel.innerHTML,'added'),0);assert.equal(changeCount(h.panel.innerHTML,'removed'),0);assert.equal(changeCount(h.panel.innerHTML,'changed'),0);assert.equal(changeCount(h.panel.innerHTML,'unchanged'),2);});
  h.click('retain');await rerun(h,v11Answer('shared 路径','A','e'.repeat(64),[{key:'root',hash:'3'},{key:'other',hash:'4'}]));
  check('rerunning unchanged materials explicitly identifies the same fingerprint',()=>{assert.ok(h.panel.innerHTML.includes('两次材料指纹相同'));assert.equal(changeCount(h.panel.innerHTML,'changed'),0);});
  h.event('lianzheng-model-updated',{configured:true});h.model(true);const beforeRefresh=h.posts().length;
  await updateContext(h,'f'.repeat(64));
  check('material update turns off prior model opt-in and performs no model retry',()=>{assert.equal(h.api.state().use_model,false);assert.equal(h.posts().length,beforeRefresh);});
  const failed=h.click('reask');await tick();h.last().reject(new TypeError('offline'));await failed;
  check('failed new answer preserves old history without applying fresh context or stale current answer',()=>{assert.equal(h.api.state().result,null);assert.equal(h.api.state().baseline.source.context_sha256,'e'.repeat(64));assert.ok(h.panel.innerHTML.includes('新回答尚未成功'));assert.ok(!h.panel.innerHTML.includes(url('A','e'.repeat(64))));});
  h.click('download-change');const failedExport=JSON.parse(await h.downloads.at(-1).text());
  check('failed comparison export cannot label the old answer as current',()=>{assert.equal(failedExport.current,null);assert.equal(failedExport.changes,null);assert.equal(failedExport.historical.status,'historical-not-current');});
  const conflict=h.click('reask');await tick();h.last().resolve({detail:'materials changed'},409);await conflict;
  check('409 preserves independent history but removes ask eligibility and does not retry',()=>{assert.ok(h.api.state().baseline);assert.equal(h.api.state().context,null);assert.equal(h.panel.querySelector('[data-tc-reask]').disabled,true);assert.equal(h.api.state().result,null);});
  h.input('changed question');
  check('editing the question clears the comparison baseline synchronously',()=>{assert.equal(h.api.state().baseline,null);assert.ok(!h.panel.innerHTML.includes('tc-history-columns'));});
  await ready(h);await ask(h,'shared 路径',v11Answer());h.click('retain');await updateContext(h);
  const late=h.click('reask');await tick();const oldJob=h.last();oldJob.ignoreAbort=true;
  h.api.configure({scope:'snapshot',snapshot_id:'A',mode:'free',question:'another question'});oldJob.resolve(v11Answer('shared 路径','A',hashes.updated));await late;
  check('programmatic question edit cancels in-flight response and removes old comparison',()=>{assert.equal(h.api.state().question,'another question');assert.equal(h.api.state().baseline,null);assert.equal(h.api.state().result,null);assert.ok(oldJob.signal.aborted);});
  await ask(h,'shared 路径',v11Answer('shared 路径','A',hashes.updated));h.click('retain');
  h.click('run');await tick();const fromA=h.last();fromA.ignoreAbort=true;
  h.event('lianzheng-snapshot-changing',{snapshot_id:'B'});h.event('lianzheng-snapshot-changed',{snapshot:'B'});await tick();h.last().resolve(context('B'));await tick();await ask(h,'shared 路径',v11Answer('shared 路径','B'));fromA.resolve(v11Answer('shared 路径','A',hashes.updated));await tick();
  check('late response from A cannot restore its answer or historical material inside B',()=>{assert.equal(h.api.state().baseline,null);assert.equal(h.api.state().result.source.snapshot_id,'B');assert.ok(!h.panel.innerHTML.includes(url('A',hashes.updated)));});
  h.click('retain');h.api.configure({scope:'case',mode:'fixed'});
  check('fixed case selection clears imported-project history and preserves fixed rendering',()=>{assert.equal(h.api.state().baseline,null);assert.ok(!h.panel.innerHTML.includes('当前项目答案卡'));assert.equal(h.api.state().scope,'case');});
  for(const [label,poison] of [
    ['foreign card binding',d=>d.columns[1].answer_card.snapshot_id='B'],
    ['stale card fingerprint',d=>d.columns[1].answer_card.context_sha256=hashes.updated],
    ['foreign evidence citation',d=>d.columns[1].answer_card.reasons[0].evidence_ids=['unknown-evidence']],
    ['cross-column citation',d=>{d.columns[0].evidence[0].id='A-only';d.columns[0].evidence_links.facts[0].evidence_ids=['A-only'];for(const key of ['conclusion'])d.columns[0].answer_card[key].evidence_ids=['A-only'];d.columns[0].answer_card.reasons[0].evidence_ids=['A-only'];d.columns[1].answer_card.conclusion.evidence_ids=['A-only'];}],
  ]){
    await ready(h);const data=v11Answer();poison(data);await ask(h,'shared 路径',data);
    check(label+' is rejected before answer-card rendering or export',()=>{assert.equal(h.api.state().result,null);assert.ok(!h.panel.querySelector('[data-tc-retain]'));assert.ok(h.api.state().error);});
  }
  await ready(h);const dangerous=v11Answer();for(const c of dangerous.columns){c.answer_card.conclusion.text='<img src=x onerror=alert(1)>';c.answer_card.unknowns[0].text='<script>evil()</script>';c.evidence[0].source_excerpt='<svg onload=evil()>';c.evidence[0].title='<iframe src=javascript:evil()>';}
  await ask(h,'shared 路径',dangerous);h.click('retain');await updateContext(h);
  check('answer text and frozen excerpts escape markup without executable elements',()=>{assert.ok(h.panel.innerHTML.includes('&lt;img'));assert.ok(h.panel.innerHTML.includes('&lt;svg'));assert.ok(!h.panel.innerHTML.includes('<img'));assert.ok(!h.panel.innerHTML.includes('<script>'));assert.ok(!h.panel.innerHTML.includes('<iframe'));});
  await rerun(h,v11Answer('shared 路径','A',hashes.updated,[]),'reask');
  check('empty evidence safely renders unknown items and counts removed retrieved evidence',()=>{assert.equal(h.api.state().result.columns[1].evidence.length,0);assert.ok(h.panel.innerHTML.includes('尚无运行测试'));assert.equal(changeCount(h.panel.innerHTML,'removed'),1);});
  h.click('forget');
  check('explicit clear removes historical data without deleting current answer',()=>{assert.equal(h.api.state().baseline,null);assert.ok(h.api.state().result);});
  const delayedOpen=harness();await tick();const openingA=delayedOpen.api.open({scope:'snapshot',snapshot_id:'A',mode:'free',question:'A question'});await tick();const pendingA=delayedOpen.last();pendingA.ignoreAbort=true;
  delayedOpen.event('lianzheng-snapshot-changing',{snapshot_id:'B'});delayedOpen.event('lianzheng-snapshot-changed',{snapshot:'B'});await tick();delayedOpen.last().resolve(context('B'));await tick();pendingA.resolve(context('A'));await openingA;
  check('late open for A cannot scroll the workbench after B becomes active',()=>{assert.equal(delayedOpen.api.state().snapshot_id,'B');assert.equal(delayedOpen.panel.scrolls||0,0);assert.equal(delayedOpen.posts().length,0);});
  check('flow stores no historical data in browser persistence',()=>assert.ok(!/localStorage|sessionStorage|indexedDB/.test(code)));
  console.log(JSON.stringify({suite:'v0.11 answer and material change UI protocol',passed,network_calls:0,real_model_calls:0,browser_layout_verified:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
