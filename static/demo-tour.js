(()=>{
  const open=document.createElement('button');open.id='open-demo';open.className='button secondary';open.textContent='▷ 参赛演示';
  document.querySelector('.heading-actions').prepend(open);
  const panel=document.createElement('section');panel.className='demo-panel hidden';panel.setAttribute('aria-label','参赛演示准备与步骤');
  panel.innerHTML='<h2>参赛演示流程</h2><div class="demo-readiness" aria-live="polite"><span id="demo-data-state">资料待载入</span><span id="demo-model-state">读取 API 状态中</span><span id="demo-answer-state">本次模型回答 0 次</span></div><div class="demo-steps"><button id="prepare-demo">载入演示资料</button><button data-demo-step="1" disabled>1 查看两条路径</button><button id="demo-local-answer" disabled>本地证据讲解</button><button data-demo-step="2" disabled>2 模型证据问答</button><button data-demo-step="3" disabled>3 多轮迁移追问</button><button data-demo-step="4" disabled>4 只修一条路径</button><button data-demo-step="5" disabled>5 完整修复对比</button><button id="download-demo" disabled>导出演示报告 ↓</button></div><p class="demo-note" id="demo-note">固定的真实 OSV 记录与人为构造的业务拓扑用于展示流程。无 API Key 时，可先讲解图谱、本地证据和修复对比；模型步骤需要实际调用成功。</p>';
  document.querySelector('.snapshot-toolbar').before(panel);
  const hide=document.createElement('button');hide.type='button';hide.className='text-button';hide.textContent='收起演示';hide.style.float='right';
  panel.querySelector('h2').append(hide);hide.addEventListener('click',()=>panel.classList.add('hidden'));
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
  open.addEventListener('click',()=>{panel.classList.toggle('hidden');readiness();});
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
