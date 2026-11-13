'use strict';
(() => {
  const launch=document.createElement('button');
  launch.type='button';launch.className='button secondary';launch.textContent='任务双栏对照';
  document.querySelector('.heading-actions').append(launch);
  const panel=document.createElement('section');
  panel.id='task-comparison-panel';panel.className='panel task-comparison-panel';panel.hidden=true;
  panel.setAttribute('aria-label','真实任务双栏对照');document.querySelector('main').append(panel);
  const instances=new Set(), selections=new Map(), esc=escapeHTML;
  const phases={before:'修复前',partial:'只更新直接依赖',after:'最终阶段',snapshot:'当前项目快照'};
  const timeouts={catalog:12000,offline:30000,model:100000};
  let catalog=null,chosen='',result=null,loading=false,running=false,error='',notice='',serial=0;
  let readPromise=null,useModel=false,mode='fixed',draft='',selectedPhase='before',pending=null,lastAttempt=null,expectedCaseHash=null;
  let scope='case',snapshotId=null,snapshotContext=null,workspaceSnapshotId=null,workspaceChanging=false;
  let readSerial=0,readController=null,readTimer=null,modelStatus=null;
  let baseline=null,acceptedAt=null,technicalOpen=false,selectedChange=null;
  const tracePositions=new Map(), captureLimit=500000;
  const clone=value=>JSON.parse(JSON.stringify(value));
  const caseURL=value=>typeof value==='string'&&/^\/api\/real-case\/files\/[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(value)?value:null;
  const task=()=>catalog?.tasks?.find(t=>t.id===chosen);
  const phaseNow=()=>scope==='snapshot'?'snapshot':mode==='free'?selectedPhase:(task()?.phase||selectedPhase);
  const questionNow=()=>mode==='free'?draft.trim():(task()?.question||'');
  const viewState=()=>({catalog,scope,snapshot_id:snapshotId,context:snapshotContext,workspace_changing:workspaceChanging,task_id:chosen,mode,phase:phaseNow(),question:questionNow(),result,baseline:baseline?clone(baseline):null,running,loading,error,notice,use_model:useModel,expected_case_hash:expectedCaseHash});
  const activeCatalog=()=>scope==='snapshot'?snapshotContext:catalog;
  const modelConfigured=()=>typeof activeCatalog()?.model_configured==='boolean'?activeCatalog().model_configured:(modelStatus??(typeof state==='object'?state.model:null))?.configured;
  const snapshotReady=()=>Boolean(!workspaceChanging&&snapshotId&&snapshotContext?.source?.snapshot_id===snapshotId&&/^[a-f0-9]{64}$/.test(snapshotContext?.source?.context_sha256||''));
  const mayRun=()=>!running&&!loading&&Boolean(questionNow())&&(scope!=='snapshot'||snapshotReady());
  function bound(value,source){return value?.scope==='snapshot'&&source?.scope==='snapshot'&&value.snapshot_id===source.snapshot_id&&value.context_sha256===source.context_sha256;}
  function sourceURL(value,source=result?.source){
    if(source?.scope!=='snapshot')return caseURL(value);
    if(typeof value!=='string'||!source.snapshot_id||!/^[a-f0-9]{64}$/.test(source.context_sha256||''))return null;
    const prefix='/api/snapshots/'+encodeURIComponent(source.snapshot_id)+'/task-comparison/sources/';
    if(!value.startsWith(prefix))return null;
    const tail=value.slice(prefix.length),query='?context_sha256='+source.context_sha256;
    return tail.endsWith(query)&&/^[A-Za-z0-9_-]+$/.test(tail.slice(0,-query.length))?value:null;
  }
  const emit=()=>window.dispatchEvent(new CustomEvent('lianzheng-task-comparison-changed',{detail:viewState()}));
  function publish(){for(const instance of instances)render(instance);emit();}
  function clearResult(){result=null;acceptedAt=null;selections.clear();tracePositions.clear();selectedChange=null;error='';notice='';lastAttempt=null;}
  function clearBaseline(){baseline=null;technicalOpen=false;selectedChange=null;}
  function leavePending(message=''){
    ++serial;
    if(pending){clearTimeout(pending.timer);pending.controller.abort();pending=null;}
    running=false;
    if(message){error=message;notice='';}
  }
  function contextChanged(){leavePending();clearResult();}
  function cancelRead(){++readSerial;if(readController)readController.abort();if(readTimer)clearTimeout(readTimer);readController=null;readTimer=null;readPromise=null;loading=false;}
  function summaryText(r){
    if(r.comparison?.result==='unscored')return '现场提问 · 不计算得分或胜负';
    return r.comparison?.result==='tie'?'参考证据覆盖打平':r.comparison?.result==='graph-more'?'图增强检索覆盖更多参考证据':'文本检索覆盖更多参考证据';
  }
  function excerptLabel(d){
    return d.source_excerpt_kind==='raw-log'?'保存的原始日志片段':['raw-text','saved-source-content'].includes(d.source_excerpt_kind)?'保存的来源原文片段':d.kind==='migration'?'原始差异文件片段':'原始 JSON 条目（解析后显示）';
  }
  function fileLink(d){const href=sourceURL(d.url);return href?`<a href="${esc(href)}" download>下载 ${esc(d.filename)} ↗</a>`:'<span>此来源暂无可下载文件。</span>';}
  function evidence(d){return `<details class="tc-evidence"><summary><span>${esc(d.id)}</span> ${esc(d.title)}</summary><small>规范化事实 · ${esc(phases[d.phase]||d.phase)} · ${esc(d.locator)}</small><pre>${esc(d.text)}</pre>${d.source_excerpt?`<details><summary>${excerptLabel(d)}${d.source_excerpt_truncated?'（节选）':''}</summary><pre>${esc(d.source_excerpt)}</pre></details>`:''}<p>${fileLink(d)}</p><code>SHA-256 ${esc(d.source_sha256||'见来源清单')}</code></details>`;}
  // A linked view is always scoped to the current result and one retrieval column.
  // Never infer an edge, citation, or semantic support from model prose.
  function linksFor(c){
    const pack=c.evidence_links||{},source=pack.source||{};
    const scoped=result?.source?.scope==='snapshot';
    const evidence=(c.evidence||[]).filter(d=>d.phase===result?.task?.phase&&(!scoped||bound(d,result.source)));
    const byId=new Map(evidence.map(d=>[d.id,d]));
    if(scoped?!bound(source,result.source):source.phase!==result?.task?.phase||source.case_bundle_sha256!==result?.source?.case_bundle_sha256)return {evidence,paths:[],facts:[]};
    const paths=(pack.paths||[]).filter(p=>{
      if(!Array.isArray(p.nodes)||p.nodes.length<2||!Array.isArray(p.edges)||p.edges.length!==p.nodes.length-1)return false;
      if(scoped&&(!bound(p,result.source)||!p.nodes.every(n=>bound(n,result.source))||!p.edges.every(e=>bound(e,result.source))))return false;
      return p.edges.every((edge,i)=>edge.source===p.nodes[i].ref&&edge.target===p.nodes[i+1].ref&&
        Array.isArray(edge.evidence_ids)&&edge.evidence_ids.length>0&&edge.evidence_ids.every(id=>
          byId.get(id)?.relations?.some(r=>r.source===edge.source&&r.target===edge.target)));
    });
    const pathIds=new Set(paths.map(p=>p.id));
    const facts=(pack.facts||[]).filter(f=>(!scoped||bound(f,result.source))&&['retrieved-fact','model-claim'].includes(f.kind)&&Array.isArray(f.evidence_ids)&&
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
      ${doc?`<div class="tc-linked-source"><div class="tc-source-location"><strong>${esc(doc.filename)}</strong><code>${esc(doc.locator)}</code><span>${esc(phases[doc.phase]||doc.phase)}</span></div><details class="tc-normalized"><summary>规范化事实摘录（非上游逐字原文）</summary><pre>${esc(doc.text)}</pre></details>${doc.source_excerpt?`<strong class="tc-excerpt-label">${excerptLabel(doc)}${doc.source_excerpt_truncated?'（节选）':''}</strong><pre class="tc-original-excerpt">${esc(doc.source_excerpt)}</pre>${doc.source_excerpt_truncated?'<p class="tc-meta">此片段已截断，完整依据请下载原文件。</p>':''}`:'<p class="tc-meta">此汇总没有对应的逐字原文片段，请下载来源文件核对。</p>'}<p>${fileLink(doc)}</p><code class="tc-source-hash">SHA-256 ${esc(doc.source_sha256||'见来源清单')}</code></div>`:''}
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
  function graphColumn(data){return data?.columns?.find(c=>c.id==='bm25+graph')||data?.columns?.[1];}
  function validCard(card,c,source){
    if(!card||!bound(card,source))return false;
    const ids=new Set(c.evidence.map(e=>e.id));
    const item=value=>value&&typeof value.text==='string'&&value.text.length<=12000&&Array.isArray(value.evidence_ids)&&value.evidence_ids.length<=16&&value.evidence_ids.every(id=>typeof id==='string'&&ids.has(id));
    return item(card.conclusion)&&['reasons','unknowns','next_steps'].every(key=>Array.isArray(card[key])&&card[key].length<=24&&card[key].every(item));
  }
  function cardFor(c,data=result){
    if(validCard(c?.answer_card,c,data?.source))return c.answer_card;
    return {...data?.source,conclusion:{text:'当前返回没有结构化答案卡，请展开双栏核对检索依据。',evidence_ids:[]},reasons:[],unknowns:[{text:'尚无可展示的结构化结论。',evidence_ids:[]}],next_steps:[],note:'未生成结构化答案卡，不据此推断项目状态。'};
  }
  function cardItem(item,index){
    return `<div class="tc-card-item"><p>${esc(item.text)}</p><div class="tc-card-citations">${item.evidence_ids.length?item.evidence_ids.map(id=>`<button type="button" data-tc-card-evidence="${esc(id)}" data-tc-column="${index}" title="${esc((result?.columns[index]?.evidence.find(e=>e.id===id)?.title||'依据')+' · '+id)}">查看依据 ${(result?.columns[index]?.evidence.findIndex(e=>e.id===id)??-1)+1}</button>`).join(''):'<small>未绑定检索证据 · 提示或待确认项</small>'}</div></div>`;
  }
  function answerCard(){
    const c=graphColumn(result);if(!c)return '';
    const card=cardFor(c),index=result.columns.indexOf(c),generation=card.generation||c.generation;
    return `<section class="tc-answer-card" aria-label="当前项目答案卡"><div class="tc-card-heading"><div><span class="tc-eyebrow">ANSWER · EVIDENCE · NEXT STEP</span><h3>当前项目答案卡</h3></div><span>${generation==='model-assisted'?'模型解释 + 已取回依据':generation==='model-fallback'?'模型解释未采纳 · 证据摘要':'离线证据摘要'}</span></div><div class="tc-card-conclusion"><h4>当前结论</h4>${cardItem(card.conclusion,index)}</div><div class="tc-card-grid">${[['reasons','依据'],['unknowns','仍待确认'],['next_steps','下一步']].map(([key,label])=>`<section><h4>${label}</h4>${card[key].length?card[key].map(item=>cardItem(item,index)).join(''):'<p class="tc-meta">本次没有列出该项。</p>'}</section>`).join('')}</div><p class="tc-meta">${esc(card.note||'基于图增强侧实际取回材料；引用绑定校验不等于语义正确性评定。')}</p><button type="button" class="button secondary" data-tc-retain ${running?'disabled':''}>保留此回答作对照</button><small class="tc-memory-note">仅保存在本页；用于同项目、同一问题的资料变化复核。</small></section>`;
  }
  // Historical records deliberately omit source URLs. Their saved excerpts remain readable,
  // but can never be used as a live download under a newer material fingerprint.
  function freezeAnswer(data){
    const c=graphColumn(data),source=data.source;
    const rawCard=cardFor(c,data),item=value=>({text:value.text,evidence_ids:[...value.evidence_ids]});
    const card={scope:source.scope,snapshot_id:source.snapshot_id,context_sha256:source.context_sha256,generation:rawCard.generation||c.generation,conclusion:item(rawCard.conclusion),reasons:rawCard.reasons.map(item),unknowns:rawCard.unknowns.map(item),next_steps:rawCard.next_steps.map(item),note:rawCard.note};
    return clone({status:'historical-not-current',question:data.task.question,answered_at:acceptedAt,retained_at:new Date().toISOString(),
      source:{scope:source.scope,snapshot_id:source.snapshot_id,context_sha256:source.context_sha256,project:source.project,label:source.label,filename:source.filename},
      column_id:c.id,generation:card.generation,answer_card:card,evidence:c.evidence.map(e=>({id:e.id,stable_key:e.stable_key,content_sha256:e.content_sha256,title:e.title,text:e.text,filename:e.filename,locator:e.locator,source_sha256:e.source_sha256,source_excerpt:e.source_excerpt,source_excerpt_kind:e.source_excerpt_kind,source_excerpt_truncated:e.source_excerpt_truncated}))});
  }
  function changesFor(current){
    const before=baseline?.evidence,after=graphColumn(current)?.evidence;
    const usable=items=>Array.isArray(items)&&items.every(e=>typeof e.stable_key==='string'&&e.stable_key&&/^[a-f0-9]{64}$/.test(e.content_sha256||''))&&new Set(items.map(e=>e.stable_key)).size===items.length;
    if(!usable(before)||!usable(after))return null;
    const old=new Map(before.map(e=>[e.stable_key,e])),fresh=new Map(after.map(e=>[e.stable_key,e]));
    return {added:after.filter(e=>!old.has(e.stable_key)),removed:before.filter(e=>!fresh.has(e.stable_key)),changed:after.filter(e=>old.has(e.stable_key)&&old.get(e.stable_key).content_sha256!==e.content_sha256),unchanged:after.filter(e=>old.get(e.stable_key)?.content_sha256===e.content_sha256)};
  }
  const answerSections={conclusion:'结论',reasons:'依据',unknowns:'仍待确认',next_steps:'下一步'};
  const changeLabels={added:'本次新增条目',removed:'本次未列出条目',changed:'文字变化',unchanged:'文字未变'};
  // Pair only within a section and an identical set of stable cited identities.
  // Uncited or ambiguous items pair by exact text only, never by position or model similarity.
  function answerChanges(oldRecord,current){
    const c=graphColumn(current),source=current?.source;
    if(!oldRecord||!c||source?.scope!=='snapshot'||oldRecord.source?.snapshot_id!==source.snapshot_id||oldRecord.question!==current.task?.question)return [];
    const oldDocs=oldRecord.evidence||[],newDocs=c.evidence||[];
    const unique=docs=>{const counts=new Map();for(const d of docs)counts.set(d.stable_key,(counts.get(d.stable_key)||0)+1);return counts;};
    const flatten=(card,docs)=>{
      const byId=new Map(docs.map(d=>[d.id,d])),counts=unique(docs),items=[];
      for(const [section] of Object.entries(answerSections))for(const [index,item] of (section==='conclusion'?[card.conclusion]:card[section]||[]).entries()){
        const citations=[...new Set(item.evidence_ids)],evidence=citations.map(id=>byId.get(id)).filter(Boolean);
        const reliable=citations.length===evidence.length&&evidence.every(d=>typeof d.stable_key==='string'&&d.stable_key&&counts.get(d.stable_key)===1&&/^[a-f0-9]{64}$/.test(d.content_sha256||''));
        const keys=reliable?[...new Set(evidence.map(d=>d.stable_key))].sort():null;
        items.push({section,index,text:item.text,evidence_ids:citations,stable_keys:keys,identity:keys?JSON.stringify([section,keys]):null});
      }return items;
    };
    const before=flatten(oldRecord.answer_card,oldDocs),after=flatten(cardFor(c,current),newDocs),used=new Set(),pairs=new Map();
    // Exact matching first keeps repeated citations deterministic when list ordering changes.
    for(const old of before){const fresh=after.find(n=>!used.has(n)&&old.identity!==null&&n.identity===old.identity&&n.text===old.text);if(fresh){used.add(fresh);pairs.set(old,fresh);}}
    for(const old of before.filter(o=>!pairs.has(o)&&o.stable_keys?.length)){
      const oldGroup=before.filter(o=>!pairs.has(o)&&o.identity===old.identity),newGroup=after.filter(n=>!used.has(n)&&n.identity===old.identity);
      if(oldGroup.length===1&&newGroup.length===1){pairs.set(old,newGroup[0]);used.add(newGroup[0]);}
    }
    const entries=[];
    const add=(old,fresh)=>{
      const status=!old?'added':!fresh?'removed':old.text===fresh.text?'unchanged':'changed';
      const changedSources=old&&fresh?old.stable_keys.filter(key=>oldDocs.find(d=>d.stable_key===key)?.content_sha256!==newDocs.find(d=>d.stable_key===key)?.content_sha256):[];
      entries.push({id:'answer-change-'+entries.length,section:(fresh||old).section,status,before:old||null,after:fresh||null,changed_source_keys:changedSources});
    };
    for(const old of before)add(old,pairs.get(old));
    for(const fresh of after)if(!used.has(fresh))add(null,fresh);
    return entries;
  }
  function originalSource(doc,source,{historical=false,allowLinks=true}={}){
    const href=!historical&&allowLinks&&bound(doc,source)?sourceURL(doc.url,source):null;
    return `<article class="tc-change-source"><strong>${esc(doc.title||doc.filename||'已保存来源')}</strong><small>${historical?'历史原文副本 · 无实时下载':'本次取回来源'} · ${esc(doc.filename||'未知文件')}</small><code>行号 / JSON 定位：${esc(doc.locator||'未提供定位')}</code>${doc.source_excerpt?`<pre class="tc-original-excerpt">${esc(doc.source_excerpt)}</pre>`:`<p class="tc-meta">未保存逐字原文；以下仅为规范化事实。</p><pre class="tc-original-excerpt">${esc(doc.text||'无可显示内容')}</pre>`}${doc.source_excerpt_truncated?'<small>保存片段已截断。</small>':''}<code>来源 SHA-256 ${esc(doc.source_sha256||'未知')}</code><code>片段内容指纹 ${esc(doc.content_sha256||'未知')}</code>${href?`<a href="${esc(href)}" data-tc-current-source download>下载本次来源 ↗</a>`:''}</article>`;
  }
  function changesPanel(oldRecord,current,selection,{allowLinks=true}={}){
    const entries=answerChanges(oldRecord,current);if(!entries.length)return '<p class="tc-meta">先保留回答，再按同项目同题重新回答，即可逐项核对原文变化。</p>';
    const chosen=entries.find(e=>e.id===selection)||entries.find(e=>e.status==='changed')||entries.find(e=>e.status==='added')||entries[0];
    const c=graphColumn(current);
    const side=(item,docs,historical)=>`<article class="tc-answer-change-side"><span class="tc-history-label">${historical?'历史回答条目':'本次回答条目'}</span>${item?`<p class="tc-change-text">${esc(item.text)}</p>${item.evidence_ids.length?item.evidence_ids.map(id=>docs.find(d=>d.id===id)).filter(Boolean).map(d=>originalSource(d,historical?oldRecord.source:current.source,{historical,allowLinks})).join(''):'<p class="tc-meta">此项没有绑定检索证据，无法定位支持原文。</p>'}`:`<p class="tc-meta">${historical?'未找到可可靠配对的历史条目。':'本次未列出可可靠配对的条目。'}不据此判断观点被否定。</p>`}</article>`;
    return `<section class="tc-answer-changes" aria-label="答案条目变化与原文联动"><div class="tc-linkage-heading"><h4>答案哪一项变了？点选核对两次原文</h4><small>可追溯引用，不自动判定正确性</small></div><div class="tc-answer-change-counts">${Object.entries(changeLabels).map(([key,label])=>`<span>${label} <b>${entries.filter(e=>e.status===key).length}</b></span>`).join('')}</div><div class="tc-change-items">${entries.map(e=>`<button type="button" data-tc-change-item="${e.id}" class="tc-change-item tc-answer-${e.status}" aria-pressed="${e.id===chosen.id}"><span>${esc(answerSections[e.section])} · ${changeLabels[e.status]}</span>${esc((e.after||e.before).text)}</button>`).join('')}</div><p class="tc-meta">按章节及稳定引用集合配对；无引用条目仅按相同文字配对。不含全文逐句差异或语义评定。引用集合变化或存在歧义时分别列为新增 / 未列出，不推断它们互相替代。文字变化、引用变化均不证明资料导致结论变化。</p><div class="tc-change-focus" role="status"><strong>${answerSections[chosen.section]} · ${changeLabels[chosen.status]}</strong><p>${chosen.status==='changed'?(chosen.changed_source_keys.length?'引用标识相同，文字和部分引用内容均变化；需对照原文人工判断。':'引用材料及内容指纹相同，仅回答文字变化。'):chosen.status==='unchanged'?(chosen.changed_source_keys.length?'条目文字未变；部分引用原文内容有变化，请继续核对。':'条目文字与引用内容指纹未变。'):'此项没有可靠配对；不表示新增事实成立或原观点失效。'}</p></div><div class="tc-answer-change-columns">${side(chosen.before,oldRecord.evidence,true)}${side(chosen.after,c.evidence,false)}</div></section>`;
  }
  function validTrace(c,data){
    const trace=c?.retrieval_trace,source=data?.source;
    if(!trace||trace.schema!=='lianzheng-retrieval-trace-v1'||trace.status!=='ready'||!bound(trace,source)||trace.method!==c.id)return null;
    const integer=value=>Number.isSafeInteger(value)&&value>=0;
    const text=value=>typeof value==='string'&&value.length<=12000;
    const noURLs=value=>!value||typeof value!=='object'||Object.entries(value).every(([key,child])=>!['url','href','source_url'].includes(key)&&noURLs(child));
    if(JSON.stringify(trace).length>100000||!noURLs(trace))return null;
    const ids=c.evidence.map(e=>e.id),idSet=new Set(ids),refs=value=>Array.isArray(value)&&value.length<=16&&value.every(id=>idSet.has(id));
    if(!Array.isArray(trace.selected_evidence_ids)||JSON.stringify(trace.selected_evidence_ids)!==JSON.stringify(ids))return null;
    const candidates=trace.candidates,selection=trace.selection,graph=trace.graph;
    if(!Array.isArray(candidates)||candidates.length>256||!integer(trace.candidate_count)||trace.candidate_count<candidates.length||typeof trace.candidates_truncated!=='boolean')return null;
    if(new Set(candidates.map(x=>x.id)).size!==candidates.length||new Set(candidates.map(x=>x.final_rank)).size!==candidates.length||!candidates.every(x=>bound(x,source)&&text(x.id)&&text(x.title)&&integer(x.final_rank)&&x.final_rank>0&&x.final_rank<=trace.candidate_count&&(x.lexical_rank===null||(integer(x.lexical_rank)&&x.lexical_rank>0))&&(x.graph_priority_rank===null||(integer(x.graph_priority_rank)&&x.graph_priority_rank>0))&&['selected','skipped-budget','not-considered-limit'].includes(x.status)&&(x.status==='selected'?idSet.has(x.evidence_id):x.evidence_id===undefined)))return null;
    const selected=candidates.filter(x=>x.status==='selected');
    if(selected.length!==ids.length||new Set(selected.map(x=>x.evidence_id)).size!==ids.length||JSON.stringify([...selected].sort((a,b)=>a.final_rank-b.final_rank).map(x=>x.evidence_id))!==JSON.stringify(ids))return null;
    if(!selection||!['limit','max_bytes','used_bytes','selected_count','skipped_budget_count','not_considered_count'].every(k=>integer(selection[k]))||selection.selected_count!==ids.length||selection.selected_count>selection.limit||selection.used_bytes>selection.max_bytes)return null;
    if(!graph||!bound(graph,source)||!['applied','text-only','no-matched-targets','no-path-intent'].includes(graph.status)||!Array.isArray(graph.matched_targets)||graph.matched_targets.length>64||!integer(graph.matched_target_count)||graph.matched_target_count<graph.matched_targets.length||typeof graph.targets_truncated!=='boolean')return null;
    const node=n=>bound(n,source)&&text(n.ref)&&text(n.name)&&text(n.version)&&text(n.locator)&&/^[a-f0-9]{64}$/.test(n.source_sha256||'')&&text(n.filename)&&refs(n.evidence_ids)&&n.evidence_ids.every(id=>c.evidence.some(d=>d.id===id&&d.ref===n.ref&&d.source_sha256===n.source_sha256));
    const declaration=e=>['declaration_excerpt','declaration_excerpt_kind','declaration_excerpt_truncated'].every(key=>e[key]===undefined)||(typeof e.declaration_excerpt==='string'&&e.declaration_excerpt.length<=800&&e.declaration_excerpt_kind==='saved-source-content'&&typeof e.declaration_excerpt_truncated==='boolean');
    if(!graph.matched_targets.every(n=>node(n)&&(n.evidence_id===undefined||n.evidence_ids.includes(n.evidence_id))))return null;
    if(!Array.isArray(graph.paths)||graph.paths.length>8||!integer(graph.path_count)||graph.path_count<graph.paths.length||typeof graph.paths_truncated!=='boolean')return null;
    if(!graph.paths.every(p=>bound(p,source)&&text(p.id)&&typeof p.complete==='boolean'&&typeof p.truncated==='boolean'&&p.complete!==p.truncated&&Array.isArray(p.nodes)&&p.nodes.length>=1&&p.nodes.length<=32&&integer(p.node_count)&&p.node_count>=p.nodes.length&&(p.complete?p.node_count===p.nodes.length:p.node_count>p.nodes.length)&&Array.isArray(p.edges)&&p.edges.length===p.nodes.length-1&&p.nodes.every(node)&&p.edges.every((e,i)=>bound(e,source)&&e.source===p.nodes[i].ref&&e.target===p.nodes[i+1].ref&&text(e.locator)&&text(e.source_locator)&&text(e.target_locator)&&/^[a-f0-9]{64}$/.test(e.source_sha256||'')&&text(e.filename)&&declaration(e)&&refs(e.evidence_ids)&&e.evidence_ids.every(id=>c.evidence.some(d=>d.id===id&&d.source_sha256===e.source_sha256&&d.relations?.some(r=>r.source===e.source&&r.target===e.target&&r.locator===e.locator))))))return null;
    if((c.id==='bm25')!==(graph.status==='text-only')||(graph.status!=='applied'&&(graph.paths.length||candidates.some(x=>x.graph_priority_rank!==null))))return null;
    if(!Array.isArray(trace.steps)||trace.steps.length!==4||!trace.steps.every((step,i)=>bound(step,source)&&step.id===['lexical','entity-match','graph-priority','budget'][i]&&text(step.label)&&text(step.detail)&&integer(step.count)))return null;
    return trace;
  }
  const graphStatusLabels={applied:'实际采用图路径优先排序','text-only':'文本侧未使用图排序','no-matched-targets':'未匹配到目标实体，未使用图排序','no-path-intent':'问题未触发路径意图，未使用图排序'};
  function traceColumn(c,index,data,positions){
    const trace=validTrace(c,data);
    if(!trace)return `<article class="tc-trace-column"><h4>${index===0?'A · 文本检索':'B · 图增强检索'}</h4><p class="tc-meta">本侧没有可验证的已记录检索过程，暂不能回放。仍可核对实际取回的证据；不会补造步骤或自动重新检索。</p></article>`;
    const position=Math.max(0,Math.min(3,positions.get(c.id)||0)),step=trace.steps[position];
    const selectedButton=(id,label)=>`<button type="button" data-tc-trace-evidence="${esc(id)}" data-tc-column="${index}">${esc(label)}</button>`;
    const paths=trace.graph.paths.map(p=>`<details class="tc-trace-path"><summary>实际用于排序的路径 · ${p.node_count} 个节点${p.truncated?'（仅显示连续前缀）':''}</summary><div class="tc-path-chain">${p.nodes.map((n,i)=>`${i?'<span class="tc-path-arrow">→</span>':''}<span class="tc-path-node"><b>${esc(n.name)}@${esc(n.version)}</b><small>${esc(n.locator)}</small></span>`).join('')}</div>${p.edges.map(e=>`<article class="tc-trace-edge"><p class="tc-meta">${esc(e.source)} → ${esc(e.target)}<br>${esc(e.filename)} · ${esc(e.locator)}<br>来源 SHA-256 ${esc(e.source_sha256)}</p>${e.declaration_excerpt!==undefined?`<strong class="tc-excerpt-label">保存的关系声明值（JSON 显示）</strong><pre class="tc-original-excerpt">${esc(e.declaration_excerpt)}</pre>${e.declaration_excerpt_truncated?'<small>声明片段已截断，请按定位核对完整清单。</small>':''}`:'<p class="tc-meta">旧记录未保存声明值，请按 JSON 定位核对来源清单。</p>'}<div>${e.evidence_ids.length?e.evidence_ids.map(id=>selectedButton(id,'查看本侧关系证据片段')).join(''):'此边存在于检索图中；本侧未取回相应关系片段。'}</div></article>`).join('')}<p class="tc-meta">检索路径用于材料排序，不等于答案推理过程或运行调用轨迹。</p></details>`).join('');
    const candidates=[...trace.candidates].sort((a,b)=>(position===0?(a.lexical_rank??Infinity)-(b.lexical_rank??Infinity):a.final_rank-b.final_rank)||a.final_rank-b.final_rank);
    return `<article class="tc-trace-column"><h4>${index===0?'A · 文本检索':'B · 图增强检索'}</h4><p class="tc-meta">${esc(graphStatusLabels[trace.graph.status])}</p><div class="tc-trace-steps" role="group" aria-label="${index===0?'A':'B'} 检索回放步骤">${trace.steps.map((s,i)=>`<button type="button" data-tc-trace-step="${i}" data-tc-column="${index}" aria-pressed="${i===position}">${i+1}. ${esc(s.label)}</button>`).join('')}</div><div class="tc-trace-focus" role="status"><strong>${position+1} / 4 · ${esc(step.label)}</strong><p>${esc(step.detail)}</p><small>记录计数 ${step.count}</small></div><div class="tc-trace-nav"><button type="button" data-tc-trace-step="${position-1}" data-tc-column="${index}" ${position===0?'disabled':''}>上一步</button><button type="button" data-tc-trace-step="${position+1}" data-tc-column="${index}" ${position===3?'disabled':''}>下一步</button></div>${position===1?`<div class="tc-trace-targets"><strong>匹配实体 ${trace.graph.matched_target_count}</strong>${trace.graph.matched_targets.map(n=>`<p>${esc(n.name)}@${esc(n.version)}<small>${esc(n.ref)}</small>${n.evidence_id?selectedButton(n.evidence_id,'核对已取回实体片段'):''}</p>`).join('')||'<p>没有匹配目标。</p>'}${trace.graph.targets_truncated?'<small>匹配实体列表已截断。</small>':''}</div>`:''}${position===2?`${paths||'<p class="tc-meta">本次没有用于优先排序的图路径。</p>'}${trace.graph.paths_truncated?'<p class="tc-meta">路径展示已截断，未显示的路径不在此处补推。</p>':''}`:''}${position===0||position===2||position===3?`<details class="tc-trace-candidates" ${position===3?'open':''}><summary>候选与最终取回 · ${trace.candidate_count} 份候选 / ${trace.selected_evidence_ids.length} 份取回</summary><p class="tc-meta">候选片段参与排序，不表示已送入答案生成。${trace.candidates_truncated?'候选展示已截断，保留全部选中项。':''}</p>${candidates.map(x=>`<div class="tc-trace-candidate ${x.status==='selected'?'selected':''}"><span>${x.status==='selected'?'已取回':x.status==='skipped-budget'?'候选 · 字节预算不足':'候选 · 达到数量上限'}</span><strong>${esc(x.title)}</strong><small>文本排名 ${x.lexical_rank??'未进入文本排序'} · 图优先序 ${x.graph_priority_rank??'未提升'} · 最终排名 ${x.final_rank}</small>${x.status==='selected'?selectedButton(x.evidence_id,'查看本侧实际原文'):''}</div>`).join('')}</details>`:''}${position===3?`<p class="tc-meta">实际取回 ${trace.selection.selected_count} / ${trace.selection.limit} 份 · ${trace.selection.used_bytes} / ${trace.selection.max_bytes} UTF-8 字节 · 跳过预算不足 ${trace.selection.skipped_budget_count} 份 · 达到数量上限后未再考虑 ${trace.selection.not_considered_count} 份。</p>`:''}</article>`;
  }
  function evidenceOverlap(data){
    if(data?.source?.scope!=='snapshot'||data.columns?.length!==2)return '';
    const [left,right]=data.columns.map(c=>c.evidence.filter(e=>bound(e,data.source))),leftIds=new Set(left.map(e=>e.id)),rightIds=new Set(right.map(e=>e.id));
    const groups=[['两侧共同取回',left.filter(e=>rightIds.has(e.id)),0],['仅 A 侧取回',left.filter(e=>!rightIds.has(e.id)),0],['仅 B 侧取回',right.filter(e=>!leftIds.has(e.id)),1]];
    return `<section class="tc-retrieval-overlap" aria-label="两侧实际取回证据交集"><h4>两侧实际取回证据交集</h4><div>${groups.map(([label,docs,index])=>`<details><summary>${label} <b>${docs.length}</b></summary>${docs.map(e=>`<button type="button" data-tc-trace-evidence="${esc(e.id)}" data-tc-column="${index}">${esc(e.title)}</button>`).join('')||'<p>无</p>'}</details>`).join('')}</div><p class="tc-meta">只比较当前项目、同次回答的最终取回集合。交集或差集大小不代表回答质量或图增强优劣。</p></section>`;
  }
  function tracePanel(data,positions=tracePositions){
    if(data?.source?.scope!=='snapshot')return '';
    return `<section class="tc-retrieval-trace" aria-label="已记录的检索过程回放"><div class="tc-linkage-heading"><h3>回放这次检索如何取回材料</h3><small>只读已完成请求 · 不重跑检索或模型</small></div><p class="tc-meta">逐步查看文本候选、实体匹配、图路径排序和预算裁剪。这是程序记录的检索轨迹，不是模型思维过程。</p><div class="tc-trace-columns">${data.columns.map((c,i)=>traceColumn(c,i,data,positions)).join('')}</div>${evidenceOverlap(data)}</section>`;
  }
  function generationLabel(value){return value==='model-assisted'?'模型解释 + 已取回依据':value==='model-fallback'?'模型解释未采纳 · 证据摘要':'离线证据摘要';}
  function sameQuestionResult(){return result?.source?.scope==='snapshot'&&baseline?.source.snapshot_id===result.source.snapshot_id&&baseline.question===result.task.question;}
  function historyView(){
    if(!baseline||scope!=='snapshot')return '';
    const current=sameQuestionResult()?result:null,changes=current?changesFor(current):null;
    const refreshed=snapshotReady()&&snapshotContext.source.context_sha256!==baseline.source.context_sha256;
    const conclusion=current?cardFor(graphColumn(current)).conclusion.text:null;
    return `<section class="tc-history" aria-label="补充资料前后回答对照"><div class="tc-card-heading"><div><span class="tc-eyebrow">SAME QUESTION · MATERIAL CHANGE</span><h3>补充资料前后回答对照</h3></div><button type="button" class="button secondary" data-tc-forget>清除历史对照</button></div><p class="tc-history-question">同一问题：${esc(baseline.question)}</p><div class="tc-history-columns"><article><span class="tc-history-label">保留回答 · 历史记录，非当前状态</span><p>${esc(baseline.answer_card.conclusion.text)}</p><small>${esc(generationLabel(baseline.generation))}<br>回答时间 ${esc(baseline.answered_at||'未知')}<br>保留时间 ${esc(baseline.retained_at)}</small><code>原材料指纹 ${esc(baseline.source.context_sha256)}</code></article><article><span class="tc-history-label">${current?'本次回答':'等待按新资料重新回答'}</span><p>${esc(conclusion||(running?'正在等待新回答；历史记录保持原样。':error?'新回答尚未成功，不能用历史回答代表新材料。':refreshed?'资料已更新。请明确点击下方按钮，再生成同题回答。':'先补充项目资料，再刷新材料并明确重新回答。'))}</p>${current?`<small>${esc(generationLabel(cardFor(graphColumn(current)).generation||graphColumn(current).generation))}<br>回答时间 ${esc(acceptedAt||'未知')}</small><code>本次材料指纹 ${esc(current.source.context_sha256)}</code>`:''}</article></div>${current?`<p class="tc-meta">${current.source.context_sha256===baseline.source.context_sha256?'两次材料指纹相同。':'两次材料指纹不同。'}上方并列展示结论摘要，下方按答案条目核对文字、引用及原文变化；不进行语义或因果判断。依据比较仅包括图增强侧两次实际取回的材料；本次未取回可能来自检索排序变化，不代表资料已删除，也不证明回答更正确或修复已完成。</p>${changes?`<div class="tc-change-grid">${[['added','新增'],['removed','本次未取回'],['changed','内容改变'],['unchanged','未变']].map(([key,label])=>`<details class="tc-change-${key}"><summary>${label}依据 <b>${changes[key].length}</b></summary>${changes[key].map(e=>`<p>${esc(e.title||e.stable_key)}<code>${esc(e.stable_key)}</code></p>`).join('')||'<p>无</p>'}</details>`).join('')}</div>`:'<p class="tc-meta">缺少稳定证据标识或内容指纹，无法可靠统计变化。</p>'}${changesPanel(baseline,current,selectedChange)}`:''}<details class="tc-history-excerpts"><summary>查看保留时的依据片段（历史副本，无下载链接）</summary>${baseline.evidence.map(e=>`<article><strong>${esc(e.title)}</strong><small>${esc(e.filename)} · ${esc(e.locator)}</small><pre>${esc(e.source_excerpt||e.text||'无保存片段')}</pre>${e.source_excerpt_truncated?'<small>保存的片段已截断。</small>':''}<code>来源 SHA-256 ${esc(e.source_sha256||'未知')}</code><code>片段内容指纹 ${esc(e.content_sha256||'未知')}</code></article>`).join('')}</details><div class="tc-actions"><button type="button" class="button secondary" data-tc-supplement ${running||loading||workspaceChanging?'disabled':''}>补充项目资料</button><button type="button" class="button primary" data-tc-reask ${!refreshed||!mayRun()?'disabled':''}>根据新资料重新回答</button><button type="button" class="button secondary" data-tc-download-change>导出回答变化 JSON</button></div><p class="tc-meta">刷新页面、换项目或改问题会清除历史对照。补资料不会自动调用模型；重新回答仍采用当前明确选择的模式。</p></section>`;
  }
  function resultColumns(){
    const columns=`<div class="tc-columns">${result.columns.map(column).join('')}</div>`;
    return scope==='snapshot'?`${answerCard()}${tracePanel(result)}<details class="tc-technical" data-tc-technical ${technicalOpen?'open':''}><summary>展开检索双栏与原文证据</summary>${columns}</details>`:columns;
  }
  function controls(instance){
    const isProject=scope==='snapshot',busy=running||loading||(isProject&&!snapshotReady());
    const source=activeCatalog()?.source;
    const scopeTabs=instance.lockScope?'':`<div class="tc-scope-tabs" role="group" aria-label="提问材料来源"><button type="button" data-tc-scope="snapshot" aria-pressed="${isProject}">当前项目</button><button type="button" data-tc-scope="case" aria-pressed="${!isProject}">固定参赛案例</button></div>`;
    const sourceCard=isProject?`<div class="tc-project-source" role="status"><strong>${esc(source?.project||'当前项目')}</strong><span>${esc(source?.label||snapshotId||'尚未选择快照')}</span><small>${loading?'正在核对当前快照、扫描与项目文档…':snapshotReady()?'本次问题仅检索此快照的材料；同名组件不会与其他项目合并。':'请先载入工作空间快照，再刷新材料状态。'}</small>${source?.context_sha256?`<code>材料指纹 ${esc(source.context_sha256.slice(0,16))} · ${esc(source.filename||'导入清单')}</code>`:''}</div>`:'';
    const fixed=`<label>选择真实任务<select data-tc-task aria-label="选择真实对照任务" ${loading||running?'disabled':''}>${catalog?.tasks.map(t=>`<option value="${esc(t.id)}" ${t.id===chosen?'selected':''}>${esc(phases[t.phase])} · ${esc(t.question)}</option>`).join('')||'<option>正在读取任务…</option>'}</select></label>`;
    const prompts=isProject?['当前清单有哪些依赖路径？','哪些组件的漏洞状态仍未确认？','这些材料足以证明安全上线吗？']:['minimist 从哪些依赖路径引入？','测试失败的依据是什么？','这些材料足以证明安全上线吗？'];
    const free=`<div class="tc-free-fields ${isProject?'tc-project-fields':''}"><label>现场问题<textarea data-tc-question aria-label="现场提问内容" maxlength="1000" rows="2" ${running?'disabled':''} placeholder="${isProject?'例如：某个组件通过哪些路径引入？请写出组件名。':'例如：只升级直接 minimist 后，哪些位置仍需核对？'}">${esc(draft)}</textarea><small data-tc-length>${draft.length}/1000 · Ctrl / ⌘ + Enter 运行</small></label>${isProject?'':`<label>材料阶段<select data-tc-phase aria-label="现场提问材料阶段" ${running?'disabled':''}>${Object.entries(phases).filter(([id])=>id!=='snapshot').map(([id,name])=>`<option value="${id}" ${selectedPhase===id?'selected':''}>${name}</option>`).join('')}</select></label>`}<div class="tc-question-chips">${prompts.map(q=>`<button type="button" data-tc-prompt="${esc(q)}" ${running?'disabled':''}>${esc(q)}</button>`).join('')}</div></div>`;
    const modeTabs=isProject?'':`<div class="tc-mode-tabs" role="group" aria-label="提问方式"><button type="button" data-tc-mode="fixed" aria-pressed="${mode==='fixed'}" ${running?'disabled':''}>固定任务对照</button><button type="button" data-tc-mode="free" aria-pressed="${mode==='free'}" ${running?'disabled':''}>现场提问</button><span>${esc(phases[phaseNow()])} · 固定 http-server 案例</span></div>`;
    return `${scopeTabs}${sourceCard}${modeTabs}<div class="tc-controls">${mode==='fixed'?fixed:free}<label class="tc-model-toggle"><input type="checkbox" data-tc-model ${useModel?'checked':''} ${busy||modelConfigured()!==true?'disabled':''}>两侧使用同一模型解释（最多两次请求，可能计费）${isProject&&modelConfigured()!==true?`<small>${modelConfigured()===false?'模型尚未配置，可先使用离线证据。':'模型状态尚未确认；先查看顶部模型设置，离线证据可直接使用。'}</small>`:''}</label><div class="tc-actions"><button type="button" class="button primary" data-tc-run ${!mayRun()?'disabled':''}>${running?'正在对照…':useModel?'运行两侧模型对照':'运行离线证据对照'}</button>${running?'<button type="button" class="button secondary" data-tc-stop>停止等待</button>':''}<button type="button" class="button secondary" data-tc-refresh ${loading||running||(isProject&&workspaceChanging)?'disabled':''}>${isProject?'刷新项目材料与模型状态':'刷新任务与模型状态'}</button>${result?'<button type="button" class="button secondary" data-tc-download>下载本次对照 JSON</button>':''}</div></div>`;
  }
  function render(instance){
    const {host,compact}=instance;
    const active=host.contains?.(document.activeElement)?document.activeElement:null;
    const focusAttr=['data-tc-change-item','data-tc-trace-step','data-tc-trace-evidence','data-tc-retain','data-tc-forget','data-tc-supplement','data-tc-reask','data-tc-card-evidence','data-tc-scope','data-tc-question','data-tc-fact','data-tc-path','data-tc-evidence','data-tc-select-evidence','data-tc-mode','data-tc-task','data-tc-phase','data-tc-model','data-tc-run','data-tc-stop','data-tc-refresh','data-tc-offline'].find(name=>active?.hasAttribute?.(name));
    const focusValue=focusAttr?active.getAttribute(focusAttr):null,focusColumn=active?.dataset?.tcColumn;
    const caret=focusAttr==='data-tc-question'?[active.selectionStart,active.selectionEnd]:null;
    host.classList.add('task-comparison-workbench');host.classList.toggle('tc-compact',compact);host.classList.toggle('tc-free-mode',mode==='free');
    host.innerHTML=`${compact?'':`<div class="panel-heading"><div><span class="tc-eyebrow">SAME SOURCES · PAIRED RETRIEVAL</span><h2>${scope==='snapshot'?'当前项目问答':'真实任务双栏对照'}</h2><p>现场提出问题，沿已取回材料核对结论。</p></div><button type="button" class="button secondary" data-tc-close>收起对照</button></div>`}<p class="tc-boundary">${scope==='snapshot'?'当前导入项目材料随所选快照切换，问题与证据按材料指纹隔离。':'固定 http-server 实验材料，不随工作空间切换。'}${mode==='free'?'自由题没有预设参考答案，不计算准确率或胜负。':'16 道开发者整理题，尚未经独立评审。'}</p>${controls(instance)}
      ${error?`<div class="tc-alert" role="alert"><p>${esc(error)}</p>${lastAttempt?'<button type="button" class="button secondary" data-tc-offline>改用离线证据重试</button>':''}</div>`:''}${notice?`<p class="tc-notice" role="status">${esc(notice)}</p>`:''}
      <details class="tc-protocol-brief"><summary>相同材料与预算 · 结构差异不等于回答准确率</summary><p>${esc(activeCatalog()?.protocol?.statement||'进入页面不会自动运行模型。')} 两侧都读取关系文本、共用片段路径连接步骤。可连通位置包含未命中目标公告的版本。</p></details>${running?'<p class="tc-notice" role="status">正在等待本次结果。停止等待只中断本机接收，服务器可能继续处理，已发生的请求仍可能计费。</p>':''}
      ${historyView()}${result?`<div class="tc-result-summary" role="status"><strong>${summaryText(result)}</strong><span>本次材料：${esc(result.source.scope==='snapshot'?`${result.source.project} · ${result.source.label}`:phases[result.task.phase])}</span><p>${esc(result.comparison.note)}</p>${result.model_calls_attempted?`<p>模型解释尝试 ${result.model_calls_attempted} 次。${result.fairness.model_pair_comparable?'两侧返回模型一致，语义优劣仍未评定。':'两侧未同时完成或模型无法确认一致，不能比较生成质量。'}</p>`:''}</div>${resultColumns()}<details class="tc-protocol"><summary>来源、统一条件与验证范围</summary>${result.source.scope==='snapshot'?`<p>快照 ${esc(result.source.snapshot_id)} · ${esc(result.source.filename)}</p><p>${esc(result.source.serialization||'来源为当前快照中保存的材料。')}</p><code>材料指纹 ${esc(result.source.context_sha256)}</code>`:`<p>提交 ${esc(result.source.commit)}</p><p>阶段来源 ${esc(result.source.lockfile)}</p>`}<p>候选片段 ${result.fairness.candidate_documents} 份 · 每侧最多 ${result.fairness.k} 份 · 片段上限 ${result.fairness.evidence_max_bytes} 字节 · 模型消息上限 ${result.fairness.model_max_input_bytes} 字节</p><code>统一语料 SHA-256 ${esc(result.fairness.corpus_sha256)}</code><p>${esc(result.fairness.shared_postprocessing)}</p><ul>${result.limitations.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></details>`:running?'':`<div class="tc-empty"><strong>${mode==='free'?'写下一个问题，再核对两侧依据':'先选一题，再运行对照'}</strong><p>默认不调用模型。现场问题和回答只保留在当前页面内存，刷新后不恢复。</p></div>`}`;
    bind(instance);
    if(focusAttr){const replacement=[...host.querySelectorAll('['+focusAttr+']')].find(e=>e.getAttribute(focusAttr)===focusValue&&e.dataset.tcColumn===focusColumn);if(replacement&&!replacement.disabled){replacement.focus({preventScroll:true});if(caret)replacement.setSelectionRange(...caret);}}
  }
  function chooseLink(index,changes){
    const c=result?.columns?.[index];if(!c)return;
    selections.set(c.id,{...(selections.get(c.id)||{}),...changes});publish();
  }
  function download(value,filename){const blob=new Blob([JSON.stringify(value,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  function bind(instance){
    const {host}=instance;
    host.querySelector('[data-tc-close]')?.addEventListener('click',()=>{panel.hidden=true;launch.focus();});
    host.querySelectorAll('[data-tc-scope]').forEach(b=>b.addEventListener('click',()=>configure({scope:b.dataset.tcScope,mode:b.dataset.tcScope==='snapshot'?'free':'fixed'})));
    host.querySelectorAll('[data-tc-mode]').forEach(b=>b.addEventListener('click',()=>configure({mode:b.dataset.tcMode})));
    host.querySelector('[data-tc-task]')?.addEventListener('change',e=>{clearBaseline();contextChanged();chosen=e.target.value;publish();});
    host.querySelector('[data-tc-phase]')?.addEventListener('change',e=>configure({phase:e.target.value}));
    host.querySelector('[data-tc-model]')?.addEventListener('change',e=>{contextChanged();useModel=e.target.checked&&modelConfigured()===true;publish();});
    host.querySelector('[data-tc-question]')?.addEventListener('input',e=>{
      const previousQuestion=questionNow(),hadBaseline=Boolean(baseline);draft=e.target.value;const cursor=e.target.selectionStart;
      if(questionNow()!==previousQuestion){clearBaseline();if(running)leavePending();}
      if(result||error||notice||hadBaseline){clearResult();publish();const replacement=host.querySelector('[data-tc-question]');replacement.focus();replacement.setSelectionRange(cursor,cursor);}
      else {for(const inst of instances){const input=inst.host.querySelector('[data-tc-question]');if(input&&input!==e.target)input.value=draft;const count=inst.host.querySelector('[data-tc-length]');if(count)count.textContent=`${draft.length}/1000 · Ctrl / ⌘ + Enter 运行`;const button=inst.host.querySelector('[data-tc-run]');if(button)button.disabled=!mayRun();}emit();}
    });
    host.querySelector('[data-tc-question]')?.addEventListener('keydown',e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();run();}});
    host.querySelectorAll('[data-tc-prompt]').forEach(b=>b.addEventListener('click',()=>{if(questionNow()!==b.dataset.tcPrompt)clearBaseline();contextChanged();draft=b.dataset.tcPrompt;publish();host.querySelector('[data-tc-question]')?.focus();}));
    host.querySelector('[data-tc-run]')?.addEventListener('click',()=>run());
    host.querySelector('[data-tc-stop]')?.addEventListener('click',()=>{leavePending('已停止本地等待；服务器可能仍在处理，已发生的模型请求仍可能计费。');publish();});
    host.querySelector('[data-tc-offline]')?.addEventListener('click',()=>{useModel=false;return run({offline:true});});
    host.querySelector('[data-tc-refresh]')?.addEventListener('click',()=>read().catch(()=>{}));
    host.querySelector('[data-tc-retain]')?.addEventListener('click',()=>{if(scope!=='snapshot'||!result||running||!bound(result.source,snapshotContext?.source)||result.task.question!==questionNow())return;const frozen=freezeAnswer(result);if(JSON.stringify(frozen).length>captureLimit){notice='本次回答超出本页历史保存上限，请缩小材料范围后再保留。';publish();return;}baseline=frozen;selectedChange=null;publish();});
    host.querySelector('[data-tc-forget]')?.addEventListener('click',()=>{clearBaseline();publish();});
    host.querySelector('[data-tc-supplement]')?.addEventListener('click',()=>{if(!baseline||baseline.source.snapshot_id!==snapshotId||workspaceChanging)return;window.dispatchEvent(new CustomEvent('lianzheng-open-project-document',{detail:{snapshot_id:snapshotId,context_sha256:snapshotContext?.source?.context_sha256||null}}));});
    host.querySelector('[data-tc-reask]')?.addEventListener('click',()=>{if(baseline&&snapshotReady()&&snapshotContext.source.context_sha256!==baseline.source.context_sha256&&baseline.question===questionNow())return run();});
    host.querySelector('[data-tc-download-change]')?.addEventListener('click',()=>{
      if(!baseline)return;
      const current=sameQuestionResult()?freezeAnswer(result):null,changes=current?changesFor(result):null;
      if(current)current.status='current-at-export';
      download({format:'lianzheng-answer-change-v2',exported_at:new Date().toISOString(),note:'本页历史副本；并列展示结论摘要，按章节及稳定引用集合配对条目，并比较同项目同题实际取回依据；文字与引用变化不构成因果或正确性结论。removed 表示本次未取回，不表示原资料删除；不证明答案更正确或修复完成。来源链接已移除，引用片段保留。',historical:clone(baseline),current,answer_changes:current?answerChanges(baseline,result):[],changes:changes?Object.fromEntries(Object.entries(changes).map(([key,items])=>[key,items.map(e=>({stable_key:e.stable_key,content_sha256:e.content_sha256,title:e.title}))])):null},'answer-change-'+baseline.source.snapshot_id+'.json');
    });
    host.querySelector('[data-tc-technical]')?.addEventListener('toggle',e=>{technicalOpen=Boolean(e.target.open);});
    host.querySelectorAll('[data-tc-change-item]').forEach(b=>b.addEventListener('click',()=>{if(answerChanges(baseline,result).some(e=>e.id===b.dataset.tcChangeItem)){selectedChange=b.dataset.tcChangeItem;publish();}}));
    host.querySelectorAll('[data-tc-trace-step]').forEach(b=>b.addEventListener('click',()=>{
      const c=result?.columns?.[Number(b.dataset.tcColumn)],position=Number(b.dataset.tcTraceStep);
      if(!validTrace(c,result)||!Number.isInteger(position)||position<0||position>3)return;
      tracePositions.set(c.id,position);publish();
    }));
    host.querySelectorAll('[data-tc-trace-evidence]').forEach(b=>b.addEventListener('click',()=>{
      const index=Number(b.dataset.tcColumn),id=b.dataset.tcTraceEvidence;
      if(!result?.columns?.[index]?.evidence.some(e=>e.id===id&&bound(e,result.source)))return;
      technicalOpen=true;chooseLink(index,{fact_id:null,evidence_id:id,path_id:null});
      host.querySelectorAll('[data-tc-evidence]')[index]?.scrollIntoView?.({behavior:'smooth',block:'center'});
    }));
    host.querySelectorAll('[data-tc-card-evidence]').forEach(b=>b.addEventListener('click',()=>{
      const index=Number(b.dataset.tcColumn),id=b.dataset.tcCardEvidence;
      if(!result?.columns?.[index]?.evidence.some(e=>e.id===id&&bound(e,result.source)))return;
      technicalOpen=true;chooseLink(index,{fact_id:null,evidence_id:id,path_id:null});
      const target=host.querySelectorAll('[data-tc-evidence]')[index];target?.scrollIntoView?.({behavior:'smooth',block:'center'});target?.focus?.({preventScroll:true});
    }));
    host.querySelector('[data-tc-download]')?.addEventListener('click',()=>{if(!result)return;const blob=new Blob([JSON.stringify(result,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='task-comparison-'+result.task.id+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
    host.querySelectorAll('[data-tc-fact]').forEach(b=>b.addEventListener('click',()=>chooseLink(Number(b.dataset.tcColumn),{fact_id:b.dataset.tcFact,evidence_id:null,path_id:null})));
    host.querySelectorAll('[data-tc-path]').forEach(b=>b.addEventListener('click',()=>chooseLink(Number(b.dataset.tcColumn),{path_id:b.dataset.tcPath})));
    host.querySelectorAll('[data-tc-evidence]').forEach(b=>b.addEventListener('change',()=>chooseLink(Number(b.dataset.tcColumn),{evidence_id:b.value})));
    host.querySelectorAll('[data-tc-select-evidence]').forEach(b=>b.addEventListener('click',()=>chooseLink(Number(b.dataset.tcColumn),{fact_id:null,evidence_id:b.dataset.tcSelectEvidence,path_id:null})));
  }
  async function request(path,body,controller){
    const response=await fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},signal:controller.signal,...(body?{body:JSON.stringify(body)}:{})});
    let data;try{data=await response.json();}catch{throw Error('服务响应无效，问题仍保留，可重新读取状态。');}
    if(!response.ok){const failure=Error(typeof data.detail==='string'?data.detail:'请求未完成，请检查当前输入和服务状态。');failure.status=response.status;throw failure;}
    return data;
  }
  async function read(){
    if(readPromise)return readPromise;
    const readingScope=scope,readingSnapshot=snapshotId,ticket=++readSerial;
    if(readingScope==='snapshot'&&(!readingSnapshot||workspaceChanging)){snapshotContext=null;error='项目快照尚未载入，请先完成项目选择。';publish();return null;}
    if(readingScope==='snapshot'){contextChanged();snapshotContext=null;}
    loading=true;error='';publish();
    const controller=new AbortController();readController=controller;let timedOut=false;
    const timer=setTimeout(()=>{timedOut=true;controller.abort();},timeouts.catalog);readTimer=timer;
    const isCurrent=()=>ticket===readSerial&&scope===readingScope&&(readingScope!=='snapshot'||snapshotId===readingSnapshot);
    readPromise=(async()=>{try{
      const path=readingScope==='snapshot'?'/api/snapshots/'+encodeURIComponent(readingSnapshot)+'/task-comparison/context':'/api/task-comparison/tasks';
      const c=await request(path,null,controller);
      if(!isCurrent())return null;
      if(readingScope==='snapshot'){
        if(!c.available||c.source?.scope!=='snapshot'||c.source.snapshot_id!==readingSnapshot||!/^[a-f0-9]{64}$/.test(c.source.context_sha256||''))throw Error('项目材料与当前快照不一致，已拒绝载入。');
        snapshotContext=c;
      }else{
        if(!c.available||!Array.isArray(c.tasks))throw Error('案例目录尚未就绪，请检查冻结材料。');
        catalog=c;
        if(!c.tasks.some(t=>t.id===chosen)){chosen=c.tasks.find(t=>t.phase===selectedPhase)?.id||c.tasks[0]?.id||'';if(mode==='fixed')clearResult();}
        if(result&&result.source.case_bundle_sha256!==c.source.case_bundle_sha256){clearResult();notice='案例依据已变化，请重新运行当前问题。';}
      }
      if(modelConfigured()!==true)useModel=false;
      return c;
    }catch(e){if(!isCurrent())return null;error=timedOut?'读取材料超时，现场问题仍保留。请检查本机服务后重试。':e.name==='TypeError'?'无法连接本机服务，问题仍保留。请恢复服务后刷新状态。':e.message;throw e;}
    finally{clearTimeout(timer);if(isCurrent()){loading=false;readPromise=null;readController=null;readTimer=null;publish();}}})();
    return readPromise;
  }
  function validateProjectResult(data,source){
    const scoped=value=>bound(value,source)&&(!value.url||Boolean(sourceURL(value.url,source)));
    if(!scoped(data.source)||data.task?.kind!=='project-question'||data.task?.phase!=='snapshot')return false;
    if(!Array.isArray(data.columns)||data.columns.length!==2)return false;
    return data.columns.every(c=>{
      const pack=c.evidence_links;
      if(!Array.isArray(c.evidence)||!pack||!scoped(pack.source)||!Array.isArray(pack.paths)||!Array.isArray(pack.facts))return false;
      if(c.answer_card!==undefined&&!validCard(c.answer_card,c,source))return false;
      const ids=new Set(c.evidence.map(d=>d.id));
      const pathIds=new Set(pack.paths.map(p=>p.id));
      if(ids.size!==c.evidence.length||pathIds.size!==pack.paths.length||!c.evidence.every(d=>scoped(d)&&d.phase==='snapshot'&&(!d.relations||d.relations.every(r=>scoped(r)))))return false;
      return pack.facts.every(f=>scoped(f)&&Array.isArray(f.evidence_ids)&&f.evidence_ids.length>0&&f.evidence_ids.every(id=>ids.has(id))&&Array.isArray(f.path_ids)&&f.path_ids.every(id=>pathIds.has(id)))&&
        pack.paths.every(p=>scoped(p)&&Array.isArray(p.nodes)&&p.nodes.every(n=>scoped(n))&&Array.isArray(p.edges)&&p.edges.every(e=>scoped(e)&&Array.isArray(e.evidence_ids)&&e.evidence_ids.every(id=>ids.has(id))));
    });
  }
  async function run({offline=false}={}){
    if(running||loading)return;
    if(scope==='snapshot'&&!snapshotReady()){error='当前项目材料尚未核对，先刷新材料后再提问。';publish();return;}
    const question=questionNow();
    if(!question||question.length>1000){error='请输入 1–1000 字的问题。';publish();return;}
    const requestMode=mode,phase=phaseNow(),taskId=chosen,model=offline?false:useModel;
    const requestScope=scope,requestSnapshot=snapshotId,requestSource=snapshotContext?.source;
    const ticket=++serial,controller=new AbortController();
    const body=requestScope==='snapshot'?{question,expected_context_sha256:requestSource.context_sha256,use_model:model}:requestMode==='free'?{question,phase,use_model:model}:{task_id:taskId,use_model:model};
    const active={controller,timer:null,timedOut:false};
    active.timer=setTimeout(()=>{if(ticket!==serial)return;active.timedOut=true;controller.abort();},model?timeouts.model:timeouts.offline);
    pending=active;running=true;clearResult();lastAttempt={mode:requestMode,phase,question,use_model:model};publish();
    try{
      const path=requestScope==='snapshot'?'/api/snapshots/'+encodeURIComponent(requestSnapshot)+'/task-comparison/ask':requestMode==='free'?'/api/task-comparison/ask':'/api/task-comparison/run';
      const data=await request(path,body,controller);
      if(ticket!==serial||scope!==requestScope||snapshotId!==requestSnapshot||mode!==requestMode||phaseNow()!==phase||questionNow()!==question)return;
      if(data.task?.phase!==phase||data.task?.question!==question||(requestMode==='fixed'&&data.task?.id!==taskId)||(requestMode==='free'&&data.comparison?.result!=='unscored'))throw Error('返回结果与本次问题或材料阶段不一致，已拒绝展示。');
      if(requestScope==='snapshot'){
        if(!bound(snapshotContext?.source,requestSource)||!validateProjectResult(data,requestSource))throw Error('返回证据与当前项目快照或材料指纹不一致，已拒绝展示，请刷新材料后重试。');
      }else if(data.source?.scope==='snapshot'||(expectedCaseHash&&data.source?.case_bundle_sha256!==expectedCaseHash)||(catalog?.source?.case_bundle_sha256&&data.source?.case_bundle_sha256!==catalog.source.case_bundle_sha256))throw Error('返回材料与当前目录不一致，请刷新案例状态后重试。');
      result=data;acceptedAt=new Date().toISOString();
      if(model&&data.columns.some(c=>c.generation!=='model-assisted')){error='本次模型解释未全部完成；下方保留实际取回证据。可以显式改用离线证据重试。';}
    }catch(e){if(ticket===serial&&requestScope==='snapshot'&&e.status===409){snapshotContext=null;lastAttempt=null;useModel=false;}if(ticket===serial)error=active.timedOut?'本地等待已超时，问题仍保留。服务器可能继续处理，已发生的模型请求仍可能计费。':e.name==='AbortError'?'本地等待已中断，服务器可能继续处理。':e.name==='TypeError'?'无法连接本机服务，问题仍保留。请恢复服务后重试。':e.message;}
    finally{clearTimeout(active.timer);if(ticket===serial){pending=null;running=false;publish();}}
  }
  function configure(options={}){
    const nextScope=options.scope??scope;
    if(!['case','snapshot'].includes(nextScope))throw Error('提问材料来源无效。');
    const currentId=workspaceSnapshotId||document.getElementById?.('snapshot-select')?.value||snapshotId;
    const nextId=nextScope==='snapshot'?(options.snapshot_id??currentId):null;
    const nextMode=nextScope==='snapshot'?'free':options.mode??(scope==='snapshot'?'fixed':mode);
    const nextPhase=nextScope==='snapshot'?'snapshot':options.phase??(phaseNow()==='snapshot'?'before':phaseNow());
    if(!['fixed','free'].includes(nextMode)||!Object.hasOwn(phases,nextPhase)||(nextScope==='case'&&nextPhase==='snapshot'))throw Error('提问方式或材料阶段无效。');
    const changed=nextScope!==scope||nextId!==snapshotId;
    if(options.question!==undefined&&(typeof options.question!=='string'||options.question.length>1000))throw Error('问题必须是 1–1000 字的文本。');
    if(options.reset||changed||nextMode!==mode||nextPhase!==phaseNow()||(typeof options.question==='string'&&options.question.trim()!==questionNow()))clearBaseline();
    contextChanged();
    if(changed){cancelRead();snapshotContext=null;}
    if(options.reset||changed){draft='';useModel=false;chosen='';expectedCaseHash=null;}
    if(typeof options.question==='string')draft=options.question;
    if('expected_case_hash' in options)expectedCaseHash=typeof options.expected_case_hash==='string'?options.expected_case_hash:null;
    scope=nextScope;snapshotId=nextId;mode=nextMode;selectedPhase=nextPhase;
    if(typeof options.task_id==='string')chosen=options.task_id;
    else if(mode==='fixed'&&(!task()||task().phase!==nextPhase))chosen=catalog?.tasks.find(t=>t.phase===nextPhase)?.id||chosen;
    publish();
    if(scope==='snapshot'&&!snapshotContext&&!workspaceChanging&&!readPromise)read().catch(()=>{});
    if(scope==='case'&&!catalog&&!readPromise)read().catch(()=>{});
    return viewState();
  }
  function reset(){return configure({scope:'case',mode:'fixed',phase:'before',task_id:'before-occurrences',reset:true});}
  function mount(host,{compact=false,lockScope=false}={}){const instance={host,compact,lockScope};instances.add(instance);render(instance);if(!activeCatalog()&&!readPromise)read().catch(()=>{});return {destroy(){instances.delete(instance);host.replaceChildren();}};}
  // The presenter receives a separate immutable capture and local selection state.
  // This renderer never calls read/run/configure and never subscribes to shared mutations.
  function mountReadonly(host,options={}){
    let captured=null,oldRecord=null,destroyed=false,choice=null,selectedDoc=null;
    const positions=new Map(),view=['answer','changes','trace'].includes(options.view)?options.view:'answer';
    const current=()=>{try{return !options.historical&&typeof options.isCurrent==='function'&&options.isCurrent()===true;}catch{return false;}};
    try{
      const raw=JSON.stringify({result:options.result||null,baseline:options.baseline||null,context:options.context||null});
      if(raw.length>captureLimit*4)throw Error('capture too large');
      const input=JSON.parse(raw),expected=input.context?.source||input.context||input.result?.source;
      if(input.result&&bound(input.result.source,expected)&&validateProjectResult(input.result,expected))captured=input.result;
      if(input.baseline&&input.baseline.source?.scope==='snapshot'&&input.baseline.source.snapshot_id===expected?.snapshot_id&&typeof input.baseline.question==='string'&&Array.isArray(input.baseline.evidence)&&input.baseline.evidence.length<=16&&JSON.stringify(input.baseline).length<=captureLimit&&validCard(input.baseline.answer_card,{evidence:input.baseline.evidence},input.baseline.source)&&(!captured||input.baseline.question===captured.task.question))oldRecord=input.baseline;
    }catch{/* An invalid capture never falls back to mutable global results. */}
    const paint=()=>{
      if(destroyed)return;
      const live=current(),c=graphColumn(captured),card=c?cardFor(c,captured):null;
      const cardHTML=()=>`<section class="tc-answer-card" aria-label="已锁定项目答案卡"><h3>已锁定项目答案卡</h3><p class="tc-meta">${esc(generationLabel(card.generation||c.generation))} · ${live?'当前材料已核对':'历史讲解副本，非当前项目状态'}</p>${Object.entries(answerSections).map(([key,label])=>`<section class="tc-readonly-card-section"><h4>${label}</h4>${(key==='conclusion'?[card.conclusion]:card[key]).map(item=>`<div class="tc-card-item"><p>${esc(item.text)}</p><div class="tc-card-citations">${item.evidence_ids.map(id=>`<button type="button" data-tc-readonly-evidence="${esc(id)}" data-tc-column="${captured.columns.indexOf(c)}">查看引用原文</button>`).join('')||'<small>此项未绑定检索证据。</small>'}</div></div>`).join('')||'<p class="tc-meta">没有列出该项。</p>'}</section>`).join('')}<p class="tc-meta">引用绑定不等于语义支持已核验。</p></section>`;
      let body=view==='changes'?(oldRecord&&captured?changesPanel(oldRecord,captured,choice,{allowLinks:live}):oldRecord?`<p class="tc-meta">保留回答为历史副本；尚无同题新回答，不计算条目变化。</p>${oldRecord.evidence.map(d=>originalSource(d,oldRecord.source,{historical:true,allowLinks:false})).join('')}`:'<p class="tc-meta">尚未保留同题回答；请返回当前项目问答，保留回答并显式重新回答后再讲解变化。</p>'):captured?(view==='answer'?cardHTML():'')+tracePanel(captured,positions):'<p class="tc-meta">尚无可核验的已完成项目回答。请返回工作台明确运行问题。</p>';
      const chosenColumn=captured?.columns?.[selectedDoc?.column],doc=chosenColumn?.evidence.find(d=>d.id===selectedDoc.id&&bound(d,captured.source));
      if(doc)body+=`<section class="tc-readonly-source" aria-label="讲解引用原文" tabindex="-1">${originalSource(doc,captured.source,{historical:!live,allowLinks:live})}</section>`;
      host.innerHTML=`<div class="tc-readonly" data-tc-readonly-status="${live?'current':'historical'}">${body}</div>`;
      host.querySelectorAll('[data-tc-change-item]').forEach(b=>b.addEventListener('click',()=>{if(destroyed)return;choice=b.dataset.tcChangeItem;paint();}));
      host.querySelectorAll('[data-tc-trace-step]').forEach(b=>b.addEventListener('click',()=>{if(destroyed)return;const column=captured?.columns?.[Number(b.dataset.tcColumn)],position=Number(b.dataset.tcTraceStep);if(validTrace(column,captured)&&Number.isInteger(position)&&position>=0&&position<=3){positions.set(column.id,position);paint();}}));
      for(const attr of ['data-tc-readonly-evidence','data-tc-trace-evidence'])host.querySelectorAll('['+attr+']').forEach(b=>b.addEventListener('click',()=>{if(destroyed)return;const column=Number(b.dataset.tcColumn),id=b.getAttribute(attr);if(captured?.columns?.[column]?.evidence.some(d=>d.id===id&&bound(d,captured.source))){selectedDoc={column,id};paint();const target=host.querySelector('.tc-readonly-source');target?.scrollIntoView?.({behavior:'smooth',block:'center'});target?.focus?.({preventScroll:true});}}));
      host.querySelectorAll('[data-tc-current-source]').forEach(a=>a.addEventListener('click',event=>{if(destroyed||!current()){event.preventDefault();paint();}}));
    };
    paint();return {destroy(){destroyed=true;host.replaceChildren();}};
  }
  window.addEventListener?.('lianzheng-snapshot-changing',event=>{
    workspaceSnapshotId=event.detail?.snapshot_id||null;workspaceChanging=true;
    if(scope!=='snapshot')return;
    clearBaseline();cancelRead();contextChanged();snapshotId=workspaceSnapshotId;snapshotContext=null;draft='';useModel=false;
    notice='项目正在切换，旧问题、回答和引用已清除。';publish();
  });
  window.addEventListener?.('lianzheng-snapshot-changed',event=>{
    workspaceSnapshotId=event.detail?.snapshot||event.detail?.snapshot_id||null;workspaceChanging=false;
    if(scope!=='snapshot')return;
    if(snapshotId!==workspaceSnapshotId)configure({scope:'snapshot',snapshot_id:workspaceSnapshotId,mode:'free',reset:true});
    else {cancelRead();read().catch(()=>{});}
  });
  window.addEventListener?.('lianzheng-snapshot-change-failed',()=>{
    if(scope!=='snapshot')return;
    cancelRead();contextChanged();snapshotContext=null;workspaceChanging=true;
    error='项目快照未载入成功，请重新选择项目后再提问；旧结果未恢复。';publish();
  });
  window.addEventListener?.('lianzheng-project-evidence-changed',event=>{
    if(scope!=='snapshot'||snapshotId!==event.detail?.snapshot_id)return;
    cancelRead();contextChanged();snapshotContext=null;useModel=false;read().catch(()=>{});
  });
  window.addEventListener?.('lianzheng-model-updated',event=>{
    modelStatus=event.detail;
    if(useModel&&modelConfigured()!==true){contextChanged();useModel=false;}
    publish();
  });
  mount(panel);
  async function open(options){if(options&&typeof options==='object'&&['scope','snapshot_id','mode','phase','question'].some(k=>k in options))configure(options);const openingScope=scope,openingSnapshot=snapshotId;panel.hidden=false;if(!activeCatalog())await read().catch(()=>{});if(scope!==openingScope||snapshotId!==openingSnapshot||(openingScope==='snapshot'&&workspaceChanging))return viewState();panel.scrollIntoView({behavior:'smooth',block:'start'});return viewState();}
  launch.addEventListener('click',()=>open());
  window.lianzhengTaskCompare={open,mount,mountReadonly,state:viewState,refresh:read,configure,reset};
})();
