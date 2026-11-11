'use strict';
(()=>{
  const button=document.createElement('button');button.type='button';button.id='open-call-control';button.className='button secondary';button.textContent='用量与限制';
  document.querySelector('.heading-actions').append(button);
  const dialog=document.createElement('dialog');dialog.id='call-control-dialog';dialog.setAttribute('aria-labelledby','call-control-title');
  dialog.innerHTML=`<div class="dialog-title"><div><h2 id="call-control-title">聊天 API 用量与限制</h2><p>从 v0.6 启用起记录本应用调用，历史回放不新增调用。</p></div><button type="button" id="close-call-control" class="icon-button" aria-label="关闭用量窗口">×</button></div><div id="call-usage-summary" role="status">读取中…</div>
    <form id="call-policy-form"><label class="field-label">每日聊天调用次数<input id="daily-calls" type="number" min="1" max="1000" required></label>
    <label class="field-label">每日金额阈值（USD，可留空）<input id="daily-budget" type="number" min="0.001" max="100" step="0.001" placeholder="留空时仅限制调用次数"></label>
    <label class="call-enable"><input id="call-policy-enabled" type="checkbox">启用每日限制</label>
    <p class="dialog-note">按 UTC 日期计数，包含连接测试和失败请求。金额采用保守预留及已知费用估算；当前只为官方 GPT-6 Luna 预留金额，其他模型开启金额阈值时会被阻止。未知费用保留预留，不按零处理。此设置不是账户账单上限，不包含独立向量服务及其他应用。</p>
    <div class="dialog-actions"><button class="button secondary" type="button" id="refresh-call-usage">刷新用量</button><button class="button primary" id="save-call-policy" type="submit">保存限制</button></div></form><div id="call-policy-message" role="status" aria-live="polite"></div><div id="recent-chat-calls"></div>`;
  document.body.append(dialog);
  function show(data){
    const p=data.policy;$('#daily-calls').value=p.daily_calls;$('#daily-budget').value=p.daily_budget_usd??'';$('#call-policy-enabled').checked=p.enabled;
    $('#call-usage-summary').innerHTML=`<div class="call-usage-metrics"><div><strong>${data.calls_today} / ${p.daily_calls}</strong><span>今日请求${p.enabled?'':'（限制未启用）'}</span></div><div><strong>$${data.budget_accounted_usd.toFixed(6)}</strong><span>估算与预留占用</span></div><div><strong>${data.unknown_cost_calls}</strong><span>费用尚不完整的请求</span></div></div><p>UTC 日期：${escapeHTML(data.day_utc)} · 处理中 ${data.in_flight} 笔${data.unreserved_calls?' · 存在未能预留金额的调用':''}</p>${data.in_flight?'<p>为防止重复调用，新的聊天请求暂时受阻。停止浏览器等待不会终止服务器请求；若服务曾异常中断，请先核对请求状态。</p>':''}`;
    const labels={returned:'接口已返回',failed:'请求失败',in_flight:'处理中',uncertain:'状态待确认'};
    $('#recent-chat-calls').innerHTML='<h3>最近请求</h3>'+(data.recent.length?'<div class="call-recent-list">'+data.recent.map(r=>`<div><strong>${escapeHTML(r.model)}</strong> · ${escapeHTML(labels[r.status]||r.status)}<br><span>${escapeHTML(new Date(r.started*1000).toLocaleString())} · 输入 ${r.input_tokens??'未知'} / 输出 ${r.output_tokens??'未知'} tokens · ${r.cost_estimate==null?'费用未知'+(r.reservation==null?'':`，保留 $${r.reservation.toFixed(6)} 预留`):`估算 $${r.cost_estimate.toFixed(6)}`}</span></div>`).join('')+'</div>':'<p>尚无本版聊天调用记录。</p>');
  }
  async function refresh(){show(await api('/api/model/usage'));}
  button.addEventListener('click',async()=>{dialog.showModal();try{await refresh();}catch(e){$('#call-usage-summary').textContent=e.message;}});
  $('#close-call-control').addEventListener('click',()=>dialog.close());
  $('#refresh-call-usage').addEventListener('click',()=>busy($('#refresh-call-usage'),'读取中…',refresh));
  $('#call-policy-form').addEventListener('submit',event=>{event.preventDefault();busy($('#save-call-policy'),'保存中…',async()=>{
    const budget=$('#daily-budget').value.trim();show(await api('/api/model/usage/policy',{method:'PUT',body:JSON.stringify({daily_calls:Number($('#daily-calls').value),daily_budget_usd:budget?Number(budget):null,enabled:$('#call-policy-enabled').checked})}));$('#call-policy-message').textContent='已保存。本地阈值不改变服务商的账单设置。';
  });});
})();
