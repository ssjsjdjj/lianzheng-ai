/* Current-project stage: a read-only, in-memory capture. Opening never asks a model. */
(()=>{
  'use strict';
  const esc=escapeHTML,clone=value=>JSON.parse(JSON.stringify(value));
  const labels=['项目简报','本场问题','答案与证据','回答变化'];
  const dialog=document.createElement('dialog');dialog.id='project-presenter-dialog';dialog.className='project-presenter-dialog';
  dialog.setAttribute('aria-labelledby','project-presenter-title');
  dialog.innerHTML=`<header class="pp-top"><div><strong>链证 AI <span>当前项目讲解</span></strong><small>从导入清单到可核查的回答</small></div><div class="pp-actions"><button type="button" data-pp-action="prepare">重新准备</button><button type="button" data-pp-action="fullscreen">浏览器全屏</button><button type="button" data-pp-action="close">退出讲解 ×</button></div></header>
    <nav class="pp-steps" aria-label="当前项目讲解步骤"></nav><section class="pp-body" aria-labelledby="project-presenter-title"><div class="pp-binding"></div><div class="pp-warning" role="status" hidden></div><h2 id="project-presenter-title" tabindex="-1"></h2><p class="pp-intro"></p><div class="pp-content"></div></section>
    <footer class="pp-footer"><div><strong class="pp-progress"></strong><p class="pp-status" role="status"></p></div><div class="pp-actions"><button type="button" data-pp-action="workbench">返回当前项目问答 ↗</button><button type="button" data-pp-action="previous">← 上一步</button><button type="button" data-pp-action="next">下一步 →</button></div></footer>`;
  document.body.append(dialog);
  const find=selector=>dialog.querySelector(selector);
  let capture=null,step=0,stale=false,paused=false,reason='',mount=null,priorFocus=null,priorOverflow='',notice='',workspaceChanging=false,opening=0;
  const binding=value=>value?.scope==='snapshot'&&typeof value.snapshot_id==='string'&&Boolean(value.snapshot_id)&&/^[a-f0-9]{64}$/.test(value.context_sha256||'');
  const same=(a,b)=>binding(a)&&binding(b)&&a.snapshot_id===b.snapshot_id&&a.context_sha256===b.context_sha256;
  const stateNow=()=>window.lianzhengTaskCompare?.state?.()||{};
  function workspace(){
    if(typeof state==='object')return {id:state.id,switching:state.switchingSnapshot};
    const brief=window.lianzhengProjectBrief?.state?.(),task=stateNow();
    return {id:document.getElementById('snapshot-select')?.value||brief?.snapshot_id||task.snapshot_id,switching:brief?.switching||task.workspace_changing};
  }
  function validBrief(b,source){
    return same(b,source)&&typeof b.project==='string'&&typeof b.label==='string'&&['npm-package-lock','cyclonedx'].includes(b.format)&&
      ['component_count','checked_components','unknown_components','knowledge_documents','issue_count'].every(key=>Number.isSafeInteger(b[key])&&b[key]>=0)&&
      b.checked_components+b.unknown_components<=b.component_count&&typeof b.graph_complete==='boolean'&&Array.isArray(b.notes)&&b.notes.every(n=>typeof n==='string');
  }
  function prepareCapture(){
    const w=workspace(),task=stateNow(),briefState=window.lianzhengProjectBrief?.state?.()||{};
    if(!w.id||w.switching||workspaceChanging)throw Error('请先完成项目选择或导入，再准备当前项目讲解。');
    const inScope=task.scope==='snapshot'&&task.snapshot_id===w.id;
    if(inScope&&(task.running||task.loading||task.workspace_changing))throw Error('当前项目资料或回答仍在载入，请等待完成后重新准备。');
    const loaded=inScope?task.context:null;
    const brief=loaded?.brief||(briefState.snapshot_id===w.id&&!briefState.loading&&!briefState.switching?briefState.brief:null);
    const source=loaded?.source||(brief?{scope:brief.scope,snapshot_id:brief.snapshot_id,context_sha256:brief.context_sha256,project:brief.project,label:brief.label}:null);
    if(!binding(source)||source.snapshot_id!==w.id||!validBrief(brief,source)||loaded&&loaded.available!==true)throw Error('当前项目简报尚未就绪，请返回项目简报载入资料后重新准备。');
    if(briefState.brief&&briefState.snapshot_id===w.id&&!same(briefState.brief,source))throw Error('简报与问答的资料版本不同，请待刷新完成后重新准备。');
    const question=inScope?String(task.question||'').trim():'',result=inScope?task.result:null,baseline=inScope?task.baseline:null;
    if(result&&(!same(result.source,source)||result.task?.phase!=='snapshot'||!question||result.task?.question!==question||!Array.isArray(result.columns)||!result.columns.length))throw Error('回答与当前项目或问题不一致，请返回问答重新核对。');
    if(baseline&&(!binding(baseline.source)||baseline.source.snapshot_id!==w.id||baseline.question!==question))throw Error('保留回答与当前项目或问题不一致，请返回问答重新核对。');
    return clone({source,context:loaded||{available:true,source,brief},brief,question,result,baseline,captured_at:new Date().toISOString(),task_bound:inScope});
  }
  function current(){
    if(!capture||stale||workspaceChanging)return false;
    const w=workspace(),task=stateNow();if(w.switching||w.id!==capture.source.snapshot_id)return false;
    if(!capture.task_bound)return task.scope!=='snapshot'||task.snapshot_id!==w.id;
    const brief=window.lianzhengProjectBrief?.state?.(),liveSource=task.context?.source||(!brief?.loading&&!brief?.switching?brief?.brief:null);
    return task.scope==='snapshot'&&task.snapshot_id===w.id&&!task.workspace_changing&&!task.loading&&!task.running&&same(liveSource,capture.source)&&
      String(task.question||'').trim()===capture.question&&JSON.stringify(task.result||null)===JSON.stringify(capture.result)&&JSON.stringify(task.baseline||null)===JSON.stringify(capture.baseline);
  }
  const publicState=()=>({open:Boolean(dialog.open),step,paused,stale,reason,snapshot_id:capture?.source.snapshot_id||null,context_sha256:capture?.source.context_sha256||null,captured_at:capture?.captured_at||null,has_answer:Boolean(capture?.result),has_baseline:Boolean(capture?.baseline)});
  const emit=()=>window.dispatchEvent(new CustomEvent('lianzheng-project-presentation-changed',{detail:publicState()}));
  function release(){mount?.destroy?.();mount=null;}
  const empty=(title,text)=>`<div class="pp-empty"><h3>${esc(title)}</h3><p>${esc(text)}</p><button type="button" data-pp-action="workbench">返回当前项目问答 ↗</button></div>`;
  function briefView(){
    const b=capture.brief,counts=[['组件位置',b.component_count],['已完成精确查询',b.checked_components],['仍待确认',b.unknown_components],['项目文档',b.knowledge_documents]];
    return `<div class="pp-project"><span>${b.format==='npm-package-lock'?'npm 锁文件':'CycloneDX 清单'}</span><h3>${esc(b.project)}</h3><p>${esc(b.label)}</p></div><div class="pp-metrics">${counts.map(([label,value])=>`<article><strong>${value}</strong><span>${label}</span></article>`).join('')}</div>
      <div class="pp-boundary"><strong>${b.graph_complete?'已声明依赖关系完整':'依赖关系存在缺口'}</strong><p>${b.unknown_components?`${b.unknown_components} 个组件位置仍待查询确认。`:''}${b.issue_count?`${b.issue_count} 项清单质量提示。`:''}查询完成不表示项目全部安全。</p></div>${b.notes.length?`<ul class="pp-notes">${b.notes.map(n=>`<li>${esc(n)}</li>`).join('')}</ul>`:''}`;
  }
  function questionView(){
    if(!capture.question)return empty('还没有本场问题','先在现有问答区选择或输入问题；明确提交后，再重新准备本场讲解。');
    return `<article class="pp-question"><span>${capture.result?'已取得回答的实际问题':'尚未提交或尚无有效回答的问题草稿'}</span><blockquote>${esc(capture.question)}</blockquote><p>${capture.result?'接下来展开这一次回答的答案卡、引用原文与实际检索记录。':'此草稿没有可展示的回答。返回现有问答区运行后，重新准备即可。'}</p></article><div class="pp-boundary"><strong>现场自由题 · 不计算胜负或正确率</strong><p>讲解只展示已载入资料，不自动运行问答或模型。评委的新问题统一回到问答区输入。</p></div>`;
  }
  function render({focus=false}={}){
    release();if(!capture)return;
    find('.pp-steps').innerHTML=labels.map((label,index)=>`<button type="button" data-pp-step="${index}" ${paused?'disabled':''} ${index===step?'aria-current="step"':''}><span>0${index+1}</span>${label}</button>`).join('');
    find('.pp-binding').textContent=`${stale?'已捕获的历史资料':'本场锁定资料'} · ${capture.brief.project} · 快照 ${capture.source.snapshot_id} · ${capture.source.context_sha256.slice(0,12)}`;
    find('.pp-binding').title=capture.source.context_sha256;
    const warning=find('.pp-warning');warning.hidden=!stale;
    warning.innerHTML=stale?`<strong>${paused?'讲解已暂停':'正在查看历史捕获资料'}</strong><p>${esc(reason)} 当前原文下载与实时跳转已停用。重新准备会捕获现有工作区的资料。</p>${paused?'<button type="button" data-pp-action="historical">仅继续查看历史捕获资料</button>':''}`:'';
    find('#project-presenter-title').textContent=labels[step];
    find('.pp-intro').textContent=['先说清项目规模和资料缺口，再回答具体问题。','保留真实提问上下文，让判断过程可以复查。','从结论展开证据，再查看本次实际检索的记录。','对比补充资料前后，哪些判断改变，哪些仍需确认。'][step];
    const host=find('.pp-content');
    if(step===0)host.innerHTML=briefView();
    else if(step===1)host.innerHTML=questionView();
    else if(!capture.result&&!(step===3&&capture.baseline))host.innerHTML=empty('当前还没有可讲解的有效回答','返回当前项目问答，手动运行问题后重新准备；保留的历史回答不会被讲解入口清空。');
    else if(window.lianzhengTaskCompare?.mountReadonly){
      host.innerHTML='';mount=window.lianzhengTaskCompare.mountReadonly(host,{result:capture.result,baseline:capture.baseline,context:capture.context,view:step===2?'answer':'changes',historical:stale,isCurrent:current});
    }else host.innerHTML=empty('答案展示组件尚未就绪','请退出讲解并刷新页面。已取得的回答仍在当前工作区。');
    find('.pp-progress').textContent=`${step+1} / ${labels.length} · ${stale?'历史捕获':'当前项目'}`;
    find('.pp-status').textContent=notice||(paused?'资料已变化。选择重新准备，或明确继续查看历史资料。':'方向键切换步骤，Esc 退出。讲解过程中新增模型调用 0 次。');
    find('[data-pp-action="previous"]').disabled=paused||step===0;
    find('[data-pp-action="next"]').disabled=paused;
    find('[data-pp-action="next"]').textContent=step===labels.length-1?'结束讲解 ✓':'下一步 →';
    if(focus){find('.pp-body').scrollTop=0;find('#project-presenter-title').focus({preventScroll:true});}emit();
  }
  function invalidate(message){
    if(!capture||stale)return;stale=true;paused=true;reason=message;notice='';
    // Destroy source actions synchronously, including when a dialog is currently closed.
    release();if(dialog.open)render();else emit();
  }
  function start(){
    if(document.getElementById('presenter-dialog')?.open)throw Error('请先退出固定案例讲解，再开始当前项目讲解。');
    const next=prepareCapture();++opening;capture=next;step=0;stale=false;paused=false;reason='';notice='';
    if(!dialog.open){priorFocus=document.activeElement;priorOverflow=document.body.style.overflow;document.body.style.overflow='hidden';dialog.showModal();}
    render({focus:true});return publicState();
  }
  function close(){if(dialog.open)dialog.close();}
  function go(index){if(capture&&!stale&&!current())invalidate('工作区已变化，请重新准备或明确查看历史捕获资料。');if(!capture||paused||!Number.isInteger(index)||index<0||index>=labels.length)return;step=index;notice='';render({focus:true});}
  async function workbench(){
    const w=workspace(),task=stateNow();
    if(!w.id||w.switching||workspaceChanging)throw Error('项目正在切换，请待当前项目载入后返回问答。');
    if(!window.lianzhengTaskCompare?.open)throw Error('问答组件尚未加载，请刷新页面后重试。');
    close();
    // open() with no options preserves the accepted result and baseline in this scope.
    return task.scope==='snapshot'&&task.snapshot_id===w.id?window.lianzhengTaskCompare.open():window.lianzhengTaskCompare.open({scope:'snapshot',snapshot_id:w.id,mode:'free'});
  }
  async function fullscreen(){
    const ticket=opening;
    try{if(document.fullscreenElement===dialog)await document.exitFullscreen();else if(dialog.requestFullscreen)await dialog.requestFullscreen();else throw Error('unavailable');if((ticket!==opening||!dialog.open)&&document.fullscreenElement===dialog)await document.exitFullscreen();}
    catch{if(ticket===opening&&dialog.open){notice='当前使用铺满页面的讲解模式；浏览器未开启系统全屏。';find('.pp-status').textContent=notice;}}
    if(ticket===opening)find('[data-pp-action="fullscreen"]').textContent=document.fullscreenElement===dialog?'退出浏览器全屏':'浏览器全屏';
  }
  dialog.addEventListener('click',async event=>{
    const button=event.target.closest('button');if(!button||!dialog.contains(button)||button.disabled)return;
    try{
      if(button.dataset.ppStep!==undefined){go(Number(button.dataset.ppStep));return;}
      switch(button.dataset.ppAction){
        case 'prepare':start();break;
        case 'close':close();break;
        case 'fullscreen':await fullscreen();break;
        case 'workbench':await workbench();break;
        case 'historical':if(stale){paused=false;notice='';render({focus:true});}break;
        case 'previous':go(step-1);break;
        case 'next':if(!paused){if(step===labels.length-1)close();else go(step+1);}break;
      }
    }catch(error){notice=error.message||'操作暂未完成，请返回工作区核对资料。';if(dialog.open)find('.pp-status').textContent=notice;else if(typeof toast==='function')toast(notice);}
  });
  dialog.addEventListener('keydown',event=>{
    if(event.altKey||event.ctrlKey||event.metaKey||event.target.closest('input,textarea,select,[contenteditable="true"]'))return;
    if(event.key==='ArrowRight'){event.preventDefault();go(step+1);}else if(event.key==='ArrowLeft'){event.preventDefault();go(step-1);}else if(event.key==='Escape'){event.preventDefault();close();}
  });
  dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
  dialog.addEventListener('close',()=>{++opening;release();document.body.style.overflow=priorOverflow;if(document.fullscreenElement===dialog)document.exitFullscreen().catch(()=>{});if(priorFocus?.isConnected)priorFocus.focus({preventScroll:true});else document.getElementById('open-demo')?.focus({preventScroll:true});emit();});
  document.addEventListener('fullscreenchange',()=>{find('[data-pp-action="fullscreen"]').textContent=document.fullscreenElement===dialog?'退出浏览器全屏':'浏览器全屏';});
  window.addEventListener('lianzheng-snapshot-changing',()=>{workspaceChanging=true;invalidate('正在切换项目，原讲解内容已停止代表当前项目。');});
  window.addEventListener('lianzheng-snapshot-changed',()=>{workspaceChanging=false;if(capture&&!current())invalidate('工作区已切换，请重新准备当前项目讲解。');});
  window.addEventListener('lianzheng-snapshot-change-failed',()=>{workspaceChanging=true;invalidate('项目切换未完成，请返回工作区重新选择。');});
  window.addEventListener('lianzheng-project-evidence-changed',event=>{if(capture?.source.snapshot_id===event.detail?.snapshot_id)invalidate('当前项目资料已更新，本场仍保留更新前捕获的内容。');});
  window.addEventListener('lianzheng-task-comparison-changed',()=>{if(capture&&!current())invalidate('工作区的问题、回答或资料版本已变化，本场不会自动替换已捕获内容。');});
  window.lianzhengProjectPresenter={start,close,go,state:publicState};
})();
