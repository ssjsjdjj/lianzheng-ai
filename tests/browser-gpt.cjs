/* Simulated browser contract only. It never contacts OpenAI and is NOT live GPT acceptance. */
const {chromium}=require('playwright');
const fs=require('fs');
const path=require('path');

(async()=>{
  fs.mkdirSync('test-results',{recursive:true});
  const browser=await chromium.launch({...(process.platform==='win32'?{channel:'msedge'}:{}),headless:true});
  const page=await browser.newPage({viewport:{width:1512,height:1100}});
  const base=process.env.LZ_TEST_URL||'http://127.0.0.1:8766';
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  let configured=false,slow=false,missingUsage=false,counter=50000,modelCalls=0;
  const settings=()=>({provider:'openai',base_url:configured?'https://api.openai.com/v1':'',model:configured?'gpt-6-luna':'',has_key:configured,configured,verified:configured,json_mode:true,remember_key:false,storage:'windows-dpapi',verification:configured?{returned_model:'ui-contract-stub',elapsed_ms:12,usage:{total_tokens:7}}:null});
  await page.route('**/api/model/settings',route=>route.fulfill({json:settings()}));
  await page.route('**/api/model/connect',async route=>{
    const request=route.request().postDataJSON();
    if(request.provider!=='openai'||request.base_url!=='https://api.openai.com/v1'||request.model!=='gpt-6-luna')throw Error('OpenAI preset was not sent correctly');
    configured=true;await route.fulfill({json:settings()});
  });
  await page.route('**/api/health',async route=>{
    const response=await route.fetch();const health=await response.json();
    await route.fulfill({json:{...health,llm_configured:configured,llm_verified:configured,model:settings()}});
  });
  await page.route('**/api/snapshots/demo-before/ask',async route=>{
    const payload=route.request().postDataJSON();
    const response=await route.fetch({postData:JSON.stringify({...payload,use_model:false})});
    const answer=await response.json();
    if(payload.use_model){
      modelCalls++;const cite=answer.citations[0];
      ++counter;answer.generation='model-assisted';
      answer.model_explanation={text:'UI 协议模拟回答，仅用于浏览器回归测试。',claims:[{text:'UI 协议模拟回答，仅用于浏览器回归测试。',evidence_ids:[cite.id],quotes:[{evidence_id:cite.id,quote:cite.text.slice(0,80)}]}],follow_up_questions:['这些检查如何落实？'],validation:'协议模拟：引用摘录检查的 UI 展示。',metadata:{provider:'openai',api_family:'responses',returned_model:'ui-contract-stub',requested_model:'gpt-6-luna',request_id:'ui-test-'+counter,elapsed_ms:18,...(missingUsage?{}:{usage:{prompt_tokens:100,completion_tokens:80,total_tokens:180},cost_estimate:{currency:'USD',amount:0.00005,estimated:true,pricing_as_of:'2026-10-30'}})}};
      answer.model_budget={input_bytes:42000,limit_bytes:48000,truncated_evidence:1,omitted_evidence:0,omitted_history_turns:0,blocked:false};
    }
    if(slow)await new Promise(resolve=>setTimeout(resolve,1200));
    await route.fulfill({json:answer}).catch(error=>{if(!/closed|cancelled|canceled|aborted/i.test(error.message))throw error;});
  });
  await page.goto(base,{waitUntil:'networkidle'});
  await page.locator('.risk-item').first().waitFor();
  await page.locator('#open-model-settings').click();
  await page.locator('#model-dialog').waitFor({state:'visible'});
  if(await page.locator('#provider-select').inputValue()!=='openai')throw Error('GPT was not the first-use preset');
  if(await page.locator('#provider-base').inputValue()!=='https://api.openai.com/v1')throw Error('Official OpenAI prefix missing');
  if(!(await page.locator('#model-credits-note').innerText()).includes('API credits'))throw Error('Pro API credit guidance missing');
  await page.locator('#close-model').click();
  await page.locator('#open-demo').click();
  await page.locator('.demo-hub-legacy > summary').filter({hasText:'构造样例与历史模型验收'}).click();
  await page.locator('#prepare-demo').click();
  await page.waitForFunction(()=>document.querySelector('#demo-data-state').textContent==='演示资料已就绪');
  await page.locator('#demo-local-answer').click();
  await page.waitForFunction(()=>document.querySelector('#demo-note').textContent.includes('本地证据讲解已完成'));
  if(modelCalls!==0)throw Error('Local demo requested a model');
  await page.locator('[data-demo-step="4"]').click();
  await page.waitForFunction(()=>document.querySelector('.compare-result.remaining')?.textContent.includes('GHSA-29mw-wpgm-hmr9'));
  await page.locator('[data-demo-step="5"]').click();
  await page.waitForFunction(()=>document.querySelector('.compare-result.resolved')?.textContent.includes('GHSA-29mw-wpgm-hmr9'));
  await page.locator('#open-model-settings').click();await page.locator('#model-dialog').waitFor({state:'visible'});await page.locator('#provider-key').fill('ui-test-placeholder');
  await page.locator('#connect-model').click();
  await page.waitForFunction(()=>document.querySelector('#model-connection-result').textContent.includes('验证成功'));
  if(await page.locator('#provider-key').inputValue())throw Error('Key was not cleared after save');
  await page.locator('#close-model').click();
  await page.locator('[data-demo-step="2"]').click();
  await page.waitForFunction(()=>document.querySelector('#answer .model-claim'));
  let answer=await page.locator('#answer').innerText();
  if(!answer.includes('OpenAI Responses')||!answer.includes('180 tokens')||!answer.includes('$0.000050'))throw Error('Returned API usage/cost missing');
  if(!answer.includes('缩短 1 条证据片段')||!answer.includes('UTF-8 字节'))throw Error('Input budget disclosure missing');
  if(!(await page.locator('#demo-answer-state').innerText()).includes('1 次'))throw Error('Current demo model answer was not counted');
  await page.locator('#new-conversation').click();missingUsage=true;
  await page.locator('#question').fill('没有用量元数据时如何展示？');await page.locator('#ask-button').click();
  await page.waitForFunction(()=>!document.querySelector('#ask-button').disabled);
  answer=await page.locator('#answer').innerText();
  if(!answer.includes('token 用量未提供')||!answer.includes('费用估算未提供'))throw Error('Missing usage was treated as zero');
  missingUsage=false;slow=true;await page.locator('#question').fill('等待较慢的测试回答');await page.locator('#ask-button').click();
  await page.locator('#cancel-question').waitFor();
  if(!(await page.locator('#question-progress').innerText()).includes('检索适用证据 → 模型生成 → 核对引用'))throw Error('Honest processing description missing');
  await page.locator('#cancel-question').click();await page.waitForFunction(()=>!document.querySelector('#ask-button').disabled);
  if(!(await page.locator('#question-progress').innerText()).includes('仍可能计费')&&!(await page.locator('#question-progress').innerText()).includes('产生 API 费用'))throw Error('Cancel did not explain server-side charging');
  await page.setViewportSize({width:390,height:844});
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('GPT UI overflowed at mobile width');
  await page.screenshot({path:path.resolve('test-results/gpt-ui-contract-mobile.png'),fullPage:false});
  if(errors.length)throw Error(errors.join('\n'));
  console.log(JSON.stringify({kind:'simulated-gpt-ui-contract-not-live-acceptance',checks:['OpenAI preset','official prefix','Pro credit guidance','offline evidence demo','partial comparison','complete comparison','key cleared','Responses metadata','usage/cost estimate','budget disclosure','demo answer receipt','missing usage is unknown','honest wait flow','stop waiting caveat','mobile layout'],pageErrors:errors}));
  await browser.close();
})().catch(error=>{console.error(error);process.exit(1)});
