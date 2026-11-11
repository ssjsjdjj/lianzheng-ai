'use strict';
(() => {
  const instances = new Map();
  let serial = 0, mountSerial = 0;
  const scenario = {snapshot:null, focus:null, sourceRequest:null, selected:new Set(), result:null, pending:false, error:''};
  const publicState = () => ({snapshot:scenario.snapshot, focus:scenario.focus,
    selected_refs:[...scenario.selected].sort(), result:scenario.result ? JSON.parse(JSON.stringify(scenario.result)) : null,
    pending:scenario.pending, error:scenario.error});
  const context = () => state.analysis && state.analysis.snapshot.id === state.id ?
    {snapshot:state.id, focus:state.analysis.focus, request:state.request} : null;
  const current = () => {
    const c=context();
    return c && c.snapshot===scenario.snapshot && c.focus===scenario.focus && c.request===scenario.sourceRequest;
  };
  const disabled = () => scenario.pending || !current();
  const nodeLabel = n => n.name+(n.version?'@'+n.version:'');

  function publish() {
    for(const instance of instances.values())render(instance);
    window.dispatchEvent(new CustomEvent('lianzheng-simulation-changed',{detail:publicState()}));
  }

  async function calculate() {
    if(!current() || !scenario.focus)return;
    const request=++serial, snapshot=scenario.snapshot, focus=scenario.focus, sourceRequest=scenario.sourceRequest;
    scenario.pending=true;scenario.error='';publish();
    try {
      const result=await api('/api/snapshots/'+encodeURIComponent(snapshot)+'/simulation',{
        method:'POST',body:JSON.stringify({focus,selected_refs:[...scenario.selected]})});
      if(request!==serial || !current() || sourceRequest!==state.request)return;
      if(result.kind!=='hypothetical' || result.snapshot.id!==snapshot || result.focus!==focus)
        throw new Error('推演响应与当前清单不一致，请刷新后重试。');
      scenario.result=result;scenario.selected=new Set(result.selected_refs);
    }catch(error){
      if(request!==serial || !current())return;
      scenario.error=error.message;
      scenario.selected=new Set(scenario.result?.selected_refs||[]);
    }finally{
      if(request===serial){scenario.pending=false;publish();}
    }
  }

  function synchronize() {
    const c=context();++serial;
    scenario.snapshot=c?.snapshot||null;scenario.focus=c?.focus||null;scenario.sourceRequest=c?.request??null;
    scenario.selected=new Set();scenario.result=null;scenario.pending=false;scenario.error='';publish();
    if(c?.focus)calculate();
  }

  function toggle(ref, instance, kind) {
    if(disabled() || !scenario.result){scenario.error='请等待当前清单载入，再操作推演。';publish();return;}
    if(!scenario.result.occurrences.some(o=>o.ref===ref))return;
    const next=new Set(scenario.selected);
    if(next.has(ref))next.delete(ref);else next.add(ref);
    if(next.size>scenario.result.selection_limit){scenario.error='单次最多选择 '+scenario.result.selection_limit+' 个位置，请分组推演。';publish();return;}
    instance.focusRef=ref;instance.focusKind=kind;
    scenario.selected=next;calculate();
  }

  function render(instance) {
    const {root,compact}=instance, result=scenario.result;
    const pending=disabled(), attr=pending?' disabled':'';
    const header=compact?'':`<div class="simulation-heading"><div><span class="simulation-eyebrow">WHAT-IF · 假设推演</span><h2>交互式修复推演</h2></div><span class="simulation-readonly">临时预览 · 不保存为清单</span></div>`;
    const intro='<div class="simulation-notice"><strong>先试着处理一个位置，观察还剩哪些风险路径。</strong><span>勾选只表示“假设该位置不再命中当前公告”。版本、依赖边和实际扫描结果保持原样；实际修复仍需新清单与测试记录。</span></div>';
    let body='';
    if(!scenario.snapshot)body='<p class="simulation-empty">正在等待项目清单…</p>';
    else if(!scenario.focus)body='<p class="simulation-empty">当前没有已知命中公告。请先选择有命中记录的快照与公告；未扫描不代表安全。</p>';
    else if(!result)body=`<p class="simulation-status" role="status">${scenario.pending?'正在读取已知命中位置…':'尚未取得推演依据。'}</p>${scenario.pending?'':'<div class="simulation-actions"><button type="button" data-sim-refresh>重新读取依据</button></div>'}`;
    else {
      const counts=result.counts;
      const cards=[['原始已知命中',counts.known_affected,''],['假设已处理',counts.assumed_handled,'assumed'],['剩余命中预览',counts.remaining,'remaining']];
      const seenTargets=new Set(result.paths.map(p=>p.target_ref));
      const pathMarkup=result.paths.map((path,i)=>`<div class="simulation-path ${path.selected?'is-assumed':'is-remaining'}" aria-label="推演代表路径 ${i+1}"><div class="simulation-path-head"><span>路径 ${i+1}</span><strong>${path.selected?'终点已假设处理':'终点仍有目标命中'}</strong></div><div class="simulation-path-nodes">${path.nodes.map((node,j)=>{
        const terminal=j===path.nodes.length-1;
        return `${j?`<span class="simulation-arrow" aria-hidden="true" title="${escapeHTML(path.edge_locators[j-1])}">→</span>`:''}${terminal?`<button class="simulation-path-target" type="button" data-sim-ref="${escapeHTML(path.target_ref)}" aria-pressed="${path.selected}" aria-label="${path.selected?'撤销假设处理':'假设处理'} ${escapeHTML(nodeLabel(node))}，位置 ${escapeHTML(path.target_ref)}，路径 ${i+1}"${attr}><span>${escapeHTML(nodeLabel(node))}</span><small>${path.selected?'已勾选 · 点击撤销':'点击假设处理此位置'}</small></button>`:`<span class="simulation-path-node" title="${escapeHTML(node.locator)}">${escapeHTML(nodeLabel(node))}</span>`}`;
      }).join('')}</div></div>`).join('');
      const occurrence = o => `<label class="simulation-occurrence ${o.selected?'is-assumed':''}"><input type="checkbox" data-sim-occurrence="${escapeHTML(o.ref)}" ${o.selected?'checked ':''}${attr} aria-label="假设处理 ${escapeHTML(nodeLabel(o))}，位置 ${escapeHTML(o.ref)}"><span><strong>${escapeHTML(nodeLabel(o))}</strong><code>${escapeHTML(o.ref)}</code><small>${escapeHTML(o.locator)} · ${o.reachable?'从项目根可达':'未从项目根可达，仍计入已知命中'}${o.reachable&&!seenTargets.has(o.ref)?' · 路径未在上方展开':''}</small></span><em>${o.selected?'假设已处理':'仍待处理'}</em></label>`;
      const initial=result.occurrences.slice(0,40), extra=result.occurrences.slice(40);
      const coverage=`${result.coverage.graph_complete?'原清单结构完整':'原清单结构存在缺失'} · ${result.coverage.unknown_scan_count} 个位置尚未完成查询`;
      body=`<div class="simulation-source"><strong>${escapeHTML(result.snapshot.project)} · ${escapeHTML(result.snapshot.label)}</strong><span>${escapeHTML(result.focus)}</span></div>
        <div class="simulation-metrics">${cards.map(([label,value,color])=>`<div class="simulation-metric ${color}"><span>${label}</span><strong>${value}</strong></div>`).join('')}</div>
        <p class="simulation-conclusion" role="status">${scenario.pending?'正在重新计算；下方暂保留上次预览。':escapeHTML(result.conclusion)}</p>
        <div class="simulation-actions"><button type="button" data-sim-all${pending||result.occurrences.length>result.selection_limit?' disabled':''}>假设处理全部已知位置</button><button type="button" data-sim-reset${attr}>重置推演</button><button type="button" data-sim-refresh${scenario.pending?' disabled':''}>重新读取依据</button></div>
        <div class="simulation-coverage ${result.coverage.can_confirm_absence?'':'is-incomplete'}">${escapeHTML(coverage)}${result.coverage.can_confirm_absence?'':'；剩余预览为零也不能排除未知风险。'}</div>
        <div class="simulation-paths">${pathMarkup||'<p class="simulation-empty">当前命中位置没有可展示的有界根路径，请查看下方完整位置列表。</p>'}</div>
        <p class="simulation-path-caption">展示 ${result.paths.length} 条代表性路径${result.paths_truncated?'（已截断）':''}；计数覆盖全部 ${counts.known_affected} 个已知命中位置。${counts.remaining_unreachable?'剩余包含 '+counts.remaining_unreachable+' 个不可达位置。':''}</p>
        <details class="simulation-occurrences"${instance.positionsOpen?' open':''}><summary>按精确出现位置选择 · ${counts.known_affected} 个</summary><div>${initial.map(occurrence).join('')}${extra.length?`<details class="simulation-extra"><summary>展开其余 ${extra.length} 个位置</summary>${extra.map(occurrence).join('')}</details>`:''}</div></details>
        <details class="simulation-limits"><summary>推演假设与适用范围</summary><ul>${result.limitations.map(item=>`<li>${escapeHTML(item)}</li>`).join('')}</ul><p>原始清单 SHA-256：<code>${escapeHTML(result.snapshot.hash)}</code></p></details>`;
    }
    const error=scenario.error?`<p class="simulation-error" role="alert">${escapeHTML(scenario.error)}${result?' 上次已计算的预览保留。':''}</p>`:'';
    root.innerHTML=header+intro+error+body;
    root.querySelectorAll('[data-sim-ref]').forEach(button=>button.addEventListener('click',()=>toggle(button.dataset.simRef,instance,'path')));
    root.querySelectorAll('[data-sim-occurrence]').forEach(input=>input.addEventListener('change',()=>toggle(input.dataset.simOccurrence,instance,'occurrence')));
    const detail=root.querySelector('.simulation-occurrences');
    detail?.addEventListener('toggle',()=>{instance.positionsOpen=detail.open;});
    root.querySelector('[data-sim-all]')?.addEventListener('click',()=>{
      if(disabled())return;scenario.selected=new Set(result.occurrences.map(o=>o.ref));calculate();
    });
    root.querySelector('[data-sim-reset]')?.addEventListener('click',()=>{if(disabled())return;scenario.selected=new Set();calculate();});
    root.querySelector('[data-sim-refresh]')?.addEventListener('click',synchronize);
    if(!scenario.pending && instance.focusRef){
      const key=instance.focusKind==='path'?'simRef':'simOccurrence';
      const candidate=[...root.querySelectorAll('[data-sim-ref],[data-sim-occurrence]')].find(el=>el.dataset[key]===instance.focusRef);
      if(candidate)candidate.focus({preventScroll:true});
      instance.focusRef=null;
    }
  }

  function mount(container, options={}) {
    if(!(container instanceof Element))throw new Error('推演需要一个页面容器。');
    unmount(container);
    const root=document.createElement('section');root.className='simulation-component'+(options.compact?' simulation-compact':'');
    root.setAttribute('role','region');root.setAttribute('aria-label',options.compact?'交互修复推演（讲解）':'交互修复推演（工作台）');
    root.dataset.simulationInstance=String(++mountSerial);container.append(root);
    const instance={root,compact:Boolean(options.compact),positionsOpen:false,focusRef:null,focusKind:null};
    instances.set(container,instance);render(instance);
    const c=context();
    if(c && (c.snapshot!==scenario.snapshot || c.focus!==scenario.focus || c.request!==scenario.sourceRequest))synchronize();
    return {refresh:synchronize,destroy:()=>{if(instances.get(container)===instance)unmount(container);}};
  }
  function unmount(container) {const instance=instances.get(container);if(instance){instance.root.remove();instances.delete(container);}}
  const host=document.createElement('section');host.id='simulation-panel';host.className='panel simulation-panel';
  document.getElementById('issues-panel').before(host);
  const launch=document.createElement('button');launch.type='button';launch.className='button secondary';launch.textContent='修复推演';
  document.querySelector('.heading-actions').prepend(launch);
  function open() {host.scrollIntoView({behavior:'smooth',block:'start'});if(!current())synchronize();}
  launch.addEventListener('click',open);
  window.lianzhengSimulation={mount,unmount,open,state:publicState};
  window.addEventListener('lianzheng-snapshot-changed',synchronize);
  mount(host);
})();
