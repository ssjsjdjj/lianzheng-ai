'use strict';
(() => {
  const esc=escapeHTML,instances=new Map();let nextId=0,data=null,loading=false,error='',serial=0;
  let from='before',to='after';
  const launch=document.createElement('button');launch.type='button';launch.className='button secondary';launch.textContent='方案与时间线';
  document.querySelector('.heading-actions').append(launch);
  const panel=document.createElement('section');panel.id='case-decisions-panel';panel.className='panel decisions-panel';panel.hidden=true;
  panel.setAttribute('aria-label','实际处理方案与修复时间线');document.querySelector('main').append(panel);
  const labels={before:'原始基线',partial:'方案 A · 仅直接依赖',after:'方案 B · 继续处理测试工具'};
  const scopeLabel={direct:'直接依赖',transitive:'已知间接依赖',unknown:'关系未知'};
  const changeLabel={added:'新增位置',removed:'移除位置',updated:'位置记录变化'};
  function fileLink(file,label){return file?.url?`<a href="${esc(file.url)}" download>${esc(label||file.name)} ↓</a>`:'';}
  function testSummary(test){return test?`${test.passing} 通过 · ${test.pending} 既有跳过 · ${test.failing} 失败`:'未记录';}
  function metric(label,value){return `<div class="decision-metric"><span>${esc(label)}</span><strong>${esc(value??'未知')}</strong></div>`;}
  function source(){return `<div class="decisions-source"><span class="decisions-tag">固定案例 · 实验记录回放</span><span>${esc(data.source.repository)} / ${esc(data.source.tag)}</span><code>${esc(data.source.commit)}</code></div>`;}
  function planCards(){
    const before=data.plans.find(p=>p.id==='before');
    return `<p class="decisions-baseline">原始基线：目标公告 <strong>${before.target_count}</strong> 个匹配位置；${before.components} 个组件位置。以下均为实际生成的处理结果。</p><div class="decision-cards">${data.plans.filter(p=>p.id!=='before').map(plan=>{
      const c=data.baseline_comparisons.find(x=>x.to_phase===plan.id),chosen=to===plan.id;
      return `<article class="decision-card ${chosen?'selected':''}"><div class="decision-card-heading"><span>${plan.id==='partial'?'A':'B'}</span><div><h3>${esc(plan.label)}</h3><p>${esc(plan.note)}</p></div></div><div class="decision-metrics">${metric('目标匹配位置',`${before.target_count} → ${plan.target_count}`)}${metric('安装位置变化',c.counts.total_changed)}</div><p class="decision-test-badge ${plan.test.failing?'failed':''}">保存的测试记录：${testSummary(plan.test)}</p><p class="decision-card-note">${plan.test.modified_assertions?`${plan.test.modified_assertions} 条断言 API 已迁移；迁移前失败日志保留。`:'测试断言未修改。'} 依赖覆盖${plan.graph_complete&&!plan.unqueried?'完整':'仍有缺口'}。</p><button type="button" class="button ${chosen?'primary':'secondary'}" data-decisions-plan="${plan.id}" aria-pressed="${chosen}" ${loading?'disabled':''}>${chosen?'已选择此方案':'选择此方案查看差异'}</button></article>`;
    }).join('')}</div>`;
  }
  function diffRows(rows){return `<div class="decision-diff-list">${rows.map(row=>`<article><div><strong>${esc((row.after||row.before).name)}</strong><span>${esc(changeLabel[row.change])} · ${esc(scopeLabel[row.dependency_kind])}</span></div><p><code>${esc(row.before?.version||'—')}</code><span> → </span><code>${esc(row.after?.version||'—')}</code>${row.before?.dev||row.after?.dev?'<span class="decision-dev">含开发依赖标记</span>':''}</p><code>${esc(row.ref)}</code><small>原清单位置：${esc((row.after||row.before).locator)}</small>${row.changed_fields.length?`<small>变化字段：${esc(row.changed_fields.join('、'))}</small>`:''}</article>`).join('')}</div>`;}
  function comparison(instance){
    const c=data.selected_comparison,correct=c.from_phase===from&&c.to_phase===to;
    const selector=(name,value,label)=>`<label>${label}<select data-decisions-select="${name}" aria-label="${label}">${Object.entries(labels).map(([p,l])=>`<option value="${p}" ${value===p?'selected':''}>${l}</option>`).join('')}</select></label>`;
    const form=`<div class="decisions-selector">${selector('from',from,'比较起点')}<span>→</span>${selector('to',to,'比较终点')}<button class="button secondary" type="button" data-decisions-refresh ${loading?'disabled':''}>${loading?'读取中…':'重新核对冻结文件'}</button></div>`;
    if(!correct)return form+'<p class="decisions-notice" role="status">正在读取所选两份实际清单的差异…</p>';
    const rows=c.changes;
    const list=(name,values)=>`<div><h4>${name} <strong>${values.length}</strong></h4>${values.length?`<p>${values.map(esc).join('<br>')}</p>`:'<p>此固定比较中无此类项。</p>'}</div>`;
    const left=data.plans.find(p=>p.id===from),right=data.plans.find(p=>p.id===to);
    return form+`<section class="decision-comparison" aria-label="实际清单差异"><h3>${esc(c.from_label)} → ${esc(c.to_label)}</h3><div class="decision-counts">${metric('新增位置',c.counts.added)}${metric('移除位置',c.counts.removed)}${metric('原位置记录变化',c.counts.updated)}${metric('其中版本变化',c.counts.version_changed)}</div><p class="decisions-muted">变化位置按终点侧分类（删除项按起点侧）：${c.counts.direct} 个直接、${c.counts.transitive} 个已知间接、${c.counts.unknown} 个关系未知。目标匹配 ${c.target.before_count} → ${c.target.after_count}。</p><p class="decisions-boundary">${c.coverage.complete?'比较使用完整的已知清单与冻结查询。':'两份清单的结构覆盖存在缺口。公告未再观察到，不代表风险已经完全消除。'} 所列差异为真实安装位置记录变化，不能当作升级工作量或兼容性评分。</p><div class="decision-links">${fileLink(left.lockfile,'下载起点原始锁文件')}${fileLink(right.lockfile,'下载终点原始锁文件')}${fileLink(right.test.log,'下载终点测试日志')}</div><details class="decision-details"><summary>根项目依赖声明变化 · ${c.root_declaration_changes.length} 项</summary>${c.root_declaration_changes.length?c.root_declaration_changes.map(d=>`<p><strong>${esc(d.name)}</strong> · ${esc(d.kind)}<br><code>${esc(d.before||'未声明')}</code> → <code>${esc(d.after||'未声明')}</code></p>`).join(''):'<p>根项目声明没有变化。</p>'}</details><details class="decision-details"><summary>查看精确安装位置差异 · ${rows.length} 项</summary>${diffRows(rows.slice(0,8))}${rows.length>8?`<details class="decision-details"><summary>展开其余 ${rows.length-8} 项（保留全部位置）</summary>${diffRows(rows.slice(8))}</details>`:''}${!rows.length?'<p>这些字段没有变化；原文件仍可下载逐字节核对。</p>':''}</details><details class="decision-details"><summary>其他公告的变化 · 新观察 ${c.other_advisories.new.length} / 仍保留 ${c.other_advisories.retained.length} / 未再观察 ${c.other_advisories.no_longer_observed.length}</summary><div class="decision-advisories">${list('新观察到',c.other_advisories.new)}${list('仍保留',c.other_advisories.retained)}${list('未再观察到',c.other_advisories.no_longer_observed)}</div><p class="decisions-muted">此处不含目标公告 ${esc(data.target.advisory_id)}；均按公告 ID 去重，不是运行时可利用性判断。</p></details></section>`;
  }
  function testDetails(test){return `<code>${esc(test.command)}</code><p>${esc(test.summary)}</p><p class="decisions-muted">${esc(test.started_at||'开始时间未记录')} → ${esc(test.finished_at||'结束时间未记录')}<br>退出码 ${esc(test.exit_code)} · ${esc(test.test_files)} 个测试文件 · ${test.coverage_enabled?'含覆盖率记录':'未测覆盖率'}</p>${fileLink(test.log,'下载本次保存的完整日志')}<details class="decision-details"><summary>环境与锁文件绑定</summary><pre>${esc(JSON.stringify(test.environment,null,2))}</pre><code>锁文件 SHA-256 ${esc(test.lockfile_sha256)}</code><code>日志 SHA-256 ${esc(test.log_sha256)}</code></details>`;}
  function timeline(){
    return `<p class="decisions-boundary">这是一条已发生实验的证据时间线。此页面没有重新执行安装或测试；目标命中归零与测试通过分别核对。</p><ol class="decision-timeline">${data.timeline.map((event,index)=>`<li class="${event.test?.failing?'failed':''}"><span class="decision-step">${index+1}</span><article><div class="decision-event-heading"><div><h3>${esc(event.title)}</h3><p>${esc(labels[event.phase])} · 冻结记录目标匹配 ${event.target_count}</p></div><span class="decision-event-status">${event.test?testSummary(event.test):'两条断言 API 迁移'}</span></div>${event.time_note?`<p class="decisions-muted">${esc(event.time_note)}</p>`:`<time>${esc(event.finished_at||'时间未记录')}</time>`}<details class="decision-details"><summary>核对这一阶段的原始证据</summary>${event.updates?.length?event.updates.map(u=>`<div class="decision-update"><strong>实际更新命令</strong><code>${esc(u.command)}</code><p>${esc(u.started_at)} → ${esc(u.finished_at)} · 退出码 ${esc(u.exit_code)}</p></div>`).join(''):''}${event.test?testDetails(event.test):`<p>${esc(event.migration.reason)}</p><p>${esc(event.migration.migration)}</p><p>${esc(event.migration.version_limit)}</p><div class="decision-links">${Object.values(event.migration.files).map(f=>fileLink(f)).join('')}</div>`}</details></article></li>`).join('')}</ol>`;
  }
  function render(instance){
    const host=instance.host;host.className=instance.compact?'decisions-content decisions-compact':'decisions-content';
    let body=instance.compact?'':`<div class="panel-heading"><div><span class="decisions-eyebrow">FROM CHOICE TO EVIDENCE</span><h2>实际方案比较与修复时间线</h2><p>选择实际方案，核对剩余命中、依赖变化与测试代价</p></div><button class="button secondary" type="button" data-decisions-close>收起</button></div>`;
    if(error)body+=`<p class="decisions-error" role="alert">${esc(error)}</p>`;
    if(!data?.available){host.innerHTML=body+`<p class="decisions-notice" role="status">${loading?'正在核对冻结案例的文件与实际结果…':esc(data?.note||'尚未载入方案资料。')}</p><button class="button secondary" type="button" data-decisions-refresh ${loading?'disabled':''}>重新读取资料</button>`;bind(instance);return;}
    body+=source()+`<p class="decisions-context">始终展示固定 http-server 案例，独立于工作台当前快照。${esc(data.target.advisory_id)} · ${esc(data.note)}</p>`;
    if(!instance.compact)body+=`<div class="decisions-tabs" role="group" aria-label="方案与时间线视图"><button type="button" data-decisions-tab="plans" aria-pressed="${instance.tab==='plans'}">实际方案比较</button><button type="button" data-decisions-tab="timeline" aria-pressed="${instance.tab==='timeline'}">修复过程时间线</button></div>`;
    body+=instance.tab==='timeline'?timeline():planCards()+comparison(instance);
    const current=!loading&&data.selected_comparison.from_phase===from&&data.selected_comparison.to_phase===to;
    body+=`<div class="decision-links decisions-footer">${current?`<a href="/api/real-case/decisions/report?from_phase=${encodeURIComponent(from)}&to_phase=${encodeURIComponent(to)}" download>导出当前方案与时间线 JSON ↓</a>`:'<span>所选比较读取完成后可导出。</span>'}<span>本次模型调用 0 · 本次上游测试执行 0</span></div>`;
    host.innerHTML=body;bind(instance);
  }
  function renderAll(){for(const instance of instances.values())render(instance);}
  function bind(instance){const host=instance.host;
    host.querySelector('[data-decisions-close]')?.addEventListener('click',()=>{panel.hidden=true;launch.focus();});
    host.querySelectorAll('[data-decisions-tab]').forEach(b=>b.addEventListener('click',()=>{instance.tab=b.dataset.decisionsTab;render(instance);}));
    host.querySelectorAll('[data-decisions-plan]').forEach(b=>b.addEventListener('click',()=>{from='before';to=b.dataset.decisionsPlan;read().catch(()=>{});}));
    host.querySelectorAll('[data-decisions-refresh]').forEach(b=>b.addEventListener('click',()=>read().catch(()=>{})));
    host.querySelectorAll('[data-decisions-select]').forEach(select=>select.addEventListener('change',()=>{if(select.dataset.decisionsSelect==='from')from=select.value;else to=select.value;read().catch(()=>{});}));
  }
  async function read(){const ticket=++serial,start=from,end=to;loading=true;error='';renderAll();try{
    const result=await api(`/api/real-case/decisions?from_phase=${encodeURIComponent(start)}&to_phase=${encodeURIComponent(end)}`);
    if(ticket!==serial||from!==start||to!==end)return null;
    if(result.available&&(result.kind!=='recorded-experiment'||result.selected_comparison.from_phase!==start||result.selected_comparison.to_phase!==end))throw Error('方案响应与所选清单不一致，请重新读取。');
    data=result;window.dispatchEvent(new CustomEvent('lianzheng-decisions-changed',{detail:data}));return result;
  }catch(e){if(ticket===serial){error=e.message;data=null;}throw e;}finally{if(ticket===serial){loading=false;renderAll();}}}
  function mount(container,options={}){const id=++nextId,host=document.createElement('div');container.append(host);
    const instance={host,compact:!!options.compact,tab:options.tab==='timeline'?'timeline':'plans'};instances.set(id,instance);render(instance);
    if(!data&&!loading)read().catch(()=>{});
    return {destroy(){instances.delete(id);host.remove();},setTab(tab){instance.tab=tab==='timeline'?'timeline':'plans';render(instance);}};
  }
  let workbench=null;
  async function open(options={}){panel.hidden=false;if(!workbench)workbench=mount(panel,options);else workbench.setTab(options.tab);
    if(data&&!loading)await read().catch(()=>{});if(!panel.hidden)panel.scrollIntoView({behavior:'smooth',block:'start'});return data;}
  launch.addEventListener('click',()=>open());
  window.lianzhengCaseDecisions={open,mount,refresh:read,state:()=>data};
})();
