/* A read-only presentation shell: model calls remain explicit in the workbench. */
(()=>{
  'use strict';
  const launch=document.createElement('button');
  launch.type='button';launch.id='open-presenter';launch.className='button secondary';launch.textContent='全屏讲解';
  document.querySelector('.heading-actions')?.append(launch);
  const dialog=document.createElement('dialog');
  dialog.id='presenter-dialog';dialog.className='presenter-dialog';
  dialog.setAttribute('aria-labelledby','presenter-title');
  dialog.innerHTML=`<header class="presenter-top"><div class="presenter-brand"><span>链证 AI</span><small>从风险问题到可核查的处理记录</small></div><div class="presenter-top-actions"><button type="button" data-presenter-action="fullscreen">浏览器全屏</button><button type="button" data-presenter-action="close" aria-label="退出全屏讲解">退出讲解 ×</button></div></header>
    <nav class="presenter-steps" aria-label="讲解步骤"></nav>
    <section class="presenter-body" aria-labelledby="presenter-title"><div class="presenter-context"></div><p class="presenter-kicker"></p><h2 id="presenter-title" tabindex="-1"></h2><p class="presenter-intro"></p><div class="presenter-content"></div></section>
    <footer class="presenter-footer"><div><span class="presenter-progress" aria-live="polite"></span><p class="presenter-status" role="status"></p></div><div class="presenter-navigation"><button type="button" data-presenter-action="previous">← 上一步</button><button type="button" data-presenter-action="next">下一步 →</button></div></footer>`;
  document.body.append(dialog);
  const find=s=>dialog.querySelector(s);
  const labels=['项目来源','路径与原文','交互推演','真实复核','报告与边界'];
  find('.presenter-steps').innerHTML=labels.map((label,index)=>`<button type="button" data-presenter-step="${index}" aria-label="第 ${index+1} 步：${label}"><span>${String(index+1).padStart(2,'0')}</span>${label}</button>`).join('');
  let step=0,selectedPath=0,caseInfo=null,caseError='',caseLoading=false,caseBusy=false,session=0;
  let priorFocus=null,priorOverflow='',simulation=null;
  const html=value=>escapeHTML(value);
  const array=value=>Array.isArray(value)?value:[];
  const integer=value=>Number.isInteger(value)&&value>=0?String(value):'待核验';
  const analysis=()=>state.analysis?.snapshot?.id===state.id?state.analysis:null;
  function lastAnswer(){
    const answer=state.lastAnswer,a=analysis();
    return answer&&a&&answer.facts?.snapshot_id===state.id&&answer.facts?.focus===a.focus?answer:null;
  }
  function releaseSimulation(){if(simulation){simulation.destroy?.();simulation=null;}}
  function sourceType(a){return !a?'等待当前项目快照':a.snapshot.demo?'构造业务拓扑 · 真实冻结公告':'当前导入清单 · 来源以文件为准';}
  function sourceLink(url,label){const safe=safeURL(url);return safe==='#'?'':`<a href="${html(safe)}" target="_blank" rel="noopener noreferrer">${html(label)} ↗</a>`;}
  function fileLink(file){
    if(typeof file?.url!=='string')return '';
    const safe=file.url.startsWith('/api/real-case/')&&!file.url.includes('\\')?file.url:safeURL(file.url);
    if(safe==='#')return '';
    return `<a class="presenter-file" href="${html(safe)}"${safe.startsWith('https:')?' target="_blank" rel="noopener noreferrer"':''}>${html(file.label||file.name||'案例文件')} ↓${file.sha256?`<small>SHA-256 ${html(file.sha256)}</small>`:''}</a>`;
  }
  function empty(message,detail=''){
    return `<div class="presenter-empty"><strong>${html(message)}</strong>${detail?`<p>${html(detail)}</p>`:''}</div>`;
  }
  function stat(value,label,note=''){
    return `<article class="presenter-stat"><strong>${html(value)}</strong><span>${html(label)}</span>${note?`<small>${html(note)}</small>`:''}</article>`;
  }
  function setHeading(kicker,title,intro){
    find('.presenter-kicker').textContent=kicker;find('#presenter-title').textContent=title;find('.presenter-intro').textContent=intro;
  }
  function targets(a){return array(a?.findings).filter(f=>f.id===a?.focus);}
  function overview(a){
    const affected=targets(a),paths=array(a?.paths),snapshot=a?.snapshot;
    setHeading('01 / 先说明问题和资料来源',a?.focus?`${affected.length} 个组件位置命中同一公告`:'从一份可追溯的依赖清单开始',
      '先确认项目、版本与数据覆盖，再解释路径和处理方案。这里展示当前工作空间的数据。');
    if(!a)return empty('尚未取得当前快照','退出讲解，载入一份项目清单后再开始。');
    const dates=array(a.nodes).map(n=>n.fetched_at).filter(Boolean).sort();
    const risk=array(a.vulnerabilities).find(v=>v.id===a.focus);
    return `<div class="presenter-stats">${stat(integer(affected.length),'目标公告命中位置','同版本不同安装位置独立保留')}${stat(integer(paths.length),'展示的代表路径',a.paths_truncated?'路径展示已截断':'不把路径展示数当成全部依赖数')}${stat(integer(a.stats?.unknown),'未完成查询的位置','未查询不代表无漏洞')}</div>
      <div class="presenter-columns"><article class="presenter-card"><h3>正在讲解的清单</h3><dl><div><dt>项目</dt><dd>${html(snapshot.project)}</dd></div><div><dt>快照</dt><dd>${html(snapshot.label)}</dd></div><div><dt>目标公告</dt><dd>${html(a.focus||'尚未选择')}</dd></div><div><dt>公告摘要</dt><dd>${html(risk?.summary||'当前没有选中公告')}</dd></div></dl><p class="presenter-boundary">${html(snapshot.demo?'业务组件与拓扑是构造案例，公告来自冻结 OSV 记录。':'按导入文件中明确声明的依赖关系分析；来源真实性与运行环境仍需分别核对。')}</p></article>
      <article class="presenter-card"><h3>证据覆盖</h3><dl><div><dt>依赖结构</dt><dd>${a.complete?'当前清单结构完整':'存在缺边或信息不足'}</dd></div><div><dt>查询来源</dt><dd>${html(array(a.sources).map(sourceLabel).join(' / ')||'尚无查询记录')}</dd></div><div><dt>最近记录</dt><dd>${html(dates.length?dateLabel(dates.at(-1)):'尚无获取时间')}</dd></div></dl><p class="presenter-boundary">${a.can_confirm_absence?'覆盖结论仅适用于当前清单和保存的公告快照。':'覆盖尚不完整，不能把未观察到风险解释成风险已消除。'}</p></article></div>
      <div class="presenter-callout"><strong>提问：如果只处理其中一个位置，另一条引入路径还在吗？</strong><span>下一步沿原始依赖边核对。</span></div>`;
  }
  function pathStage(a){
    setHeading('02 / 让结论可以点开核对','沿依赖路径找到位置，再核对原文',
      '路径来自清单中的依赖边，公告文本与适用版本作为证据单独呈现。');
    if(!a)return empty('尚未取得当前快照');
    const map=new Map(array(a.nodes).map(n=>[n.id,n]));
    const paths=array(a.paths).filter(p=>Array.isArray(p)&&p.every(ref=>map.has(ref))).slice(0,5);
    if(selectedPath>=paths.length)selectedPath=0;
    const selected=paths[selectedPath],target=selected?map.get(selected.at(-1)):null;
    const docs=array(a.documents).filter(d=>!a.focus||d.vulnerability===a.focus);
    const matching=docs.filter(d=>!target||d.ref===target.id||(d.package===target.name&&d.version===target.version));
    const evidence=(matching.length?matching:docs).slice(0,3);
    const edges=new Map(array(a.edges).map(e=>[JSON.stringify([e.source,e.target]),e.locator]));
    const list=paths.length?paths.map((path,index)=>`<button type="button" class="presenter-path ${index===selectedPath?'selected':''}" data-presenter-path="${index}" aria-pressed="${index===selectedPath}"><b>路径 ${index+1}</b><span class="presenter-path-chain">${path.map(ref=>{const node=map.get(ref);return `<span class="presenter-path-node ${ref===path.at(-1)?'target':''}">${html(node.name)}<small>${html(node.version||'项目根节点')}</small></span>`;}).join('<span class="presenter-path-arrow" aria-hidden="true">→</span>')}</span></button>`).join(''):empty('当前没有可展示的目标路径','可能尚未选中公告、目标不可达，或依赖关系有缺失；请核对当前清单。');
    const locators=selected?`<details class="presenter-details"><summary>核对所选路径的原始位置</summary><ol>${selected.map((ref,index)=>`<li><strong>${html(map.get(ref).name)}</strong><code>${html(map.get(ref).locator||ref)}</code>${index?`<span>引入边：${html(edges.get(JSON.stringify([selected[index-1],ref]))||'未提供位置')}</span>`:''}</li>`).join('')}</ol></details>`:'';
    return `<div class="presenter-columns presenter-path-columns"><article class="presenter-card"><h3>选择一条路径</h3><div class="presenter-path-list">${list}</div><p class="presenter-boundary">${a.paths_truncated||array(a.paths).length>5?'仅展示前 5 条代表路径，不能据此宣称已枚举全部路径。':'这里展示代表性路径；未扫描或缺失信息仍会限制结论。'}</p>${locators}</article><article class="presenter-card"><h3>当前公告原文</h3>${evidence.length?evidence.map(d=>`<section class="presenter-evidence"><span>${html(sourceLabel(d.source))} · ${html(d.version||'版本未提供')}</span><h4>${html(d.title||d.vulnerability||'引用证据')}</h4><p class="presenter-excerpt">${html(String(d.text||'').slice(0,440))}${String(d.text||'').length>440?'…':''}</p><details class="presenter-details"><summary>查看完整原文与定位</summary><p>${html(d.locator||'未提供定位')}</p><pre>${html(d.text||'尚无原文')}</pre>${sourceLink(d.url,'查看原始来源')}</details></section>`).join(''):empty('当前尚无适用的公告原文','不能用缺失证据证明不存在风险。')}<p class="presenter-boundary">原句存在不自动证明语义支持、运行时可利用性或业务兼容性。</p></article></div>`;
  }
  function simulationStage(){
    setHeading('03 / 由评委选择一个处理位置','选择位置，观察剩余目标命中如何变化',
      '这是临时假设，不会改写依赖清单、保存修复结果或发起模型调用。');
    return `<div class="presenter-simulation-host"></div>`;
  }
  function testRecord(record,title){
    const exists=record&&typeof record==='object';
    const result=exists&&typeof record.exit_code==='number'?(record.exit_code===0?'记录中的命令执行成功':`记录中的退出码：${record.exit_code}`):'尚无可核对的执行结果';
    return `<article class="presenter-card"><h3>${html(title)}</h3><strong class="presenter-result ${exists&&record.exit_code===0?'recorded':''}">${html(result)}</strong>${record?.command?`<code class="presenter-command">${html(record.command)}</code>`:''}<p>${html(record?.summary||'未提供测试摘要。')}</p>${record?.executed_at?`<small>记录时间：${html(dateLabel(record.executed_at))}</small>`:''}<p class="presenter-boundary">仅说明所列命令与测试范围的执行结果，不证明业务全覆盖。</p></article>`;
  }
  function caseStage(){
    setHeading('04 / 用实际材料复核假设','查看真实项目的修复记录与测试凭据',
      '单独核对固定来源、实际生成的新清单和测试结果；推演状态不会用于替代这些材料。');
    if(caseLoading&&!caseInfo)return empty('正在读取本机真实案例资料','此操作不调用模型。');
    if(!caseInfo?.available)return empty('真实案例资料尚未就绪',caseError||'只有经过采集与验证的资料才会在这里显示。');
    // This endpoint's verification is a recorded experiment, even after its files are loaded.
    // Current workspace checks are reported separately and must never relabel archived counts.
    const c=caseInfo,v=c.verification||{},current=c.current||{};
    const supported=v.target_before_count>0&&v.target_after_count===0&&v.comparison_complete===true&&v.same_knowledge_snapshot===true;
    const currentNotice=c.prepared?(current.basis_matches_recorded===false?
      `<p class="presenter-case-stale" role="alert"><strong>当前工作空间的依据已变化。</strong>下方保留的是实验记录，不能据此判定本机当前状态已修复。当前清单的目标命中：修复前 ${integer(current.target_before_count)}，修复后 ${integer(current.target_after_count)}；请打开案例详情重新核对。</p>`:
      `<p class="presenter-record-note">${current.basis_matches_recorded===true?'本机已载入的依据与保存实验一致；这不会重新执行测试。':'案例文件已载入；当前工作空间的依据一致性尚待核对。'}</p>`):
      '<p class="presenter-record-note">下方为随案例保存的实际实验结果，尚未载入当前工作空间。</p>';
    return `<div class="presenter-case-heading"><div><span class="presenter-tag">随案例保存的实验记录 · 非本次重跑</span><h3>${html(c.title||c.project||'真实项目案例')}</h3><p>${html(c.project||'')} · ${html(c.focus||'目标公告待指定')}</p></div><div class="presenter-case-actions"><button type="button" data-presenter-action="prepare-case" ${caseBusy?'disabled':''}>${caseBusy?'载入中…':c.prepared?'重新读取案例状态':'载入案例到工作空间'}</button><button type="button" data-presenter-action="open-case">打开案例详情 ↗</button></div></div>
      ${currentNotice}<div class="presenter-stats presenter-case-counts">${stat(integer(v.target_before_count),'原始清单 · 目标命中','固定提交中的实际锁文件')}${stat(integer(v.target_partial_count),'部分处理 · 目标命中','实际生成的中间锁文件')}${stat(integer(v.target_after_count),'完整处理 · 目标命中','实际生成的新锁文件')}</div>
      <p class="presenter-boundary">${supported?'保存记录表明：所列完整清单在同一公告快照下，目标公告不再命中。其他公告、运行环境与业务上线仍需另行确认。':'保存记录尚不足以确认目标公告已消除。请核对剩余命中、依赖覆盖与公告时间一致性。'}</p>
      <div class="presenter-columns">${testRecord(c.tests?.before,'修复前的实际测试记录')}${testRecord(c.tests?.after,'修复后的实际测试记录')}</div>
      <article class="presenter-card presenter-provenance"><h3>可追溯来源与文件</h3><p>${sourceLink(c.source?.url,'上游项目 / 固定提交')}<span>${html(c.source?.license||'许可证待核对')}</span></p><code>${html(c.source?.commit||'尚未提供固定提交')}</code><details class="presenter-details"><summary>展开来源文件与校验值 · ${array(c.files).length} 份</summary><div class="presenter-files">${array(c.files).map(fileLink).join('')}</div></details>${array(c.limitations).length?`<details class="presenter-details"><summary>查看本案例的验证边界</summary><ul>${c.limitations.map(note=>`<li>${html(note)}</li>`).join('')}</ul></details>`:''}</article>`;
  }
  function reportStage(a){
    const answer=lastAnswer(),kind=answer?(state.lastAnswerReplay?'历史回放':answer.generation==='model-assisted'?'本次模型返回':'本地证据解释'):'尚未展示问答';
    setHeading('05 / 留下能复核的交付物','把依据、处理记录和待确认事项一起交付',
      '报告用于继续核对与协作；每种结论都保留它的来源和范围。');
    return `<div class="presenter-columns"><article class="presenter-card"><h3>当前问答状态</h3><span class="presenter-tag">${html(kind)}</span>${answer?`<h4>${html(answer.question)}</h4><p>${html(answer.conclusion)}</p><p class="presenter-boundary">${state.lastAnswerReplay?'展示当时保存的回答和引用，本次没有重新调用模型。':answer.generation==='model-assisted'?'该回答来自模型接口；引用核对与人工语义复核仍是不同步骤。':'该回答由本地图事实和证据模板形成，没有生成模型解释。'}</p>`:'<p>可以先展示图谱与清单复核。此讲解模式不会为了补齐步骤而自动请求模型。</p>'}<button type="button" data-presenter-action="review-answer">退出并核对问答 ↗</button></article>
      <article class="presenter-card"><h3>报告中需要区分的三件事</h3><ol class="presenter-checklist"><li><strong>图事实与原文</strong><span>哪些位置命中、从哪里引入、引用指向哪里。</span></li><li><strong>人工判断与任务记录</strong><span>支持范围、处理责任和检查项由操作者记录。</span></li><li><strong>实际清单与测试凭据</strong><span>与假设推演分开记录，保留未完成验证事项。</span></li></ol>${a?`<a class="presenter-primary-link" href="/api/snapshots/${encodeURIComponent(state.id)}/report?format=html">导出当前快照报告 ↓</a>`:''}</article></div>
      <div class="presenter-callout"><strong>评委可核对：每个结论用了什么依据，还有哪些地方不能确认。</strong><span>清单命中不等于运行时可利用；单个公告无命中不等于项目全部安全。</span></div>`;
  }
  function render({focus=false}={}){
    if(!dialog.open)return;
    releaseSimulation();
    dialog.classList.toggle('presenter-step-simulation',step===2);
    dialog.classList.toggle('presenter-step-case',step===3);
    const a=analysis();
    find('.presenter-context').innerHTML=`<span class="presenter-tag">${html(sourceType(a))}</span><span>${html(a?.snapshot.project||'工作空间未就绪')} · ${html(a?.snapshot.label||'等待快照')}</span>`;
    const content=[overview,pathStage,simulationStage,caseStage,reportStage][step](a);
    find('.presenter-content').innerHTML=content;
    dialog.querySelectorAll('[data-presenter-step]').forEach(button=>{const active=Number(button.dataset.presenterStep)===step;button.classList.toggle('active',active);if(active)button.setAttribute('aria-current','step');else button.removeAttribute('aria-current');});
    find('.presenter-progress').textContent=`${step+1} / ${labels.length} · ${labels[step]}`;
    find('[data-presenter-action="previous"]').disabled=step===0;
    find('[data-presenter-action="next"]').textContent=step===labels.length-1?'结束讲解 ✓':'下一步 →';
    if(step===2){
      const host=find('.presenter-simulation-host');
      if(window.lianzhengSimulation?.mount)simulation=window.lianzhengSimulation.mount(host,{compact:true});
      else host.innerHTML=empty('推演组件尚未加载','请退出讲解并刷新应用；这里不会显示虚构的推演结果。');
    }
    if(focus){find('.presenter-body').scrollTop=0;find('#presenter-title').focus({preventScroll:true});}
  }
  async function readCase(){
    const serial=session;caseLoading=true;caseError='';
    try{const result=await api('/api/real-case');if(serial!==session)return;caseInfo=result;}
    catch(error){if(serial!==session)return;caseError=error.message;caseInfo=null;}
    finally{if(serial===session){caseLoading=false;if(dialog.open&&step===3)render();}}
  }
  function open(){
    if(dialog.open)return;
    priorFocus=document.activeElement;priorOverflow=document.body.style.overflow;document.body.style.overflow='hidden';
    ++session;step=0;selectedPath=0;dialog.showModal();
    find('.presenter-status').textContent='方向键切换步骤，Esc 退出。讲解模式不会自动调用模型。';
    render({focus:true});readCase();
  }
  function close(){if(dialog.open)dialog.close();}
  function go(index){step=Math.max(0,Math.min(labels.length-1,index));render({focus:true});}
  async function prepareCase(){
    if(caseBusy)return;
    if(!window.lianzhengRealCase?.prepare){find('.presenter-status').textContent='案例载入组件尚未就绪，请退出讲解后刷新页面。';return;}
    const serial=session;caseBusy=true;render();
    try{const result=await window.lianzhengRealCase.prepare();if(serial!==session)return;if(result)caseInfo=result;else await readCase();find('.presenter-status').textContent='案例状态已更新。显示的测试记录仍是保存的实际执行记录，并未在此重新运行。';}
    catch(error){if(serial===session)find('.presenter-status').textContent=error.message;}
    finally{caseBusy=false;if(serial===session&&dialog.open)render();}
  }
  async function fullscreen(){
    const button=find('[data-presenter-action="fullscreen"]');
    try{if(document.fullscreenElement===dialog)await document.exitFullscreen();else if(dialog.requestFullscreen)await dialog.requestFullscreen();else throw new Error('当前浏览器不支持系统全屏');}
    catch{find('.presenter-status').textContent='当前仍为铺满页面的讲解模式；浏览器系统全屏未启用。';}
    button.textContent=document.fullscreenElement===dialog?'退出浏览器全屏':'浏览器全屏';
  }
  launch.addEventListener('click',open);
  dialog.addEventListener('click',event=>{
    const button=event.target.closest('button');if(!button||!dialog.contains(button))return;
    if(button.dataset.presenterStep!==undefined){go(Number(button.dataset.presenterStep));return;}
    if(button.dataset.presenterPath!==undefined){selectedPath=Number(button.dataset.presenterPath);render();find(`[data-presenter-path="${selectedPath}"]`)?.focus({preventScroll:true});return;}
    switch(button.dataset.presenterAction){
      case 'close':close();break;
      case 'previous':go(step-1);break;
      case 'next':if(step===labels.length-1)close();else go(step+1);break;
      case 'fullscreen':fullscreen();break;
      case 'prepare-case':prepareCase();break;
      case 'open-case':close();if(window.lianzhengRealCase?.open)window.lianzhengRealCase.open();else toast('真实案例组件尚未就绪，请刷新页面后重试。');break;
      case 'review-answer':close();changeView('questions');break;
    }
  });
  dialog.addEventListener('keydown',event=>{
    const editing=event.target.closest('input,textarea,select,[contenteditable="true"]');
    if(editing||event.altKey||event.ctrlKey||event.metaKey)return;
    if(event.key==='ArrowRight'){event.preventDefault();if(step<labels.length-1)go(step+1);}
    if(event.key==='ArrowLeft'){event.preventDefault();if(step>0)go(step-1);}
  });
  dialog.addEventListener('close',()=>{
    ++session;caseLoading=false;releaseSimulation();document.body.style.overflow=priorOverflow;
    if(document.fullscreenElement===dialog)document.exitFullscreen().catch(()=>{});
    if(priorFocus?.isConnected)priorFocus.focus({preventScroll:true});else launch.focus({preventScroll:true});
  });
  document.addEventListener('fullscreenchange',()=>{find('[data-presenter-action="fullscreen"]').textContent=document.fullscreenElement===dialog?'退出浏览器全屏':'浏览器全屏';});
  window.addEventListener('lianzheng-snapshot-changed',()=>{
    selectedPath=0;if(dialog.open){find('.presenter-status').textContent='当前快照已切换，讲解内容已同步；推演和实际复核保持分开。';render();}
  });
  window.addEventListener('lianzheng-answer-rendered',()=>{if(dialog.open&&step===4)render();});
  window.addEventListener('lianzheng-case-loaded',event=>{caseInfo=event.detail;caseError='';if(dialog.open&&step===3)render();});
  window.lianzhengPresenter={open,close};
})();
