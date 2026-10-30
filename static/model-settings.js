(()=>{
  const qs=s=>document.querySelector(s);
  const launch=document.createElement('button');launch.className='model-launch';launch.id='open-model-settings';launch.textContent='◉ 模型设置';
  qs('.top-status').prepend(launch);
  const banner=document.createElement('div');banner.className='model-readiness';banner.innerHTML='<div><strong id="model-readiness-title">正在读取模型状态</strong><span id="model-readiness-detail">连接验证、实际问答和历史回放分别标注。</span></div><button id="model-banner-open">连接 GPT API ↗</button>';
  qs('main').prepend(banner);
  const dialog=document.createElement('dialog');dialog.id='model-dialog';
  dialog.innerHTML=`<form id="model-form"><div class="dialog-title"><div><h2>连接 GPT 与其他模型</h2><p>密钥保留在本机服务端；测试会向所选服务发送一次最小 API 请求。</p></div><button type="button" class="icon-button" id="close-model" aria-label="关闭模型设置">×</button></div><label class="field-label">服务商<select id="provider-select"><option value="openai">OpenAI / GPT 官方</option><option value="deepseek">DeepSeek 官方</option><option value="qwen">通义千问兼容接口</option><option value="compatible">其他兼容接口</option><option value="local">本地兼容服务</option></select></label><div class="model-credits-note" id="model-credits-note"><strong>已有 ChatGPT Pro？</strong><span>符合条件的订阅可先到 ChatGPT 账单页领取 API credits，再使用 OpenAI 平台创建的 API Key。会员登录不会自动连接到本项目。</span><a href="https://developers.openai.com/api/docs/guides/chatgpt-api-credits" target="_blank" rel="noopener noreferrer">查看官方领取条件与步骤 ↗</a></div><label class="field-label">API 地址<input id="provider-base" required maxlength="2000" placeholder="https://api.openai.com/v1"></label><label class="field-label">模型名称<input id="provider-model" required maxlength="160" placeholder="gpt-6-luna"></label><label class="field-label">API 密钥<input id="provider-key" type="password" maxlength="8192" autocomplete="new-password" spellcheck="false" placeholder="在本机填写，不要发到聊天"></label><div class="model-options"><label><input type="checkbox" id="provider-json" checked>启用结构化 JSON 输出</label><label><input type="checkbox" id="provider-remember" checked>记住本机密钥</label></div><p class="dialog-note" id="model-storage-note"></p><div class="model-connection-result" id="model-connection-result" role="status" aria-live="polite">尚未验证。点击测试并保存后，会显示服务返回的模型和耗时。</div><p class="dialog-note" id="provider-help"></p><div class="dialog-actions"><button type="button" class="button secondary" id="cancel-model">取消</button><button type="submit" class="button primary" id="connect-model">测试并保存</button></div></form>`;
  document.body.append(dialog);
  let current=null;
  const defaults={openai:['https://api.openai.com/v1','gpt-6-luna'],deepseek:['https://api.deepseek.com','deepseek-flash'],qwen:['https://dashscope.aliyuncs.com/compatible-mode/v1','qwen-plus'],compatible:['',''],local:['http://127.0.0.1:11434/v1','']};
  const labels={openai:'GPT API',deepseek:'DeepSeek',qwen:'通义千问',compatible:'兼容模型',local:'本地服务'};
  function providerHelp(provider){
    qs('#model-credits-note').classList.toggle('hidden',provider!=='openai');
    const help=qs('#provider-help');
    help.replaceChildren();
    const text=provider==='openai'?'默认选择低成本的 gpt-6-luna，也可填写你的 API 账户可用的其他模型。连接验证成功不等于真实问答已完成验收。':provider==='deepseek'?'DeepSeek 默认使用 deepseek-flash。连接验证成功后，仍需检查实际问答与引用。':'请填写服务商提供的模型名与 API 前缀。连接成功后，仍需检查实际问答与引用。';
    help.append(document.createTextNode(text+' API 使用按服务商规则计费。'));
    if(provider==='openai'||provider==='deepseek'){
      const link=document.createElement('a');link.href=provider==='openai'?'https://platform.openai.com':'https://platform.deepseek.com/api_keys';
      link.target='_blank';link.rel='noopener noreferrer';link.textContent=' 打开官方 API 控制台 ↗';help.append(link);
    }
  }
  async function request(path,options={}){
    const r=await fetch(path,{...options,headers:{'Content-Type':'application/json'}});
    const result=await r.json();if(!r.ok)throw new Error(typeof result.detail==='string'?result.detail:'模型设置请求失败。');return result;
  }
  function status(config){
    current=config;
    const provider=config.base_url?(labels[config.provider]||'模型'):'GPT API';
    qs('#model-readiness-title').textContent=config.verified?`${provider} 连接验证已通过`:config.configured?'模型已配置，尚未验证':`${provider} 尚未连接`;
    qs('#model-readiness-detail').textContent=config.verified?`${config.verification?.returned_model||config.model} · 最近连接验证 ${config.verification?.elapsed_ms??'未提供'} ms · 实际问答仍需通过引用原文核验。`:'在模型设置中填写 API Key 并验证；本地证据问答、图谱和修复对比可先使用。';
    banner.classList.toggle('ready',config.verified);launch.classList.toggle('ready',config.verified);
    qs('#model-banner-open').textContent=config.verified?'查看模型设置 ↗':`连接 ${provider} ↗`;
    window.dispatchEvent(new CustomEvent('lianzheng-model-updated',{detail:config}));
  }
  async function open(){
    try{
      const config=await request('/api/model/settings');current=config;
      const provider=config.base_url&&defaults[config.provider]?config.provider:'openai';
      qs('#provider-select').value=provider;
      qs('#provider-base').value=config.base_url||defaults[provider][0];
      qs('#provider-model').value=config.model||defaults[provider][1];
      qs('#provider-key').value='';qs('#provider-key').placeholder=config.has_key?'已在服务端保存；留空保留当前端点的密钥':'在本机填写，不要发到聊天';
      qs('#provider-json').checked=config.json_mode!==false;
      qs('#provider-remember').checked=config.configured?config.remember_key:true;
      qs('#model-storage-note').textContent=config.storage==='windows-dpapi'?'记住密钥时使用 Windows 本机账户加密保存；取消记住则仅本次进程有效。密钥不会回传页面或进入源码包。':'记住密钥时保存为本机权限受限的服务端文件；取消记住则仅本次进程有效。密钥不会回传页面或进入源码包。';
      qs('#model-connection-result').textContent=config.verified?`最近验证成功：${config.verification?.returned_model||config.model}，${config.verification?.elapsed_ms??'未提供'} ms。当前请求是否成功仍以问答结果为准。`:config.load_error||'尚未验证。填写后点击测试并保存。';
      providerHelp(provider);
      dialog.showModal();
    }catch(error){qs('#model-readiness-detail').textContent=error.message;}
  }
  launch.addEventListener('click',open);qs('#model-banner-open').addEventListener('click',open);
  for(const id of ['close-model','cancel-model'])qs('#'+id).addEventListener('click',()=>{qs('#provider-key').value='';dialog.close();});
  dialog.addEventListener('close',()=>{qs('#provider-key').value='';});
  qs('#provider-select').addEventListener('change',e=>{const d=defaults[e.target.value];qs('#provider-base').value=d[0];qs('#provider-model').value=d[1];qs('#provider-key').value='';providerHelp(e.target.value);});
  qs('#model-form').addEventListener('submit',async event=>{
    event.preventDefault();const button=qs('#connect-model');button.disabled=true;button.textContent='验证连接…';
    qs('#model-connection-result').textContent='正在向所选服务发送一次最小 JSON 请求，请等待真实返回结果。';
    try{
      const config=await request('/api/model/connect',{method:'POST',body:JSON.stringify({provider:qs('#provider-select').value,base_url:qs('#provider-base').value.trim(),model:qs('#provider-model').value.trim(),api_key:qs('#provider-key').value.trim(),json_mode:qs('#provider-json').checked,remember_key:qs('#provider-remember').checked})});
      qs('#provider-key').value='';status(config);
      qs('#model-connection-result').textContent=`API 连接验证成功。服务返回：${config.verification?.returned_model||'未声明模型名'}；耗时 ${config.verification?.elapsed_ms??'未提供'} ms；用量 ${config.verification?.usage?.total_tokens??'未提供'} tokens。关闭窗口后可进行问答；连接验证不代表每个回答都已通过核验。`;
    }catch(error){qs('#model-connection-result').textContent=error.message;}
    finally{button.disabled=false;button.textContent='测试并保存';}
  });
  request('/api/model/settings').then(config=>{status(config);if(new URLSearchParams(location.search).get('setup')==='model')open();}).catch(()=>{qs('#model-readiness-title').textContent='模型设置暂不可用';});
})();
