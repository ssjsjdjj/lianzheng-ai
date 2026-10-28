"""Small, bounded Chat Completions client. Never surface raw provider errors or keys."""
import json
import re
import time
from urllib.parse import urlsplit

import httpx

from .domain import InputError


class ModelError(ValueError):
    pass


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
        if parts.path.rstrip('/').endswith(('/chat/completions','/embeddings')):raise ValueError()
        _=parts.port
    except ValueError as error:
        raise InputError('请填写 HTTPS API 前缀；本地服务可用 HTTP。地址不能包含密钥、账号或完整请求路径。') from error
    return value.rstrip('/'),local


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


class ChatClient:
    def __init__(self,config):
        self.config=config

    def complete(self,messages,max_tokens=None,probe=False):
        c=self.config
        base,_=validate_endpoint(c['base_url'])
        payload={'model':c['model'],'messages':messages,'stream':False,'temperature':0,
                 'max_tokens':max_tokens or 2400}
        if c.get('json_mode',True):payload['response_format']={'type':'json_object'}
        if c.get('provider')=='deepseek' or urlsplit(base).hostname=='api.deepseek.com':
            payload['thinking']={'type':'disabled'}
        if c.get('provider')=='qwen':payload['enable_thinking']=False
        headers={'Content-Type':'application/json'}
        if c.get('api_key'):headers['Authorization']='Bearer '+c['api_key']
        started=time.perf_counter()
        try:
            # Redirects must not send credentials to another endpoint.
            with httpx.Client(timeout=20 if probe else 65,follow_redirects=False) as client:
                response=client.post(base+'/chat/completions',headers=headers,json=payload)
                if response.status_code in (401,403):raise ModelError('模型服务鉴权失败，请检查密钥及其 API 访问权限。')
                if response.status_code==402:raise ModelError('模型账户余额或额度不足，请在服务商控制台检查。')
                if response.status_code==429:raise ModelError('模型服务限流，请稍后重试。')
                if response.status_code==404:raise ModelError('模型名称或 API 地址不存在，请核对设置。')
                if not 200<=response.status_code<300:raise ModelError(f'模型服务返回 HTTP {response.status_code}，已保留本地证据。')
                data=response.json()
            if not isinstance(data,dict):raise ModelError('模型服务响应格式错误。')
            choices=data['choices']
            choice=choices[0]
            if choice.get('finish_reason') not in (None,'stop'):
                raise ModelError('模型回复未正常完成或被截断，请缩短问题后重试。')
            content=choice['message']['content']
            if not isinstance(content,str):raise ModelError('模型没有返回可显示的回答。')
            key=c.get('api_key','')
            def safe(value):
                text=str(value)[:180] if value is not None else None
                return text.replace(key,'[redacted]') if text and key else text
            metadata={'provider':c.get('provider','compatible'),'requested_model':c['model'],
                      'returned_model':safe(data.get('model')),'request_id':safe(data.get('id')),
                      'usage':usage_numbers(data),'elapsed_ms':round((time.perf_counter()-started)*1000),
                      'transport':'http-request'}
            return content,metadata
        except httpx.TimeoutException as error:raise ModelError('模型请求超时，未重复计费重试；可稍后再次提问。') from error
        except httpx.HTTPError as error:raise ModelError('无法连接模型服务，请检查网络和 API 地址。') from error
        except (KeyError,IndexError,TypeError,ValueError) as error:
            if isinstance(error,ModelError):raise
            raise ModelError('模型服务响应格式无效，已保留本地证据。') from error

    def probe(self):
        content,meta=self.complete([
            {'role':'system','content':'Return valid JSON only. Reply exactly {"ok":true}.'},
            {'role':'user','content':'验证本次 API 连接，仅返回 JSON 对象 {"ok":true}，不要其他内容。'}
        ],max_tokens=128,probe=True)
        if parse_json_content(content).get('ok') is not True:
            raise ModelError('已收到服务响应，但 JSON 连接验证未通过，请确认模型支持结构化输出。')
        return meta
