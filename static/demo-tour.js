(()=>{
  const open=document.createElement('button');open.id='open-demo';open.className='button secondary';open.textContent='▷ 参赛演示';
  document.querySelector('.heading-actions').prepend(open);
  const panel=document.createElement('section');panel.className='demo-panel hidden';panel.innerHTML='<h2>参赛演示流程</h2><div class="demo-steps"><button id="prepare-demo">载入演示资料</button><button data-demo-step="1" disabled>1 查看两条路径</button><button data-demo-step="2" disabled>2 真实模型问答</button><button data-demo-step="3" disabled>3 多轮迁移追问</button><button data-demo-step="4" disabled>4 只修一条路径</button><button data-demo-step="5" disabled>5 完整修复对比</button><button id="download-demo" disabled>导出演示报告 ↓</button></div><p class="demo-note" id="demo-note">演示使用固定的真实 OSV 查询记录和人为构造的业务拓扑；不会删除已有项目和问答。真实模型步骤需要先连接模型。</p>';
  document.querySelector('.snapshot-toolbar').before(panel);
  const hide=document.createElement('button');hide.type='button';hide.className='text-button';hide.textContent='收起演示';hide.style.float='right';
  panel.querySelector('h2').append(hide);hide.addEventListener('click',()=>panel.classList.add('hidden'));
  let demo=null;
  open.addEventListener('click',()=>panel.classList.toggle('hidden'));
  document.querySelector('#prepare-demo').addEventListener('click',()=>busy(document.querySelector('#prepare-demo'),'载入中…',async()=>{
    demo=await api('/api/demo/prepare',{method:'POST',body:'{}'});
    await loadSnapshots();await selectSnapshot(demo.initial,demo.focus);
    panel.querySelectorAll('[data-demo-step],#download-demo').forEach(button=>button.disabled=false);
    document.querySelector('#demo-note').textContent='演示资料已载入。迁移说明标为人为样例；模型调用成功与否以实际回答为准。';
  }));
  panel.querySelectorAll('[data-demo-step]').forEach(button=>button.addEventListener('click',async()=>{
    if(!demo)return;
    panel.querySelectorAll('[data-demo-step]').forEach(b=>b.disabled=true);
    try{
      const step=Number(button.dataset.demoStep);
      if(step===1){await selectSnapshot(demo.initial,demo.focus);changeView('graph');}
      if(step===2||step===3){
        const health=await api('/api/health');
        if(!health.llm_verified){document.querySelector('#open-model-settings').click();throw new Error('请先在本机填写密钥并完成真实连接验证。');}
        if(state.id!==demo.initial||state.analysis.focus!==demo.focus)await selectSnapshot(demo.initial,demo.focus);
        if(step===2)newConversation();
        $('#use-model').checked=true;changeView('questions');
        const prompt=step===2?'这个漏洞通过哪些路径进入项目？请结合证据解释为什么只升级报表组件可能不够。':`那升级到 ${demo.target_version} 时，迁移文档要求检查哪些内容？`;
        if(step===3&&!state.parentId)throw new Error('请先完成第 2 步，再进行多轮追问。');
        $('#question').value=prompt;await askQuestion();
        if(!state.lastAnswer||state.lastAnswer.question!==prompt||state.lastAnswer.generation!=='model-assisted')throw new Error('尚未取得通过引用校验的模型回答；请查看当前错误提示后重试。');
      }
      if(step===4||step===5){
        $('#compare-before').value=demo.initial;$('#compare-after').value=step===4?demo.partial:demo.resolved;
        changeView('compare',false);await runCompare();
      }
      panel.querySelectorAll('[data-demo-step]').forEach(b=>b.classList.toggle('active',b===button));
      $('#demo-note').textContent=`第 ${step} 步已执行；报告保留真实调用元数据和当前证据。模型校验不是独立准确率评测。`;
    }catch(error){toast(error.message);$('#demo-note').textContent=error.message;}
    finally{panel.querySelectorAll('[data-demo-step]').forEach(b=>b.disabled=false);}
  }));
  $('#download-demo').addEventListener('click',()=>{window.location.href='/api/demo/report';});
})();
