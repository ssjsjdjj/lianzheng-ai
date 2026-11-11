'use strict';
(() => {
  const button=document.createElement('button');button.type='button';button.className='button secondary';button.textContent='真实修复案例';
  document.querySelector('.heading-actions').append(button);
  const panel=document.createElement('section');panel.id='real-case-panel';panel.className='panel real-case-panel';panel.hidden=true;panel.setAttribute('aria-label','真实修复案例');
  document.querySelector('main').append(panel);
  let data=null,serial=0,loading=false,lastError='';
  const esc=escapeHTML;
  function render(error=lastError) {
    const c=data;
    panel.innerHTML=`<div class="panel-heading"><div><span class="case-eyebrow">REPRODUCIBLE CASE</span><h2>${esc(c?.title||'真实修复案例')}</h2><p>固定上游来源 → 实际依赖更新 → 冻结公告证据 → 测试记录</p></div><button type="button" class="button secondary" data-case-close>收起案例</button></div>`;
    if(error)panel.insertAdjacentHTML('beforeend',`<p class="case-alert" role="alert">${esc(error)}</p>`);
    if(!c?.available){panel.insertAdjacentHTML('beforeend',`<p class="case-boundary">${loading?'正在核对案例文件与来源…':esc(c?.limitations?.join(' ')||'案例暂未载入。')}</p><button type="button" class="button secondary" data-case-refresh>刷新案例</button>`);bind();return;}
    const v=c.verification||{},tests=c.tests||{};
    const source=safeURL(c.source?.url);
    const metric=(title,value)=>`<div class="case-metric"><span>${esc(title)}</span><strong>${Number.isInteger(value)?value:'未记录'}</strong><small>目标公告匹配位置 · 冻结实验记录</small></div>`;
    const phaseLabels={before:'修复前',partial:'仅更新直接依赖',after:'最终依赖更新后'};
    const testRows=Object.entries(tests).filter(([phase,t])=>Object.hasOwn(phaseLabels,phase)&&t&&typeof t==='object').map(([phase,t])=>`<article class="case-test"><h3>${phaseLabels[phase]} · ${t.exit_code===0?'命令成功':t.exit_code==null?'未记录退出码':'命令未通过'}</h3><code>${esc(t.command)}</code><p>${esc(t.summary||'详细范围见原始测试日志。')}</p>${t.scope?`<p>${esc(t.scope)}</p>`:''}<small>退出码：${esc(t.exit_code??'未知')}。命令成功不等于所有业务场景已验证。</small></article>`).join('');
    panel.insertAdjacentHTML('beforeend',`<div class="case-source"><span class="pill teal">公开源码 · 本地修复实验</span><p>${source!=='#'?`<a href="${esc(source)}" target="_blank" rel="noopener noreferrer">查看上游来源 ↗</a>`:''} <span>许可证：${esc(c.source?.license||'见许可证文件')}</span></p><code>固定提交 ${esc(c.source?.commit||'未记录')}</code><p>目标公告 <strong>${esc(c.focus)}</strong> · ${esc(c.target?.package)}</p></div>
      <div class="case-metrics">${metric('修复前',v.target_before_count)}${Number.isInteger(v.target_partial_count)?metric('只更新直接依赖后',v.target_partial_count):''}${metric('最终依赖更新后',v.target_after_count)}</div>
      <p class="case-boundary">${esc(c.note)} ${v.comparison_complete?'该固定输入的图结构和精确版本查询覆盖完整。':'清单存在缺边或未查询项；目标匹配数下降不等于完整风险已消除。'}</p>
      ${c.current&&!c.current.basis_matches_recorded?'<p class="case-alert" role="status">当前工作空间的扫描依据已变化。上方数字属于冻结实验，不能替代当前扫描结果；重新载入不会覆盖已有扫描。</p>':''}
      <div class="case-actions"><button type="button" class="button primary" data-case-prepare ${loading?'disabled':''}>${loading?'载入中…':c.prepared?'已载入 · 查看修复前':'载入真实案例'}</button>${c.prepared?`<button type="button" class="button secondary" data-case-phase="before">查看修复前</button>${c.partial_snapshot_id?'<button type="button" class="button secondary" data-case-phase="partial">查看仅直接依赖修复</button>':''}<button type="button" class="button secondary" data-case-phase="after">查看实际修复后</button><button type="button" class="button secondary" data-case-compare>比较实际前后清单</button>`:''}<button type="button" class="button secondary" data-case-refresh>刷新案例状态</button></div>
      <p class="case-muted">载入不会安装软件、执行上游代码、联网扫描或请求模型。当前工作空间与案例导入均保留原始锁文件。</p>
      <h3 class="case-subheading">实际测试命令与执行范围</h3><div class="case-test-grid">${testRows||'<p>尚无测试记录。</p>'}</div>
      <details class="case-details"><summary>查看来源文件、测试日志和 SHA-256（${c.files.length} 份）</summary><div class="case-files">${c.files.map(f=>`<a href="${esc(f.url)}" download><strong>${esc(f.label||f.name)} ↓</strong><span>${esc(f.name)}</span><code>${esc(f.sha256)}</code></a>`).join('')}</div></details>
      <details class="case-details"><summary>实验边界与尚待确认事项</summary><ul>${(c.limitations||[]).map(x=>`<li>${esc(x)}</li>`).join('')}</ul></details>`);
    bind();
  }
  function bind(){
    panel.querySelector('[data-case-close]')?.addEventListener('click',()=>{panel.hidden=true;button.focus();});
    panel.querySelector('[data-case-refresh]')?.addEventListener('click',()=>read().catch(()=>{}));
    panel.querySelector('[data-case-prepare]')?.addEventListener('click',()=>prepare().catch(()=>{}));
    panel.querySelectorAll('[data-case-phase]').forEach(b=>b.addEventListener('click',()=>view(b.dataset.casePhase).catch(e=>toast(e.message))));
    panel.querySelector('[data-case-compare]')?.addEventListener('click',()=>compare().catch(e=>toast(e.message)));
  }
  function publish(){window.dispatchEvent(new CustomEvent('lianzheng-case-loaded',{detail:data}));}
  async function read(){const ticket=++serial;loading=true;lastError='';render();try{
    const result=await api('/api/real-case');if(ticket!==serial)return null;data=result;publish();return data;
  }catch(error){if(ticket!==serial)return null;lastError=error.message;throw error;
  }finally{if(ticket===serial){loading=false;render();}}}
  async function view(phase){
    if(!data?.prepared||!['before','partial','after'].includes(phase))return;
    const target=data[phase+'_snapshot_id'];if(!target)return;
    const ticket=++serial,expected=state.request+1;loading=false;lastError='';render();
    try{await selectSnapshot(target,phase==='after'?null:data.focus);
      if(ticket===serial&&state.request===expected&&state.id===target)changeView('graph');
    }catch(error){if(ticket===serial&&state.request===expected)throw error;}
  }
  async function compare(){
    if(!data?.prepared)return;
    const ticket=++serial,selection=state.request,before=data.before_snapshot_id,after=data.after_snapshot_id;
    loading=false;lastError='';render();
    try{await loadSnapshots();if(ticket!==serial||state.request!==selection)return;
      $('#compare-before').value=before;$('#compare-after').value=after;changeView('compare');$('#compare-form').requestSubmit();
    }catch(error){if(ticket===serial&&state.request===selection)throw error;}
  }
  async function prepare(){const ticket=++serial,selection=state.request;loading=true;lastError='';render();try{
    const result=await api('/api/real-case/prepare',{method:'POST'});if(ticket!==serial)return;data=result;
    await loadSnapshots();if(ticket!==serial)return null;
    if(state.request===selection)await selectSnapshot(data.before_snapshot_id,data.focus);
    if(ticket!==serial)return null;publish();return data;
  }catch(error){if(ticket!==serial)return null;lastError=error.message;throw error;
  }finally{if(ticket===serial){loading=false;render();}}}
  async function open(){const selection=state.request;panel.hidden=false;try{
    const result=await read();if(result&&!panel.hidden&&state.request===selection)panel.scrollIntoView({behavior:'smooth',block:'start'});return result;
  }catch{return null;}}
  button.addEventListener('click',open);
  window.lianzhengRealCase={open,prepare,state:()=>data,refresh:read};
})();
