/* One competition entry; legacy synthetic workflows remain explicitly secondary. */
(()=>{
  'use strict';
  const launch=document.createElement('button');launch.id='open-demo';launch.type='button';launch.className='button primary';launch.textContent='参赛演示';
  document.querySelector('.heading-actions').prepend(launch);
  const panel=document.createElement('section');panel.id='demo-hub';panel.className='demo-hub';panel.hidden=true;panel.setAttribute('aria-label','统一参赛演示准备');
  panel.innerHTML=`<div class="demo-hub-heading"><div><span class="demo-hub-eyebrow">ONE CASE · LIVE EVIDENCE</span><h2>从一个真实问题，走到可核查的处理方案</h2><p>整场围绕 http-server 的同一份实验材料。选择节奏，核对准备状态，再开始讲解。</p></div><button type="button" class="text-button" data-hub-close>收起准备</button></div>
    <div class="demo-hub-formats"><article><span>90 秒 · 4 步</span><h3>快速说明价值</h3><p>项目来源 → 任务对照 → 实际方案 → 证据交付</p><button type="button" class="button primary" data-hub-start="quick">开始精简讲解</button></article><article><span>3 分钟 · 7 步</span><h3>完整展示判断过程</h3><p>加入原文路径、交互推演与失败修复时间线</p><button type="button" class="button primary" data-hub-start="full">开始完整讲解</button></article><article><span>现场挑战</span><h3>让评委提出新问题</h3><p>限定当前案例与阶段，结论可以逐条展开核对</p><button type="button" class="button secondary" data-hub-free>进入现场自由提问</button></article></div>
    <div class="demo-hub-project"><div><strong>换成你自己的项目</strong><p>导入依赖清单后直接提问；回答、原文和路径只引用选中的项目快照。</p></div><div><button type="button" class="button secondary" data-hub-import>导入项目清单</button><button type="button" class="button primary" data-hub-project>提问当前项目</button><button type="button" class="button secondary" data-hub-project-present>讲解当前项目 · 4 步</button></div></div>
    <div class="demo-hub-preflight"><div class="demo-hub-check-heading"><div><h3>演示预检</h3><p>只检查本机状态和公开材料；不发送模型请求，也不验证服务商余额。</p></div><button type="button" class="button secondary" data-hub-check>运行本机预检</button></div><div data-hub-checks role="status"></div></div>
    <div class="demo-hub-recovery"><div><strong>从上次停下的位置继续</strong><p data-hub-resume-note>本标签页只保存案例校验值、讲解档位与步骤；不保存现场问题或答案。</p></div><div><button type="button" class="button secondary" data-hub-resume disabled>恢复上次讲解</button><button type="button" class="button secondary" data-hub-cached hidden>继续本页已载入资料</button></div></div>
    <p class="demo-hub-status" data-hub-status role="status">开始讲解会载入已校验的案例快照，不会重跑测试或覆盖已有记录。</p>
    <details class="demo-hub-legacy"><summary>构造样例与历史模型验收</summary><p>以下是旧版人为构造的业务拓扑，独立于上方真实案例主线。模型步骤需手动触发并可能计费。</p><div id="legacy-demo-host"></div></details>`;
  document.querySelector('.snapshot-toolbar').before(panel);
  let preflight=null,checkError='',checking=false,starting=false,ticket=0;
  const find=s=>panel.querySelector(s),esc=escapeHTML;
  function render(){
    const ps=window.lianzhengPresenter?.state?.(),saved=ps?.saved;
    const mismatch=Boolean(saved&&preflight?.case?.bundle_sha256&&saved.case_hash!==preflight.case.bundle_sha256);
    const labels={pass:'已通过',warn:'需留意',fail:'未通过'};
    find('[data-hub-check]').disabled=checking||starting;find('[data-hub-check]').textContent=checking?'正在检查本机…':'重新运行本机预检';
    find('[data-hub-checks]').innerHTML=checkError?`<p class="demo-hub-error" role="alert">${esc(checkError)}</p><p>可重新预检；已经载入本页的材料可以明确作为此前记录继续讲解。</p>`:preflight?
      `<div class="demo-hub-check-summary"><strong>${preflight.offline_ready?'离线主线已就绪':'请先处理未通过项'}</strong><span>本机检查 ${esc(dateLabel(preflight.checked_at))} · 新增模型调用 ${preflight.model_calls??0}</span></div><div class="demo-hub-check-grid">${(preflight.checks||[]).map(c=>`<div class="demo-check ${['pass','warn','fail'].includes(c.status)?c.status:'warn'}"><span>${esc(labels[c.status]||'待核对')}</span><strong>${esc(c.label)}</strong><p>${esc(c.detail)}</p></div>`).join('')}</div><p class="demo-hub-model-note">模型配置与既有连接验证只反映本机记录，当前远端可用性未探测。新问答是否可用仍以实际返回为准。</p>`:
      `<p>${checking?'正在核对服务、案例文件与本地调用限制…':'尚未运行预检。打开此面板不会调用模型。'}</p>`;
    panel.querySelectorAll('[data-hub-start],[data-hub-free]').forEach(button=>button.disabled=starting||checking||preflight?.offline_ready===false);
    find('[data-hub-resume]').disabled=starting||checking||!saved||mismatch||preflight?.offline_ready===false;
    find('[data-hub-resume-note]').textContent=mismatch?'案例校验值已变化，旧进度不能恢复，请从头开始。':saved?`可恢复${saved.mode==='quick'?'精简':'完整'}讲解的已保存步骤。恢复会重新核对案例；问题、答案与模型开关均不保存。`:'本标签页只保存案例校验值、讲解档位与步骤；不保存现场问题或答案。';
    find('[data-hub-cached]').hidden=!checkError||!ps?.case_hash||ps?.context_broken;
    find('[data-hub-cached]').disabled=starting||checking;
    panel.setAttribute('aria-busy',String(checking||starting));
  }
  async function check(){
    if(checking)return;checking=true;checkError='';const serial=++ticket;render();
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),10000);
    try{const response=await api('/api/demo/preflight',{signal:controller.signal});if(serial!==ticket)return;preflight=response;}
    catch(error){if(serial!==ticket)return;preflight=null;checkError=error.name==='AbortError'?'本机预检超时，请确认服务运行后重试。':'暂时无法取得本机预检，请确认服务运行后重试。';}
    finally{clearTimeout(timer);if(serial===ticket){checking=false;render();}}
  }
  async function start(options){
    if(starting||checking)return;starting=true;find('[data-hub-status]').textContent='正在核对并准备同一份真实案例；没有发送模型请求。';render();
    try{if(!window.lianzhengPresenter?.start)throw Error('讲解组件尚未加载，请刷新页面后重试。');await window.lianzhengPresenter.start(options);find('[data-hub-status]').textContent='本场已准备。重置或恢复只影响讲解状态，历史问答与用户记录保留。';}
    catch(error){find('[data-hub-status]').textContent=error.message||'准备失败，请重新预检后再试。';}
    finally{starting=false;render();}
  }
  function open(){panel.hidden=false;render();panel.scrollIntoView({behavior:'smooth',block:'start'});if(!preflight&&!checking)check();}
  launch.addEventListener('click',open);
  find('[data-hub-close]').addEventListener('click',()=>{panel.hidden=true;launch.focus();});
  find('[data-hub-check]').addEventListener('click',check);
  panel.querySelectorAll('[data-hub-start]').forEach(b=>b.addEventListener('click',()=>start({mode:b.dataset.hubStart})));
  find('[data-hub-free]').addEventListener('click',()=>start({mode:'full',entry:'free'}));
  find('[data-hub-import]').addEventListener('click',()=>document.getElementById('open-import').click());
  find('[data-hub-project]').addEventListener('click',async()=>{
    try{if(!state.id||state.switchingSnapshot)throw Error('请先选择或导入一份项目快照。');const current=window.lianzhengTaskCompare.state();if(current.scope==='snapshot'&&current.snapshot_id===state.id)await window.lianzhengTaskCompare.open();else await window.lianzhengTaskCompare.open({scope:'snapshot',snapshot_id:state.id,mode:'free'});}
    catch(error){toast(error.message||'当前项目尚未就绪，请重新选择快照。');}
  });
  find('[data-hub-project-present]').addEventListener('click',()=>{
    try{if(!window.lianzhengProjectPresenter?.start)throw Error('当前项目讲解组件尚未加载，请刷新页面后重试。');window.lianzhengProjectPresenter.start();}
    catch(error){find('[data-hub-status]').textContent=error.message||'当前项目尚未就绪，请返回问答核对资料。';}
  });
  find('[data-hub-resume]').addEventListener('click',()=>start({resume:true}));
  find('[data-hub-cached]').addEventListener('click',()=>{
    try{window.lianzhengPresenter?.reopen?.();}catch(error){find('[data-hub-status]').textContent=error.message;}
  });
  window.addEventListener('lianzheng-presentation-changed',render);
  window.lianzhengDemoHub={open,check,state:()=>({preflight,checking,starting,error:checkError})};
  render();
})();

(()=>{
  const panel=document.createElement('section');panel.className='demo-panel legacy-demo-panel';panel.setAttribute('aria-label','构造样例与历史模型验收');
  panel.innerHTML='<h2>构造业务流程样例</h2><div class="demo-readiness" aria-live="polite"><span id="demo-data-state">资料待载入</span><span id="demo-model-state">读取 API 状态中</span><span id="demo-answer-state">本次模型回答 0 次</span></div><div class="demo-steps"><button id="prepare-demo">载入演示资料</button><button data-demo-step="1" disabled>1 查看两条路径</button><button id="demo-local-answer" disabled>本地证据讲解</button><button data-demo-step="2" disabled>2 模型证据问答</button><button data-demo-step="3" disabled>3 多轮迁移追问</button><button data-demo-step="4" disabled>4 只修一条路径</button><button data-demo-step="5" disabled>5 完整修复对比</button><button id="download-demo" disabled>导出演示报告 ↓</button></div><p class="demo-note" id="demo-note">固定的真实 OSV 记录与人为构造的业务拓扑用于展示流程。无 API Key 时，可先讲解图谱、本地证据和修复对比；模型步骤需要实际调用成功。</p>';
  document.getElementById('legacy-demo-host').append(panel);
  let demo=null,modelConfig=state.model,completed=new Set(),accepted=new Map(),running=false;
  function readiness(){
    $('#demo-data-state').textContent=demo?'演示资料已就绪':'资料待载入';
    $('#demo-data-state').classList.toggle('ready',Boolean(demo));
    const verified=Boolean(modelConfig?.verified);
    const provider=modelConfig?.provider==='openai'?'GPT API':modelConfig?.provider==='deepseek'?'DeepSeek API':modelConfig?.provider==='local'?'本地 API':'兼容 API';
    $('#demo-model-state').textContent=verified?`${provider} 连接已验证`:'API 尚未验证 · 可先演示本地流程';
    $('#demo-model-state').classList.toggle('ready',verified);
    $('#demo-answer-state').textContent=`本次通过引用核验的模型回答 ${accepted.size} 次`;
    $('#demo-answer-state').classList.toggle('ready',accepted.size>0);
    $('[data-demo-step="2"]').textContent=modelConfig?.provider==='openai'?'2 GPT 证据问答':'2 模型证据问答';
    panel.querySelectorAll('[data-demo-step]').forEach(button=>{
      const done=completed.has(Number(button.dataset.demoStep));button.classList.toggle('complete',done);
      button.setAttribute('aria-label',button.textContent+(done?'，本次已完成':''));
    });
  }
  function lock(value){
    running=value;
    panel.querySelectorAll('[data-demo-step],#demo-local-answer').forEach(button=>button.disabled=value||!demo);
    $('#prepare-demo').disabled=value;$('#download-demo').disabled=!demo;
  }
  async function useInitial(){
    if(state.id!==demo.initial||state.analysis.focus!==demo.focus)await selectSnapshot(demo.initial,demo.focus);
  }
  $('#prepare-demo').addEventListener('click',()=>busy($('#prepare-demo'),'载入中…',async()=>{
    if(state.pendingQuestion)throw new Error('请先等待当前问答结束，或点击“停止等待”。');
    demo=await api('/api/demo/prepare',{method:'POST',body:'{}'});completed=new Set();accepted=new Map();
    await loadSnapshots();await selectSnapshot(demo.initial,demo.focus);
    const health=await api('/api/health');modelConfig=health.model||modelConfig;
    lock(false);readiness();
    $('#demo-note').textContent='资料已载入。本次完成标记从零开始，已有项目和问答仍保留。可按图谱 → 模型问答 → 追问 → 部分修复 → 完整修复演示，也可先使用本地证据讲解。';
  }));
  $('#demo-local-answer').addEventListener('click',async()=>{
    if(!demo||running)return;lock(true);
    try{
      if(state.pendingQuestion)throw new Error('请先等待当前问答结束，或点击“停止等待”。');
      await useInitial();newConversation();$('#use-model').checked=false;changeView('questions');
      $('#question').value='这个漏洞通过哪些路径进入项目？只升级报表组件够吗？';
      const answer=await askQuestion();
      if(!answer)throw new Error('尚未取得本地证据回答，请查看问答区的提示。');
      $('#demo-note').textContent='本地证据讲解已完成：图计算事实与公告原文已关联。本步没有请求聊天模型，也不会计为已完成模型验收。';
    }catch(error){toast(error.message);$('#demo-note').textContent=error.message;}
    finally{lock(false);readiness();}
  });
  panel.querySelectorAll('[data-demo-step]').forEach(button=>button.addEventListener('click',async()=>{
    if(!demo||running)return;lock(true);
    try{
      if(state.pendingQuestion)throw new Error('请先等待当前问答结束，或点击“停止等待”。');
      const step=Number(button.dataset.demoStep);
      if(step===1){await useInitial();changeView('graph');}
      if(step===2||step===3){
        const health=await api('/api/health');modelConfig=health.model||modelConfig;readiness();
        if(!health.llm_verified){$('#open-model-settings').click();throw new Error('请先填写 API Key 并通过连接验证。无密钥时可继续图谱、本地证据讲解和修复对比。');}
        await useInitial();
        if(step===2)newConversation();
        if(step===3&&(!completed.has(2)||!state.parentId||state.lastAnswerReplay))throw new Error('请先在本次演示完成第 2 步，再继续模型追问。历史回放不计为本次调用。');
        $('#use-model').checked=true;changeView('questions');
        const prompt=step===2?'这个漏洞通过哪些路径进入项目？请结合证据解释为什么只升级报表组件可能不够。':`那升级到 ${demo.target_version} 时，迁移文档要求检查哪些内容？`;
        $('#question').value=prompt;const answer=await askQuestion();
        if(!answer||answer.question!==prompt||answer.generation!=='model-assisted')throw new Error('尚未取得通过引用核验的模型回答；请查看问答区的回退原因后重试。');
      }
      if(step===4||step===5){
        $('#compare-before').value=demo.initial;$('#compare-after').value=step===4?demo.partial:demo.resolved;
        changeView('compare',false);const comparison=await runCompare();
        if(!comparison)throw new Error('快照比较尚未完成，请查看提示后重试。');
      }
      completed.add(step);panel.querySelectorAll('[data-demo-step]').forEach(b=>b.classList.toggle('active',b===button));readiness();
      $('#demo-note').textContent=`第 ${step} 步已执行。图谱和比较来自清单计算；模型回答计数只包含本次收到并通过引用核验的回答，不能替代独立效果评测。`;
    }catch(error){toast(error.message);$('#demo-note').textContent=error.message;}
    finally{lock(false);readiness();}
  }));
  window.addEventListener('lianzheng-model-updated',event=>{modelConfig=event.detail;readiness();});
  window.addEventListener('lianzheng-answer-rendered',event=>{
    const {answer,replayed}=event.detail;
    if(!demo||replayed||answer.facts?.snapshot_id!==demo.initial||answer.generation!=='model-assisted')return;
    const meta=answer.model_explanation?.metadata;
    accepted.set(answer.id||meta?.request_id||answer.created+answer.question,answer);readiness();
  });
  $('#download-demo').addEventListener('click',()=>{window.location.href='/api/demo/report';});
  readiness();
})();
