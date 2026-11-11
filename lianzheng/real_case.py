"""Read and import a frozen, provenance-preserving experiment without network calls."""
import hashlib
import json
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from .domain import InputError, parse_bom
from .lockfiles import convert_package_lock
from .osv import evidence_documents, findings_for
from .store import now


class _VerifiedFiles(dict):
    """Paths for metadata plus the exact bytes validated in this bundle read."""
    def __init__(self, manifest_bytes):
        super().__init__()
        self.contents={}
        self.manifest_bytes=manifest_bytes


class RealCase:
    def __init__(self, service, directory):
        self.service=service
        self.directory=Path(directory)

    @staticmethod
    def _relative(name):
        if not isinstance(name,str) or not name or '\\' in name or ':' in name or any(ord(c)<32 or ord(c)==127 for c in name):
            raise InputError('案例文件路径无效。')
        path=PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or str(path)!=name or any(part!=part.rstrip(' .') for part in path.parts):
            raise InputError('案例文件路径无效。')
        return path

    def _bundle(self):
        manifests=sorted(self.directory.glob('*/case.json'))
        if not manifests:raise KeyError('尚未安装真实案例包。')
        if len(manifests)!=1:raise InputError('当前版本需要唯一的固定案例包。')
        manifest=manifests[0]
        if manifest.is_symlink():raise InputError('案例清单不能是符号链接。')
        raw=manifest.read_bytes()
        try:case=json.loads(raw)
        except (ValueError,UnicodeError):raise InputError('案例清单不是有效的 UTF-8 JSON。')
        if (not isinstance(case,dict) or not isinstance(case.get('files'),list) or
            not all(isinstance(case.get(k),str) and case[k] for k in ('id','title')) or
            not isinstance(case.get('source'),dict) or not isinstance(case.get('target'),dict) or
            not isinstance(case['target'].get('advisory_id'),str) or not case['target']['advisory_id'] or
            not isinstance(case.get('tests',{}),dict) or
            not isinstance(case.get('limitations',[]),list) or
            ('project' in case and (not isinstance(case['project'],str) or not case['project']))):
            raise InputError('案例清单缺少有效的来源、目标公告或文件列表。')
        base=manifest.parent.resolve();files=_VerifiedFiles(raw);names=set()
        if not base.is_relative_to(self.directory.resolve()):raise InputError('案例目录超出允许范围。')
        for entry in case['files']:
            if not isinstance(entry,dict) or not isinstance(entry.get('sha256'),str) or len(entry['sha256'])!=64:
                raise InputError('案例文件条目缺少有效的 SHA-256。')
            name=entry.get('name');relative=self._relative(name);path=base/str(relative)
            if name.casefold() in names or name.casefold()=='case.json':raise InputError('案例文件清单重复。')
            names.add(name.casefold())
            if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(base):
                raise InputError('案例文件不存在或超出案例目录。')
            if path.stat().st_size>40*1024*1024:raise InputError('案例文件过大。')
            content=path.read_bytes()
            if len(content)>40*1024*1024:raise InputError('案例文件过大。')
            if hashlib.sha256(content).hexdigest()!=entry['sha256']:
                raise InputError('案例文件校验失败，请恢复原始案例包后重试。')
            files[name]=path;files.contents[name]=content
        required=('before_lockfile','after_lockfile','osv_snapshot')+(('partial_lockfile',) if case.get('partial_lockfile') else ())
        for field in required:
            if not isinstance(case.get(field),str):raise InputError('案例缺少必需的证据文件。')
            if case.get(field) not in files:raise InputError('案例缺少必需的证据文件。')
        for phase in ('before','partial','after'):
            test=case.get('tests',{}).get(phase,{})
            if not isinstance(test,dict):raise InputError('案例测试记录格式不正确。')
            log=test.get('log_file')
            if log and not isinstance(log,str):raise InputError('测试日志路径无效。')
            if log and log not in files:raise InputError('测试日志不在案例文件清单中。')
        return case,files,hashlib.sha256(raw).hexdigest(),manifest

    def _plans(self,case,files,digest):
        def decoded(name):
            try:return json.loads(files.contents[name].decode('utf-8'))
            except (ValueError,UnicodeError):raise InputError('案例证据文件不是有效的 UTF-8 JSON。')
        frozen=decoded(case['osv_snapshot'])
        if not isinstance(frozen,dict):raise InputError('案例漏洞证据格式不完整。')
        records=frozen.get('records');stamp=frozen.get('fetched_at');plans=[]
        if not isinstance(records,dict) or not isinstance(stamp,str) or not stamp:
            raise InputError('案例漏洞证据格式不完整。')
        phases=('before','partial','after') if case.get('partial_lockfile') else ('before','after')
        if case.get('partial_lockfile') and case['partial_lockfile'] not in files:raise InputError('案例缺少部分修复清单。')
        for phase in phases:
            raw=decoded(case[phase+'_lockfile'])
            bom=convert_package_lock(raw);graph=parse_bom(bom)
            for prop in bom.get('metadata',{}).get('properties',[]):
                if prop.get('name')=='lianzheng:import:warning':
                    graph['issues'].append({'code':'import_warning','message':prop['value'][:1500]})
            identifier='case-'+digest[:20]+'-'+phase
            scans={};documents=[];hits=0
            for node in graph['nodes']:
                if node['root']:continue
                key=f"npm:{node.get('package_name')}:{node.get('package_version')}"
                data=records.get(key)
                if isinstance(data,dict) and isinstance(data.get('vulns',[]),list) and not data.get('next_page_token'):
                    ids=[v.get('id') if isinstance(v,dict) else None for v in data.get('vulns',[])]
                    if any(not isinstance(v,str) or not v for v in ids) or len(set(ids))!=len(ids):
                        raise InputError('案例漏洞记录缺少公告标识或存在重复标识。')
                    scan={'status':'checked','source':'frozen-case-osv','fetched_at':stamp,'data':data,'error':None}
                else:
                    scan={'status':'unscanned','source':'none','fetched_at':None,'data':{},'error':'固定案例未包含此精确版本的完整查询记录。'}
                scans[node['id']]=scan
                if node.get('package_name'):
                    try:
                        hits+=sum(x['id']==case['target']['advisory_id'] for x in findings_for(node,scan))
                        documents.extend(evidence_documents(identifier,node,scan))
                    except (TypeError,KeyError,AttributeError):
                        raise InputError('案例漏洞记录的包匹配或严重程度字段格式不正确。')
            canonical=json.dumps(bom,sort_keys=True,ensure_ascii=False).encode()
            plans.append({'id':identifier,'phase':phase,'raw_lockfile':raw,'raw':bom,'graph':graph,
                          'hash':hashlib.sha256(canonical).hexdigest(),'scans':scans,'documents':documents,
                          'target_count':hits,'unknown':sum(x['status']!='checked' for x in scans.values())})
        return plans

    def status(self):
        try:case,files,digest,manifest=self._bundle()
        except KeyError:return {'available':False,'prepared':False,'title':'真实修复案例','limitations':['尚未安装案例证据包。']}
        plans=self._plans(case,files,digest);left,right=plans[0],plans[-1]
        partial=next((p for p in plans if p['phase']=='partial'),None)
        prepared=True
        for plan in plans:
            try:
                item=self.service.store.get(plan['id'])
                if item['hash']!=plan['hash']:raise InputError('案例快照与固定证据不一致。')
            except KeyError:prepared=False
        verification={'kind':'recorded-experiment','target_before_count':left['target_count'],
                      'target_after_count':right['target_count'],
                      'target_partial_count':partial['target_count'] if partial else None,
                      'before_components':len(left['scans']),'after_components':len(right['scans']),
                      'before_unknown':left['unknown'],'after_unknown':right['unknown'],
                      'before_graph_complete':left['graph']['complete'],'after_graph_complete':right['graph']['complete'],
                      'same_knowledge_snapshot':True,
                      'comparison_complete':left['graph']['complete'] and right['graph']['complete'] and not left['unknown'] and not right['unknown']}
        current=None
        if prepared:
            a=self.service.analyze(left['id'],include_documents=False,include_paths=False)
            b=self.service.analyze(right['id'],include_documents=False,include_paths=False)
            current={'target_before_count':sum(x['id']==case['target']['advisory_id'] for x in a['findings']),
                     'target_after_count':sum(x['id']==case['target']['advisory_id'] for x in b['findings']),
                     'basis_matches_recorded':all(self.service.store.scans(p['id'])==p['scans'] for p in plans)}
        links=[{**entry,'url':'/api/real-case/files/'+quote(entry['name'],safe='/')} for entry in case['files']]
        links.insert(0,{'name':'case.json','label':'案例来源与实验说明','sha256':digest,'url':'/api/real-case/files/case.json'})
        return {'available':True,'prepared':prepared,'id':case['id'],'title':case['title'],
                'project':case.get('project',case['title']),'source':case['source'],'focus':case['target']['advisory_id'],
                'target':case['target'],'before_snapshot_id':left['id'] if prepared else None,
                'after_snapshot_id':right['id'] if prepared else None,
                'partial_snapshot_id':partial['id'] if prepared and partial else None,'verification':verification,'current':current,
                'tests':case.get('tests',{}),'limitations':case.get('limitations',[]),'files':links,
                'bundle_sha256':digest,'recorded':True,
                'note':'固定公开源码上的本地修复实验；不是上游已合并的修复或客户生产验证。载入仅恢复冻结证据，不重新执行测试、查询或调用模型。'}

    def prepare(self):
        case,files,digest,manifest=self._bundle();plans=self._plans(case,files,digest)
        # Import both snapshots, original locks and evidence in one transaction.
        # Repeating this action never replaces existing scans or user annotations.
        with self.service.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS lockfile_sources(snapshot_id TEXT PRIMARY KEY REFERENCES snapshots(id),source TEXT NOT NULL)')
            for plan in plans:
                existing=db.execute('SELECT hash FROM snapshots WHERE id=?',(plan['id'],)).fetchone()
                if existing:
                    if existing['hash']!=plan['hash']:raise InputError('案例快照冲突，未覆盖已有数据。')
                    continue
                db.execute('INSERT INTO snapshots VALUES(?,?,?,?,?,?,?,?)',
                           (plan['id'],case.get('project',case['title']),
                            {'before':'真实上游锁文件 · 修复前','partial':'本地实际更新 · 仅直接依赖','after':'本地实际更新锁文件 · 修复后'}[plan['phase']],
                            now(),plan['hash'],0,json.dumps(plan['raw']),json.dumps(plan['graph'])))
                db.execute('INSERT INTO lockfile_sources VALUES(?,?)',(plan['id'],json.dumps(plan['raw_lockfile'],ensure_ascii=False)))
                for ref,scan in plan['scans'].items():db.execute('INSERT INTO scans VALUES(?,?,?)',(plan['id'],ref,json.dumps(scan)))
                for doc in plan['documents']:db.execute('INSERT INTO documents VALUES(?,?,?)',(doc['id'],plan['id'],json.dumps(doc)))
        return self.status()

    def file(self,name):
        self._relative(name)
        case,files,digest,manifest=self._bundle()
        if name=='case.json':return manifest
        if name not in files:raise KeyError('案例文件不存在。')
        return files[name]

    def file_bytes(self,name):
        """Return a verified immutable download, without reopening a checked path."""
        relative=self._relative(name)
        case,files,digest,manifest=self._bundle()
        if name=='case.json':return 'case.json',files.manifest_bytes
        if name not in files:raise KeyError('案例文件不存在。')
        return relative.name,files.contents[name]
