/* A read-only presentation shell: model calls remain explicit in the workbench. */
(()=>{
  'use strict';
  const dialog=document.createElement('dialog');
  dialog.id='presenter-dialog';dialog.className='presenter-dialog';
  dialog.setAttribute('aria-labelledby','presenter-title');
  dialog.innerHTML=`<header class="presenter-top"><div class="presenter-brand"><span>链证 AI</span><small>同一案例，从风险问题到处理证据</small></div><div class="presenter-top-actions"><button type="button" data-presenter-action="restart">从头开始</button><button type="button" data-presenter-action="fullscreen">浏览器全屏</button><button type="button" data-presenter-action="close" aria-label="退出全屏讲解">退出讲解 ×</button></div></header>
    <nav class="presenter-steps" aria-label="讲解步骤"></nav>
    <section class="presenter-body" aria-labelledby="presenter-title"><div class="presenter-context"></div><p class="presenter-kicker"></p><h2 id="presenter-title" tabindex="-1"></h2><p class="presenter-intro"></p><div class="presenter-content"></div></section>
    <footer class="presenter-footer"><div><span class="presenter-progress" aria-live="polite"></span><p class="presenter-status" role="status"></p></div><div class="presenter-navigation"><button type="button" data-presenter-action="previous">← 上一步</button><button type="button" data-presenter-action="next">下一步 →</button></div></footer>`;
  document.body.append(dialog);
  const find=s=>dialog.querySelector(s);
  const labels=['项目来源','路径与原文','任务对照','交互推演','方案比较','修复时间线','报告与边界'];
  const PROGRESS_KEY='lianzheng-presenter-v09';
  const flows={quick:[0,2,4,6],full:[0,1,2,3,4,5,6]};
  let step=0,mode='full',selectedPath=0,caseInfo=null,lockedAnalysis=null,lockedSource=null,contextBroken=false,busyStart=false,startSerial=0;
  let priorFocus=null,priorOverflow='',simulation=null,comparisonMount=null,decisionsMount=null;
  const html=value=>escapeHTML(value),array=value=>Array.isArray(value)?value:[];
  const integer=value=>Number.isInteger(value)&&value>=0?String(value):'待核验';
  const analysis=()=>lockedAnalysis;
  const activeFlow=()=>flows[mode];
  function savedProgress(){try{
    const saved=JSON.parse(sessionStorage.getItem(PROGRESS_KEY)||'null');
    return saved&&/^[a-f0-9]{64}$/.test(saved.case_hash)&&Object.hasOwn(flows,saved.mode)&&
      Number.isInteger(saved.step)&&flows[saved.mode].includes(saved.step)?
      {case_hash:saved.case_hash,mode:saved.mode,step:saved.step}:null;
  }catch{return null;}}
  function saveProgress(){if(!caseInfo?.bundle_sha256)return;try{
    sessionStorage.setItem(PROGRESS_KEY,JSON.stringify({case_hash:caseInfo.bundle_sha256,mode,step}));
  }catch{/* Storage may be disabled; the in-memory presentation still works. */}
    window.dispatchEvent(new CustomEvent('lianzheng-presentation-changed',{detail:publicState()}));
  }
  const publicState=()=>({open:dialog.open,starting:busyStart,mode,step,saved:savedProgress(),case_hash:caseInfo?.bundle_sha256||null,context_broken:contextBroken});
  async function request(path,options={},timeout=15000){const control=new AbortController();const timer=setTimeout(()=>control.abort(),timeout);
    try{return await api(path,{...options,signal:control.signal});}catch(error){
      if(error.name==='AbortError')throw Error('本机服务读取超时，请确认服务运行后重试。没有调用模型。');
      throw error;
    }finally{clearTimeout(timer);}}
  function releaseSimulation(){
    if(simulation){simulation.destroy?.();simulation=null;}
    if(comparisonMount){comparisonMount.destroy?.();comparisonMount=null;}
    if(decisionsMount){decisionsMount.destroy?.();decisionsMount=null;}
  }
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
    find('.presenter-kicker').textContent=String(activeFlow().indexOf(step)+1).padStart(2,'0')+' / '+kicker.replace(/^\d+\s*\/\s*/,'');find('#presenter-title').textContent=title;find('.presenter-intro').textContent=intro;
  }
  function targets(a){return array(a?.findings).filter(f=>f.id===a?.focus);}
  function overview(a){
    const affected=targets(a),paths=array(a?.paths),snapshot=a?.snapshot;
    setHeading('01 / 先说明问题和资料来源',a?.focus?`${affected.length} 个组件位置命中同一公告`:'从一份可追溯的依赖清单开始',
      '本场始终使用 http-server 的同一份冻结案例：先查来源，再看残留、方案与测试。');
    if(!a)return empty('尚未取得当前快照','退出讲解，载入一份项目清单后再开始。');
    const dates=array(a.nodes).map(n=>n.fetched_at).filter(Boolean).sort();
    const risk=array(a.vulnerabilities).find(v=>v.id===a.focus);
    return `<div class="presenter-stats">${stat(integer(affected.length),'目标公告命中位置','同版本不同安装位置独立保留')}${stat(integer(paths.length),'展示的代表路径',a.paths_truncated?'路径展示已截断':'不把路径展示数当成全部依赖数')}${stat(integer(a.stats?.unknown),'未完成查询的位置','未查询不代表无漏洞')}</div>
      <div class="presenter-columns"><article class="presenter-card"><h3>正在讲解的清单</h3><dl><div><dt>项目</dt><dd>${html(snapshot.project)}</dd></div><div><dt>快照</dt><dd>${html(snapshot.label)}</dd></div><div><dt>目标公告</dt><dd>${html(a.focus||'尚未选择')}</dd></div><div><dt>公告摘要</dt><dd>${html(risk?.summary||'当前没有选中公告')}</dd></div></dl><p class="presenter-boundary">${html('固定上游源码 '+(caseInfo?.source?.commit||'')+' · '+(caseInfo?.source?.license||'许可证待核对')+'。这是保存的本地实验，不是生产部署验证。')}</p></article>
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
    setHeading('04 / 由评委选择一个处理位置','选择位置，观察剩余目标命中如何变化',
      '这是临时假设，不会改写依赖清单、保存修复结果或发起模型调用。');
    return `<div class="presenter-simulation-host"></div>`;
  }
  function comparisonStage(){
    setHeading('03 / 同一任务，两种证据组织方式','让检索差异和依据同时可见',
      '固定真实案例材料与相同输入上限。先核对证据；语义支持仍需人工复核。');
    return '<div class="presenter-comparison-host"></div>';
  }
  function decisionsStage(){
    setHeading('05 / 对比实际生成的处理方案','选方案，也看残留、改动和测试代价',
      '这里比较真实实验的清单与测试记录，和上一页的假设推演分开。');
    return '<div class="presenter-decisions-host"></div>';
  }
  function timelineStage(){
    setHeading('06 / 保留失败和迁移过程','从依赖更新，到测试失败，再到兼容迁移',
      '每一步连接当时的命令、文件与日志。播放保存的记录不会重跑测试。');
    return '<div class="presenter-timeline-host"></div>';
  }
  function reportStage(a){
    const q=window.lianzhengTaskCompare?.state?.(),r=q?.result;
    const matching=r&&r.source?.case_bundle_sha256===caseInfo?.bundle_sha256;
    const kind=matching?(r.fairness?.model_pair_comparable?'两侧模型返回已取得':'离线证据或未完成模型解释'):'本场尚未完成任务对照';
    setHeading('交付 / 留下能复核的材料','把依据、处理记录和待确认事项一起交付',
      '这里汇总本场同一案例的问答状态与公开实验资料，不自动补答或请求模型。');
    return `<div class="presenter-columns"><article class="presenter-card"><h3>本场任务对照</h3><span class="presenter-tag">${html(kind)}</span>${matching?`<h4>${html(r.task.question)}</h4><p>当前阶段：${html({before:'修复前',partial:'仅直接依赖更新',after:'最终阶段'}[r.task.phase]||r.task.phase)}。${r.comparison?.result==='unscored'?'现场问题没有参考标注，不计算正确率或胜负。':'固定题参考证据覆盖与答案语义正确性分别核对。'}</p><p class="presenter-boundary">两侧取证与模型返回仍需人工核对；本页面没有新增模型请求。</p>`:'<p>可以直接交付案例材料，或回到任务对照补充现场问题。</p>'}<button type="button" data-presenter-action="review-answer">返回本场任务对照 ↗</button></article>
      <article class="presenter-card"><h3>报告中保留三种依据</h3><ol class="presenter-checklist"><li><strong>图事实与原文</strong><span>精确安装位置、已声明关系与可下载的来源。</span></li><li><strong>实际方案与测试记录</strong><span>残留、改动、失败与兼容迁移均保留。</span></li><li><strong>仍待确认的事项</strong><span>覆盖缺口、运行时暴露与上线兼容分别核对。</span></li></ol>${a?`<a class="presenter-primary-link" href="/api/snapshots/${encodeURIComponent(a.snapshot.id)}/report?format=html">导出本场基线快照报告 ↓</a>`:''}</article></div>
      <div class="presenter-evidence-export"><a class="presenter-primary-link" href="/api/real-case/evidence.zip">下载真实案例证据包 ↓</a><span>包含公开案例清单、差异、成功与失败日志及校验索引；现场任务结果可回到双栏单独导出。</span></div>
      <div class="presenter-callout"><strong>每个结论都能追到来源，每个未确认事项都有位置。</strong><span>目标公告未再观察到不等于项目全部安全；保存的测试记录不等于现场重跑。</span></div>`;
  }
  function render({focus=false}={}){
    if(!dialog.open)return;
    releaseSimulation();
    dialog.classList.toggle('presenter-step-simulation',step===3);
    dialog.classList.toggle('presenter-step-case',step===4||step===5);
    dialog.classList.toggle('presenter-step-comparison',step===2);
    dialog.classList.toggle('presenter-quick',mode==='quick');
    const flow=activeFlow(),position=flow.indexOf(step),a=analysis();
    find('.presenter-steps').style.setProperty('--presenter-step-count',String(flow.length));
    find('.presenter-steps').innerHTML=flow.map((index,i)=>`<button type="button" data-presenter-step="${index}" aria-label="第 ${i+1} 步：${labels[index]}" ${index===step?'class="active" aria-current="step"':''}><span>${String(i+1).padStart(2,'0')}</span>${labels[index]}</button>`).join('');
    find('.presenter-context').innerHTML=`<span class="presenter-tag">同一真实案例 · 保存的实验</span><span>http-server v14.1.0 · ${html(caseInfo?.focus||'')}</span>`;
    find('.presenter-progress').textContent=`${position+1} / ${flow.length} · ${labels[step]} · ${mode==='quick'?'90 秒精简':'3 分钟完整'}`;
    find('[data-presenter-action="previous"]').disabled=position===0;
    find('[data-presenter-action="next"]').textContent=position===flow.length-1?'结束讲解 ✓':'下一步 →';
    if(contextBroken){
      setHeading('资料上下文已变化','先重新核对同一案例，再继续讲解','工作空间已切换或重新读取，当前展示已暂停，避免把不同依据混在一起。');
      find('.presenter-content').innerHTML=empty('本场进度仍保留','重新核对不会覆盖原有清单、历史问答或人工记录。')+'<p><button type="button" data-presenter-action="recover">重新核对并恢复此步骤</button></p>';
    }else{
      find('.presenter-content').innerHTML=[overview,pathStage,comparisonStage,simulationStage,decisionsStage,timelineStage,reportStage][step](a);
      if(step===3){const host=find('.presenter-simulation-host');
        if(window.lianzhengSimulation?.mount)simulation=window.lianzhengSimulation.mount(host,{compact:true});
        else host.innerHTML=empty('推演组件尚未加载','请退出讲解，刷新页面后恢复进度。');}
      if(step===2){const host=find('.presenter-comparison-host');
        if(window.lianzhengTaskCompare?.mount)comparisonMount=window.lianzhengTaskCompare.mount(host,{compact:true});
        else host.innerHTML=empty('任务组件尚未加载','请退出讲解，刷新页面后恢复进度。');}
      if(step===4||step===5){const host=find(step===4?'.presenter-decisions-host':'.presenter-timeline-host');
        if(window.lianzhengCaseDecisions?.mount)decisionsMount=window.lianzhengCaseDecisions.mount(host,{compact:true,tab:step===4?'plans':'timeline'});
        else host.innerHTML=empty('方案组件尚未加载','请退出讲解，刷新页面后恢复进度。');}
    }
    if(focus){find('.presenter-body').scrollTop=0;find('#presenter-title').focus({preventScroll:true});}
    saveProgress();
  }
  async function start(options={}){
    if(busyStart)throw Error('讲解资料正在准备，请等待完成。');
    if(state.pendingQuestion||window.lianzhengTaskCompare?.state?.().running)throw Error('仍有问题等待返回，请先完成或停止本地等待，再开始新一场。');
    const saved=options.resume?savedProgress():null;
    if(options.resume&&!saved)throw Error('没有可恢复的本场进度，请从头开始。');
    const nextMode=saved?.mode||(options.mode==='quick'?'quick':'full');
    const serial=++startSerial,ensureCurrent=()=>{if(serial!==startSerial)throw Error('已停止本场准备，晚到的读取结果不会重新打开讲解。');};
    busyStart=true;window.dispatchEvent(new CustomEvent('lianzheng-presentation-changed',{detail:publicState()}));
    try{
      const check=await request('/api/demo/preflight');
      ensureCurrent();
      if(!check.offline_ready||!check.case?.available)throw Error('案例预检未通过，请在准备面板核对失败项后重试。');
      if(saved&&saved.case_hash!==check.case.bundle_sha256)throw Error('案例材料已变化，旧进度不能恢复，请从头开始重新核对。');
      const current=await request('/api/real-case/prepare',{method:'POST',body:'{}'},25000);
      ensureCurrent();
      if(!current.available||!current.prepared||current.bundle_sha256!==check.case.bundle_sha256||
         current.current?.basis_matches_recorded!==true||!current.before_snapshot_id)throw Error('本机案例依据与冻结记录不一致，未覆盖已有数据，请核对后重试。');
      await loadSnapshots();ensureCurrent();await selectSnapshot(current.before_snapshot_id,current.focus);ensureCurrent();
      if(state.id!==current.before_snapshot_id||state.analysis?.focus!==current.focus)throw Error('工作空间在准备期间发生切换，请重新开始本场。');
      caseInfo=current;lockedSource=state.analysis;lockedAnalysis=JSON.parse(JSON.stringify(lockedSource));contextBroken=false;
      mode=nextMode;step=saved?.step||(flows[mode].includes(options.step)?options.step:options.entry==='free'?2:0);selectedPath=0;
      window.lianzhengTaskCompare?.configure?.({mode:options.entry==='free'?'free':'fixed',phase:'before',task_id:'before-occurrences',reset:true,expected_case_hash:current.bundle_sha256});
      window.lianzhengCaseDecisions?.reset?.();
      if(!dialog.open){priorFocus=document.activeElement;priorOverflow=document.body.style.overflow;document.body.style.overflow='hidden';dialog.showModal();}
      find('.presenter-status').textContent=saved?'已恢复导航位置；问题、答案与模型开关未保存。':'方向键切换，Esc 返回准备面板。切换步骤不会自动调用模型。';
      render({focus:true});return publicState();
    }finally{if(serial===startSerial)busyStart=false;window.dispatchEvent(new CustomEvent('lianzheng-presentation-changed',{detail:publicState()}));}
  }
  function open(){window.lianzhengDemoHub?.open?.();}
  function reopen(){
    if(dialog.open)return;
    if(!caseInfo||!lockedAnalysis||contextBroken||state.analysis!==lockedSource)throw Error('本页没有可继续的同一案例资料，请恢复服务后重新核对。');
    priorFocus=document.activeElement;priorOverflow=document.body.style.overflow;document.body.style.overflow='hidden';dialog.showModal();
    find('.presenter-status').textContent='继续本页此前载入的已核对资料；当前服务状态未复查，新请求可能不可用。';render({focus:true});
  }
  function close(){if(dialog.open)dialog.close();}
  function go(index){if(!activeFlow().includes(index)||busyStart)return;step=index;render({focus:true});}
  async function restart(recover=false){
    if(busyStart)return;
    const button=find(`[data-presenter-action="${recover?'recover':'restart'}"]`);if(button)button.disabled=true;
    try{await start({mode,step:recover?step:0});}
    catch(error){find('.presenter-status').textContent=error.message;}
    finally{if(button)button.disabled=false;}
  }
  async function fullscreen(){
    const button=find('[data-presenter-action="fullscreen"]');
    try{if(document.fullscreenElement===dialog)await document.exitFullscreen();else if(dialog.requestFullscreen)await dialog.requestFullscreen();else throw Error();}
    catch{find('.presenter-status').textContent='当前为铺满页面的讲解模式；浏览器系统全屏未启用。';}
    button.textContent=document.fullscreenElement===dialog?'退出浏览器全屏':'浏览器全屏';
  }
  dialog.addEventListener('click',event=>{
    const button=event.target.closest('button');if(!button||!dialog.contains(button))return;
    if(button.dataset.presenterStep!==undefined){go(Number(button.dataset.presenterStep));return;}
    if(button.dataset.presenterPath!==undefined){selectedPath=Number(button.dataset.presenterPath);render();find(`[data-presenter-path="${selectedPath}"]`)?.focus({preventScroll:true});return;}
    const flow=activeFlow(),position=flow.indexOf(step);
    switch(button.dataset.presenterAction){
      case 'close':close();break;
      case 'previous':go(flow[position-1]);break;
      case 'next':if(position===flow.length-1)close();else go(flow[position+1]);break;
      case 'fullscreen':fullscreen();break;
      case 'restart':restart();break;
      case 'recover':restart(true);break;
      case 'review-answer':go(2);break;
    }
  });
  dialog.addEventListener('keydown',event=>{
    if(event.target.closest('input,textarea,select,[contenteditable="true"]')||event.altKey||event.ctrlKey||event.metaKey)return;
    const flow=activeFlow(),position=flow.indexOf(step);
    if(event.key==='ArrowRight'){event.preventDefault();go(flow[position+1]);}
    if(event.key==='ArrowLeft'){event.preventDefault();go(flow[position-1]);}
  });
  dialog.addEventListener('close',()=>{
    ++startSerial;busyStart=false;releaseSimulation();document.body.style.overflow=priorOverflow;
    if(document.fullscreenElement===dialog)document.exitFullscreen().catch(()=>{});
    if(priorFocus?.isConnected)priorFocus.focus({preventScroll:true});else document.getElementById('open-demo')?.focus({preventScroll:true});
    window.dispatchEvent(new CustomEvent('lianzheng-presentation-changed',{detail:publicState()}));
  });
  document.addEventListener('fullscreenchange',()=>{find('[data-presenter-action="fullscreen"]').textContent=document.fullscreenElement===dialog?'退出浏览器全屏':'浏览器全屏';});
  window.addEventListener('lianzheng-snapshot-changed',()=>{
    if(dialog.open&&!busyStart&&state.analysis!==lockedSource){contextBroken=true;find('.presenter-status').textContent='工作空间已变化，已暂停讲解，等待重新核对。';render({focus:true});}
  });
  window.addEventListener('lianzheng-task-comparison-changed',()=>{if(dialog.open&&step===6&&!contextBroken)render();});
  window.addEventListener('lianzheng-decisions-changed',event=>{
    if(dialog.open&&caseInfo&&event.detail?.bundle_sha256!==caseInfo.bundle_sha256){contextBroken=true;find('.presenter-status').textContent='方案材料与本场案例校验值不同，已暂停讲解。';render({focus:true});}
  });
  window.lianzhengPresenter={open,start,reopen,close,state:publicState};
})();
