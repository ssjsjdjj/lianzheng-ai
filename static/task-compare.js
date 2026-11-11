'use strict';
(() => {
  const launch=document.createElement('button');
  launch.type='button';launch.className='button secondary';launch.textContent='任务双栏对照';
  document.querySelector('.heading-actions').append(launch);
  const panel=document.createElement('section');
  panel.id='task-comparison-panel';panel.className='panel task-comparison-panel';panel.hidden=true;
  panel.setAttribute('aria-label','真实任务双栏对照');document.querySelector('main').append(panel);
  const instances=new Set(), selections=new Map(), esc=escapeHTML;
  const phases={before:'修复前',partial:'只更新直接依赖',after:'最终阶段'};
  const timeouts={catalog:12000,offline:30000,model:100000};
  let catalog=null,chosen='',result=null,loading=false,running=false,error='',notice='',serial=0;
  let readPromise=null,useModel=false,mode='fixed',draft='',selectedPhase='before',pending=null,lastAttempt=null,expectedCaseHash=null;
  const caseURL=value=>typeof value==='string'&&/^\/api\/real-case\/files\/[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(value)?value:null;
  const task=()=>catalog?.tasks?.find(t=>t.id===chosen);
  const phaseNow=()=>mode==='free'?selectedPhase:(task()?.phase||selectedPhase);
  const questionNow=()=>mode==='free'?draft.trim():(task()?.question||'');
  const state=()=>({catalog,task_id:chosen,mode,phase:phaseNow(),question:questionNow(),result,running,loading,error,notice,use_model:useModel,expected_case_hash:expectedCaseHash});
  const emit=()=>window.dispatchEvent(new CustomEvent('lianzheng-task-comparison-changed',{detail:state()}));
  function publish(){for(const instance of instances)render(instance);emit();}
  function clearResult(){result=null;selections.clear();error='';notice='';lastAttempt=null;}
  function leavePending(message=''){
    ++serial;
    if(pending){clearTimeout(pending.timer);pending.controller.abort();pending=null;}
    running=false;
    if(message){error=message;notice='';}
  }
  function contextChanged(){leavePending();clearResult();}
  function summaryText(r){
    if(r.comparison?.result==='unscored')return '现场提问 · 不计算得分或胜负';
    return r.comparison?.result==='tie'?'参考证据覆盖打平':r.comparison?.result==='graph-more'?'图增强检索覆盖更多参考证据':'文本检索覆盖更多参考证据';
  }
  function excerptLabel(d){
    return d.source_excerpt_kind==='raw-log'?'保存的原始日志片段':d.kind==='migration'?'原始差异文件片段':'原始 JSON 条目（解析后显示）';
  }
  function fileLink(d){const href=caseURL(d.url);return href?`<a href="${esc(href)}" download>下载 ${esc(d.filename)} ↗</a>`:'<span>此来源暂无可下载文件。</span>';}
  function evidence(d){return `<details class="tc-evidence"><summary><span>${esc(d.id)}</span> ${esc(d.title)}</summary><small>规范化事实 · ${esc(phases[d.phase]||d.phase)} · ${esc(d.locator)}</small><pre>${esc(d.text)}</pre>${d.source_excerpt?`<details><summary>${excerptLabel(d)}${d.source_excerpt_truncated?'（节选）':''}</summary><pre>${esc(d.source_excerpt)}</pre></details>`:''}<p>${fileLink(d)}</p><code>SHA-256 ${esc(d.source_sha256||'见来源清单')}</code></details>`;}
  // A linked view is always scoped to the current result and one retrieval column.
  // Never infer an edge, citation, or semantic support from model prose.
  function linksFor(c){
    const pack=c.evidence_links||{},source=pack.source||{};
    const evidence=(c.evidence||[]).filter(d=>d.phase===result?.task?.phase);
    const byId=new Map(evidence.map(d=>[d.id,d]));
    if(source.phase!==result?.task?.phase||source.case_bundle_sha256!==result?.source?.case_bundle_sha256)return {evidence,paths:[],facts:[]};
    const paths=(pack.paths||[]).filter(p=>{
      if(!Array.isArray(p.nodes)||p.nodes.length<2||!Array.isArray(p.edges)||p.edges.length!==p.nodes.length-1)return false;
      return p.edges.every((edge,i)=>edge.source===p.nodes[i].ref&&edge.target===p.nodes[i+1].ref&&
        Array.isArray(edge.evidence_ids)&&edge.evidence_ids.length>0&&edge.evidence_ids.every(id=>
          byId.get(id)?.relations?.some(r=>r.source===edge.source&&r.target===edge.target)));
    });
    const pathIds=new Set(paths.map(p=>p.id));
    const facts=(pack.facts||[]).filter(f=>['retrieved-fact','model-claim'].includes(f.kind)&&Array.isArray(f.evidence_ids)&&
      f.evidence_ids.length>0&&f.evidence_ids.every(id=>byId.has(id))).map(f=>({...f,path_ids:(f.path_ids||[]).filter(id=>pathIds.has(id)&&
        paths.find(p=>p.id===id).edges.some(edge=>edge.evidence_ids.some(e=>f.evidence_ids.includes(e))))}));
    return {evidence,paths,facts};
  }
  function selectionFor(c){
    const links=linksFor(c),selected=selections.get(c.id)||{};
    const fact=links.facts.find(f=>f.id===selected.fact_id)||(!selected.evidence_id?links.facts[0]:null);
    const allowed=fact?links.evidence.filter(e=>fact.evidence_ids.includes(e.id)):links.evidence;
    const doc=allowed.find(e=>e.id===selected.evidence_id)||allowed[0];
    const paths=links.paths.filter(p=>fact?fact.path_ids.includes(p.id):p.edges.some(e=>e.evidence_ids.includes(doc?.id)));
    const path=paths.find(p=>p.id===selected.path_id)||paths[0];
    return {links,fact,doc,paths,path};
  }
  function linkage(c,index){
    const {links,fact,doc,paths,path}=selectionFor(c);
    if(!links.evidence.length)return '<div class="tc-linked-empty">本侧没有可联动的证据，暂不能定位原文或依赖路径。</div>';
    const facts=links.facts.map((f,i)=>`<button type="button" class="tc-fact ${fact?.id===f.id?'selected':''}" data-tc-fact="${esc(f.id)}" data-tc-column="${index}" aria-pressed="${fact?.id===f.id}"><span>${f.kind==='model-claim'?'模型句子':'依据摘要'} ${i+1}</span>${esc(f.text)}</button>`).join('');
    return `<section class="tc-linkage" aria-label="${index===0?'A':'B'} 结论与证据联动"><div class="tc-linkage-heading"><h4>点一句，核对路径与原文</h4><small>支持范围仍待人工复核</small></div>${facts?`<div class="tc-facts">${facts}</div>`:''}
      <div class="tc-linked-focus"><strong>${fact?.kind==='model-claim'?'当前模型句子':'当前依据摘要'}</strong><p>${esc(fact?.text||doc?.title||'请选择证据')}</p></div>
      <div class="tc-linked-path"><div class="tc-linked-label">关联路径 <span>仅由本侧已取回关系连接</span></div>${paths.length>1?`<div class="tc-path-tabs">${paths.map((p,i)=>`<button type="button" data-tc-path="${esc(p.id)}" data-tc-column="${index}" aria-pressed="${path?.id===p.id}">路径 ${i+1}</button>`).join('')}</div>`:''}${path?`<div class="tc-path-chain" role="img" aria-label="${esc(path.label)}">${path.nodes.map((node,i)=>`${i?`<span class="tc-path-arrow ${path.edges[i-1].evidence_ids.includes(doc?.id)?'selected':''}" title="${esc(path.edges[i-1].evidence_ids.join('、'))}">→</span>`:''}<span class="tc-path-node ${doc?.ref===node.ref?'selected':''}"><b>${esc(node.name)}@${esc(node.version)}</b><small>${esc(node.ref)}</small></span>`).join('')}</div><p class="tc-meta">${path.edges.length} 条已核对依赖边；这不是全部依赖路径或运行时调用轨迹。</p>`:`<p class="tc-path-missing">${doc&&['test','source','migration'].includes(doc.kind)?'这份日志或来源材料没有对应依赖路径，可直接核对下方原文。':'本侧取回片段尚未连接出对应路径；不代表原清单中没有路径。'}</p>`}</div>
      <label class="tc-linked-select">核对这句话的来源<select data-tc-evidence data-tc-column="${index}" aria-label="${index===0?'A':'B'} 联动证据">${(fact?links.evidence.filter(e=>fact.evidence_ids.includes(e.id)):links.evidence).map(e=>`<option value="${esc(e.id)}" ${doc?.id===e.id?'selected':''}>${esc(e.title)}</option>`).join('')}</select></label>
      ${doc?`<div class="tc-linked-source"><div class="tc-source-location"><strong>${esc(doc.filename)}</strong><code>${esc(doc.locator)}</code><span>${esc(phases[doc.phase])}</span></div><details class="tc-normalized"><summary>规范化事实摘录（非上游逐字原文）</summary><pre>${esc(doc.text)}</pre></details>${doc.source_excerpt?`<strong class="tc-excerpt-label">${excerptLabel(doc)}${doc.source_excerpt_truncated?'（节选）':''}</strong><pre class="tc-original-excerpt">${esc(doc.source_excerpt)}</pre>${doc.source_excerpt_truncated?'<p class="tc-meta">此片段已截断，完整依据请下载原文件。</p>':''}`:'<p class="tc-meta">此汇总没有对应的逐字原文片段，请下载来源文件核对。</p>'}<p>${fileLink(doc)}</p><code class="tc-source-hash">SHA-256 ${esc(doc.source_sha256||'见来源清单')}</code></div>`:''}
      <details class="tc-evidence-picker"><summary>切换到本侧其他证据 · ${links.evidence.length} 份</summary><div>${links.evidence.map(e=>`<button type="button" data-tc-select-evidence="${esc(e.id)}" data-tc-column="${index}">${esc(e.title)}</button>`).join('')}</div></details></section>`;
  }
  function column(c,index){
    const m=c.metrics||{},meta=c.model?.metadata||c.attempt_metadata||{},budget=meta.input_budget;
    const generation=c.generation==='model-assisted'?'本次模型返回':c.generation==='model-fallback'?'模型未完成 · 保留证据':'离线证据对照';
    const unscored=result?.comparison?.result==='unscored';
    return `<article class="tc-column"><div class="tc-column-heading"><span>${index===0?'A':'B'}</span><div><h3>${index===0?'BM25 文本检索':'BM25 + 图增强检索'}</h3><small>${generation}</small></div></div><div class="tc-metrics"><div><strong>${unscored?'未评分':`${m.reference_found??0}/${m.reference_total??0}`}</strong><span>${unscored?'自由题无预设参考答案':'参考证据覆盖'}</span></div><div><strong>${m.connected_target_occurrences??0}</strong><span>片段可连通的 ${esc(m.connected_target_package||'目标包')} 位置</span></div><div><strong>${m.retrieval_ms??'—'} ms</strong><span>本次检索与片段处理</span></div></div>${c.warning?`<p class="tc-alert">${esc(c.warning)}</p>`:''}
      <details class="tc-answer-detail"><summary>${c.generation==='model-assisted'?'展开本次模型回答':'展开本侧取回材料摘要'}</summary><p class="tc-answer">${esc(c.answer)}</p></details>${linkage(c,index)}
      <p class="tc-meta">检索片段 ${m.retrieved??0} 份 · ${m.evidence_bytes??0} UTF-8 字节（含来源元数据，非 token）</p>
      ${c.model||c.attempt_metadata?`<details class="tc-model"><summary>模型解释的引用与尝试记录</summary><p>${esc(c.model?.validation||'引用仍需人工复核。')} 引用校验针对规范化事实，不是上游原文逐字核验。</p>${(c.model?.claims||[]).map(x=>`<div><p>${esc(x.text)}</p>${(x.quotes||[]).map(q=>`<blockquote>${esc(q.quote)}<small>${esc(q.evidence_id)}</small></blockquote>`).join('')}</div>`).join('')}<p>返回模型：${esc(meta.returned_model||'未返回')} · 用量：${esc(meta.usage?.total_tokens??'未知')} tokens</p>${budget?`<p>本侧输入处理：${esc(JSON.stringify(budget))}</p>`:''}</details>`:''}
      <details class="tc-sources"><summary>核对本侧全部证据与文件（${c.evidence?.length||0} 份）</summary>${(c.evidence||[]).map(evidence).join('')}</details>${unscored?'':`<details class="tc-reference"><summary>开发者参考标注与未取回项</summary><p>标注仅用于检索后评分，尚未经独立人工评审。</p><p>参考：${esc((m.expected_evidence_ids||[]).join('、')||'无')}</p><p>未取回：${esc((m.missing_evidence_ids||[]).join('、')||'无')}</p></details>`}</article>`;
  }
  function controls(){
    const fixed=`<label>选择真实任务<select data-tc-task aria-label="选择真实对照任务" ${loading||running?'disabled':''}>${catalog?.tasks.map(t=>`<option value="${esc(t.id)}" ${t.id===chosen?'selected':''}>${esc(phases[t.phase])} · ${esc(t.question)}</option>`).join('')||'<option>正在读取任务…</option>'}</select></label>`;
    const free=`<div class="tc-free-fields"><label>现场问题<textarea data-tc-question aria-label="现场提问内容" maxlength="1000" rows="2" ${running?'disabled':''} placeholder="例如：只升级直接 minimist 后，哪些位置仍需核对？">${esc(draft)}</textarea><small data-tc-length>${draft.length}/1000 · Ctrl / ⌘ + Enter 运行</small></label><label>材料阶段<select data-tc-phase aria-label="现场提问材料阶段" ${running?'disabled':''}>${Object.entries(phases).map(([id,name])=>`<option value="${id}" ${selectedPhase===id?'selected':''}>${name}</option>`).join('')}</select></label><div class="tc-question-chips">${['minimist 从哪些依赖路径引入？','测试失败的依据是什么？','这些材料足以证明安全上线吗？'].map(q=>`<button type="button" data-tc-prompt="${esc(q)}" ${running?'disabled':''}>${esc(q)}</button>`).join('')}</div></div>`;
    return `<div class="tc-mode-tabs" role="group" aria-label="提问方式"><button type="button" data-tc-mode="fixed" aria-pressed="${mode==='fixed'}" ${running?'disabled':''}>固定任务对照</button><button type="button" data-tc-mode="free" aria-pressed="${mode==='free'}" ${running?'disabled':''}>现场提问</button><span>${esc(phases[phaseNow()])} · 固定 http-server 案例</span></div><div class="tc-controls">${mode==='fixed'?fixed:free}<label class="tc-model-toggle"><input type="checkbox" data-tc-model ${useModel?'checked':''} ${running||!catalog?.model_configured?'disabled':''}>两侧使用同一模型解释（最多两次请求，可能计费）</label><div class="tc-actions"><button type="button" class="button primary" data-tc-run ${running||loading||!questionNow()?'disabled':''}>${running?'正在对照…':useModel?'运行两侧模型对照':'运行离线证据对照'}</button>${running?'<button type="button" class="button secondary" data-tc-stop>停止等待</button>':''}<button type="button" class="button secondary" data-tc-refresh ${loading||running?'disabled':''}>刷新任务与模型状态</button>${result?'<button type="button" class="button secondary" data-tc-download>下载本次对照 JSON</button>':''}</div></div>`;
  }
  function render(instance){
    const {host,compact}=instance;
    const active=host.contains?.(document.activeElement)?document.activeElement:null;
    const focusAttr=['data-tc-question','data-tc-fact','data-tc-path','data-tc-evidence','data-tc-select-evidence','data-tc-mode','data-tc-task','data-tc-phase','data-tc-model','data-tc-run','data-tc-stop','data-tc-refresh','data-tc-offline'].find(name=>active?.hasAttribute?.(name));
    const focusValue=focusAttr?active.getAttribute(focusAttr):null,focusColumn=active?.dataset?.tcColumn;
    const caret=focusAttr==='data-tc-question'?[active.selectionStart,active.selectionEnd]:null;
    host.classList.add('task-comparison-workbench');host.classList.toggle('tc-compact',compact);host.classList.toggle('tc-free-mode',mode==='free');
    host.innerHTML=`${compact?'':`<div class="panel-heading"><div><span class="tc-eyebrow">SAME SOURCES · PAIRED RETRIEVAL</span><h2>真实任务双栏对照</h2><p>现场提出问题，沿已取回材料核对结论。</p></div><button type="button" class="button secondary" data-tc-close>收起对照</button></div>`}<p class="tc-boundary">固定 http-server 实验材料，不随工作空间切换。${mode==='free'?'自由题没有预设参考答案，不计算准确率或胜负。':'16 道开发者整理题，尚未经独立评审。'}</p>${controls()}
      ${error?`<div class="tc-alert" role="alert"><p>${esc(error)}</p>${lastAttempt?'<button type="button" class="button secondary" data-tc-offline>改用离线证据重试</button>':''}</div>`:''}${notice?`<p class="tc-notice" role="status">${esc(notice)}</p>`:''}
      <details class="tc-protocol-brief"><summary>相同材料与预算 · 结构差异不等于回答准确率</summary><p>${esc(catalog?.protocol?.statement||'进入页面不会自动运行模型。')} 两侧都读取关系文本、共用片段路径连接步骤。可连通位置包含未命中目标公告的版本。</p></details>${running?'<p class="tc-notice" role="status">正在等待本次结果。停止等待只中断本机接收，服务器可能继续处理，已发生的请求仍可能计费。</p>':''}
      ${result?`<div class="tc-result-summary" role="status"><strong>${summaryText(result)}</strong><span>本次材料：${esc(phases[result.task.phase])}</span><p>${esc(result.comparison.note)}</p>${result.model_calls_attempted?`<p>模型解释尝试 ${result.model_calls_attempted} 次。${result.fairness.model_pair_comparable?'两侧返回模型一致，语义优劣仍未评定。':'两侧未同时完成或模型无法确认一致，不能比较生成质量。'}</p>`:''}</div><div class="tc-columns">${result.columns.map(column).join('')}</div><details class="tc-protocol"><summary>来源、统一条件与验证范围</summary><p>提交 ${esc(result.source.commit)}</p><p>阶段来源 ${esc(result.source.lockfile)}</p><p>候选片段 ${result.fairness.candidate_documents} 份 · 每侧最多 ${result.fairness.k} 份 · 片段上限 ${result.fairness.evidence_max_bytes} 字节 · 模型消息上限 ${result.fairness.model_max_input_bytes} 字节</p><code>统一语料 SHA-256 ${esc(result.fairness.corpus_sha256)}</code><p>${esc(result.fairness.shared_postprocessing)}</p><ul>${result.limitations.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></details>`:running?'':`<div class="tc-empty"><strong>${mode==='free'?'写下一个问题，再核对两侧依据':'先选一题，再运行对照'}</strong><p>默认不调用模型。现场问题和回答只保留在当前页面内存，刷新后不恢复。</p></div>`}`;
    bind(instance);
    if(focusAttr){const replacement=[...host.querySelectorAll('['+focusAttr+']')].find(e=>e.getAttribute(focusAttr)===focusValue&&e.dataset.tcColumn===focusColumn);if(replacement&&!replacement.disabled){replacement.focus({preventScroll:true});if(caret)replacement.setSelectionRange(...caret);}}
  }
  function chooseLink(index,changes){
    const c=result?.columns?.[index];if(!c)return;
    selections.set(c.id,{...(selections.get(c.id)||{}),...changes});publish();
  }
  function bind(instance){
    const {host}=instance;
    host.querySelector('[data-tc-close]')?.addEventListener('click',()=>{panel.hidden=true;launch.focus();});
    host.querySelectorAll('[data-tc-mode]').forEach(b=>b.addEventListener('click',()=>configure({mode:b.dataset.tcMode})));
    host.querySelector('[data-tc-task]')?.addEventListener('change',e=>{contextChanged();chosen=e.target.value;publish();});
    host.querySelector('[data-tc-phase]')?.addEventListener('change',e=>configure({phase:e.target.value}));
    host.querySelector('[data-tc-model]')?.addEventListener('change',e=>{contextChanged();useModel=e.target.checked;publish();});
    host.querySelector('[data-tc-question]')?.addEventListener('input',e=>{
      draft=e.target.value;const cursor=e.target.selectionStart;
      if(result||error||notice){clearResult();publish();const replacement=host.querySelector('[data-tc-question]');replacement.focus();replacement.setSelectionRange(cursor,cursor);}
      else {for(const inst of instances){const input=inst.host.querySelector('[data-tc-question]');if(input&&input!==e.target)input.value=draft;const count=inst.host.querySelector('[data-tc-length]');if(count)count.textContent=`${draft.length}/1000 · Ctrl / ⌘ + Enter 运行`;const button=inst.host.querySelector('[data-tc-run]');if(button)button.disabled=running||loading||!draft.trim();}emit();}
    });
    host.querySelector('[data-tc-question]')?.addEventListener('keydown',e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();run();}});
    host.querySelectorAll('[data-tc-prompt]').forEach(b=>b.addEventListener('click',()=>{contextChanged();draft=b.dataset.tcPrompt;publish();host.querySelector('[data-tc-question]')?.focus();}));
    host.querySelector('[data-tc-run]')?.addEventListener('click',()=>run());
    host.querySelector('[data-tc-stop]')?.addEventListener('click',()=>{leavePending('已停止本地等待；服务器可能仍在处理，已发生的模型请求仍可能计费。');publish();});
    host.querySelector('[data-tc-offline]')?.addEventListener('click',()=>{useModel=false;return run({offline:true});});
    host.querySelector('[data-tc-refresh]')?.addEventListener('click',()=>read().catch(()=>{}));
    host.querySelector('[data-tc-download]')?.addEventListener('click',()=>{if(!result)return;const blob=new Blob([JSON.stringify(result,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='task-comparison-'+result.task.id+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
    host.querySelectorAll('[data-tc-fact]').forEach(b=>b.addEventListener('click',()=>chooseLink(Number(b.dataset.tcColumn),{fact_id:b.dataset.tcFact,evidence_id:null,path_id:null})));
    host.querySelectorAll('[data-tc-path]').forEach(b=>b.addEventListener('click',()=>chooseLink(Number(b.dataset.tcColumn),{path_id:b.dataset.tcPath})));
    host.querySelectorAll('[data-tc-evidence]').forEach(b=>b.addEventListener('change',()=>chooseLink(Number(b.dataset.tcColumn),{evidence_id:b.value})));
    host.querySelectorAll('[data-tc-select-evidence]').forEach(b=>b.addEventListener('click',()=>chooseLink(Number(b.dataset.tcColumn),{fact_id:null,evidence_id:b.dataset.tcSelectEvidence,path_id:null})));
  }
  async function request(path,body,controller){
    const response=await fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},signal:controller.signal,...(body?{body:JSON.stringify(body)}:{})});
    let data;try{data=await response.json();}catch{throw Error('服务响应无效，问题仍保留，可重新读取状态。');}
    if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'请求未完成，请检查当前输入和服务状态。');
    return data;
  }
  async function read(){
    if(readPromise)return readPromise;
    loading=true;error='';publish();
    const controller=new AbortController();let timedOut=false;
    const timer=setTimeout(()=>{timedOut=true;controller.abort();},timeouts.catalog);
    readPromise=(async()=>{try{
      const c=await request('/api/task-comparison/tasks',null,controller);
      if(!c.available||!Array.isArray(c.tasks))throw Error('案例目录尚未就绪，请检查冻结材料。');
      catalog=c;
      if(!c.tasks.some(t=>t.id===chosen)){chosen=c.tasks.find(t=>t.phase===selectedPhase)?.id||c.tasks[0]?.id||'';if(mode==='fixed')clearResult();}
      if(result&&result.source.case_bundle_sha256!==c.source.case_bundle_sha256){clearResult();notice='案例依据已变化，请重新运行当前问题。';}
      if(!c.model_configured)useModel=false;
      return c;
    }catch(e){error=timedOut?'读取目录超时，现场问题仍保留。请检查本机服务后重试。':e.name==='TypeError'?'无法连接本机服务，问题仍保留。请恢复服务后刷新状态。':e.message;throw e;}
    finally{clearTimeout(timer);loading=false;readPromise=null;publish();}})();
    return readPromise;
  }
  async function run({offline=false}={}){
    if(running||loading)return;
    const question=questionNow();
    if(!question||question.length>1000){error='请输入 1–1000 字的问题。';publish();return;}
    const requestMode=mode,phase=phaseNow(),taskId=chosen,model=offline?false:useModel;
    const ticket=++serial,controller=new AbortController();
    const body=requestMode==='free'?{question,phase,use_model:model}:{task_id:taskId,use_model:model};
    const active={controller,timer:null,timedOut:false};
    active.timer=setTimeout(()=>{if(ticket!==serial)return;active.timedOut=true;controller.abort();},model?timeouts.model:timeouts.offline);
    pending=active;running=true;clearResult();lastAttempt={mode:requestMode,phase,question,use_model:model};publish();
    try{
      const data=await request(requestMode==='free'?'/api/task-comparison/ask':'/api/task-comparison/run',body,controller);
      if(ticket!==serial||mode!==requestMode||phaseNow()!==phase||questionNow()!==question)return;
      if(data.task?.phase!==phase||data.task?.question!==question||(requestMode==='fixed'&&data.task?.id!==taskId)||(requestMode==='free'&&data.comparison?.result!=='unscored'))throw Error('返回结果与本次问题或材料阶段不一致，已拒绝展示。');
      if((expectedCaseHash&&data.source?.case_bundle_sha256!==expectedCaseHash)||(catalog?.source?.case_bundle_sha256&&data.source?.case_bundle_sha256!==catalog.source.case_bundle_sha256))throw Error('返回材料与当前目录不一致，请刷新案例状态后重试。');
      result=data;
      if(model&&data.columns.some(c=>c.generation!=='model-assisted')){error='本次模型解释未全部完成；下方保留实际取回证据。可以显式改用离线证据重试。';}
    }catch(e){if(ticket===serial)error=active.timedOut?'本地等待已超时，问题仍保留。服务器可能继续处理，已发生的模型请求仍可能计费。':e.name==='AbortError'?'本地等待已中断，服务器可能继续处理。':e.name==='TypeError'?'无法连接本机服务，问题仍保留。请恢复服务后重试。':e.message;}
    finally{clearTimeout(active.timer);if(ticket===serial){pending=null;running=false;publish();}}
  }
  function configure(options={}){
    const nextMode=options.mode??mode,nextPhase=options.phase??phaseNow();
    if(!['fixed','free'].includes(nextMode)||!Object.hasOwn(phases,nextPhase))throw Error('提问方式或材料阶段无效。');
    contextChanged();
    if(options.reset){draft='';useModel=false;chosen='';expectedCaseHash=null;}
    if('expected_case_hash' in options)expectedCaseHash=typeof options.expected_case_hash==='string'?options.expected_case_hash:null;
    mode=nextMode;selectedPhase=nextPhase;
    if(typeof options.task_id==='string')chosen=options.task_id;
    else if(mode==='fixed'&&(!task()||task().phase!==nextPhase))chosen=catalog?.tasks.find(t=>t.phase===nextPhase)?.id||chosen;
    publish();return state();
  }
  function reset(){return configure({mode:'fixed',phase:'before',task_id:'before-occurrences',reset:true});}
  function mount(host,{compact=false}={}){const instance={host,compact};instances.add(instance);render(instance);if(!catalog&&!readPromise)read().catch(()=>{});return {destroy(){instances.delete(instance);host.replaceChildren();}};}
  mount(panel);
  async function open(options){if(options&&typeof options==='object'&&('mode'in options||'phase'in options))configure(options);panel.hidden=false;if(!catalog)await read().catch(()=>{});panel.scrollIntoView({behavior:'smooth',block:'start'});return state();}
  launch.addEventListener('click',()=>open());
  window.lianzhengTaskCompare={open,mount,state,refresh:read,configure,reset};
})();
