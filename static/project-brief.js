/* Current-snapshot briefing. Read-only context; suggestions never submit a question. */
(()=>{
  'use strict';
  const anchor=document.querySelector('.snapshot-toolbar');
  if(!anchor)return;
  const panel=document.createElement('section');panel.id='project-brief';panel.className='project-brief';
  panel.setAttribute('aria-label','当前项目简报');panel.setAttribute('tabindex','-1');anchor.after(panel);
  const esc=escapeHTML;
  let snapshotId=null,brief=null,loading=false,switching=false,error='',serial=0,controller=null,timer=null,workspaceRequest=null;
  const publicState=()=>({snapshot_id:snapshotId,brief,loading,switching,error});
  const count=value=>Number.isSafeInteger(value)&&value>=0;
  function valid(context,id){
    const b=context?.brief,s=context?.source;
    return context?.available===true&&s?.scope==='snapshot'&&s.snapshot_id===id&&/^[a-f0-9]{64}$/.test(s.context_sha256||'')&&
      b?.scope==='snapshot'&&b.snapshot_id===id&&b.context_sha256===s.context_sha256&&
      typeof b.project==='string'&&typeof b.label==='string'&&['npm-package-lock','cyclonedx'].includes(b.format)&&
      ['component_count','checked_components','unknown_components','knowledge_documents','issue_count'].every(key=>count(b[key]))&&
      b.checked_components+b.unknown_components<=b.component_count&&typeof b.graph_complete==='boolean'&&
      Array.isArray(b.suggestions)&&b.suggestions.length<=3&&new Set(b.suggestions.map(q=>q?.id)).size===b.suggestions.length&&
      b.suggestions.every(q=>q&&typeof q.id==='string'&&q.id.length>0&&q.id.length<=100&&typeof q.question==='string'&&q.question.trim().length>0&&q.question.length<=1000&&typeof q.label==='string'&&q.label.length<=200)&&
      Array.isArray(b.notes)&&b.notes.length<=10&&b.notes.every(n=>typeof n==='string'&&n.length<=1500);
  }
  function cancel(){++serial;if(controller)controller.abort();if(timer)clearTimeout(timer);controller=null;timer=null;loading=false;}
  function clear(){cancel();brief=null;error='';}
  function ready(id,hash){return !loading&&!switching&&brief&&snapshotId===id&&brief.snapshot_id===id&&brief.context_sha256===hash;}
  function render(){
    panel.setAttribute('aria-busy',String(loading||switching));
    const header='<div class="pb-heading"><div><span class="pb-eyebrow">YOUR PROJECT · CURRENT EVIDENCE</span><h2>当前项目简报</h2></div>'+
      `<button type="button" class="text-button" data-pb-refresh ${!snapshotId||loading||switching?'disabled':''}>${loading?'正在读取…':'刷新简报'}</button></div>`;
    if(!brief){
      panel.innerHTML=header+`<div class="pb-message" role="${error?'alert':'status'}">${esc(error||(switching?'正在切换项目，旧项目简报已收起。':loading?'正在核对当前项目清单、查询记录与文档…':snapshotId?'当前项目简报尚未载入。':'选择或导入一份项目清单，查看规模、资料缺口和可提问方向。'))}</div>`;
    }else{
      const b=brief,format=b.format==='npm-package-lock'?'npm 锁文件':'CycloneDX 清单';
      const metrics=[['组件出现位置',b.component_count,'同版本的不同安装位置分别计数'],['完成精确查询',b.checked_components,'查询完成不表示项目全部安全'],['仍待查询确认',b.unknown_components,'未扫描或失败保留为未知'],['项目文档',b.knowledge_documents,'只使用适用当前版本的内容']];
      const coverage=b.graph_complete?'已声明依赖关系完整':'依赖关系存在缺口';
      panel.innerHTML=header+`<div class="pb-identity"><strong>${esc(b.project)}</strong><span>${esc(b.label)} · ${format}</span></div>
        <div class="pb-metrics">${metrics.map(([label,value,note])=>`<div><span>${label}</span><strong>${value}</strong><small>${note}</small></div>`).join('')}</div>
        <div class="pb-coverage ${!b.graph_complete||b.unknown_components?'pb-warning':''}"><strong>${coverage}</strong><span>${b.issue_count?`${b.issue_count} 项清单质量提示。`:''}${b.unknown_components?` ${b.unknown_components} 个位置的漏洞状态仍未确认。`:' 已查询记录只覆盖当前清单与所用公告。'}</span></div>
        ${b.notes.length?`<ul class="pb-notes">${b.notes.map(note=>`<li>${esc(note)}</li>`).join('')}</ul>`:''}
        <div class="pb-actions"><div><h3>从当前项目开始提问</h3><p>选择问题只会填入问答框，由你决定何时运行。</p></div><button type="button" class="button secondary" data-pb-document>补充项目文档</button></div>
        <div class="pb-suggestions">${b.suggestions.length?b.suggestions.map(q=>`<button type="button" data-pb-question="${esc(q.id)}"><span>${esc(q.label)}</span><strong>${esc(q.question)}</strong><i aria-hidden="true">↗</i></button>`).join(''):'<p>当前材料尚不足以生成针对组件的问题。可补充有效清单或适用文档。</p>'}</div>
        <details class="pb-source"><summary>查看本份简报的资料版本</summary><span>仅当前快照 · ${esc(snapshotId)}</span><code>${esc(b.context_sha256)}</code><p>切换项目或资料更新会重新核对；简报不请求模型或在线扫描。</p></details>`;
      const id=snapshotId,hash=b.context_sha256;
      panel.querySelectorAll('[data-pb-question]').forEach(button=>button.addEventListener('click',async()=>{
        if(!ready(id,hash))return;
        const q=brief.suggestions.find(item=>item.id===button.dataset.pbQuestion);if(!q)return;
        try{
          if(!window.lianzhengTaskCompare?.open)throw Error('问答组件尚未加载，请刷新页面后重试。');
          await window.lianzhengTaskCompare.open({scope:'snapshot',snapshot_id:id,mode:'free',question:q.question});
        }catch(e){if(ready(id,hash)){error='无法打开问答，请刷新页面后重试。';brief=null;render();}}
      }));
      panel.querySelector('[data-pb-document]')?.addEventListener('click',()=>{
        if(ready(id,hash))window.dispatchEvent(new CustomEvent('lianzheng-open-project-document',{detail:{snapshot_id:id}}));
      });
    }
    panel.querySelector('[data-pb-refresh]')?.addEventListener('click',()=>refresh());
  }
  async function refresh(){
    if(!snapshotId||switching||loading)return;
    clear();loading=true;const request=serial,id=snapshotId,current=new AbortController();controller=current;
    const timeout=setTimeout(()=>current.abort(),12000);timer=timeout;render();
    try{
      const response=await fetch('/api/snapshots/'+encodeURIComponent(id)+'/task-comparison/context',{method:'GET',signal:current.signal,headers:{'Accept':'application/json'}});
      const context=await response.json();
      if(request!==serial||snapshotId!==id||switching)return;
      if(!response.ok)throw Error('当前项目资料暂不可读，请确认服务正常后刷新简报。');
      if(!valid(context,id))throw Error('项目简报与当前资料不一致，请刷新或重新选择快照。');
      brief=context.brief;
    }catch(e){
      if(request!==serial||snapshotId!==id||switching)return;
      brief=null;error=current.signal.aborted?'读取项目简报超时，请确认服务正常后重试。':e.message==='项目简报与当前资料不一致，请刷新或重新选择快照。'?e.message:'当前项目简报暂不可读，请确认服务正常后刷新。';
    }finally{
      clearTimeout(timeout);
      if(request===serial){loading=false;controller=null;timer=null;render();}
    }
  }
  window.addEventListener('lianzheng-snapshot-changing',event=>{
    clear();snapshotId=event.detail?.snapshot_id||null;workspaceRequest=event.detail?.request??null;switching=true;render();
  });
  window.addEventListener('lianzheng-snapshot-changed',event=>{
    const id=event.detail?.snapshot||event.detail?.snapshot_id||null;
    if(switching&&snapshotId!==id)return;
    clear();snapshotId=id;switching=false;render();refresh();
  });
  window.addEventListener('lianzheng-snapshot-change-failed',event=>{
    if(event.detail?.snapshot_id!==snapshotId||workspaceRequest!==null&&event.detail?.request!==workspaceRequest)return;
    clear();switching=true;error='所选项目未载入成功，请重新选择项目；旧简报未恢复。';render();
  });
  window.addEventListener('lianzheng-project-evidence-changed',event=>{
    if(event.detail?.snapshot_id!==snapshotId)return;
    clear();render();if(!switching)refresh();
  });
  function open(){
    if(!brief&&!loading&&!switching&&snapshotId)refresh();
    panel.scrollIntoView({behavior:'smooth',block:'start'});
    panel.focus({preventScroll:true});
  }
  window.lianzhengProjectBrief={open,refresh,state:publicState};
  render();
  // If the main workspace finished before this deferred script loaded, recover
  // only its selected identity. All displayed fields still come from context.
  if(typeof state==='object'&&!state.switchingSnapshot&&state.id&&state.analysis?.snapshot?.id===state.id){snapshotId=state.id;refresh();}
})();
