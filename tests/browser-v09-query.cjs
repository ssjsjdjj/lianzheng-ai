/* UI state/protocol tests in a minimal DOM harness. No browser, server, API key or network.
 * These cover cancellation, stale responses, scope validation and unscored free questions;
 * layout and actual clicks are verified separately in browser acceptance.
 */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const code=fs.readFileSync(path.join(__dirname,'../static/task-compare.js'),'utf8');
const source={case_bundle_sha256:'bundle-a',commit:'fixed-commit',lockfile:'before.package-lock.json'};
const catalog={available:true,model_configured:true,source,tasks:[{id:'before-occurrences',question:'minimist 依赖路径是什么？',phase:'before'}],protocol:{statement:'same corpus'}};
function harness(){
  const nodes=[];let pendingFetch=[];const timers=[];const calls=[];
  class Element{
    constructor(tag='div'){this.tagName=tag.toUpperCase();this._html='';this.attrs={};this.fields=new Map();this.listeners={};this.dataset={};this.classList={add(){},toggle(){}};this.hidden=false;nodes.push(this);}
    set innerHTML(value){this._html=value;this.fields.clear();}get innerHTML(){return this._html;}
    setAttribute(name,value){this.attrs[name]=value;}append(){}replaceChildren(){this.innerHTML='';}scrollIntoView(){}focus(){document.activeElement=this;}setSelectionRange(){}
    addEventListener(name,fn){this.listeners[name]=fn;}
    querySelector(selector){const name=selector.match(/^\[([^\]]+)\]$/)?.[1];if(!name||!this.innerHTML.includes(name))return null;if(!this.fields.has(selector))this.fields.set(selector,new Element('input'));return this.fields.get(selector);}
    querySelectorAll(){return [];}
    click(){return this.listeners.click?.({target:this});}
  }
  const heading=new Element(),main=new Element();
  const document={activeElement:null,querySelector:s=>s==='.heading-actions'?heading:s==='main'?main:null,createElement:tag=>new Element(tag)};
  const window={dispatchEvent(){}};
  const context=vm.createContext({document,window,AbortController,Blob,URL,CustomEvent:class{constructor(type,init){this.type=type;this.detail=init.detail;}},console,
    escapeHTML:value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
    setTimeout:(fn,ms)=>{const t={fn,ms,active:true};timers.push(t);return t;},clearTimeout:t=>{if(t)t.active=false;},
    fetch:(url,options)=>{
      calls.push({url,body:options.body?JSON.parse(options.body):null,signal:options.signal});
      if(url.endsWith('/tasks'))return Promise.resolve({ok:true,json:async()=>catalog});
      return new Promise((resolve,reject)=>{const job={url,options,resolve:data=>resolve({ok:true,json:async()=>data}),reject,ignoreAbort:false};pendingFetch.push(job);options.signal.addEventListener('abort',()=>{if(!job.ignoreAbort){const e=new Error('aborted');e.name='AbortError';reject(e);}});});
    }});
  vm.runInContext(code,context);
  const panel=nodes.find(n=>n.id==='task-comparison-panel');
  return {api:window.lianzhengTaskCompare,panel,calls,timers,get pending(){return pendingFetch;},click(name){return panel.querySelector('[data-tc-'+name+']').click();},input(text){const e=panel.querySelector('[data-tc-question]');e.value=text;e.selectionStart=text.length;e.listeners.input({target:e});}};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function answer(question='minimist 路径',phase='before',kind='free'){
  const doc={id:'e1',title:'minimist 原始位置',phase,text:'minimist 依赖事实。',filename:phase+'.package-lock.json',url:'/api/real-case/files/'+phase+'.package-lock.json',locator:'/packages/node_modules~1minimist',ref:'minimist-ref',relations:[{source:'root',target:'minimist-ref'}],source_sha256:'abc',source_excerpt:'{"version":"1.2.5"}',kind:'occurrence'};
  const path={id:'p1',label:'root → minimist',nodes:[{ref:'root',name:'http-server',version:'14.1.0'},{ref:'minimist-ref',name:'minimist',version:'1.2.5'}],edges:[{source:'root',target:'minimist-ref',evidence_ids:['e1']}]};
  const column=id=>({id,method:id,generation:'offline-evidence',answer:'离线摘要',evidence:[doc],paths:['root → minimist'],metrics:{reference_found:null,reference_total:null,retrieved:1,connected_target_occurrences:1,retrieval_ms:1,evidence_bytes:100},evidence_links:{source:{...source,phase},paths:[path],facts:[{id:'fact1',text:'minimist 依赖事实。',evidence_ids:['e1'],path_ids:['p1'],kind:'retrieved-fact'}]}});
  return {release:'0.9.0',task:{id:kind==='fixed'?'before-occurrences':'free-hash',question,phase,kind:kind==='fixed'?'curated-task':'free-question'},source:{...source,lockfile:phase+'.package-lock.json'},fairness:{},columns:[column('bm25'),column('bm25+graph')],comparison:{result:kind==='fixed'?'tie':'unscored',note:'无预设答案'},limitations:[],model_calls_attempted:0};
}
(async()=>{
  let count=0;
  const check=(name,fn)=>{fn();count++;console.log('PASS '+name);};
  const h=harness();await tick();
  check('opening only reads catalog',()=>assert.equal(h.calls.filter(c=>c.body).length,0));
  h.api.configure({mode:'free',phase:'before',reset:true});h.input('  minimist 路径  ');
  const run=h.click('run');await tick();
  check('free request uses explicit phase and defaults offline',()=>assert.deepEqual(h.calls.at(-1).body,{question:'minimist 路径',phase:'before',use_model:false}));
  const pending=h.pending.at(-1);h.click('run');
  check('duplicate clicks do not submit again',()=>assert.equal(h.pending.length,1));
  pending.resolve(answer());await run;
  check('free result never renders invented scores or winner',()=>{assert.ok(h.panel.innerHTML.includes('未评分'));assert.ok(h.panel.innerHTML.includes('不计算得分或胜负'));assert.ok(!h.panel.innerHTML.includes('0/0'));});
  check('source and path originate in selected evidence',()=>{assert.ok(h.panel.innerHTML.includes('root → minimist'));assert.ok(h.panel.innerHTML.includes('before.package-lock.json'));assert.ok(h.panel.innerHTML.includes('&quot;version&quot;'));});
  h.input('after question');
  check('editing clears previous answer',()=>assert.equal(h.api.state().result,null));
  h.api.configure({phase:'after'});const slow=h.click('run');await tick();const old=h.pending.at(-1);old.ignoreAbort=true;h.click('stop');
  check('stop is local-only and preserves the question',()=>{assert.equal(h.api.state().running,false);assert.equal(h.api.state().question,'after question');assert.ok(h.api.state().error.includes('服务器可能仍在处理'));});
  h.input('new question');const next=h.click('run');await tick();h.pending.at(-1).resolve(answer('new question','after'));await next;
  old.resolve(answer('after question','after'));await slow;
  check('late response cannot replace a newer result',()=>assert.equal(h.api.state().result.task.question,'new question'));
  h.input('timed out');const timed=h.click('run');await tick();h.timers.filter(t=>t.active&&t.ms===30000).at(-1).fn();await timed;
  check('offline timeout preserves draft and exposes recovery',()=>{assert.equal(h.api.state().question,'timed out');assert.ok(h.api.state().error.includes('超时'));assert.ok(h.panel.innerHTML.includes('data-tc-offline'));});
  const toggle=h.panel.querySelector('[data-tc-model]');toggle.checked=true;toggle.listeners.change({target:toggle});const model=h.click('run');await tick();h.pending.at(-1).reject(new Error('simulated model unavailable'));await model;
  const retry=h.click('offline');await tick();
  check('explicit recovery always sends use_model false',()=>assert.equal(h.calls.at(-1).body.use_model,false));
  h.pending.at(-1).resolve(answer('timed out','after'));await retry;
  h.input('wrong phase');const wrong=h.click('run');await tick();h.pending.at(-1).resolve(answer('wrong phase','before'));await wrong;
  check('mismatched result is not displayed',()=>{assert.equal(h.api.state().result,null);assert.ok(h.api.state().error.includes('不一致'));});
  h.api.reset();
  check('reset returns to fixed before without model or stale answer',()=>{assert.equal(h.api.state().mode,'fixed');assert.equal(h.api.state().phase,'before');assert.equal(h.api.state().result,null);assert.equal(h.api.state().use_model,false);});
  h.api.configure({mode:'free',phase:'before'});h.input('<img src=x onerror=alert(1)>');const escaped=h.click('run');await tick();h.pending.at(-1).resolve(answer('<img src=x onerror=alert(1)>'));await escaped;
  check('free text is escaped in DOM',()=>{assert.ok(h.panel.innerHTML.includes('&lt;img'));assert.ok(!h.panel.innerHTML.includes('<img src=x'));});
  h.input('tampered evidence');const bad=h.click('run');await tick();const poisoned=answer('tampered evidence');poisoned.columns[0].evidence_links.paths[0].edges[0].evidence_ids=['other-column'];h.pending.at(-1).resolve(poisoned);await bad;
  check('cross-column edge citation is rejected',()=>{const a=h.panel.innerHTML.split('aria-label="A 结论与证据联动"')[1].split('aria-label="B 结论与证据联动"')[0];assert.ok(!a.includes('class="tc-path-chain"'));});
  h.api.configure({mode:'free',phase:'before',expected_case_hash:'different-bundle'});h.input('pinned question');const pinned=h.click('run');await tick();h.pending.at(-1).resolve(answer('pinned question'));await pinned;
  check('presentation source pin rejects changed case bytes',()=>{assert.equal(h.api.state().result,null);assert.ok(h.api.state().error.includes('材料'));});
  h.api.configure({expected_case_hash:null});h.input('log question');const log=h.click('run');await tick();const logged=answer('log question');for(const col of logged.columns){col.evidence[0].kind='test';col.evidence[0].source_excerpt_kind='raw-log';col.evidence[0].source_excerpt='2 failing';col.evidence_links.paths=[];col.evidence_links.facts[0].path_ids=[];}h.pending.at(-1).resolve(logged);await log;
  check('log evidence shows raw log without an invented dependency path',()=>{assert.ok(h.panel.innerHTML.includes('保存的原始日志片段'));assert.ok(h.panel.innerHTML.includes('没有对应依赖路径'));assert.ok(!h.panel.innerHTML.includes('class="tc-path-chain"'));});
  h.input('slow model');const opt=h.panel.querySelector('[data-tc-model]');opt.checked=true;opt.listeners.change({target:opt});const modelTimeout=h.click('run');await tick();h.timers.filter(t=>t.active&&t.ms===100000).at(-1).fn();await modelTimeout;
  check('model timeout does not retry automatically',()=>{assert.ok(h.api.state().error.includes('计费'));assert.equal(h.api.state().running,false);assert.equal(h.calls.at(-1).body.use_model,true);});
  const beforeRefresh=h.calls.filter(c=>c.body).length;await h.api.refresh();
  check('refresh only reads status and never retries a paid request',()=>assert.equal(h.calls.filter(c=>c.body).length,beforeRefresh));
  console.log(JSON.stringify({suite:'v0.9 UI state protocol',passed:count,network_calls:0,real_model_calls:0,browser_layout_verified:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
