"""Local server settings; credential values are never returned to the browser."""
import base64
import ctypes
import json
import os
from pathlib import Path
from threading import RLock
from urllib.parse import urlsplit

from .domain import InputError
from .providers import ChatClient,validate_endpoint
from .store import now


def protect_key(value):
    if not value:return None
    if os.name!='nt':return {'format':'local-file','value':value}
    class Blob(ctypes.Structure):
        _fields_=[('size',ctypes.c_ulong),('data',ctypes.POINTER(ctypes.c_ubyte))]
    raw=value.encode();buffer=ctypes.create_string_buffer(raw)
    source=Blob(len(raw),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)));result=Blob()
    crypt=ctypes.WinDLL('crypt32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    if not crypt.CryptProtectData(ctypes.byref(source),None,None,None,None,1,ctypes.byref(result)):
        raise InputError('Windows 本机密钥加密失败，配置未保存。')
    try:return {'format':'windows-dpapi','value':base64.b64encode(ctypes.string_at(result.data,result.size)).decode()}
    finally:kernel.LocalFree(result.data)


def unprotect_key(value):
    if not value:return ''
    if value['format']=='local-file':return value['value']
    if value['format']!='windows-dpapi' or os.name!='nt':raise ValueError('密钥不属于当前系统')
    class Blob(ctypes.Structure):
        _fields_=[('size',ctypes.c_ulong),('data',ctypes.POINTER(ctypes.c_ubyte))]
    raw=base64.b64decode(value['value']);buffer=ctypes.create_string_buffer(raw)
    source=Blob(len(raw),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)));result=Blob()
    crypt=ctypes.WinDLL('crypt32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    if not crypt.CryptUnprotectData(ctypes.byref(source),None,None,None,None,1,ctypes.byref(result)):
        raise ValueError('无法解密本机密钥')
    try:return ctypes.string_at(result.data,result.size).decode()
    finally:kernel.LocalFree(result.data)


def env_file(path):
    values={}
    if not path or not Path(path).is_file():return values
    for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
        text=line.strip()
        if not text or text.startswith('#') or '=' not in text:continue
        key,value=text.split('=',1);key=key.strip();value=value.strip()
        if key.startswith('LZ_') or key=='DEEPSEEK_API_KEY':
            if len(value)>=2 and value[0]==value[-1] and value[0] in ('"',"'"):value=value[1:-1]
            values[key]=value
    return values


class ModelSettings:
    def __init__(self,path,dotenv=None):
        self.path=Path(path);self.dotenv=dotenv;self.lock=RLock();self.saved=None;self.load_error=None
        if self.path.exists():
            try:
                value=json.loads(self.path.read_text(encoding='utf-8'))
                value['api_key']=unprotect_key(value.pop('protected_key',None))
                self.saved=value
            except (ValueError,KeyError,TypeError,OSError):self.load_error='本机模型配置无法读取，请重新填写并测试。'

    def current(self):
        with self.lock:
            if self.saved is not None:return dict(self.saved)
        env=env_file(self.dotenv)
        def get(key,default=''):return os.getenv(key,env.get(key,default))
        key=get('LZ_LLM_API_KEY') or get('DEEPSEEK_API_KEY')
        base=get('LZ_LLM_BASE_URL') or ('https://api.deepseek.com' if key else '')
        provider='deepseek' if urlsplit(base).hostname=='api.deepseek.com' else 'compatible'
        return {'base_url':base,'model':get('LZ_LLM_MODEL') or ('deepseek-flash' if provider=='deepseek' else ''),
                'provider':provider,'api_key':key,'json_mode':True,'remember_key':False,'verification':None,
                'strict_citations':True}

    def public(self):
        current=self.current()
        try:
            safe_base,local=validate_endpoint(current.get('base_url',''));valid_endpoint=True
        except InputError:safe_base='';local=False;valid_endpoint=False
        configured=bool(valid_endpoint and current.get('model') and (current.get('api_key') or local))
        return {'provider':current.get('provider','deepseek'),'base_url':safe_base,
                'model':current.get('model',''),'has_key':bool(current.get('api_key')),'configured':configured,
                'json_mode':current.get('json_mode',True),'verified':bool(current.get('verification')),
                'verification':current.get('verification'),'remember_key':current.get('remember_key',False),
                'storage':'windows-dpapi' if os.name=='nt' else 'local-file-permissions',
                'load_error':self.load_error}

    def candidate(self,payload):
        base,local=validate_endpoint(payload['base_url'].strip())
        provider=payload.get('provider','deepseek')
        if provider not in ('deepseek','qwen','compatible','local'):raise InputError('不支持的模型服务类型。')
        if provider=='deepseek' and base not in ('https://api.deepseek.com','https://api.deepseek.com/v1'):
            raise InputError('DeepSeek 官方模式只接受官方 API 地址；其他服务请选择兼容接口。')
        current=self.current();key=payload.get('api_key','').strip()
        if not key and base==current.get('base_url') and provider==current.get('provider'):key=current.get('api_key','')
        if not key and not local:raise InputError('尚未配置 API 密钥，请在本机设置窗口填写。')
        model=payload['model'].strip()
        if not model:raise InputError('请填写模型名称。')
        if any(c in key for c in ('\r','\n','\x00')):raise InputError('密钥包含无效字符。')
        return {'provider':provider,'base_url':base,'model':model,'api_key':key,
                'json_mode':payload.get('json_mode',True),'remember_key':payload.get('remember_key',True),
                'verification':None,'strict_citations':True}

    def test_and_save(self,payload):
        candidate=self.candidate(payload)
        meta=ChatClient(candidate).probe()
        candidate['verification']={**meta,'verified_at':now()}
        disk={k:v for k,v in candidate.items() if k!='api_key'}
        # Memory-only keys do not leave a persistent 'verified' claim after restart.
        if candidate['remember_key']:
            disk['protected_key']=protect_key(candidate['api_key'])
        else:
            disk['protected_key']=None
            disk['verification']=None
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temp=self.path.with_suffix('.tmp')
        with self.lock:
            try:
                temp.write_text(json.dumps(disk,ensure_ascii=False,indent=2),encoding='utf-8')
                os.chmod(temp,0o600);temp.replace(self.path)
            except OSError as error:raise InputError('模型验证已返回，但本机配置保存失败，请检查目录权限。') from error
            self.saved=candidate;self.load_error=None
        return self.public()
