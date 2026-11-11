'use strict';
(() => {
  const labels={pending:'待人工复核',supported:'支持',partial:'部分支持',insufficient:'证据不足',conflict:'来源冲突'};
  let generation=0;

  window.addEventListener('lianzheng-answer-rendered',event=>{
    const answer=event.detail?.answer;
    const snapshot=answer?.facts?.snapshot_id;
    const serial=++generation;
    const elements=[...document.querySelectorAll('#answer .model-claim')];
    if(!answer?.id||!snapshot||!elements.length)return;
    const current=()=>serial===generation&&state.id===snapshot&&state.lastAnswer?.id===answer.id&&elements[0].isConnected;
    const path=`/api/snapshots/${encodeURIComponent(snapshot)}/history/${answer.id}/reviews`;
    const panels=elements.map((element,index)=>{
      const panel=document.createElement('section');panel.className='claim-review';
      panel.setAttribute('aria-label',`第 ${index+1} 项结论的人工复核`);
      panel.innerHTML='<p class="claim-review-loading" role="status">读取人工复核记录…</p>';
      element.append(panel);return panel;
    });

    function render(item){
      const panel=panels[item.claim_index];
      if(!panel||!current())return;
      const id=`claim-review-${answer.id}-${item.claim_index}`;
      const review=item.review;
      const saved=review.status==='pending'?'待人工复核':`人工标记：${labels[review.status]}`;
      panel.innerHTML=`<div class="claim-review-overview"><span class="claim-literal-status ${item.literal_check.status==='matched'?'matched':'attention'}">${escapeHTML(item.literal_check.label)}</span><strong class="claim-review-badge" data-status="${escapeHTML(review.status)}">${escapeHTML(saved)}</strong></div>
        <p class="claim-review-boundary">原句存在不等于结论受到支持。请核对上方结论与摘录，再标注支持范围。</p>
        ${item.attention_points.length?`<ul class="claim-review-hints">${item.attention_points.map(h=>`<li>${escapeHTML(h)}</li>`).join('')}</ul>`:''}
        ${item.stale_review_count?'<p class="claim-review-stale">内容发生过变化，旧标注已留档；当前内容需要重新复核。</p>':''}
        <details class="claim-review-editor"><summary>复核结论与原文的支持范围</summary>
          <label for="${id}-status">第 ${item.claim_index+1} 项复核结果</label>
          <select id="${id}-status">${Object.entries(labels).map(([value,label])=>`<option value="${value}"${review.status===value?' selected':''}>${label}</option>`).join('')}</select>
          <label for="${id}-note">支持范围或疑点</label>
          <textarea id="${id}-note" rows="3" maxlength="1000" placeholder="例如：原文仅要求提供测试记录，尚不能证明测试已经通过。">${escapeHTML(review.note)}</textarea>
          <div class="claim-review-actions"><button type="button" class="button secondary claim-review-save">保存人工复核</button><button type="button" class="text-button claim-review-refresh">刷新记录</button></div>
          <p class="claim-review-save-status" role="status" aria-live="polite">${review.updated_at?'已保存于 '+escapeHTML(dateLabel(review.updated_at)):'尚未保存人工判断。'}</p>
          <p class="claim-review-boundary">记录由本机使用者填写，不代表独立专家审定；不会改写原回答或调用模型。</p>
        </details>
        ${item.event_count?`<details class="claim-review-audit"><summary>复核记录 ${item.event_count} 次${item.event_count>20?'（显示最近 20 次）':''}</summary><ol>${item.events.map(e=>`<li><strong>${escapeHTML(labels[e.status])}</strong> · ${escapeHTML(dateLabel(e.created_at))}${!e.current_content?' · 旧内容标注':''}<p>${escapeHTML(e.note||'未填写备注')}</p></li>`).join('')}</ol></details>`:''}`;
      panel.querySelector('.claim-review-refresh').addEventListener('click',()=>load(item.claim_index));
      panel.querySelector('.claim-review-save').addEventListener('click',async()=>{
        if(!current())return;
        const button=panel.querySelector('.claim-review-save');
        const status=panel.querySelector('select').value;
        const note=panel.querySelector('textarea').value;
        const statusLine=panel.querySelector('.claim-review-save-status');
        const controls=[...panel.querySelectorAll('select,textarea,button')];
        controls.forEach(control=>{control.disabled=true;});statusLine.textContent='保存中…';
        try{
          const result=await api(`${path}/${item.claim_index}`,{method:'PUT',body:JSON.stringify({status,note,fingerprint:item.fingerprint,revision:review.revision})});
          if(!current())return;
          // Keep unsaved edits to other claims intact when saving this one.
          result.claims.filter(claim=>claim.claim_index===item.claim_index).forEach(render);
          const updated=panels[item.claim_index];
          updated.querySelector('.claim-review-editor').open=true;
          updated.querySelector('.claim-review-save-status').textContent='人工复核已保存；原回答保持不变。';
        }catch(error){
          if(current()&&panel.isConnected){statusLine.textContent=error.message;controls.forEach(control=>{control.disabled=false;});}
        }
      });
    }

    async function load(onlyIndex){
      try{
        const result=await api(path);
        if(!current())return;
        result.claims.filter(item=>onlyIndex===undefined||item.claim_index===onlyIndex).forEach(render);
      }catch(error){
        if(!current())return;
        for(const [index,panel] of panels.entries()){
          if(onlyIndex!==undefined&&index!==onlyIndex)continue;
          panel.replaceChildren();
          const message=document.createElement('p');message.className='claim-review-boundary';
          message.textContent=`人工复核记录未加载：${error.message}`;
          const retry=document.createElement('button');retry.type='button';retry.className='text-button';retry.textContent='重试加载复核';
          retry.addEventListener('click',()=>load(index));panel.append(message,retry);
        }
      }
    }
    load();
  });
})();
