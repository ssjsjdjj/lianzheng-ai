/* Project-brief UI protocol in a minimal DOM. No network, server or model calls.
 * This verifies state and bindings; real browser appearance is checked separately.
 */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const code=fs.readFileSync(path.join(__dirname,'../static/project-brief.js'),'utf8');
const hashes={A:'a'.repeat(64),B:'b'.repeat(64),updated:'c'.repeat(64)};
const clone=value=>JSON.parse(JSON.stringify(value));
const decode=value=>value.replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&amp;/g,'&');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function context(id='A',hash=hashes[id]){
  const binding={scope:'snapshot',snapshot_id:id,context_sha256:hash};
  return {available:true,source:{...binding},brief:{...binding,project:'实际项目 '+id,label:'已导入清单 '+id,format:'npm-package-lock',component_count:8,checked_components:2,unknown_components:6,graph_complete:false,knowledge_documents:1,issue_count:2,
    suggestions:[{id:'component-path',label:'查实际组件',question:'alpha-'+id+' 的依赖路径是什么？'},{id:'coverage',label:'确认材料缺口',question:'当前 '+id+' 有哪些组件身份或查询记录尚待确认？'},{id:'documents',label:'查项目文档',question:'当前 '+id+' 项目文档补充了哪些信息？'}],notes:['未进行查询的位置保持未知。']}};
}
function harness(options={}){
  const nodes=[],jobs=[],calls=[],opens=[],events=[],timers=[],listeners=new Map();
  class Element{
    constructor(tag='div'){this.tagName=tag.toUpperCase();this._html='';this.attrs={};this.fields=null;this.listeners={};this.dataset={};this.scrolled=0;nodes.push(this);}
    set innerHTML(value){this._html=value;this.fields=null;}get innerHTML(){return this._html;}
    setAttribute(name,value){this.attrs[name]=value;}getAttribute(name){return this.attrs[name]??null;}hasAttribute(name){return name in this.attrs;}
    after(node){this.afterNode=node;}scrollIntoView(){this.scrolled++;}focus(){document.activeElement=this;}
    addEventListener(name,fn){this.listeners[name]=fn;}
    querySelectorAll(selector){
      const attr=selector.match(/^\[([^\]]+)\]$/)?.[1];if(!attr)return [];
      if(!this.fields){this.fields=[];for(const match of this.innerHTML.matchAll(/<button\b([^>]*)>/g)){
        const element=new Element('button');for(const attribute of match[1].matchAll(/([\w-]+)(?:="([^"]*)")?/g)){const name=attribute[1],value=decode(attribute[2]||'');element.attrs[name]=value;if(name.startsWith('data-'))element.dataset[name.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=value;}
        element.disabled=element.hasAttribute('disabled');this.fields.push(element);
      }}return this.fields.filter(e=>e.hasAttribute(attr));
    }
    querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
    click(){return this.disabled?undefined:this.listeners.click?.({target:this});}
  }
  const anchor=new Element(),document={activeElement:null,querySelector:selector=>selector==='.snapshot-toolbar'&&!options.noAnchor?anchor:null,createElement:tag=>new Element(tag)};
  const window={lianzhengTaskCompare:{open:async value=>{opens.push(clone(value));if(options.openError)throw Error('missing comparison');}},addEventListener:(name,fn)=>{if(!listeners.has(name))listeners.set(name,[]);listeners.get(name).push(fn);},dispatchEvent:event=>{events.push(event);for(const fn of listeners.get(event.type)||[])fn(event);}};
  const globals={document,window,AbortController,CustomEvent:class{constructor(type,init){this.type=type;this.detail=init.detail;}},console,
    escapeHTML:value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
    setTimeout:(fn,ms)=>{const timer={fn,ms,active:true};timers.push(timer);return timer;},clearTimeout:timer=>{if(timer)timer.active=false;},
    fetch:(url,options)=>{
      const call={url,method:options.method,body:options.body,signal:options.signal};calls.push(call);
      return new Promise((resolve,reject)=>{const job={...call,ignoreAbort:false,resolve:(data,status=200)=>resolve({ok:status<400,status,json:async()=>data}),reject};jobs.push(job);options.signal.addEventListener('abort',()=>{if(!job.ignoreAbort){const error=new Error('aborted');error.name='AbortError';reject(error);}});});
    }};
  if(options.workspace)globals.state=options.workspace;
  vm.runInContext(code,vm.createContext(globals));
  const panel=nodes.find(n=>n.id==='project-brief');
  return {api:window.lianzhengProjectBrief,anchor,panel,document,calls,opens,events,timers,jobs,last:()=>jobs.at(-1),event:(name,detail)=>window.dispatchEvent({type:name,detail}),
    click:name=>panel.querySelector('[data-pb-'+name+']')?.click(),
    question:id=>panel.querySelectorAll('[data-pb-question]').find(n=>n.dataset.pbQuestion===id),
    timeout(){for(const timer of timers.filter(t=>t.active)){timer.active=false;timer.fn();}},
  };
}
async function select(h,id='A',data=context(id)){
  h.event('lianzheng-snapshot-changing',{snapshot_id:id,request:h.jobs.length+1});h.event('lianzheng-snapshot-changed',{snapshot:id});h.last().resolve(data);await tick();
}
function workspaceHarness(options={}){
  const source=fs.readFileSync(path.join(__dirname,'../static/app.js'),'utf8'),nodes=new Map(),jobs=[],events=[],opens=[],openJobs=[],briefs=[],notices=[],views=[],knowledge=[],knowledgeJobs=[],snapshotJobs=[];
  const analysis=id=>({snapshot:{id},nodes:[{package_name:'minimist-'+id,package_version:'1.2.5',scan_status:'unscanned'}]});
  const state={id:'A',request:0,analysis:analysis('A'),switchingSnapshot:false,documents:[],history:[],turns:[],parentId:null};
  class Node{
    constructor(){this.value='';this.textContent='';this.innerHTML='';this.files=[];this.open=false;this.closed=0;this.listeners={};this.disabled=false;}
    reset(){for(const id of ['#document-title','#document-target','#document-url','#document-text'])get(id).value='';get('#document-binding').value='0';get('#document-kind').value='project';}
    showModal(){this.open=true;}close(){this.open=false;this.closed++;}addEventListener(name,fn){this.listeners[name]=fn;}
  }
  const get=id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);};
  const scope=vm.createContext({state,$:get,$$:()=>[],TextDecoder,console,escapeHTML:value=>String(value??''),
    CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail;}},
    api:(url,options={})=>new Promise((resolve,reject)=>jobs.push({url,method:options.method||'GET',body:options.body?JSON.parse(options.body):null,resolve,reject})),
    busy:async(_button,_text,action)=>{try{return await action();}catch(error){notices.push(error.message);return null;}},
    toast:message=>notices.push(message),changeView:view=>views.push(view),stopWaiting(){},renderConversation(){},renderAnalysis(){},
    refreshKnowledge:(snapshot,serial)=>{knowledge.push({snapshot,serial});return options.holdKnowledge?new Promise((resolve,reject)=>knowledgeJobs.push({resolve,reject})):Promise.resolve();},refreshHistory:async()=>{},
    loadSnapshots:()=>options.holdSnapshotList?new Promise(resolve=>snapshotJobs.push({resolve})):Promise.resolve(),
    window:{dispatchEvent:event=>events.push(event),lianzhengTaskCompare:{open:value=>{opens.push(clone(value));return options.holdOpen?new Promise(resolve=>openJobs.push({resolve})):Promise.resolve();}},lianzhengProjectBrief:{open:async()=>{briefs.push(state.id);}}},
  });
  for(const name of ['selectSnapshot','importFile','openDocument','importDocument']){
    const start=source.search(new RegExp('(?:async )?function '+name+'\\(')),end=source.slice(start+1).search(/\n(?:async )?function \w+\(/);
    assert.ok(start>=0&&end>=0,'root function '+name+' has source boundaries');vm.runInContext(source.slice(start,start+1+end),scope);
  }
  const fileStart=source.indexOf("$('#document-file').addEventListener('change',async()=>{"),fileEnd=source.indexOf('\n});',fileStart);
  assert.ok(fileStart>=0&&fileEnd>fileStart);vm.runInContext(source.slice(fileStart,fileEnd+4),scope);
  const event={preventDefault(){}};
  return {state,get,jobs,events,opens,openJobs,briefs,notices,views,knowledge,knowledgeJobs,snapshotJobs,analysis,last:()=>jobs.at(-1),
    select:scope.selectSnapshot,open:options=>scope.openDocument(options),submit:()=>scope.importDocument(event),
    import(){get('#bom-file').files=[{size:100,text:async()=>'{"lockfileVersion":3}'}];get('#import-project').value='imported project';get('#import-label').value='new';get('#import-dialog').showModal();return scope.importFile(event);},
    fill(text='current project notes'){get('#document-title').value='project note';get('#document-binding').value='0';get('#document-text').value=text;},
    posts:()=>jobs.filter(job=>job.method==='POST'),
  };
}
async function finishWorkspaceSelection(h,id,pending){h.last().resolve(h.analysis(id));await tick();if(h.knowledgeJobs.length)h.knowledgeJobs.at(-1).resolve();await pending;}
async function workspaceTests(check){
  const switched=workspaceHarness();switched.open({returnToQuestion:true});switched.fill();const selecting=switched.select('B');await switched.submit();
  check('workspace switch closes and invalidates the document session before any stale submit',()=>{assert.equal(switched.state.documentSession,null);assert.equal(switched.get('#document-dialog').open,false);assert.equal(switched.posts().length,0);assert.ok(switched.notices.at(-1).includes('项目已切换'));});
  await finishWorkspaceSelection(switched,'B',selecting);
  switched.open();switched.state.switchingSnapshot=true;await switched.submit();
  check('a document cannot be submitted while workspace selection is in progress',()=>assert.equal(switched.posts().length,0));

  const late=workspaceHarness();late.open({returnToQuestion:true});late.fill('A only');const savingA=late.submit(),oldPost=late.last();const selectingB=late.select('B');await finishWorkspaceSelection(late,'B',selectingB);late.open({returnToQuestion:true});late.fill('B only');const savingB=late.submit(),newPost=late.last(),sessionB=late.state.documentSession,closeCount=late.get('#document-dialog').closed;
  oldPost.resolve({chunk_count:1});await savingA;
  check('late A document success cannot close or enable the newer B submission',()=>{assert.equal(late.state.documentSession,sessionB);assert.equal(late.get('#document-dialog').open,true);assert.equal(late.get('#document-dialog').closed,closeCount);assert.equal(late.get('#document-submit').disabled,true);assert.equal(sessionB.submitting,true);assert.equal(late.opens.length,0);assert.deepEqual(late.posts().map(job=>[job.url,job.body.text]),[['/api/snapshots/A/documents','A only'],['/api/snapshots/B/documents','B only']]);assert.equal(late.events.at(-1).detail.snapshot_id,'A');});
  newPost.resolve({chunk_count:2});await savingB;
  check('current document success returns to the same question scope without resetting its baseline',()=>{assert.deepEqual(late.opens,[{scope:'snapshot',snapshot_id:'B',mode:'free'}]);assert.equal(late.get('#document-dialog').open,false);assert.equal(late.get('#document-submit').disabled,false);assert.equal(late.state.id,'B');assert.equal(late.events.at(-1).type,'lianzheng-project-evidence-changed');assert.equal(late.events.at(-1).detail.snapshot_id,'B');assert.ok(late.notices.at(-1).includes('明确点击重新提问'));});

  const reopened=workspaceHarness();reopened.open({returnToQuestion:true});reopened.fill();const firstSave=reopened.submit(),firstPost=reopened.last();reopened.open({returnToQuestion:false});const newerSession=reopened.state.documentSession;firstPost.resolve({chunk_count:1});await firstSave;
  check('reopening a document for the same project also invalidates old dialog callbacks',()=>{assert.equal(reopened.state.documentSession,newerSession);assert.equal(reopened.get('#document-dialog').open,true);assert.equal(reopened.get('#document-submit').disabled,false);assert.equal(reopened.opens.length,0);assert.equal(reopened.knowledge.length,0);});

  const duplicate=workspaceHarness();duplicate.open();duplicate.fill();const active=duplicate.submit();await duplicate.submit();
  check('duplicate document submits cannot produce a second POST while the session is pending',()=>assert.equal(duplicate.posts().length,1));
  duplicate.last().reject(Error('temporary document service failure'));await active;
  check('a current document failure preserves the form and permits an explicit retry',()=>{assert.equal(duplicate.get('#document-dialog').open,true);assert.equal(duplicate.get('#document-submit').disabled,false);assert.equal(duplicate.get('#document-text').value,'current project notes');assert.ok(duplicate.notices.at(-1).includes('temporary document'));});

  const delayedList=workspaceHarness({holdKnowledge:true});delayedList.open({returnToQuestion:true});delayedList.fill();const delayedSave=delayedList.submit();delayedList.last().resolve({chunk_count:1});await tick();delayedList.open({returnToQuestion:false});const currentSession=delayedList.state.documentSession;delayedList.knowledgeJobs[0].resolve();await delayedSave;
  check('a delayed post-save document refresh cannot return a newer form to an old question',()=>{assert.equal(delayedList.state.documentSession,currentSession);assert.equal(delayedList.get('#document-dialog').open,true);assert.equal(delayedList.opens.length,0);});

  const file=workspaceHarness();file.open();let resolveFile;file.get('#document-file').files=[{size:100,name:'old-A.txt',arrayBuffer:()=>new Promise(resolve=>resolveFile=resolve)}];const reading=file.get('#document-file').listeners.change();file.open();file.fill('new form text');resolveFile(new TextEncoder().encode('old A file body').buffer);await reading;
  check('a late local file read cannot insert old text into a newly opened document form',()=>assert.equal(file.get('#document-text').value,'new form text'));

  const importEarly=workspaceHarness();const early=importEarly.import();await tick();const create=importEarly.last(),chooseB=importEarly.select('B');await finishWorkspaceSelection(importEarly,'B',chooseB);create.resolve({snapshot:{id:'imported'}});await early;
  check('a delayed import response saves its snapshot without switching away from the newer project',()=>{assert.equal(importEarly.state.id,'B');assert.equal(importEarly.jobs.filter(job=>job.url==='/api/snapshots/imported').length,0);assert.equal(importEarly.opens.length,0);assert.equal(importEarly.briefs.length,0);assert.ok(importEarly.notices.at(-1).includes('清单已保存'));});

  const importLate=workspaceHarness({holdOpen:true});const importing=importLate.import();await tick();importLate.last().resolve({snapshot:{id:'imported'}});await tick();importLate.last().resolve(importLate.analysis('imported'));await tick();assert.equal(importLate.opens.length,1);const lateSelection=importLate.select('B');await finishWorkspaceSelection(importLate,'B',lateSelection);importLate.openJobs[0].resolve();await importing;
  check('an import waiting for question context does not jump to a brief after another selection',()=>{assert.equal(importLate.state.id,'B');assert.equal(importLate.briefs.length,0);assert.ok(!importLate.notices.some(message=>message.includes('项目简报已就绪')));});

  const sameId=workspaceHarness({holdOpen:true});const importingSame=sameId.import();await tick();sameId.last().resolve({snapshot:{id:'imported'}});await tick();sameId.last().resolve(sameId.analysis('imported'));await tick();const reselect=sameId.select('imported');await finishWorkspaceSelection(sameId,'imported',reselect);sameId.openJobs[0].resolve();await importingSame;
  check('reselecting the same snapshot invalidates delayed import navigation by request identity',()=>assert.equal(sameId.briefs.length,0));

  const normal=workspaceHarness();const imported=normal.import();await tick();normal.last().resolve({snapshot:{id:'imported'}});await tick();normal.last().resolve(normal.analysis('imported'));await imported;
  check('normal import selects its project, prepares free questions, and ends on its brief',()=>{assert.deepEqual(normal.opens,[{scope:'snapshot',snapshot_id:'imported',mode:'free'}]);assert.deepEqual(normal.briefs,['imported']);assert.deepEqual(normal.views,['overview']);assert.equal(normal.get('#import-dialog').open,false);assert.ok(normal.notices.at(-1).includes('项目简报已就绪'));assert.equal(normal.posts().length,1);});
}
(async()=>{
  let passed=0;const check=(name,fn)=>{fn();passed++;console.log('PASS '+name);};
  const h=harness();
  check('new briefing follows the snapshot toolbar and makes no request before selection',()=>{assert.equal(h.anchor.afterNode,h.panel);assert.equal(h.panel.getAttribute('aria-label'),'当前项目简报');assert.equal(h.calls.length,0);assert.equal(h.panel.querySelectorAll('[data-pb-question]').length,0);});
  h.event('lianzheng-snapshot-changing',{snapshot_id:'A',request:1});
  check('pending workspace selection does not read a snapshot before selection succeeds',()=>{assert.equal(h.calls.length,0);assert.equal(h.panel.getAttribute('aria-busy'),'true');assert.ok(h.panel.innerHTML.includes('正在切换项目'));});
  h.event('lianzheng-snapshot-changed',{snapshot:'A'});
  check('successful selection only reads its own current context',()=>{assert.equal(h.calls.length,1);assert.equal(h.last().url,'/api/snapshots/A/task-comparison/context');assert.equal(h.last().method,'GET');assert.equal(h.last().body,undefined);assert.ok(h.panel.innerHTML.includes('正在核对'));});
  h.last().resolve(context());await tick();
  check('brief displays actual identity, counts and unknown coverage without claiming safety',()=>{assert.equal(h.api.state().brief.component_count,8);assert.ok(h.panel.innerHTML.includes('实际项目 A'));assert.ok(h.panel.innerHTML.includes('已导入清单 A'));assert.ok(h.panel.innerHTML.includes('6 个位置的漏洞状态仍未确认'));assert.ok(h.panel.innerHTML.includes('依赖关系存在缺口'));assert.ok(h.panel.innerHTML.includes('查询完成不表示项目全部安全'));assert.equal(h.panel.querySelectorAll('[data-pb-question]').length,3);assert.equal(h.panel.getAttribute('aria-busy'),'false');});
  const reads=h.calls.length;await h.question('component-path').click();
  check('suggestion only opens the current project question draft without a query or model call',()=>{assert.deepEqual(h.opens,[{scope:'snapshot',snapshot_id:'A',mode:'free',question:'alpha-A 的依赖路径是什么？'}]);assert.equal(h.calls.length,reads);});
  h.click('document');
  check('supplement action identifies exactly the current snapshot',()=>{assert.deepEqual(clone(h.events.at(-1).detail),{snapshot_id:'A'});assert.equal(h.events.at(-1).type,'lianzheng-open-project-document');assert.equal(h.calls.length,reads);});
  h.api.open();
  check('open scrolls and focuses the loaded brief without re-reading or invoking model',()=>{assert.equal(h.document.activeElement,h.panel);assert.equal(h.panel.scrolled,1);assert.equal(h.calls.length,reads);assert.equal(h.opens.length,1);});
  const detachedQuestion=h.question('component-path'),detachedDocument=h.panel.querySelector('[data-pb-document]');
  h.event('lianzheng-snapshot-changing',{snapshot_id:'B',request:2});await detachedQuestion.click();detachedDocument.click();
  check('switch clears all previous project text and detached actions immediately',()=>{assert.equal(h.api.state().brief,null);assert.ok(!h.panel.innerHTML.includes('实际项目 A'));assert.equal(h.opens.length,1);assert.equal(h.events.filter(e=>e.type==='lianzheng-open-project-document').length,1);});
  h.event('lianzheng-snapshot-changed',{snapshot:'B'});const slow=h.last();slow.ignoreAbort=true;
  h.event('lianzheng-snapshot-changing',{snapshot_id:'A',request:3});h.event('lianzheng-snapshot-changed',{snapshot:'A'});h.last().resolve(context());await tick();slow.resolve(context('B'));await tick();
  check('a late aborted context cannot replace the selected project even with identical button ids',()=>{assert.ok(slow.signal.aborted);assert.equal(h.api.state().brief.snapshot_id,'A');assert.ok(!h.panel.innerHTML.includes('实际项目 B'));assert.equal(h.api.state().loading,false);});
  const beforeOtherEvidence=h.calls.length;h.event('lianzheng-project-evidence-changed',{snapshot_id:'B'});
  check('another project evidence event does not alter or read the current brief',()=>{assert.equal(h.calls.length,beforeOtherEvidence);assert.equal(h.api.state().brief.snapshot_id,'A');});
  const preUpdateQuestion=h.question('component-path');h.event('lianzheng-project-evidence-changed',{snapshot_id:'A'});await preUpdateQuestion.click();
  check('document changes discard old brief and block detached questions until revalidated',()=>{assert.equal(h.api.state().brief,null);assert.equal(h.api.state().loading,true);assert.ok(!h.panel.innerHTML.includes('实际项目 A'));assert.equal(h.opens.length,1);});
  const updated=context('A',hashes.updated);updated.brief.knowledge_documents=2;updated.brief.notes=['新增发布文档已纳入当前资料。'];h.last().resolve(updated);await tick();
  check('refreshed evidence uses the new fingerprint and document count',()=>{assert.equal(h.api.state().brief.context_sha256,hashes.updated);assert.equal(h.api.state().brief.knowledge_documents,2);assert.ok(h.panel.innerHTML.includes('新增发布文档已纳入当前资料'));});
  await preUpdateQuestion.click();
  check('detached questions tied to an old same-project fingerprint remain unusable',()=>assert.equal(h.opens.length,1));
  for(const [name,mutate] of [
    ['source snapshot mismatch',data=>data.source.snapshot_id='B'],
    ['brief snapshot mismatch',data=>data.brief.snapshot_id='B'],
    ['brief hash mismatch',data=>data.brief.context_sha256=hashes.updated],
    ['case scope',data=>data.brief.scope='case'],
    ['missing identity',data=>delete data.source.context_sha256],
    ['negative count',data=>data.brief.checked_components=-1],
    ['inconsistent counts',data=>data.brief.checked_components=8],
    ['duplicate suggested ids',data=>data.brief.suggestions[1].id=data.brief.suggestions[0].id],
  ]){
    const pending=h.api.refresh(),data=context();mutate(data);h.last().resolve(data);await pending;
    check(name+' is rejected before showing project content or actions',()=>{assert.equal(h.api.state().brief,null);assert.ok(h.api.state().error.includes('不一致'));assert.equal(h.panel.querySelectorAll('[data-pb-question]').length,0);assert.ok(!h.panel.innerHTML.includes('实际项目 A'));assert.equal(h.panel.querySelector('[data-pb-document]'),null);});
  }
  const recover=h.api.refresh();h.last().resolve(context());await recover;
  const fail=h.api.refresh();h.last().resolve({detail:'sensitive internal diagnostic'},503);await fail;
  check('service errors clear the previous brief without leaking diagnostics or inventing sources',()=>{assert.equal(h.api.state().brief,null);assert.ok(h.api.state().error.includes('暂不可读'));assert.ok(!h.panel.innerHTML.includes('实际项目 A'));assert.ok(!h.panel.innerHTML.includes('sensitive'));assert.equal(h.panel.querySelector('[data-pb-refresh]').disabled,false);});
  const beforeRetry=h.calls.length;h.click('refresh');h.click('refresh');
  check('retry is explicit and duplicate refresh clicks cannot issue concurrent reads',()=>assert.equal(h.calls.length,beforeRetry+1));
  h.last().resolve(context());await tick();const timed=h.api.refresh();h.timeout();await timed;
  check('timeout leaves a retryable empty brief rather than cached previous content',()=>{assert.equal(h.api.state().brief,null);assert.ok(h.api.state().error.includes('超时'));assert.equal(h.api.state().loading,false);assert.equal(h.panel.querySelector('[data-pb-refresh]').disabled,false);});
  const beforeOpen=h.calls.length;h.api.open();
  check('open after an error may reread context but never runs a suggested query',()=>{assert.equal(h.calls.length,beforeOpen+1);assert.equal(h.opens.length,1);});
  h.last().resolve(context());await tick();
  h.event('lianzheng-snapshot-changing',{snapshot_id:'B',request:4});h.event('lianzheng-snapshot-change-failed',{snapshot_id:'B',request:3});
  check('outdated failure events cannot cancel a later workspace selection',()=>{assert.equal(h.api.state().error,'');assert.equal(h.api.state().switching,true);});
  h.event('lianzheng-snapshot-change-failed',{snapshot_id:'B',request:4});const readsAfterFailure=h.calls.length;h.api.open();await h.api.refresh();
  check('failed selection does not restore an older project or read the unselected snapshot',()=>{assert.equal(h.api.state().brief,null);assert.equal(h.api.state().switching,true);assert.equal(h.calls.length,readsAfterFailure);assert.ok(h.api.state().error.includes('未载入成功'));});
  const escaped=context('B');escaped.brief.project='<img src=x onerror="bad()">';escaped.brief.notes=['<script>bad()</script>'];escaped.brief.suggestions[0].label='x" onclick="bad()';escaped.brief.suggestions[0].question='<svg onload="bad()">';await select(h,'B',escaped);
  check('project fields, notes and suggestions are rendered as escaped text',()=>{assert.ok(!h.panel.innerHTML.includes('<img'));assert.ok(!h.panel.innerHTML.includes('<script>'));assert.ok(!h.panel.innerHTML.includes('<svg'));assert.ok(h.panel.innerHTML.includes('&lt;svg'));assert.ok(h.panel.innerHTML.includes('&quot;'));});
  const empty=context('A');empty.brief.component_count=0;empty.brief.checked_components=0;empty.brief.unknown_components=0;empty.brief.suggestions=[];await select(h,'A',empty);
  check('empty evidence does not fabricate component questions',()=>{assert.equal(h.panel.querySelectorAll('[data-pb-question]').length,0);assert.ok(h.panel.innerHTML.includes('当前材料尚不足'));});
  const demo=context('A');demo.brief.checked_components=0;demo.brief.unknown_components=0;await select(h,'A',demo);
  check('demo-status components need not be counted as live-checked or unknown',()=>assert.equal(h.api.state().brief.component_count,8));
  const bootstrap=harness({workspace:{id:'A',switchingSnapshot:false,analysis:{snapshot:{id:'A'},project:'OLD ANALYSIS SHOULD NEVER RENDER'}}});bootstrap.last().resolve(context());await tick();
  check('late script initialization only uses selected identity and fetches fresh brief fields',()=>{assert.equal(bootstrap.calls.length,1);assert.ok(bootstrap.panel.innerHTML.includes('实际项目 A'));assert.ok(!bootstrap.panel.innerHTML.includes('OLD ANALYSIS'));});
  const mismatch=harness({workspace:{id:'A',switchingSnapshot:false,analysis:{snapshot:{id:'B'}}}}),switching=harness({workspace:{id:'A',switchingSnapshot:true,analysis:{snapshot:{id:'A'}}}});
  check('inconsistent or switching workspace state cannot bootstrap a brief from stale analysis',()=>{assert.equal(mismatch.calls.length,0);assert.equal(switching.calls.length,0);});
  const missing=harness({noAnchor:true});
  check('a page without the workspace anchor is left untouched',()=>{assert.equal(missing.api,undefined);assert.equal(missing.calls.length,0);assert.equal(missing.panel,undefined);});
  const encoded=harness();const encodedId='项目 A/1';await select(encoded,encodedId,context(encodedId,hashes.A));
  check('snapshot identity is URI-encoded and never used as a remote destination',()=>assert.equal(encoded.last().url,'/api/snapshots/'+encodeURIComponent(encodedId)+'/task-comparison/context'));
  check('every request in the brief lifecycle is a local context GET without a body',()=>{for(const run of [h,bootstrap,mismatch,switching,missing,encoded])for(const call of run.calls){assert.equal(call.method,'GET');assert.equal(call.body,undefined);assert.match(call.url,/^\/api\/snapshots\/[^/]+\/task-comparison\/context$/);}assert.ok(!/localStorage|sessionStorage|indexedDB/.test(code));});
  await workspaceTests(check);
  if(process.argv[2]){
    const data=JSON.parse(fs.readFileSync(process.argv[2],'utf8')),actual=data.context||data,real=harness();await select(real,actual.source.snapshot_id,actual);
    check('actual backend context satisfies the project briefing contract',()=>{assert.equal(real.api.state().error,'');assert.ok(real.api.state().brief);assert.equal(real.api.state().brief.context_sha256,actual.source.context_sha256);});
  }
  console.log(JSON.stringify({suite:'v0.11 project-brief UI protocol',passed,network_calls:0,real_model_calls:0,browser_layout_verified:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
