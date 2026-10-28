import hashlib
import json
from pathlib import Path

import httpx

from .domain import affected_fixed_versions
from .store import now


class OSVClient:
    def __init__(self, store, fixtures: Path):
        self.store = store
        self.fixture = json.loads((fixtures/'osv-cache.json').read_text(encoding='utf-8'))

    def query(self, name, version, live=False):
        key = f'npm:{name}:{version}'
        if not live:
            if key in self.fixture['records']:
                return {'status':'checked', 'source':'frozen-osv', 'fetched_at':self.fixture['fetched_at'],
                        'data':self.fixture['records'][key], 'error':None}
            cached = self.store.cache_get(key)
            if cached:
                return {**cached, 'source':'cached-osv'}
            return {'status':'unscanned', 'source':'none', 'fetched_at':None,
                    'data':{}, 'error':'本地无此精确版本记录；请手动执行在线扫描。'}
        try:
            records, token, pages = {}, None, 0
            with httpx.Client(timeout=20, follow_redirects=False) as client:
                while True:
                    payload = {'version':version, 'package':{'name':name, 'ecosystem':'npm'}}
                    if token:
                        payload['page_token'] = token
                    response = client.post('https://api.osv.dev/v1/query', json=payload)
                    response.raise_for_status()
                    result = response.json()
                    if not isinstance(result, dict):
                        raise ValueError('OSV 响应不是对象')
                    for record in result.get('vulns', []):
                        if not isinstance(record, dict) or not isinstance(record.get('id'), str):
                            raise ValueError('OSV 漏洞记录格式错误')
                        records[record['id']] = record
                    token = result.get('next_page_token'); pages += 1
                    if not token:
                        break
                    if pages >= 20:
                        raise ValueError('OSV 分页超出上限，不能声明扫描完成')
            value = {'status':'checked','source':'live-osv','fetched_at':now(),'data':{'vulns':list(records.values())},'error':None}
            self.store.cache_put(key, value)
            return value
        except (httpx.HTTPError, ValueError, TypeError) as error:
            return {'status':'failed','source':'live-osv','fetched_at':now(),'data':{},
                    'error':f'在线查询失败，未得出无漏洞结论：{type(error).__name__}'}


def severity(record):
    label = record.get('database_specific', {}).get('severity', 'UNKNOWN').upper()
    return label if label in {'CRITICAL','HIGH','MODERATE','LOW'} else 'UNKNOWN'


def findings_for(node, result):
    return [{'id':v['id'], 'summary':v.get('summary',v['id']), 'severity':severity(v),
             'aliases':v.get('aliases',[]), 'fixed_versions':affected_fixed_versions(v,node['package_name']),
             'ref':node['id'], 'package':node['package_name'], 'version':node['package_version'],
             'source':result['source'],'fetched_at':result['fetched_at'],
             'url':f"https://osv.dev/vulnerability/{v['id']}"}
            for v in result.get('data',{}).get('vulns',[]) if not v.get('withdrawn')]


def evidence_documents(snapshot, node, result):
    documents=[]
    for vuln in result.get('data',{}).get('vulns',[]):
        if vuln.get('withdrawn'):
            continue
        text = f"{vuln.get('summary', '')}\n{vuln.get('details', '')}"
        fixed = affected_fixed_versions(vuln,node['package_name'])
        text += '\n匹配包：'+node['package_name']+'；匹配版本：'+node['package_version']
        text += '\n该包公告中的修复边界：'+(', '.join(fixed) or '未声明')
        identifier = hashlib.sha256(f"{snapshot}:{node['id']}:{vuln['id']}".encode()).hexdigest()[:16]
        documents.append({'id':identifier,'vulnerability':vuln['id'],'package':node['package_name'],
                          'version':node['package_version'],'ref':node['id'],'title':vuln.get('summary',vuln['id']),
                          'text':text,'url':f"https://osv.dev/vulnerability/{vuln['id']}",
                          'locator':f"OSV {vuln['id']} details / affected",'fetched_at':result['fetched_at'],
                          'source':result['source'],'hash':hashlib.sha256(text.encode()).hexdigest()})
    return documents
