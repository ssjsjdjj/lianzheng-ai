import json
import os
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .domain import InputError
from .service import Service
from .providers import ModelError
from .reports import report_html
from .remediation import RemediationTasks
from .claim_review import ClaimReviews
from .simulation import RepairSimulation
from .real_case import RealCase

ROOT=Path(__file__).resolve().parent.parent


class Question(BaseModel):
    question:str=Field(min_length=1,max_length=2000)
    focus:str | None=None
    mode:str='graph'
    use_model:bool=False
    parent_id:int | None=Field(default=None,ge=1)


class ModelConnection(BaseModel):
    provider:str='openai'
    base_url:str=Field(min_length=1,max_length=2000)
    model:str=Field(min_length=1,max_length=160)
    api_key:str=Field(default='',max_length=8192,json_schema_extra={'writeOnly':True})
    json_mode:bool=True
    remember_key:bool=True


class ScanRequest(BaseModel):
    live:bool=False


class DocumentRequest(BaseModel):
    title:str=Field(min_length=1,max_length=160)
    package:str=Field(min_length=1,max_length=214)
    version:str=Field(min_length=1,max_length=100)
    target_version:str | None=Field(default=None,max_length=100)
    kind:str='migration'
    text:str=Field(min_length=1,max_length=200000)
    url:str=Field(default='',max_length=2000)


class TaskCreate(BaseModel):
    focus:str=Field(min_length=1,max_length=200)
    title:str | None=Field(default=None,max_length=200)
    owner:str=Field(default='',max_length=120)


class TaskPatch(BaseModel):
    revision:int=Field(ge=1,strict=True)
    title:str | None=Field(default=None,max_length=200)
    owner:str | None=Field(default=None,max_length=120)
    status:str | None=None
    note:str | None=Field(default=None,max_length=2000)
    checks:dict | None=None


class TaskVerify(BaseModel):
    revision:int=Field(ge=1,strict=True)
    after_snapshot_id:str=Field(min_length=1,max_length=200)


class ReviewSave(BaseModel):
    status:str
    note:str=Field(default='',max_length=1000)
    fingerprint:str=Field(min_length=64,max_length=64)
    revision:int=Field(ge=0,strict=True)


class CallPolicy(BaseModel):
    daily_calls:int=Field(ge=1,le=1000,strict=True)
    daily_budget_usd:float | None=Field(default=None,ge=.001,le=100,allow_inf_nan=False)
    enabled:bool=Field(default=True,strict=True)


class SimulationRequest(BaseModel):
    focus:str=Field(min_length=1,max_length=200)
    selected_refs:list[str]=Field(default_factory=list,max_length=2000)


def create_app(database=None,seed=True):
    service=Service(database or os.getenv('LZ_DATABASE',str(ROOT/'data/lianzheng.sqlite3')),ROOT/'fixtures')
    if seed:service.seed()
    app=FastAPI(title='链证 AI',version='0.7.0',description='本地 GraphRAG 软件依赖风险工作台。')
    app.state.service=service
    tasks=RemediationTasks(service);reviews=ClaimReviews(service)
    simulation=RepairSimulation(service);real_case=RealCase(service,ROOT/'fixtures/real-case')

    @app.post('/api/snapshots/{identifier}/simulation')
    def simulate(identifier:str,body:SimulationRequest):
        return simulation.preview(identifier,body.focus,body.selected_refs)

    @app.get('/api/real-case')
    def case_status():return real_case.status()

    @app.post('/api/real-case/prepare')
    def case_prepare():return real_case.prepare()

    @app.get('/api/real-case/files/{name:path}')
    def case_file(name:str):
        filename,content=real_case.file_bytes(name)
        return Response(content,media_type='application/octet-stream',
                        headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(filename,safe='')})

    @app.get('/api/model/usage')
    def model_usage():return service.call_control.public()

    @app.put('/api/model/usage/policy')
    def model_policy(body:CallPolicy):return service.call_control.update(body.model_dump())

    @app.get('/api/snapshots/{identifier}/tasks')
    def list_tasks(identifier:str):return tasks.list(identifier)

    @app.post('/api/snapshots/{identifier}/tasks',status_code=201)
    def add_task(identifier:str,body:TaskCreate):return tasks.create(identifier,body.focus,body.title,body.owner)

    @app.get('/api/tasks/{task_id}')
    def task(task_id:str):return tasks.get(task_id)

    @app.patch('/api/tasks/{task_id}')
    def update_task(task_id:str,body:TaskPatch):
        return tasks.update(task_id,body.model_dump(exclude_unset=True,exclude={'revision'}),expected_revision=body.revision)

    @app.post('/api/tasks/{task_id}/verify')
    def verify_task(task_id:str,body:TaskVerify):return tasks.verify(task_id,body.after_snapshot_id,expected_revision=body.revision)

    @app.get('/api/tasks/{task_id}/report')
    def task_report(task_id:str):
        return Response(json.dumps(tasks.report(task_id),ensure_ascii=False,indent=2),media_type='application/json',
                        headers={'Content-Disposition':'attachment; filename="remediation-task.json"'})

    @app.get('/api/snapshots/{identifier}/history/{answer_id}/reviews')
    def answer_reviews(identifier:str,answer_id:int):return reviews.get(identifier,answer_id)

    @app.put('/api/snapshots/{identifier}/history/{answer_id}/reviews/{claim_index}')
    def save_review(identifier:str,answer_id:int,claim_index:int,body:ReviewSave):
        return reviews.save(identifier,answer_id,claim_index,body.status,body.note,
                            expected_fingerprint=body.fingerprint,expected_revision=body.revision)

    @app.get('/benchmark',include_in_schema=False)
    def benchmark_report():
        report=ROOT/'evaluation/benchmark-results.html'
        if not report.is_file():return JSONResponse({'detail':'尚未生成离线评测报告。'},status_code=404)
        return FileResponse(report,media_type='text/html')

    @app.middleware('http')
    async def headers(request,call_next):
        origin=request.headers.get('origin')
        if request.method not in ('GET','HEAD','OPTIONS') and origin and origin.rstrip('/')!=str(request.base_url).rstrip('/'):
            return JSONResponse({'detail':'不允许跨站修改本地数据。'},status_code=403)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='DENY'
        if request.url.path.startswith('/api/'):response.headers['Cache-Control']='no-store'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        if request.url.path in ('/docs','/redoc','/docs/oauth2-redirect'):
            # FastAPI's generated documentation uses a CDN and an inline bootstrap.
            # The application UI retains the stricter policy above.
            response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.exception_handler(InputError)
    async def input_error(request,error):return JSONResponse({'detail':str(error)},status_code=400)

    @app.exception_handler(KeyError)
    async def missing(request,error):return JSONResponse({'detail':'快照或资源不存在。'},status_code=404)

    @app.exception_handler(ModelError)
    async def model_error(request,error):return JSONResponse({'detail':str(error)},status_code=400)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request,error):
        # The default validation body echoes input, which may include an API key.
        return JSONResponse({'detail':'请求参数未通过校验，请检查字段类型、必填项和长度。'},status_code=422)

    @app.get('/api/health')
    def health():
        return {'status':'ok','version':'0.7.0','llm_configured':service.models.public()['configured'],
                'llm_verified':service.models.public()['verified'],'model':service.models.public(),
                'embedding_configured':bool(os.getenv('LZ_EMBEDDING_BASE_URL') and os.getenv('LZ_EMBEDDING_MODEL')),
                'osv_snapshot':service.osv.fixture['fetched_at'],'local_only':True}

    @app.get('/api/model/settings')
    def model_settings():return service.models.public()

    @app.post('/api/model/connect')
    def model_connect(body:ModelConnection):return service.models.test_and_save(body.model_dump())

    @app.post('/api/demo/prepare')
    def demo_prepare():
        service.seed()
        document=service.import_document('demo-before',{
            'title':'参赛演示迁移检查 人为样例','package':'lodash','version':'4.17.20',
            'target_version':service.osv.fixture['demo_resolved_version'],'kind':'migration','url':'',
            'text':(ROOT/'fixtures/migration-demo.md').read_text(encoding='utf-8')})
        return {'initial':'demo-before','partial':'demo-partial','resolved':'demo-resolved',
                'focus':'GHSA-29mw-wpgm-hmr9','target_version':service.osv.fixture['demo_resolved_version'],
                'document':document,'model_verified':service.models.public()['verified']}

    @app.get('/api/demo/report')
    def demo_report():
        analysis=service.analyze('demo-before')
        history=service.store.history('demo-before')
        analysis['remediation_tasks']=tasks.list('demo-before')
        analysis['claim_reviews']=[reviews.get('demo-before',h['id']) for h in history if (h['answer'].get('model_explanation') or {}).get('claims')]
        comparisons=[('仅升级一条路径',service.compare('demo-before','demo-partial')),
                     ('两条路径均已升级',service.compare('demo-before','demo-resolved'))]
        return Response(report_html(analysis,history,comparisons,service.models.public()),media_type='text/html',
                        headers={'Content-Disposition':'attachment; filename="lianzheng-demo-report.html"'})

    @app.get('/api/snapshots')
    def snapshots():return service.list_snapshots()

    @app.post('/api/snapshots',status_code=201)
    async def import_snapshot(request:Request):
        chunks=[];size=0
        async for chunk in request.stream():
            size+=len(chunk)
            if size>5*1024*1024:raise InputError('单次导入文件最多 5 MB。')
            chunks.append(chunk)
        try:
            payload=json.loads(b''.join(chunks))
            if not isinstance(payload,dict):raise InputError('请求必须是 JSON 对象。')
            raw=payload.get('bom',payload)
            project=payload.get('project') if 'bom' in payload else None
            label=payload.get('label') if 'bom' in payload else None
            if any(x is not None and (not isinstance(x,str) or len(x)>120) for x in (project,label)):
                raise InputError('项目与快照名称必须为不超过 120 字的文本。')
            importer=service.import_lockfile if isinstance(raw,dict) and 'lockfileVersion' in raw else service.import_bom
            return await run_in_threadpool(importer,raw,project,label)
        except (json.JSONDecodeError,UnicodeDecodeError,TypeError,AttributeError) as error:
            raise InputError('JSON 内容或 CycloneDX 字段结构无效。') from error

    @app.get('/api/snapshots/{identifier}')
    def snapshot(identifier:str,focus:str | None=None):return service.analyze(identifier,focus)

    @app.post('/api/snapshots/{identifier}/scan')
    def scan(identifier:str,body:ScanRequest):return service.scan(identifier,body.live)

    @app.post('/api/snapshots/{identifier}/ask')
    def ask(identifier:str,body:Question):
        if body.mode not in ('graph','text'):raise InputError('mode 必须为 graph 或 text。')
        if not body.question.strip():raise InputError('问题不能为空。')
        return service.ask(identifier,body.question.strip(),body.focus,body.mode,body.use_model,body.parent_id)

    @app.get('/api/snapshots/{identifier}/history')
    def history(identifier:str):
        service.store.get(identifier)
        return service.store.history(identifier)

    @app.get('/api/snapshots/{identifier}/documents')
    def documents(identifier:str):return service.list_documents(identifier)

    @app.post('/api/snapshots/{identifier}/documents',status_code=201)
    def add_document(identifier:str,body:DocumentRequest):
        return service.import_document(identifier,body.model_dump())

    @app.get('/api/snapshots/{identifier}/documents/{document_id}')
    def document(identifier:str,document_id:str):
        return service.store.document(identifier,document_id)

    @app.delete('/api/snapshots/{identifier}/documents/{document_id}')
    def remove_document(identifier:str,document_id:str):
        service.store.remove_document(identifier,document_id)
        return {'deleted':document_id}

    @app.get('/api/compare')
    def compare(before:str,after:str):return service.compare(before,after)

    @app.get('/api/snapshots/{identifier}/bom')
    def bom(identifier:str):
        raw=service.store.get(identifier)['raw']
        return Response(json.dumps(raw,ensure_ascii=False,indent=2),media_type='application/json',
                        headers={'Content-Disposition':'attachment; filename="snapshot.cdx.json"'})

    @app.get('/api/snapshots/{identifier}/lockfile')
    def original_lockfile(identifier:str):
        service.store.get(identifier)
        with service.store.connect() as db:
            exists=db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='lockfile_sources'").fetchone()
            row=db.execute('SELECT source FROM lockfile_sources WHERE snapshot_id=?',(identifier,)).fetchone() if exists else None
        if not row:raise KeyError('当前快照不是锁文件导入。')
        return Response(row['source'],media_type='application/json',headers={'Content-Disposition':'attachment; filename="package-lock.json"'})

    @app.get('/api/snapshots/{identifier}/report')
    def report(identifier:str,format:str='json'):
        result=service.analyze(identifier)
        if identifier.startswith('case-'):
            case=real_case.status()
            if identifier in {case.get('before_snapshot_id'),case.get('partial_snapshot_id'),case.get('after_snapshot_id')}:
                result['real_case']=case
        result['history']=service.store.history(identifier)
        result['remediation_tasks']=tasks.list(identifier)
        result['claim_reviews']=[reviews.get(identifier,h['id']) for h in result['history'] if (h['answer'].get('model_explanation') or {}).get('claims')]
        if format=='html':
            return Response(report_html(result,result['history'],model=service.models.public()),media_type='text/html',
                            headers={'Content-Disposition':'attachment; filename="lianzheng-report.html"'})
        if format!='json':raise InputError('报告格式仅支持 json 或 html。')
        return Response(json.dumps(result,ensure_ascii=False,indent=2),media_type='application/json',
                        headers={'Content-Disposition':'attachment; filename="lianzheng-report.json"'})

    @app.get('/')
    def index():return FileResponse(ROOT/'static/index.html')

    app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
    return app


app=create_app()
