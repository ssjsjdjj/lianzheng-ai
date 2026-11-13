'use strict';
const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeURL = value => {try {const u = new URL(value); return u.protocol === 'https:' ? u.href : '#';} catch {return '#';}};
const state = {snapshots:[], id:'demo-before', analysis:null, mode:'graph', view:'overview', zoom:1, request:0,documents:[],history:[],parentId:null,turns:[],pendingQuestion:null,model:null,lastAnswerReplay:false};
let toastTimer;
function toast(message) {$('#toast').textContent = message; $('#toast').classList.add('visible'); clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('#toast').classList.remove('visible'),4500);}
async function api(path, options={}) {
  const bounded=!options.signal&&['GET','HEAD'].includes((options.method||'GET').toUpperCase());
  const controller=bounded?new AbortController():null,timer=controller?setTimeout(()=>controller.abort(),15000):null;
  try{
    const response = await fetch(path,{...options, ...(controller?{signal:controller.signal}:{}),headers:{'Content-Type':'application/json',...options.headers}});
    let result;try {result=await response.json();} catch(error) {if(error.name==='AbortError')throw error;throw new Error('服务响应无效，请检查后端日志。');}
    if (!response.ok) throw new Error(typeof result.detail==='string' ? result.detail : '请求未通过校验，请检查输入内容。');
    return result;
  }catch(error){if(controller?.signal.aborted)throw new Error('本机服务读取超时，请确认服务运行后重试。');throw error;}
  finally{if(timer)clearTimeout(timer);}
}
async function busy(button, text, action) {const old=button.textContent; button.disabled=true;button.textContent=text;try{return await action();}catch(error){toast(error.message);return null;}finally{button.disabled=false;button.textContent=old;}}
const dateLabel = value => value ? new Date(value).toLocaleString('zh-CN',{hour12:false}) : '未查询';
const sourceLabel = value => ({'frozen-osv':'冻结 OSV','frozen-case-osv':'真实案例冻结 OSV','live-osv':'实时 OSV','cached-osv':'OSV 缓存','user-document':'用户导入文档','graph-evidence':'清单图事实','none':'未查询','demo':'演示组件'}[value] || value);
const statusLabel = value => ({checked:'已查询',unscanned:'未扫描',unsupported:'身份信息不足',failed:'查询失败','demo-component':'演示构造',project:'项目根节点'}[value] || value);

async function loadSnapshots() {
  state.snapshots=await api('/api/snapshots');
  $('#snapshot-select').innerHTML=state.snapshots.map(s=>`<option value="${escapeHTML(s.id)}">${escapeHTML(s.project)} · ${escapeHTML(s.label)}</option>`).join('');
  if(!state.snapshots.some(s=>s.id===state.id)) state.id=state.snapshots[0]?.id;
  $('#snapshot-select').value=state.id;
  updateCompareOptions();
}
async function selectSnapshot(id,focus=null) {
  const serial=++state.request;
  state.switchingSnapshot=true;stopWaiting();state.lastAnswer=null;state.lastAnswerReplay=false;
  $('#answer').textContent='正在切换项目资料，旧回答已收起。';
  $('#evidence-list').innerHTML='';$('#evidence-count').textContent='0';
  state.documents=[];state.history=[];state.parentId=null;state.turns=[];renderConversation();
  $('#document-count').textContent='0';$('#history-count').textContent='0';
  $('#document-list').textContent='正在读取所选项目文档…';$('#history-list').textContent='正在读取所选项目问答记录…';
  window.dispatchEvent(new CustomEvent('lianzheng-snapshot-changing',{detail:{snapshot_id:id,request:serial}}));
  let analysis;
  try{analysis=await api('/api/snapshots/'+encodeURIComponent(id)+(focus?'?focus='+encodeURIComponent(focus):''));}
  catch(error){if(serial===state.request)window.dispatchEvent(new CustomEvent('lianzheng-snapshot-change-failed',{detail:{snapshot_id:id,request:serial}}));throw error;}
  if(serial!==state.request)return;
  state.id=id;state.analysis=analysis;state.switchingSnapshot=false;
  $('#snapshot-select').value=id;
  renderAnalysis();
  if(state.request===serial)window.dispatchEvent(new CustomEvent('lianzheng-snapshot-changed',{detail:{snapshot:state.id,analysis:state.analysis}}));
  const refreshed=await Promise.allSettled([refreshKnowledge(id,serial),refreshHistory(id,serial)]);
  if(refreshed.some(r=>r.status==='rejected')&&state.request===serial)toast('文档或历史暂时未加载，可点击刷新后重试。');
}
function metric(label,value,foot,icon,color='') {return `<article class="metric"><div class="metric-label">${label}</div><span class="metric-icon">${icon}</span><div class="metric-value ${color}">${escapeHTML(value)}</div><div class="metric-foot">${escapeHTML(foot)}</div></article>`;}
function renderAnalysis() {
  state.activePath=null;
  state.lastAnswer=null;
  state.parentId=null;state.turns=[];renderConversation();
  const a=state.analysis,s=a.stats;
  $('#sidebar-project').textContent=a.snapshot.project;
  $('#sidebar-project').title=a.snapshot.project;
  $('.project-avatar').textContent=a.snapshot.project.slice(0,1);
  $('#snapshot-count').textContent=`${state.snapshots.filter(x=>x.project===a.snapshot.project).length} 份依赖快照`;
  $('#quality-pill').textContent=a.complete?'依赖结构完整':'存在数据缺失';
  $('#quality-pill').className='pill '+(a.complete?'teal':'orange');
  const times=a.nodes.map(n=>n.fetched_at).filter(Boolean).sort();
  const origins=a.sources.filter(s=>s!=='demo').map(sourceLabel).join(' / ');
  $('#notice-text').textContent=(a.snapshot.demo?'演示项目：业务组件与依赖拓扑为构造案例；漏洞记录来自真实 OSV 查询。':'已导入本地项目清单；仅按清单中明确声明的依赖关系分析。')+` 数据来源：${origins||'无查询记录'}；${times.length?'最近获取 '+dateLabel(times.at(-1)):'尚未扫描'}。`;
  $('#metrics').innerHTML=metric('组件出现位置',s.components,'按清单位置保留，不合并同版本','◫')+
    metric('匹配漏洞公告',s.vulnerabilities,'按公告 ID 去重，非风险概率','⚑','risk')+
    metric('受影响位置',s.affected_occurrences,`${s.reachable_affected} 个从项目根节点可达`,'⌘','teal')+
    metric('未完成查询',s.unknown,`已查询 ${s.checked} 个位置`,'◷',s.unknown?'risk':'');
  $('#risk-count').textContent=s.vulnerabilities;
  renderRisks();renderGraph();renderEvidence();renderIssues();
  $('#answer').innerHTML='<div class="answer-placeholder"><span>▤</span><strong>从一个问题开始</strong><p>选择上方问题，查看路径、证据与尚待确认的信息。</p></div>';
  const uniquePaths=a.paths.length;
  const map=Object.fromEntries(a.nodes.map(n=>[n.id,n]));
  $('#path-summary').innerHTML=a.focus?`<strong>${uniquePaths} 条代表性引入路径</strong> · ${escapeHTML(a.focus)}${a.paths_truncated?' · 结果已截断，消除判断使用完整可达性计算':''}`+
    a.paths.map(p=>`<div class="path-line">${p.map(r=>escapeHTML(map[r].name)).join(' <span>→</span> ')}</div>`).join(''):
    `<strong>当前已查询数据未匹配公告</strong><div class="path-line">${a.can_confirm_absence?'只针对本次查询快照，不代表项目绝对安全。':'仍有未扫描或缺失项，不能确认漏洞已全部消除。'}</div>`;
  $('#graph-caption').textContent=a.focus?`选中公告 ${a.focus} · 点击节点查看依据`:'依赖关系图 · 已保留全部清单位置';
}
function renderRisks() {
  const a=state.analysis,query=$('#risk-search').value.trim().toLowerCase();
  const risks=a.vulnerabilities.filter(v=>(v.id+' '+v.summary+' '+v.aliases.join(' ')).toLowerCase().includes(query));
  $('#risk-list').innerHTML=risks.length?risks.map(v=>`<button class="risk-item ${v.id===a.focus?'selected':''}" data-risk="${escapeHTML(v.id)}"><div class="risk-item-top"><span class="severity ${escapeHTML(v.severity)}">${escapeHTML(v.severity)}</span><span class="risk-package">${escapeHTML(v.package)}</span></div><div class="risk-title">${escapeHTML(v.summary)}</div><div class="risk-id">${escapeHTML(v.id)}</div><div class="risk-bottom"><span>${a.findings.filter(x=>x.id===v.id).length} 个匹配位置</span><span class="risk-arrow">↗</span></div></button>`).join(''):
    `<div class="empty-state">${query?'没有匹配的公告':'✓<strong>本次查询未匹配公告</strong>请同时检查未扫描项与数据完整性。'}</div>`;
  $$('#risk-list [data-risk]').forEach(b=>b.addEventListener('click',()=>selectSnapshot(state.id,b.dataset.risk).catch(e=>toast(e.message))));
}
function renderGraph() {
  const a=state.analysis;
  const active=state.activePath,activeNodes=new Set(active?.nodes||[]);
  const pathNodes=new Set(a.paths.flat());
  const priority=n=>activeNodes.has(n.id)?-1:n.root?0:pathNodes.has(n.id)?1:n.findings.includes(a.focus)?2:3;
  const all=[...a.nodes].sort((x,y)=>priority(x)-priority(y)).slice(0,40),shown=new Set(all.map(n=>n.id)),level=new Map([[a.root,0]]);
  const adjacent=new Map();
  for(const edge of a.edges){if(!adjacent.has(edge.source))adjacent.set(edge.source,[]);adjacent.get(edge.source).push(edge.target);}
  const queue=[a.root];
  for(let i=0;i<queue.length;i++)for(const child of adjacent.get(queue[i])||[])if(!level.has(child)){level.set(child,Math.min(4,level.get(queue[i])+1));queue.push(child);}
  all.forEach(n=>{if(!level.has(n.id))level.set(n.id,Math.min(4,Math.max(...level.values())+1));});
  const layers={};all.forEach(n=>(layers[level.get(n.id)]??=[]).push(n));
  const max=Math.max(...level.values(),1),height=Math.max(410,...Object.values(layers).map(l=>l.length*100+40));
  const width=Math.max(860,(max+1)*230),positions=new Map();
  Object.entries(layers).forEach(([l,nodes])=>nodes.forEach((n,i)=>positions.set(n.id,{x:25+Number(l)*(width-230)/max,y:(i+1)*height/(nodes.length+1)-28})));
  const highlighted=new Set();(active?[active.nodes]:a.paths).forEach(path=>path.slice(1).forEach((r,i)=>highlighted.add(path[i]+'\u0000'+r)));
  const edges=a.edges.filter(e=>shown.has(e.source)&&shown.has(e.target)).map(e=>{
    const from=positions.get(e.source),to=positions.get(e.target),sx=from.x+180,sy=from.y+29,tx=to.x,ty=to.y+29;
    return `<path class="graph-edge ${highlighted.has(e.source+'\u0000'+e.target)?'highlight':''} ${active?(highlighted.has(e.source+'\u0000'+e.target)?'answer-linked':'muted'):''}" data-source="${escapeHTML(e.source)}" data-target="${escapeHTML(e.target)}" d="M${sx},${sy} C${sx+58},${sy} ${tx-58},${ty} ${tx},${ty}" marker-end="url(#arrow)"><title>${escapeHTML(e.locator)}</title></path>`;
  }).join('');
  const nodes=all.map(n=>{const pos=positions.get(n.id),risk=n.findings.includes(a.focus);const label=n.name.length>23?n.name.slice(0,21)+'…':n.name;return `<g class="graph-node ${n.root?'root':''} ${risk?'risk':''}" data-node="${escapeHTML(n.id)}" tabindex="0" role="button" aria-label="${escapeHTML(n.name+' '+n.version)}" transform="translate(${pos.x},${pos.y})"><title>${escapeHTML(n.name+'@'+n.version+' · '+n.locator)}</title><rect width="180" height="59" rx="7"/><circle class="node-marker" cx="16" cy="20" r="3"/><text class="node-name" x="27" y="24">${escapeHTML(label)}</text><text class="node-version" x="15" y="44">${escapeHTML(n.root?'PROJECT ROOT':n.version+'  ·  '+(risk?'匹配公告':statusLabel(n.scan_status)))}</text></g>`;}).join('');
  $('#dependency-graph').innerHTML=`<defs><marker id="arrow" markerWidth="7" markerHeight="7" refX="6" refY="3" orient="auto"><path d="M0 0 L6 3 L0 6" fill="none" stroke="#93acaa" stroke-width="1"/></marker></defs>${edges}${nodes}`;
  $$('#dependency-graph [data-node]').forEach(node=>{
    node.classList.toggle('answer-linked',activeNodes.has(node.dataset.node));
    node.classList.toggle('muted',Boolean(active)&&!activeNodes.has(node.dataset.node));
  });
  let selection=$('#graph-answer-selection');
  if(!selection){selection=document.createElement('div');selection.id='graph-answer-selection';selection.className='graph-answer-selection';selection.setAttribute('aria-live','polite');$('#path-summary').before(selection);}
  selection.classList.toggle('hidden',!active);
  selection.innerHTML=active?`<strong>正在核对回答中的路径</strong><p>${escapeHTML(active.label)}</p><div><button type="button" id="return-to-answer">返回问答 ↓</button><button type="button" id="clear-answer-path">显示全部代表路径</button></div>`:'';
  if(active){$('#return-to-answer').addEventListener('click',()=>changeView('questions'));$('#clear-answer-path').addEventListener('click',()=>{state.activePath=null;renderGraph();});}
  state.graphSize={width,height};state.zoom=1;updateZoom();
  $('#graph-limit').textContent=a.nodes.length>40?`显示 40 / ${a.nodes.length}，优先选中路径`:'';
  $$('#dependency-graph [data-node]').forEach(element=>{
    function choose(){const n=a.nodes.find(n=>n.id===element.dataset.node);$$('.graph-node').forEach(x=>x.classList.remove('selected'));element.classList.add('selected');$('#node-detail').innerHTML=`<strong>${escapeHTML(n.name)}${n.version?' @ '+escapeHTML(n.version):''}</strong> · ${escapeHTML(statusLabel(n.scan_status))}<br>清单位置：${escapeHTML(n.locator)}${n.scan_error?'<br>'+escapeHTML(n.scan_error):''}${n.fetched_at?'<br>数据获取：'+escapeHTML(dateLabel(n.fetched_at)):''}`;}
    element.addEventListener('click',choose);element.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose();}});
  });
}
function updateZoom() {if(!state.graphSize)return;const {width,height}=state.graphSize,w=width/state.zoom,h=height/state.zoom;$('#dependency-graph').setAttribute('viewBox',`${(width-w)/2} ${(height-h)/2} ${w} ${h}`);}
function renderEvidence(citations=null) {
  const bindings=new Set(state.analysis.findings.filter(v=>v.id===state.analysis.focus).map(v=>v.package+'\u0000'+v.version));
  const docs=citations||state.analysis.documents.filter(d=>d.source==='user-document'?bindings.has(d.package+'\u0000'+d.version):!state.analysis.focus||d.vulnerability===state.analysis.focus);
  $('#evidence-count').textContent=docs.length;
  $('#evidence-list').innerHTML=docs.length?docs.map((d,i)=>`<article class="evidence-card" id="evidence-${escapeHTML(d.id)}"><div class="evidence-meta"><span class="evidence-number">E${String(i+1).padStart(2,'0')}</span><span>${escapeHTML(sourceLabel(d.source))}</span></div><h3>${escapeHTML(d.title)}</h3><p>${escapeHTML(d.version)}${d.target_version?' → '+escapeHTML(d.target_version):''} · ${escapeHTML(d.locator)}</p><details><summary>展开原文与匹配范围 ↓</summary><p>${escapeHTML(d.text)}</p>${d.trust?'<p>'+escapeHTML(d.trust)+'</p>':''}</details><div class="evidence-foot"><span>${escapeHTML(dateLabel(d.fetched_at))}</span>${d.url&&safeURL(d.url)!=='#'?`<a href="${escapeHTML(safeURL(d.url))}" target="_blank" rel="noopener noreferrer">${d.source==='user-document'?'查看文档来源':'查看 OSV 原文'} ↗</a>`:'<span>本地导入，未填写来源链接</span>'}</div></article>`).join(''):'<div class="empty-state">当前没有适用的证据。<br>可导入绑定当前包和版本的项目文档。</div>';
}
function renderIssues() {
  const a=state.analysis,issues=[...a.issues];
  const unknown=a.nodes.filter(n=>!n.root&&!['checked','demo-component'].includes(n.scan_status));
  for(const node of unknown)issues.push({message:`${node.name}@${node.version}：${node.scan_error||statusLabel(node.scan_status)}`});
  const item=x=>`<div class="quality-item"><span aria-hidden="true">△</span><span>${escapeHTML(x.message)}</span></div>`;
  const coverage=[!a.complete?'依赖清单结构存在缺失，无法确认完整覆盖。':'',unknown.length?`${unknown.length} 个组件尚未完成精确版本查询；未扫描或查询失败不代表安全。`:''].filter(Boolean).join(' ');
  const overview=issues.length?`<p class="quality-summary">共 ${issues.length} 项数据质量提示。${escapeHTML(coverage)}${issues.length>8?' 默认展示前 8 项，可展开查看全部记录。':''}</p>`:'';
  const remaining=issues.length>8?`<details class="quality-more"><summary><span class="quality-more-closed">展开其余 ${issues.length-8} 项</span><span class="quality-more-open">收起其余 ${issues.length-8} 项</span><small>共 ${issues.length} 项 · 完整记录均保留</small></summary>${issues.slice(8).map(item).join('')}</details>`:'';
  $('#issues-list').innerHTML=(issues.length?overview+issues.slice(0,8).map(item).join('')+remaining:'<div class="quality-item good"><span>✓</span><span>已声明组件的依赖关系与精确版本查询已完成；结论仅覆盖当前清单和公告快照。</span></div>')+
    (a.snapshot.demo?'<div class="quality-item"><span>i</span><span>@demo/report-kit 与 @demo/export-kit 是演示业务组件，不执行真实包漏洞查询。</span></div>':'');
}
async function askQuestion(event) {
  event?.preventDefault();const text=$('#question').value.trim();if(!text)return;
  if(state.switchingSnapshot){toast('项目资料尚未载入，请重新选择快照后再提问。');return;}
  if(!state.analysis)return;
  if(state.pendingQuestion){toast('当前问题仍在等待结果；可先点击“停止等待”。');return;}
  const snapshot=state.id,focus=state.analysis.focus,serial=state.request,useModel=$('#use-model').checked;
  const controller=new AbortController(),run={controller,cancelled:false};
  state.pendingQuestion=run;state.lastAnswer=null;state.lastAnswerReplay=false;
  const button=$('#ask-button'),progress=$('#question-progress'),cancel=$('#cancel-question');
  const original=button.textContent;button.disabled=true;button.textContent='分析中…';cancel.classList.remove('hidden');progress.classList.remove('hidden');
  const began=Date.now();
  const update=()=>{
    const seconds=Math.floor((Date.now()-began)/1000);
    button.textContent=`分析中 ${seconds}s`;
    progress.textContent=(useModel?'处理流程：检索适用证据 → 模型生成 → 核对引用。':'处理流程：检索适用证据 → 计算依赖事实 → 关联原文。')+` 正在等待完成结果，已等待 ${seconds} 秒。`;
  };
  update();const timer=setInterval(update,1000);
  window.dispatchEvent(new CustomEvent('lianzheng-question-state',{detail:{pending:true,useModel}}));
  try{
    const answer=await api(`/api/snapshots/${encodeURIComponent(snapshot)}/ask`,{method:'POST',signal:controller.signal,body:JSON.stringify({question:text,focus,mode:state.mode,use_model:useModel,parent_id:state.parentId})});
    if(run.cancelled)return;
    if(snapshot!==state.id||serial!==state.request){progress.textContent='这轮问答已保存到原快照记录；当前选择已改变，未覆盖当前页面。';toast('问答已保存到原快照记录。');return;}
    state.parentId=answer.id;state.turns.push({question:text,conclusion:answer.conclusion,id:answer.id});
    renderAnswer(answer);renderEvidence(answer.citations);renderConversation();
    progress.textContent=answer.generation==='model-assisted'?'分析完成：模型回答已通过引用编号与原文摘录核验；仍需人工判断语义和业务适用性。':useModel?'分析完成：本轮展示本地证据解释，模型调用状态见回答。':'分析完成：已关联当前清单事实与原文证据。';
    await refreshHistory(snapshot,serial).catch(()=>toast('回答已完成，问答记录列表暂未刷新。'));
    return answer;
  }catch(error){
    if(error.name==='AbortError'||run.cancelled){
      progress.textContent='已停止等待。服务端可能继续处理并产生 API 费用；稍后可刷新问答记录查看结果。';
      return null;
    }
    progress.textContent='本次分析未完成：'+error.message;toast(error.message);return null;
  }finally{
    clearInterval(timer);
    if(state.pendingQuestion===run){state.pendingQuestion=null;button.disabled=false;button.textContent=original;cancel.classList.add('hidden');}
    window.dispatchEvent(new CustomEvent('lianzheng-question-state',{detail:{pending:false}}));
  }
}
function stopWaiting(){
  if(!state.pendingQuestion)return;
  state.pendingQuestion.cancelled=true;state.pendingQuestion.controller.abort();
}
function modelMetadataHTML(meta){
  if(!meta)return '';
  const usage=meta.usage||{},parts=[meta.api_family==='responses'?'OpenAI Responses':'模型 API',meta.provider||'服务商未声明'];
  if(Number.isFinite(meta.elapsed_ms))parts.push(`${meta.elapsed_ms} ms`);
  parts.push(Number.isFinite(usage.total_tokens)?`${usage.total_tokens} tokens`:'token 用量未提供');
  if(Number.isFinite(usage.prompt_tokens))parts.push(`输入 ${usage.prompt_tokens}`);
  if(Number.isFinite(usage.completion_tokens))parts.push(`输出 ${usage.completion_tokens}`);
  const cost=meta.cost_estimate;
  const amount=cost?.currency==='USD'&&Number.isFinite(cost.amount)?cost.amount:Number.isFinite(meta.estimated_cost_usd)?meta.estimated_cost_usd:null;
  const displayAmount=amount>0&&amount<0.000001?'<0.000001':amount?.toFixed(6);
  parts.push(amount===null?'费用估算未提供':`估算费用 $${displayAmount} USD（账单为准）`);
  if(meta.request_id)parts.push('请求 '+meta.request_id);
  return '<div class="model-metadata">'+parts.map(escapeHTML).join(' · ')+'</div>';
}
function modelBudgetHTML(budget){
  if(!budget)return '';
  if(budget.blocked)return '<p class="model-budget">本轮输入超出预算，未发起模型调用；当前展示本地证据结果。</p>';
  const counts=[Number.isInteger(budget.truncated_evidence)&&budget.truncated_evidence>0?`缩短 ${budget.truncated_evidence} 条证据片段`:'',Number.isInteger(budget.omitted_evidence)&&budget.omitted_evidence>0?`省略 ${budget.omitted_evidence} 条候选证据`:'',Number.isInteger(budget.omitted_history_turns)&&budget.omitted_history_turns>0?`省略 ${budget.omitted_history_turns} 轮上文`:''].filter(Boolean);
  const size=Number.isInteger(budget.input_bytes)&&Number.isInteger(budget.limit_bytes)?`${budget.input_bytes.toLocaleString()} / ${budget.limit_bytes.toLocaleString()} UTF-8 字节（不是 token 数）` : '';
  if(!counts.length&&!size)return '';
  return '<p class="model-budget">本轮输入预算：'+[size,...counts].filter(Boolean).map(escapeHTML).join('；')+'。完整引用原文仍保留在本地证据区。</p>';
}
function renderAnswer(a,{replayed=false}={}) {
  if(state.activePath){state.activePath=null;renderGraph();}
  state.lastAnswer=a;
  state.lastAnswerReplay=replayed;
  const mode=a.mode==='text'?'文本 RAG 对照':'图与文本联合检索';
  const model=a.model_explanation;
  const answerPaths=answerPathDetails(a);
  const pathHTML=answerPaths.length?`<section class="answer-paths" aria-label="回答关联的依赖路径"><strong>沿图谱核对这次回答</strong>${answerPaths.map((p,i)=>`<button type="button" data-answer-path="${escapeHTML(p.id)}"><span>路径 ${i+1} ↗</span> ${escapeHTML(p.label)}</button>`).join('')}</section>`:'';
  const factsHTML=`<ul>${a.statements.map(s=>`<li>${escapeHTML(s)}</li>`).join('')}</ul>`;
  const detailHTML=model?`<details class="engine-facts"><summary>查看图计算事实与检索片段（${a.statements.length} 项）</summary>${factsHTML}</details>`:factsHTML;
  let modelHTML='';
  if(model){
    const meta=model.metadata;
    const clauses=model.claims?.length?model.claims.map(c=>`<div class="model-claim"><p>${escapeHTML(c.text)}</p><details><summary>核对原文摘录与引用 ↓</summary>${c.quotes.map(q=>`<div class="model-quote">“${escapeHTML(q.quote)}” <a class="citation-link" href="#evidence-${escapeHTML(q.evidence_id)}">查看原文 ↗</a></div>`).join('')}</details></div>`).join(''):`<p>${escapeHTML(model.text)}</p>`;
    modelHTML=`<h3>模型解释 · ${escapeHTML(meta?.returned_model||meta?.requested_model||'历史模型记录')}</h3>${modelMetadataHTML(meta)}${clauses}<p>${escapeHTML(model.validation)}</p>`;
  }
  $('#answer').innerHTML=`<div class="answer-status"><span class="pill ${a.insufficient?'orange':'teal'}">${a.insufficient?'保留未知':'证据已关联'}</span><span>${escapeHTML(mode)} · ${escapeHTML(a.retrieval.toUpperCase())}${a.parent_id?' · 追问':''} · ${a.generation==='model-assisted'?'模型回答':'本地证据解释'}</span></div>${replayed?'<p class="history-replay-note">历史回放：展示当时的回答与用量，本次未重新调用模型。</p>':''}<h3>${escapeHTML(a.conclusion)}</h3>${modelBudgetHTML(a.model_budget)}${modelHTML}${detailHTML}${a.model_attempt?`<p class="model-metadata">本轮模型返回未通过校验，已回退本地结果；已发生的调用仍可能计费。</p>${modelMetadataHTML(a.model_attempt)}`:''}<div>${a.citations.map((c,i)=>`<a class="citation-link" href="#evidence-${escapeHTML(c.id)}">证据 E${String(i+1).padStart(2,'0')} ↗</a>`).join('')}</div><p class="limit">${a.limits.map(escapeHTML).join('<br>')}</p>${model?.follow_up_questions?.length?`<div class="follow-up-suggestions">${model.follow_up_questions.map(q=>`<button data-follow-up="${escapeHTML(q)}">${escapeHTML(q)} ↗</button>`).join('')}</div>`:''}`;
  $$('#answer [data-follow-up]').forEach(button=>button.addEventListener('click',()=>{$('#question').value=button.dataset.followUp;askQuestion();}));
  $('#answer').insertAdjacentHTML('afterbegin',pathHTML);
  $$('#answer [data-answer-path]').forEach(button=>button.addEventListener('click',()=>showAnswerPath(a,button.dataset.answerPath)));
  $$('#answer .model-quote').forEach((element,index)=>{
    const quote=model?.claims?.flatMap(claim=>claim.quotes||[])[index];
    const path=answerPaths.find(p=>p.id===quote?.evidence_id);
    if(path){const button=document.createElement('button');button.className='citation-link';button.textContent='查看依赖路径 ↗';button.addEventListener('click',()=>showAnswerPath(a,path.id));element.append(button);}
    element.querySelector('a.citation-link')?.addEventListener('click',event=>{event.preventDefault();openAnswerEvidence(quote?.evidence_id,quote);});
  });
  $$('#answer a.citation-link').filter(link=>!link.closest('.model-quote')).forEach(link=>link.addEventListener('click',event=>{
    event.preventDefault();openAnswerEvidence(link.getAttribute('href').slice('#evidence-'.length));
  }));
  window.dispatchEvent(new CustomEvent('lianzheng-answer-rendered',{detail:{answer:a,replayed}}));
}
function renderConversation(){
  if(!$('#conversation-summary'))return;
  const prior=state.turns.slice(0,-1).slice(-3);
  $('#conversation-summary').innerHTML=prior.map(turn=>`<div class="conversation-turn"><strong>上文提问</strong> ${escapeHTML(turn.question)}<br>${escapeHTML(turn.conclusion)}</div>`).join('');
  $('#conversation-context').textContent=state.parentId?`可继续追问 · 当前对话 ${state.turns.length} 轮`:'新对话 · 每轮重新检索适用证据';
}
function newConversation(){
  state.activePath=null;if(state.analysis)renderGraph();
  ++state.request;state.parentId=null;state.turns=[];state.lastAnswer=null;renderConversation();
  $('#answer').innerHTML='<div class="answer-placeholder"><strong>已开启新对话</strong><p>后续问题不会继承上一段对话的目标版本。</p></div>';
}
function changeView(view,autoCompare=true) {
  state.view=view;$$('.nav').forEach(n=>n.classList.toggle('active',n.dataset.view===view));
  const labels={overview:'风险总览',graph:'图谱溯源',questions:'证据问答',documents:'项目文档',compare:'快照对比'};
  $('#breadcrumb-view').textContent=labels[view];
  $('#page-title').textContent=view==='compare'?'修复结果对比':'依赖风险工作台';
  $('#page-description').textContent=view==='compare'?'比较两份实际清单，区分目标漏洞消除与其他风险保留。':'连接项目依赖与公告证据，查清风险来源并验证修复结果。';
  $('#overview-view').classList.toggle('hidden',view==='compare');$('#compare-view').classList.toggle('hidden',view!=='compare');
  if(view==='graph')$('#graph-panel').scrollIntoView({behavior:'smooth',block:'start'});
  else if(view==='questions')$('#questions-panel').scrollIntoView({behavior:'smooth',block:'start'});
  else if(view==='documents')$('#documents-panel').scrollIntoView({behavior:'smooth',block:'start'});
  else {window.scrollTo({top:0,behavior:'smooth'});if(view==='compare'&&autoCompare&&!$('#comparison').children.length)runCompare();}
}
function updateCompareOptions() {
  const options=state.snapshots.map(s=>`<option value="${escapeHTML(s.id)}">${escapeHTML(s.project)} · ${escapeHTML(s.label)}</option>`).join('');
  const before=$('#compare-before').value,after=$('#compare-after').value;
  $('#compare-before').innerHTML=options;$('#compare-after').innerHTML=options;
  $('#compare-before').value=state.snapshots.some(s=>s.id===before)?before:state.snapshots[0]?.id;
  $('#compare-after').value=state.snapshots.some(s=>s.id===after)?after:(state.snapshots.find(s=>s.id==='demo-partial')?.id||state.snapshots.at(-1)?.id);
}
async function runCompare(event) {
  event?.preventDefault();const button=$('#compare-form button');
  return await busy(button,'比较中…',async()=>{
    const result=await api(`/api/compare?before=${encodeURIComponent($('#compare-before').value)}&after=${encodeURIComponent($('#compare-after').value)}`);
    const count=result.resolved.length;
    const makeColumn=(title,ids,kind)=>`<section class="panel compare-result ${kind}"><h3>${title} <span class="count">${ids.length}</span></h3>${ids.length?ids.map(id=>`<div class="result-id">${escapeHTML(id)}</div>`).join(''):'<p>当前比较无此类变化</p>'}</section>`;
    $('#comparison').innerHTML=`<div class="comparison-summary"><div class="metrics">${metric('修复前匹配公告',result.before_stats.vulnerabilities,'包括已知的全部组件位置','◷')}${metric('修复后匹配公告',result.after_stats.vulnerabilities,'仍需逐项核对影响范围','◷')}${metric('已消除目标公告',count,result.comparison_complete?'新快照中已无可达命中位置':'覆盖不足，消失项保留为未知','✓','teal')}${metric('仍保留公告',result.remaining.length,'仍有至少一个可达匹配位置','⌘','risk')}</div></div><div class="compare-columns">${makeColumn('已消除',result.resolved,'resolved')}${makeColumn('仍保留',result.remaining,'remaining')}${makeColumn('新增',result.introduced,'introduced')}</div>${result.not_observed.length?makeColumn('仅未观察到，尚不能确认消除',result.not_observed,'remaining'):''}<section class="panel"><div class="panel-heading"><div><h2>相同位置的版本变化</h2><p>bom-ref 不稳定时不会猜测位置对应关系</p></div></div><table class="change-table"><thead><tr><th>组件位置</th><th>组件</th><th>修复前</th><th>修复后</th></tr></thead><tbody>${result.component_changes.length?result.component_changes.map(c=>`<tr><td>${escapeHTML(c.ref)}</td><td>${escapeHTML(c.name)}</td><td>${escapeHTML(c.from)}</td><td>${escapeHTML(c.to)}</td></tr>`).join(''):'<tr><td colspan="4">无可确认的同位置版本变化</td></tr>'}</tbody></table></section><p class="comparison-note">${escapeHTML(result.note)}</p>`;
    return result;
  });
}
async function importFile(event) {
  event.preventDefault();const file=$('#bom-file').files[0];if(!file)return;
  await busy($('#import-submit'),'解析清单…',async()=>{
    if(file.size>5*1024*1024)throw new Error('文件超过 5 MB 上限。');
    let raw;try{raw=JSON.parse(await file.text());}catch{throw new Error('文件不是有效的 JSON。');}
    const result=await api('/api/snapshots',{method:'POST',body:JSON.stringify({bom:raw,project:$('#import-project').value.trim(),label:$('#import-label').value.trim()})});
    const importedId=result.snapshot.id;await loadSnapshots();await selectSnapshot(importedId);
    if(state.id!==importedId||state.switchingSnapshot)throw new Error('清单已保存，当前项目选择已变化，请重新选中导入快照。');
    $('#import-dialog').close();changeView('overview');
    await window.lianzhengTaskCompare?.open?.({scope:'snapshot',snapshot_id:importedId,mode:'free'});
    toast('清单已导入，可直接提问当前项目；未扫描项会保留为未知。');
  });
}
async function refreshKnowledge(snapshot=state.id,serial=state.request) {
  const documents=await api(`/api/snapshots/${encodeURIComponent(snapshot)}/documents`);
  if(snapshot!==state.id||serial!==state.request)return;
  state.documents=documents;
  $('#document-count').textContent=documents.length;
  $('#document-list').innerHTML=documents.length?documents.map(d=>`<article class="document-item"><div class="document-item-head"><div><strong>${escapeHTML(d.title)}</strong><small>${escapeHTML(d.package)} ${escapeHTML(d.version)}${d.target_version?' → '+escapeHTML(d.target_version):''}</small></div><span class="pill neutral">${d.kind==='migration'?'迁移说明':'项目要求'}</span></div><div class="document-meta">${d.chunk_count} 个片段 · ${d.character_count} 字符 · ${escapeHTML(dateLabel(d.created))}</div><details data-document-preview="${escapeHTML(d.id)}"><summary>预览原文 ↓</summary><pre>正在加载原文…</pre></details><div class="document-actions"><span>适用范围由导入者声明</span><button class="text-button remove-document" data-remove-document="${escapeHTML(d.id)}">移出文档库</button></div></article>`).join(''):'<div class="empty-state"><strong>把迁移依据连接到项目</strong>导入 Markdown 或纯文本，并绑定包与精确版本。<br>后续回答会引用适用片段和原始行号。</div>';
  $$('#document-list [data-document-preview]').forEach(details=>details.addEventListener('toggle',async()=>{
    if(!details.open||details.dataset.loaded)return;
    details.dataset.loaded='1';
    try{const document=await api(`/api/snapshots/${encodeURIComponent(snapshot)}/documents/${encodeURIComponent(details.dataset.documentPreview)}`);details.querySelector('pre').textContent=document.text;}
    catch(error){details.querySelector('pre').textContent=error.message;delete details.dataset.loaded;}
  }));
  $$('#document-list [data-remove-document]').forEach(button=>button.addEventListener('click',()=>busy(button,'移除中…',async()=>{
    await api(`/api/snapshots/${encodeURIComponent(snapshot)}/documents/${encodeURIComponent(button.dataset.removeDocument)}`,{method:'DELETE'});
    window.dispatchEvent(new CustomEvent('lianzheng-project-evidence-changed',{detail:{snapshot_id:snapshot}}));
    await refreshKnowledge(snapshot,serial);toast('已从后续检索中移除；历史回答中的原始引用仍保留。');
  })));
}
async function refreshHistory(snapshot=state.id,serial=state.request) {
  const history=await api(`/api/snapshots/${encodeURIComponent(snapshot)}/history`);
  if(snapshot!==state.id||serial!==state.request)return;
  state.history=history;$('#history-count').textContent=history.length;
  $('#history-list').innerHTML=history.length?history.map(item=>`<button class="history-item" data-history="${item.id}"><strong>${escapeHTML(item.question)}</strong><span>${escapeHTML(dateLabel(item.created))}<i>${item.answer.mode==='text'?'文本 RAG':'GraphRAG'} · ${item.answer.citations.length} 条引用</i></span></button>`).join(''):'<div class="empty-state">当前快照还没有问答记录。<br>完成提问后会保存回答与当时的引用。</div>';
  $$('#history-list [data-history]').forEach(button=>button.addEventListener('click',async()=>{
    if(state.switchingSnapshot||snapshot!==state.id||serial!==state.request)return;
    const item=history.find(h=>String(h.id)===button.dataset.history);if(!item)return;
    const focus=item.answer.facts?.focus;
    let expected=state.request;
    if(focus&&state.analysis.focus!==focus&&state.analysis.vulnerabilities.some(v=>v.id===focus)){
      expected=state.request+1;await selectSnapshot(snapshot,focus);
    }
    if(state.switchingSnapshot||snapshot!==state.id||expected!==state.request)return;
    stopWaiting();
    $('#question').value=item.question;state.mode=item.answer.mode;
    $$('[data-mode]').forEach(b=>b.classList.toggle('active',b.dataset.mode===state.mode));
    renderAnswer(item.answer,{replayed:true});renderEvidence(item.answer.citations);changeView('questions');
    state.parentId=!focus||state.analysis.focus===focus?item.id:null;
    state.turns=[{question:item.question,conclusion:item.answer.conclusion,id:item.id}];renderConversation();
    toast('已恢复当时的回答与证据快照，未重新调用模型。');
  }));
}
function openDocument() {
  if(!state.analysis||state.switchingSnapshot)return;
  $('#document-form').reset();
  const bindings=new Map();
  for(const node of state.analysis.nodes)if(node.package_name&&node.scan_status!=='demo-component')bindings.set(node.package_name+'\u0000'+node.package_version,{package:node.package_name,version:node.package_version});
  state.documentBindings=[...bindings.values()];state.documentSnapshot=state.id;
  if(!state.documentBindings.length){toast('当前快照没有可绑定的精确 npm 组件版本。');return;}
  $('#document-binding').innerHTML=state.documentBindings.map((b,i)=>`<option value="${i}">${escapeHTML(b.package)} @ ${escapeHTML(b.version)}</option>`).join('');
  $('#document-dialog').showModal();
}
async function importDocument(event) {
  event.preventDefault();const snapshot=state.documentSnapshot;
  await busy($('#document-submit'),'分块并建立索引…',async()=>{
    const binding=state.documentBindings[Number($('#document-binding').value)];
    if(!binding)throw new Error('请选择有效的组件版本。');
    const result=await api(`/api/snapshots/${encodeURIComponent(snapshot)}/documents`,{method:'POST',body:JSON.stringify({
      ...binding,title:$('#document-title').value.trim(),target_version:$('#document-target').value.trim()||null,
      kind:$('#document-kind').value,url:$('#document-url').value.trim(),text:$('#document-text').value
    })});
    window.dispatchEvent(new CustomEvent('lianzheng-project-evidence-changed',{detail:{snapshot_id:snapshot}}));
    $('#document-dialog').close();await refreshKnowledge(snapshot);
    toast(`文档已保存，建立 ${result.chunk_count} 个可定位片段。现在可以询问迁移要求。`);
  });
}
async function start() {
  try{
    const migrationPrompt=document.createElement('button');
    migrationPrompt.textContent='迁移文档有哪些要求？ ↗';
    migrationPrompt.addEventListener('click',()=>{$('#question').value='迁移文档中列出了哪些升级检查要求？';askQuestion();});
    $('.prompt-list').append(migrationPrompt);
    const health=await api('/api/health');
    $('#use-model').disabled=!health.llm_configured;
    $('#generation-mode').textContent=health.llm_configured?'模型可用 · 按需开启':'本地证据模式';
    $('#use-model').checked=Boolean(health.llm_verified);
    $('#use-model').parentElement.title=health.llm_configured?'只发送选中快照的相关证据。':'在服务器配置 LZ_LLM_BASE_URL 和 LZ_LLM_MODEL 后可开启。';
    await loadSnapshots();if(state.id)await selectSnapshot(state.id);
  }catch(error){toast(error.message);$('#notice-text').textContent='无法连接服务，请确认启动脚本正在运行。';}
}
$$('.nav').forEach(button=>button.addEventListener('click',()=>changeView(button.dataset.view)));
$('#snapshot-select').addEventListener('change',e=>selectSnapshot(e.target.value).catch(error=>toast(error.message)));
$('#risk-search').addEventListener('input',()=>state.analysis&&renderRisks());
$('#zoom-in').addEventListener('click',()=>{state.zoom=Math.min(2.2,state.zoom+.15);updateZoom();});
$('#zoom-out').addEventListener('click',()=>{state.zoom=Math.max(.7,state.zoom-.15);updateZoom();});
$('#zoom-reset').addEventListener('click',()=>{state.zoom=1;updateZoom();});
$('#question-form').addEventListener('submit',askQuestion);
$('#cancel-question').addEventListener('click',stopWaiting);
$$('[data-prompt]').forEach(b=>b.addEventListener('click',()=>{$('#question').value=b.dataset.prompt;askQuestion();}));
$$('[data-mode]').forEach(b=>b.addEventListener('click',()=>{state.mode=b.dataset.mode;newConversation();$$('[data-mode]').forEach(x=>x.classList.toggle('active',x===b));}));
$('#question').addEventListener('keydown',e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();askQuestion();}});
$('#compare-form').addEventListener('submit',runCompare);
$('#export-report').addEventListener('click',()=>{if(state.id)window.location.href='/api/snapshots/'+encodeURIComponent(state.id)+'/report?format=html';});
$('#download-bom').addEventListener('click',()=>{if(state.id)window.location.href='/api/snapshots/'+encodeURIComponent(state.id)+'/bom';});
$('#live-scan').addEventListener('click',()=>busy($('#live-scan'),'在线查询中…',async()=>{
  const original=state.id;
  const result=await api(`/api/snapshots/${encodeURIComponent(original)}/scan`,{method:'POST',body:JSON.stringify({live:true})});
  window.dispatchEvent(new CustomEvent('lianzheng-project-evidence-changed',{detail:{snapshot_id:original}}));
  await loadSnapshots();if(original===state.id)await selectSnapshot(original);toast(`在线查询完成：${result.checked} 个位置已查询，${result.failed} 个失败。`);
}));
$('#open-import').addEventListener('click',()=>{$('#import-project').value=state.analysis?.snapshot.project||'';$('#import-label').value='';$('#import-dialog').showModal();});
$('#close-import').addEventListener('click',()=>$('#import-dialog').close());
$('#cancel-import').addEventListener('click',()=>$('#import-dialog').close());
$('#bom-file').addEventListener('change',()=>{$('#file-status').textContent=$('#bom-file').files[0]?.name||'每份快照独立保存，原文件不会被覆盖';});
$('#import-form').addEventListener('submit',importFile);
$('#open-document').addEventListener('click',openDocument);
$('#close-document').addEventListener('click',()=>$('#document-dialog').close());
$('#cancel-document').addEventListener('click',()=>$('#document-dialog').close());
$('#document-form').addEventListener('submit',importDocument);
$('#refresh-history').addEventListener('click',()=>busy($('#refresh-history'),'读取中…',()=>refreshHistory()));
$('#document-file').addEventListener('change',async()=>{
  const file=$('#document-file').files[0];if(!file)return;
  try{
    if(file.size>1024*1024)throw new Error('文档文件最多 1 MB，正文最多 200000 字符。');
    const text=new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer());
    if(text.length>200000)throw new Error('文档超过 200000 字符上限，请拆分。');
    $('#document-text').value=text;
    if(!$('#document-title').value)$('#document-title').value=file.name.replace(/\.(md|txt)$/i,'').slice(0,160);
  }catch(error){toast(error instanceof TypeError?'无法按 UTF-8 读取文档，请转换编码后重试。':error.message);}
});
const conversationControls=document.createElement('div');conversationControls.className='conversation-controls';conversationControls.innerHTML='<span id="conversation-context">新对话</span><button type="button" id="new-conversation">＋ 新对话</button>';
$('#question-form').before(conversationControls);
const conversationSummary=document.createElement('div');conversationSummary.id='conversation-summary';conversationSummary.className='conversation-summary';conversationControls.before(conversationSummary);
$('#new-conversation').addEventListener('click',newConversation);
window.addEventListener('lianzheng-model-updated',event=>{
  const model=event.detail;state.model=model;$('#use-model').disabled=!model.configured;
  $('#use-model').checked=Boolean(model.verified);
  $('#generation-mode').textContent=model.verified?'真实模型已验证':model.configured?'模型待验证':'本地证据模式';
  $('#use-model').parentElement.title='模型解释会发送当前问题所需的证据，API 密钥保留在服务器端。';
});
start();
