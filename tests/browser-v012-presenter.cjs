/* Current-project presentation protocol in a minimal DOM. No server/model calls.
 * Layout, native fullscreen and real downloaded bytes are separate browser checks.
 */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const code=fs.readFileSync(path.join(__dirname,'../static/project-presenter.js'),'utf8');
const clone=value=>JSON.parse(JSON.stringify(value));
const hash={A:'a'.repeat(64),B:'b'.repeat(64),new:'c'.repeat(64)};
const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const decode=value=>value.replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&amp;/g,'&');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function fixture(id='A',digest=hash[id]){
  const source={scope:'snapshot',snapshot_id:id,context_sha256:digest,project:'项目 '+id,label:'导入清单 '+id};
  const brief={...source,format:'npm-package-lock',component_count:8,checked_components:2,unknown_components:6,knowledge_documents:1,issue_count:1,graph_complete:false,notes:['未扫描的位置保持未知。'],suggestions:[]};
  const item={text:'已发现一条依赖路径。',evidence_ids:['path']};
  const result={source:clone(source),task:{question:'实际问题 '+id,phase:'snapshot',kind:'project-question'},columns:[{id:'bm25+graph',generation:'offline-evidence',answer_card:{...source,conclusion:item,reasons:[item],unknowns:[],next_steps:[]},evidence:[{...source,id:'path',title:'路径原文',source_excerpt:'{"from":"root"}',url:'/api/snapshots/'+id+'/task-comparison/sources/manifest?context_sha256='+digest}]}]};
  const baseline={question:result.task.question,source:{...source,context_sha256:'d'.repeat(64)},answer_card:{...source,context_sha256:'d'.repeat(64),conclusion:{text:'补充资料前的回答。',evidence_ids:[]}},evidence:[]};
  return {task:{scope:'snapshot',snapshot_id:id,context:{available:true,source,brief},question:result.task.question,result,baseline,running:false,loading:false,workspace_changing:false},brief:{snapshot_id:id,brief:clone(brief),loading:false,switching:false},workspace:{id,switchingSnapshot:false}};
}
function harness(options={}){
  const data=fixture(),nodes=[],events=[],mounts=[],opens=[],listeners=new Map(),fullJobs=[];
  let network=0,persistence=0,configures=0,fullscreenExits=0;
  class Element{
    constructor(tag='div'){this.tagName=tag.toUpperCase();this.attrs={};this.dataset={};this.children=[];this.listeners={};this.style={};this._html='';this.open=false;this.isConnected=true;nodes.push(this);}
    setAttribute(name,value){this.attrs[name]=String(value);if(name==='id')this.id=value;if(name==='class')this.className=value;if(name==='disabled')this.disabled=true;if(name.startsWith('data-'))this.dataset[name.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=String(value);}
    getAttribute(name){return this.attrs[name]??null;}hasAttribute(name){return name in this.attrs;}
    set innerHTML(value){
      this._html=value;this.children=[];const stack=[this];
      for(const match of value.matchAll(/<(\/)?([\w-]+)([^>]*)>/g)){
        if(match[1]){if(stack.length>1)stack.pop();continue;}
        const element=new Element(match[2]);for(const attr of match[3].matchAll(/([\w-]+)(?:="([^"]*)")?/g))element.setAttribute(attr[1],decode(attr[2]||''));
        stack.at(-1).append(element);if(!['INPUT','BR','HR','IMG','META','LINK'].includes(element.tagName))stack.push(element);
      }
    }
    get innerHTML(){return this._html;}
    append(node){node.parent=this;this.children.push(node);}contains(node){return node===this||this.children.some(c=>c.contains(node));}
    matches(selector){
      if(selector[0]==='.')return (this.className||'').split(' ').includes(selector.slice(1));
      if(selector[0]==='#')return this.id===selector.slice(1);
      const attr=selector.match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/);if(attr)return this.hasAttribute(attr[1])&&(attr[2]===undefined||this.getAttribute(attr[1])===attr[2]);
      return selector.toUpperCase()===this.tagName;
    }
    closest(selector){return selector.split(',').some(s=>this.matches(s))?this:this.parent?.closest(selector)||null;}
    querySelectorAll(selector){return this.children.flatMap(c=>[...(selector.split(',').some(s=>c.matches(s))?[c]:[]),...c.querySelectorAll(selector)]);}
    querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
    addEventListener(name,fn){this.listeners[name]=fn;}focus(){document.activeElement=this;}
    showModal(){this.open=true;}close(){this.open=false;this.listeners.close?.({target:this});}
    requestFullscreen(){return options.holdFullscreen?new Promise((resolve,reject)=>fullJobs.push({resolve:()=>{document.fullscreenElement=this;resolve();},reject})):Promise.reject(Error('denied'));}
  }
  const body=new Element('body'),fixed=new Element('dialog');fixed.id='presenter-dialog';fixed.open=Boolean(options.fixedOpen);body.append(fixed);
  const document={body,activeElement:null,fullscreenElement:null,createElement:tag=>new Element(tag),getElementById:id=>nodes.find(n=>n.id===id),addEventListener:(name,fn)=>{document[name]=fn;},exitFullscreen:async()=>{fullscreenExits++;document.fullscreenElement=null;}};
  const window={
    lianzhengProjectBrief:{state:()=>data.brief},
    lianzhengTaskCompare:{state:()=>data.task,configure:()=>{configures++;throw Error('must not configure');},open:async function(value){opens.push(arguments.length?clone(value):null);if(options.openError)throw Error('问答暂不可用');return data.task;},mountReadonly:(host,settings)=>{
      const entry={host,settings,destroyed:false};mounts.push(entry);
      host.innerHTML=`<article class="tc-readonly"><h3>${escape(settings.result?.columns[0]?.answer_card?.conclusion?.text||settings.baseline?.answer_card?.conclusion?.text||'无有效回答')}</h3><p>${escape(settings.result?.columns[0]?.evidence[0]?.source_excerpt||'')}</p>${!settings.historical&&settings.isCurrent()?'<a href="/api/current-source">查看当前原文</a>':''}</article>`;
      return {destroy(){entry.destroyed=true;}};
    }},
    addEventListener:(name,fn)=>{if(!listeners.has(name))listeners.set(name,[]);listeners.get(name).push(fn);},dispatchEvent:event=>{events.push(event);for(const fn of listeners.get(event.type)||[])fn(event);},
  };
  if(options.noHelper)delete window.lianzhengTaskCompare.mountReadonly;
  const guard=new Proxy({},{get(){persistence++;throw Error('must not persist question data');}});
  vm.runInContext(code,vm.createContext({window,document,state:data.workspace,escapeHTML:escape,console,CustomEvent:class{constructor(type,init){this.type=type;this.detail=init.detail;}},fetch(){network++;throw Error('must not request');},localStorage:guard,sessionStorage:guard}));
  const dialog=document.getElementById('project-presenter-dialog'),find=s=>dialog.querySelector(s);
  return {api:window.lianzhengProjectPresenter,data,dialog,fixed,document,window,events,mounts,opens,fullJobs,find,
    event:(name,detail)=>window.dispatchEvent({type:name,detail}),
    click:action=>dialog.listeners.click({target:find('[data-pp-action="'+action+'"]')}),
    key:key=>dialog.listeners.keydown({key,target:dialog,preventDefault(){}}),
    stats:()=>({network,persistence,configures,fullscreenExits}),
    set(id,digest=hash[id]){const next=fixture(id,digest);Object.assign(data.workspace,next.workspace);data.task=next.task;data.brief=next.brief;},
  };
}
(async()=>{
  let passed=0;const check=(name,fn)=>{fn();passed++;console.log('PASS '+name);};
  const h=harness();
  check('mount creates an independent closed project dialog with no request',()=>{assert.equal(h.dialog.open,false);assert.equal(h.dialog.getAttribute('aria-labelledby'),'project-presenter-title');assert.equal(h.stats().network,0);});
  const resultBefore=JSON.stringify(h.data.task.result),baselineBefore=JSON.stringify(h.data.task.baseline);h.api.start();
  check('start captures only selected project source and four steps',()=>{assert.equal(h.api.state().snapshot_id,'A');assert.equal(h.api.state().context_sha256,hash.A);assert.equal(h.api.state().has_answer,true);assert.equal(h.find('.pp-steps').querySelectorAll('[data-pp-step]').length,4);assert.equal(h.dialog.open,true);});
  check('brief reports real counts and unresolved coverage rather than a safety claim',()=>{const text=h.find('.pp-content').innerHTML;assert.ok(text.includes('项目 A'));assert.ok(text.includes('6 个组件位置'));assert.ok(text.includes('查询完成不表示项目全部安全'));});
  h.api.go(1);
  check('question is a read-only actual answered prompt',()=>{assert.ok(h.find('.pp-content').innerHTML.includes('实际问题 A'));assert.equal(h.find('.pp-content').querySelectorAll('textarea,input').length,0);assert.ok(h.find('.pp-content').innerHTML.includes('已取得回答的实际问题'));});
  h.api.go(2);
  check('answer reuses read-only helper with a bound independent capture',()=>{const m=h.mounts.at(-1);assert.equal(m.settings.view,'answer');assert.equal(m.settings.context.source.snapshot_id,'A');assert.equal(m.settings.historical,false);assert.equal(m.settings.isCurrent(),true);assert.notEqual(m.settings.result,h.data.task.result);assert.notEqual(m.settings.baseline,h.data.task.baseline);});
  const answerMount=h.mounts.at(-1);h.api.go(3);
  check('change step reuses the same question and baseline in isolated helper state',()=>{assert.equal(answerMount.destroyed,true);assert.equal(h.mounts.at(-1).settings.view,'changes');assert.equal(h.mounts.at(-1).settings.baseline.question,'实际问题 A');});
  h.key('ArrowLeft');h.key('ArrowRight');
  check('keyboard navigation does not alter accepted answer or baseline',()=>{assert.equal(h.api.state().step,3);assert.equal(JSON.stringify(h.data.task.result),resultBefore);assert.equal(JSON.stringify(h.data.task.baseline),baselineBefore);assert.equal(h.stats().configures,0);});
  await h.click('workbench');
  check('returning to the same project opens existing workbench without configure/options',()=>{assert.deepEqual(h.opens,[null]);assert.equal(h.dialog.open,false);assert.equal(JSON.stringify(h.data.task.result),resultBefore);assert.equal(JSON.stringify(h.data.task.baseline),baselineBefore);});
  check('all normal stages make no requests or browser persistence writes',()=>{assert.equal(h.stats().network,0);assert.equal(h.stats().persistence,0);assert.equal(h.stats().configures,0);});

  const changed=harness();changed.api.start();changed.api.go(2);const live=changed.mounts.at(-1);
  changed.event('lianzheng-snapshot-changing',{snapshot_id:'B',request:1});
  check('switch start immediately pauses and destroys existing live source actions',()=>{assert.equal(changed.api.state().paused,true);assert.equal(changed.api.state().stale,true);assert.equal(live.destroyed,true);assert.equal(live.settings.isCurrent(),false);assert.equal(changed.mounts.at(-1).settings.historical,true);assert.equal(changed.find('[data-pp-action="next"]').disabled,true);});
  changed.key('ArrowRight');
  check('paused keyboard navigation cannot advance a stale presentation',()=>assert.equal(changed.api.state().step,2));
  changed.set('B');changed.event('lianzheng-snapshot-changed',{snapshot:'B'});changed.event('lianzheng-task-comparison-changed',{scope:'snapshot',snapshot_id:'A',context:fixture('A').task.context,result:fixture('A').task.result});
  check('late old answer event cannot replace captured A with new B or revive it',()=>{assert.equal(changed.api.state().snapshot_id,'A');assert.equal(changed.api.state().paused,true);assert.equal(changed.mounts.at(-1).settings.result.source.snapshot_id,'A');});
  await changed.click('historical');changed.api.go(3);
  check('historical continuation is explicit and never reenables current-source links',()=>{assert.equal(changed.api.state().paused,false);assert.equal(changed.api.state().stale,true);assert.equal(changed.api.state().step,3);assert.ok(changed.find('.pp-binding').textContent.includes('历史资料'));assert.equal(changed.mounts.at(-1).settings.isCurrent(),false);assert.equal(changed.find('.pp-content').querySelectorAll('a').length,0);});
  changed.api.start();
  check('explicit reprepare captures consistent newly selected project',()=>{assert.equal(changed.api.state().snapshot_id,'B');assert.equal(changed.api.state().context_sha256,hash.B);assert.equal(changed.api.state().stale,false);assert.equal(changed.api.state().step,0);});
  changed.event('lianzheng-project-evidence-changed',{snapshot_id:'A'});
  check('another project evidence event does not interrupt current presentation',()=>assert.equal(changed.api.state().stale,false));
  changed.event('lianzheng-project-evidence-changed',{snapshot_id:'B'});
  check('same-project evidence update pauses before replacement context arrives',()=>{assert.equal(changed.api.state().paused,true);assert.equal(changed.api.state().context_sha256,hash.B);});
  changed.set('B',hash.new);changed.event('lianzheng-task-comparison-changed',changed.data.task);
  check('late refreshed context never automatically recaptures a historical presentation',()=>assert.equal(changed.api.state().context_sha256,hash.B));
  changed.api.start();
  check('reprepare selects the updated context and keeps prior baseline available',()=>{assert.equal(changed.api.state().context_sha256,hash.new);assert.equal(changed.api.state().has_baseline,true);assert.equal(changed.stats().network,0);});

  const edited=harness();edited.api.start();edited.api.go(2);const original=edited.mounts.at(-1).settings.result.columns[0].answer_card.conclusion.text;edited.data.task.result.columns[0].answer_card.conclusion.text='late external mutation';edited.event('lianzheng-task-comparison-changed',edited.data.task);
  check('accepted response objects cannot mutate the captured presentation',()=>{assert.equal(edited.api.state().stale,true);assert.equal(edited.mounts.at(-1).settings.result.columns[0].answer_card.conclusion.text,original);});
  const draft=harness();draft.data.task.result=null;draft.data.task.baseline=null;draft.api.start();draft.api.go(1);
  check('draft-only presentation permits briefing but labels its question unanswered',()=>{assert.equal(draft.api.state().has_answer,false);assert.ok(draft.find('.pp-content').innerHTML.includes('尚无有效回答'));});
  draft.api.go(2);
  check('empty answer step routes to existing workbench and does not invent an answer',()=>{assert.equal(draft.mounts.length,0);assert.ok(draft.find('.pp-content').innerHTML.includes('没有可讲解的有效回答'));assert.equal(draft.find('.pp-content').querySelectorAll('[data-pp-action="workbench"]').length,1);assert.equal(draft.stats().network,0);});
  const empty=harness();empty.data.task.question='';empty.data.task.result=null;empty.data.task.baseline=null;empty.api.start();empty.api.go(1);
  check('no-question capture remains a usable project brief without simulated question',()=>assert.ok(empty.find('.pp-content').innerHTML.includes('还没有本场问题')));
  const retained=harness();retained.data.task.result=null;retained.api.start();retained.api.go(3);
  check('baseline-only changes route keeps historical answer in the read-only helper',()=>{assert.equal(retained.mounts.at(-1).settings.result,null);assert.equal(retained.mounts.at(-1).settings.baseline.question,'实际问题 A');});
  const briefOnly=harness();briefOnly.data.task.context=null;briefOnly.data.task.result=null;briefOnly.data.task.baseline=null;briefOnly.api.start();briefOnly.api.go(1);
  check('loaded brief still supports draft presentation when answer context is unavailable',()=>{assert.equal(briefOnly.api.state().stale,false);assert.equal(briefOnly.api.state().step,1);assert.equal(briefOnly.api.state().has_answer,false);assert.ok(briefOnly.find('.pp-content').innerHTML.includes('实际问题 A'));});
  const fixed=harness();fixed.data.task={scope:'case',question:'固定案例问题',result:{source:{case_bundle_sha256:'fixed'}},baseline:null};fixed.api.start();fixed.api.go(1);
  check('fixed-case question and answer never appear as the imported project',()=>{assert.equal(fixed.api.state().has_answer,false);assert.ok(!fixed.find('.pp-content').innerHTML.includes('固定案例问题'));assert.equal(fixed.fixed.open,false);});
  await fixed.click('workbench');
  check('explicit project workbench action may switch from fixed-case scope',()=>assert.deepEqual(fixed.opens,[{scope:'snapshot',snapshot_id:'A',mode:'free'}]));
  const fixedOpen=harness({fixedOpen:true});
  check('current-project start cannot replace an open fixed-case presentation',()=>{assert.throws(()=>fixedOpen.api.start(),/先退出固定案例/);assert.equal(fixedOpen.fixed.open,true);assert.equal(fixedOpen.dialog.open,false);});

  for(const [name,mutate] of [
    ['answer snapshot',d=>d.task.result.source.snapshot_id='B'],
    ['answer context hash',d=>d.task.result.source.context_sha256=hash.B],
    ['answer question',d=>d.task.result.task.question='other'],
    ['answer phase',d=>d.task.result.task.phase='before'],
    ['empty answer columns',d=>d.task.result.columns=[]],
    ['baseline snapshot',d=>d.task.baseline.source.snapshot_id='B'],
    ['baseline question',d=>d.task.baseline.question='other'],
    ['brief snapshot',d=>d.task.context.brief.snapshot_id='B'],
    ['brief hash',d=>d.task.context.brief.context_sha256=hash.B],
    ['brief count',d=>d.task.context.brief.component_count=-1],
    ['separately loaded brief hash',d=>d.brief.brief.context_sha256=hash.B],
  ]){
    const rejected=harness();mutate(rejected.data);
    check('reject inconsistent capture: '+name,()=>{assert.throws(()=>rejected.api.start());assert.equal(rejected.dialog.open,false);assert.equal(rejected.mounts.length,0);assert.equal(rejected.stats().network,0);});
  }
  for(const key of ['loading','running','workspace_changing']){
    const pending=harness();pending.data.task[key]=true;
    check('pending '+key+' is not captured as a complete current answer',()=>{assert.throws(()=>pending.api.start(),/等待完成/);assert.equal(pending.api.state().snapshot_id,null);});
  }
  const switching=harness();switching.data.workspace.switchingSnapshot=true;
  check('pending workspace switch cannot prepare an old project capture',()=>assert.throws(()=>switching.api.start(),/先完成项目选择/));
  const failed=harness();failed.api.start();failed.event('lianzheng-snapshot-changing',{snapshot_id:'B'});failed.event('lianzheng-snapshot-change-failed',{snapshot_id:'B'});
  check('failed project switch leaves previous capture paused until selection succeeds',()=>{assert.equal(failed.api.state().paused,true);assert.throws(()=>failed.api.start(),/先完成项目选择/);});

  const fullscreen=harness();fullscreen.api.start();await fullscreen.click('fullscreen');
  check('fullscreen denial keeps a usable page-filling dialog and explains fallback',()=>{assert.equal(fullscreen.dialog.open,true);assert.ok(fullscreen.find('.pp-status').textContent.includes('铺满页面'));assert.equal(fullscreen.document.fullscreenElement,null);});
  fullscreen.key('Escape');
  check('Escape exits and restores page scrolling without clearing accepted answer',()=>{assert.equal(fullscreen.dialog.open,false);assert.equal(fullscreen.document.body.style.overflow,undefined);assert.equal(fullscreen.data.task.result.task.question,'实际问题 A');});
  const lateFullscreen=harness({holdFullscreen:true});lateFullscreen.api.start();const fullPending=lateFullscreen.click('fullscreen');lateFullscreen.api.close();lateFullscreen.fullJobs[0].resolve();await fullPending;
  check('a late fullscreen completion cannot leave a closed presentation fullscreen',()=>{assert.equal(lateFullscreen.dialog.open,false);assert.equal(lateFullscreen.document.fullscreenElement,null);assert.equal(lateFullscreen.stats().fullscreenExits,1);});
  const noHelper=harness({noHelper:true});noHelper.api.start();noHelper.api.go(2);
  check('missing renderer offers workbench recovery without model calls',()=>{assert.ok(noHelper.find('.pp-content').innerHTML.includes('展示组件尚未就绪'));assert.equal(noHelper.stats().network,0);});

  const xss=harness(),payload='<img src=x onerror="alert(1)"><script>alert(1)</script>';
  xss.data.task.context.brief.project=payload;xss.data.task.context.brief.notes=[payload];xss.data.brief.brief.project=payload;xss.data.task.question=payload;xss.data.task.result.task.question=payload;xss.data.task.baseline.question=payload;xss.api.start();
  check('project name and brief notes are escaped at stage boundaries',()=>{assert.ok(xss.find('.pp-content').innerHTML.includes('&lt;img'));assert.equal(xss.find('.pp-content').querySelectorAll('img,script').length,0);});
  xss.api.go(1);
  check('question is escaped rather than interpreted as HTML',()=>{assert.ok(xss.find('.pp-content').innerHTML.includes('&lt;script&gt;'));assert.equal(xss.find('.pp-content').querySelectorAll('img,script').length,0);});
  const offline=harness();offline.api.start();for(let i=1;i<4;i++)offline.api.go(i);
  check('already loaded offline materials need no server, model or persistence',()=>assert.deepEqual(offline.stats(),{network:0,persistence:0,configures:0,fullscreenExits:0}));
  check('new unified entry is explicitly current-project and does not replace fixed-case starts',()=>{const hub=fs.readFileSync(path.join(__dirname,'../static/demo-tour.js'),'utf8');assert.ok(hub.includes('讲解当前项目 · 4 步'));assert.ok(hub.includes('window.lianzhengProjectPresenter.start()'));assert.ok(hub.includes('data-hub-start="quick"'));assert.ok(hub.includes('data-hub-start="full"'));});
  const hubSource=fs.readFileSync(path.join(__dirname,'../static/demo-tour.js'),'utf8'),hubStart=hubSource.indexOf("find('[data-hub-project]').addEventListener"),hubEnd=hubSource.indexOf('\n  });',hubStart)+6,hubOpens=[];
  let hubClick,hubTask={scope:'snapshot',snapshot_id:'A'};
  vm.runInNewContext(hubSource.slice(hubStart,hubEnd),{state:{id:'A',switchingSnapshot:false},find:()=>({addEventListener(_name,fn){hubClick=fn;}}),window:{lianzhengTaskCompare:{state:()=>hubTask,open:async function(options){hubOpens.push(arguments.length?clone(options):null);}}},toast:message=>{throw Error(message);}});
  await hubClick();
  check('unified current-project question entry preserves already accepted answers',()=>assert.deepEqual(hubOpens,[null]));
  hubTask={scope:'case'};await hubClick();
  check('unified question entry explicitly configures only when changing scope',()=>assert.deepEqual(hubOpens.at(-1),{scope:'snapshot',snapshot_id:'A',mode:'free'}));
  console.log(JSON.stringify({suite:'v0.12 current project presentation protocol',passed,network_calls:0,real_model_calls:0,browser_layout_verified:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
