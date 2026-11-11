"""Bounded provider clients. Never surface raw provider errors or credentials."""
import json
import re
import time
from urllib.parse import urlsplit

import httpx

from .domain import InputError


class ModelError(ValueError):
    def __init__(self,message,metadata=None):
        super().__init__(message)
        self.metadata=metadata


class ModelWarning(str):
    def __new__(cls,message,metadata=None):
        obj=super().__new__(cls,message);obj.metadata=metadata;return obj


def validate_endpoint(value):
    try:
        parts=urlsplit(value)
        local=parts.hostname in ('localhost','127.0.0.1','::1')
        if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError()
        if parts.scheme!='https' and not (parts.scheme=='http' and local):raise ValueError()
        if parts.path.rstrip('/').endswith(('/chat/completions','/embeddings','/responses')):raise ValueError()
        _=parts.port
    except ValueError as error:
        raise InputError('请填写 HTTPS API 前缀；本地服务可用 HTTP。地址不能包含密钥、账号或完整请求路径。') from error
    return value.rstrip('/'),local


def validate_provider_endpoint(value,provider):
    if provider not in (None,'openai','deepseek','qwen','compatible','local'):
        raise InputError('不支持的模型服务类型。')
    base,local=validate_endpoint(value)
    if provider=='openai' and base!='https://api.openai.com/v1':
        raise InputError('OpenAI 官方模式只接受 https://api.openai.com/v1；其他服务请选择兼容接口。')
    if provider=='deepseek' and base not in ('https://api.deepseek.com','https://api.deepseek.com/v1'):
        raise InputError('DeepSeek 官方模式只接受官方 API 地址；其他服务请选择兼容接口。')
    return base,local


def openai_reasoning_effort(model):
    if model.startswith(('gpt-6.1-sol','gpt-6-astra')):return 'low'
    if model.startswith(('gpt-6-luna','gpt-6-sol','gpt-6.1-terra')):return 'none'
    return None


def openai_format(probe=False,strict=True,quote_ids=None):
    if probe:
        name='connection_probe'
        schema={'type':'object','properties':{'ok':{'type':'boolean','enum':[True]}},
                'required':['ok'],'additionalProperties':False}
    elif strict:
        name='evidence_explanation'
        quote={'type':'object','properties':{'evidence_id':{'type':'string'},'quote':{'type':'string'}},
               'required':['evidence_id','quote'],'additionalProperties':False}
        claim={'type':'object','properties':{'text':{'type':'string'},
               'evidence_ids':{'type':'array','items':{'type':'string'}},
               'quotes':{'type':'array','items':quote}},
               'required':['text','evidence_ids','quotes'],'additionalProperties':False}
        if quote_ids:
            claim={'type':'object','properties':{'text':{'type':'string'},
                   'quote_ids':{'type':'array','items':{'type':'string','enum':quote_ids},'minItems':1,'maxItems':4}},
                   'required':['text','quote_ids'],'additionalProperties':False}
        schema={'type':'object','properties':{'claims':{'type':'array','items':claim},
                'follow_up_questions':{'type':'array','items':{'type':'string'}}},
                'required':['claims','follow_up_questions'],'additionalProperties':False}
    else:return {'type':'json_object'}
    # The application still validates evidence IDs, verbatim quotes and versions.
    return {'type':'json_schema','name':name,'strict':True,'schema':schema}


def parse_json_content(content):
    if not isinstance(content,str) or not content.strip():raise ModelError('模型返回空内容，请换用非思考模式或稍后重试。')
    text=content.strip()
    if text.startswith('```'):
        text=re.sub(r'^```(?:json)?\s*','',text,flags=re.I)
        text=re.sub(r'\s*```$','',text)
    try:result=json.loads(text)
    except (ValueError,TypeError) as error:raise ModelError('模型未返回完整 JSON，已保留证据结果。') from error
    if not isinstance(result,dict):raise ModelError('模型返回的 JSON 必须是对象。')
    return result


def usage_numbers(data):
    usage=data.get('usage',{})
    if not isinstance(usage,dict):return {}
    return {k:v for k,v in usage.items() if k in ('prompt_tokens','completion_tokens','total_tokens') and type(v) is int and v>=0}


def responses_usage(data):
    usage=data.get('usage',{})
    if not isinstance(usage,dict):return {}
    valid=lambda value:type(value) is int and value>=0
    result={k:usage[k] for k in ('input_tokens','output_tokens','total_tokens') if valid(usage.get(k))}
    for source,alias in (('input_tokens','prompt_tokens'),('output_tokens','completion_tokens')):
        if source in result:result[alias]=result[source]
    for key,names in (('input_tokens_details',('cached_tokens','cache_write_tokens')),
                      ('output_tokens_details',('reasoning_tokens',))):
        details=usage.get(key)
        if isinstance(details,dict):
            cleaned={name:details[name] for name in names if valid(details.get(name))}
            result.update(cleaned)
            if key=='input_tokens_details':
                writes=details.get('cache_write_tokens_details')
                if isinstance(writes,dict):
                    cleaned_writes={k:writes[k] for k in ('ttl_30m_tokens','ttl_12h_tokens') if valid(writes.get(k))}
                    if cleaned_writes:cleaned['cache_write_tokens_details']=cleaned_writes
            if cleaned:result[key]=cleaned
    return result


def luna_cost_estimate(data,usage):
    # Public Standard pricing checked 2026-10-30. Unknown fields are never zero.
    if data.get('model')!='gpt-6-luna' or data.get('service_tier')!='default':return None
    required=('input_tokens','output_tokens','cached_tokens','cache_write_tokens')
    if any(key not in usage for key in required):return None
    inputs,outputs,cached,written=(usage[key] for key in required)
    if cached+written>inputs:return None
    write_30,write_12=0,0
    if written:
        details=usage.get('input_tokens_details',{}).get('cache_write_tokens_details',{})
        if not all(k in details for k in ('ttl_30m_tokens','ttl_12h_tokens')):return None
        write_30,write_12=details['ttl_30m_tokens'],details['ttl_12h_tokens']
        if write_30+write_12!=written:return None
    multiplier=2 if inputs>272000 else 1
    output_multiplier=1.5 if inputs>272000 else 1
    amount=((inputs-cached-written)*.10*multiplier+cached*.01*multiplier+
            write_30*.125*multiplier+write_12*.25*multiplier+outputs*.50*output_multiplier)/1000000
    return {'currency':'USD','amount':round(amount,10),'estimated':True,'pricing_as_of':'2026-10-30',
            'model':'gpt-6-luna','basis':'public standard text token rates; excludes tax and regional premiums'}


def responses_text(data,metadata):
    status=data.get('status')
    if status=='incomplete':
        details=data.get('incomplete_details')
        reason=details.get('reason') if isinstance(details,dict) else None
        message=('模型回复触发内容限制，已保留本地证据。' if reason=='content_filter' else
                 '模型回复未正常完成或被截断，已保留本地证据；可缩短问题后重试。')
        raise ModelError(message,metadata)
    if status!='completed' or data.get('error'):
        raise ModelError('模型服务未完成回答，已保留本地证据。',metadata)
    output=data.get('output')
    if not isinstance(output,list):raise ModelError('模型服务响应缺少输出列表。',metadata)
    parts=[]
    for item in output:
        if not isinstance(item,dict):raise ModelError('模型服务输出格式错误。',metadata)
        if item.get('type')!='message':continue
        if item.get('role')!='assistant' or item.get('status','completed')!='completed':
            raise ModelError('模型消息未完整返回，已保留本地证据。',metadata)
        content=item.get('content')
        if not isinstance(content,list):raise ModelError('模型消息内容格式错误。',metadata)
        for part in content:
            if not isinstance(part,dict):raise ModelError('模型消息内容格式错误。',metadata)
            if part.get('type')=='refusal':raise ModelError('模型未提供本次解释，已保留本地证据。',metadata)
            if part.get('type')=='output_text':
                if not isinstance(part.get('text'),str):raise ModelError('模型没有返回可显示的回答。',metadata)
                parts.append(part['text'])
    text=''.join(parts)
    if not text.strip():raise ModelError('模型返回空内容，已保留本地证据。',metadata)
    return text


class ChatClient:
    def __init__(self,config):
        self.config=config

    def complete(self,messages,max_tokens=None,probe=False,quote_ids=None):
        c=self.config
        provider=c.get('provider','compatible')
        base,_=validate_provider_endpoint(c['base_url'],provider)
        is_openai=provider=='openai' or urlsplit(base).hostname=='api.openai.com'
        if is_openai:base,_=validate_provider_endpoint(base,'openai')
        if is_openai and not c.get('api_key'):
            raise ModelError('尚未配置 OpenAI API 密钥，真实模型仍待验收；请在本机设置窗口填写。')
        input_limit=c.get('max_input_bytes',48000)
        if type(input_limit) is not int or not 1<=input_limit<=48000:
            raise InputError('模型输入预算必须为 1 至 48000 字节的整数。')
        input_bytes=len(json.dumps(messages,ensure_ascii=False,separators=(',',':')).encode('utf-8'))
        if input_bytes>input_limit:
            raise ModelError('输入证据超过本轮模型预算，未调用模型；已保留本地证据。')
        limit=max_tokens if max_tokens is not None else c.get('max_output_tokens',2400)
        if type(limit) is not int or not 16<=limit<=16384:raise InputError('输出 token 上限必须为 16 至 16384 的整数。')
        effort=openai_reasoning_effort(c['model']) if is_openai else None
        if is_openai:
            payload={'model':c['model'],'input':messages,'stream':False,'store':False,'service_tier':'default',
                     'max_output_tokens':limit,'text':{'format':openai_format(probe,c.get('strict_citations',True),quote_ids)}}
            if effort:payload['reasoning']={'effort':effort}
            endpoint=base+'/responses'
        else:
            payload={'model':c['model'],'messages':messages,'stream':False,'temperature':0,'max_tokens':limit}
            if c.get('json_mode',True):payload['response_format']={'type':'json_object'}
            if provider=='deepseek' or urlsplit(base).hostname=='api.deepseek.com':payload['thinking']={'type':'disabled'}
            if provider=='qwen':payload['enable_thinking']=False
            endpoint=base+'/chat/completions'
        headers={'Content-Type':'application/json'}
        if c.get('api_key'):headers['Authorization']='Bearer '+c['api_key']
        guard=c.get('usage_guard')
        ticket=guard.reserve(c,payload) if guard else None
        try:
            result=self._request(payload,endpoint,headers,input_bytes,input_limit,limit,is_openai,effort,probe)
        except Exception as error:
            if guard:guard.finish(ticket,getattr(error,'metadata',None),'failed')
            raise
        if guard:guard.finish(ticket,result[1],'returned')
        return result

    def _request(self,payload,endpoint,headers,input_bytes,input_limit,limit,is_openai,effort,probe):
        c=self.config;provider=c.get('provider','compatible')
        started=time.perf_counter()
        try:
            # Redirects must not send credentials to another endpoint.
            with httpx.Client(timeout=20 if probe else 65,follow_redirects=False) as client:
                response=client.post(endpoint,headers=headers,json=payload)
                if response.status_code in (401,403):raise ModelError('模型服务鉴权失败，请检查密钥及其 API 访问权限。')
                if response.status_code==402:raise ModelError('模型账户余额或额度不足，请在服务商控制台检查。')
                if response.status_code==429:
                    try:
                        error_body=response.json()
                        error_info=error_body.get('error',{}) if isinstance(error_body,dict) else {}
                        error_code=error_info.get('code') if isinstance(error_info,dict) else None
                    except ValueError:error_code=None
                    if error_code in ('insufficient_quota','credit_balance_exhausted'):
                        raise ModelError('模型 API 额度不足，请在 API 平台确认已领取额度、所属组织及可用余额。')
                    raise ModelError('模型服务限流，请稍后重试。')
                if response.status_code==404:raise ModelError('模型名称或 API 地址不存在，请核对设置。')
                if not 200<=response.status_code<300:raise ModelError(f'模型服务返回 HTTP {response.status_code}，已保留本地证据。')
                data=response.json()
            if not isinstance(data,dict):raise ModelError('模型服务响应格式错误。')
            key=c.get('api_key','')
            def safe(value):
                text=str(value)[:180] if value is not None else None
                return text.replace(key,'[redacted]') if text and key else text
            metadata={'provider':'openai' if is_openai else provider,'requested_model':safe(c['model']),
                      'returned_model':safe(data.get('model')),'request_id':safe(data.get('id')),
                      'usage':responses_usage(data) if is_openai else usage_numbers(data),
                      'elapsed_ms':round((time.perf_counter()-started)*1000),'transport':'http-request',
                      'api_family':'responses' if is_openai else 'chat-completions','max_output_tokens':limit,
                      'input_bytes':input_bytes,'max_input_bytes':input_limit}
            if is_openai:
                metadata.update(api='responses',reasoning_effort=effort,store=False,service_tier=safe(data.get('service_tier')))
                cost=luna_cost_estimate(data,metadata['usage'])
                if cost:metadata['cost_estimate']=cost
                content=responses_text(data,metadata)
            else:
                choice=data['choices'][0]
                if choice.get('finish_reason') not in (None,'stop'):
                    raise ModelError('模型回复未正常完成或被截断，请缩短问题后重试。',metadata)
                content=choice['message']['content']
                if not isinstance(content,str):raise ModelError('模型没有返回可显示的回答。',metadata)
            return content,metadata
        except httpx.TimeoutException as error:raise ModelError('模型请求超时，未重复计费重试；可稍后再次提问。') from error
        except httpx.HTTPError as error:raise ModelError('无法连接模型服务，请检查网络和 API 地址。') from error
        except (KeyError,IndexError,TypeError,ValueError) as error:
            if isinstance(error,ModelError):raise
            raise ModelError('模型服务响应格式无效，已保留本地证据。') from error

    def probe(self):
        effort=openai_reasoning_effort(self.config['model']) if self.config.get('provider')=='openai' else None
        content,meta=self.complete([
            {'role':'system','content':'Return valid JSON only. Reply exactly {"ok":true}.'},
            {'role':'user','content':'验证本次 API 连接，仅返回 JSON 对象 {"ok":true}，不要其他内容。'}
        ],max_tokens=1024 if effort=='low' else 128,probe=True)
        if parse_json_content(content).get('ok') is not True:
            raise ModelError('已收到服务响应，但 JSON 连接验证未通过，请确认模型支持结构化输出。')
        return meta
