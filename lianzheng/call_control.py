"""Local chat API admission control. It is not an account billing limit."""
import hashlib
import json
import math
import time
from datetime import datetime,timezone
from uuid import uuid4

from .domain import InputError
from .providers import ModelError


class CallControl:
    def __init__(self,store):
        self.store=store
        with store.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS call_policy (
                id INTEGER PRIMARY KEY CHECK(id=1), daily_calls INTEGER NOT NULL,
                daily_budget_usd REAL, enabled INTEGER NOT NULL);
            INSERT OR IGNORE INTO call_policy VALUES(1,20,NULL,1);
            CREATE TABLE IF NOT EXISTS chat_calls (
                id TEXT PRIMARY KEY, day TEXT NOT NULL, started REAL NOT NULL,
                finished REAL, fingerprint TEXT NOT NULL, provider TEXT NOT NULL,
                model TEXT NOT NULL, status TEXT NOT NULL, reservation REAL,
                cost_estimate REAL, input_tokens INTEGER, output_tokens INTEGER);
            CREATE INDEX IF NOT EXISTS ix_chat_calls_day ON chat_calls(day);
            ''')

    def update(self,values):
        if set(values)-{'daily_calls','daily_budget_usd','enabled'}:raise InputError('调用限制字段无效。')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current=dict(db.execute('SELECT daily_calls,daily_budget_usd,enabled FROM call_policy WHERE id=1').fetchone())
            current['enabled']=bool(current['enabled']);current.update(values)
            if type(current['daily_calls']) is not int or not 1<=current['daily_calls']<=1000:
                raise InputError('每日聊天调用次数必须为 1 至 1000。')
            budget=current['daily_budget_usd']
            if budget is not None and (type(budget) not in (int,float) or not math.isfinite(budget) or not .001<=budget<=100):
                raise InputError('金额阈值需为 0.001 至 100 美元，或留空。')
            if type(current['enabled']) is not bool:raise InputError('启用状态必须为布尔值。')
            db.execute('UPDATE call_policy SET daily_calls=?,daily_budget_usd=?,enabled=? WHERE id=1',
                       (current['daily_calls'],budget,int(current['enabled'])))
        return self.public()

    def public(self):
        day=datetime.now(timezone.utc).date().isoformat()
        with self.store.connect() as db:
            policy=dict(db.execute('SELECT daily_calls,daily_budget_usd,enabled FROM call_policy WHERE id=1').fetchone())
            rows=[dict(r) for r in db.execute('SELECT id,provider,model,started,status,reservation,cost_estimate,input_tokens,output_tokens FROM chat_calls WHERE day=? ORDER BY started DESC',(day,))]
            outstanding=[dict(r) for r in db.execute("SELECT id,day,provider,model,started,reservation FROM chat_calls WHERE status='in_flight' ORDER BY started")]
        policy['enabled']=bool(policy['enabled'])
        held=sum(r['cost_estimate'] if r['cost_estimate'] is not None else r['reservation'] or 0 for r in rows)
        unknown=sum(r['cost_estimate'] is None for r in rows)
        return {'policy':policy,'day_utc':day,'calls_today':len(rows),'in_flight':len(outstanding),'outstanding':outstanding,
                'known_estimated_usd':round(sum(r['cost_estimate'] or 0 for r in rows),8),
                'budget_accounted_usd':round(held,8),'unknown_cost_calls':unknown,
                'unreserved_calls':sum(r['cost_estimate'] is None and r['reservation'] is None for r in rows),
                'recent':rows[:20],
                'note':'仅控制本应用聊天请求，含连接测试与失败请求；UTC 零点换日。金额为本地保守预留/估算，不是服务商账单上限，不包含独立 Embedding 或其他应用。未知费用不视为零。'}

    def reserve(self,config,payload):
        stamp=time.time();day=datetime.now(timezone.utc).date().isoformat()
        text=json.dumps(payload,ensure_ascii=False,sort_keys=True)
        fingerprint=hashlib.sha256((config['base_url']+'\n'+text).encode()).hexdigest()
        reservation=None
        if (config.get('base_url')=='https://api.openai.com/v1' and config.get('model')=='gpt-6-luna'
                and payload.get('service_tier')=='default'):
            # UTF-8 bytes are a deliberately loose token proxy, including schema overhead.
            # Highest short-context cache-write rate, output cap, and 25% allowance.
            reservation=round(((len(text.encode('utf-8'))+4096)*.25+payload['max_output_tokens']*.50)*1.25/1_000_000,8)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            # Never expire an in-flight request by elapsed time: read timeouts are not a total deadline.
            policy=db.execute('SELECT * FROM call_policy WHERE id=1').fetchone()
            rows=db.execute('SELECT * FROM chat_calls WHERE day=?',(day,)).fetchall()
            active=db.execute("SELECT fingerprint FROM chat_calls WHERE status='in_flight'").fetchall()
            if active:
                message='相同请求正在处理中，已拦截重复调用。' if any(r['fingerprint']==fingerprint for r in active) else '已有聊天请求处理中，请等待完成后再试。'
                raise ModelError(message)
            if policy['enabled']:
                if len(rows)>=policy['daily_calls']:raise ModelError('已达到本应用今日聊天调用次数上限，保留本地证据结果。')
                budget=policy['daily_budget_usd']
                if budget is not None:
                    if reservation is None:raise ModelError('当前模型无法保守预估费用，金额阈值已阻止本次请求；可使用本地证据模式。')
                    if any(r['cost_estimate'] is None and r['reservation'] is None for r in rows):
                        raise ModelError('今日存在无法估算的历史调用，金额阈值已阻止新增请求。')
                    used=sum(r['cost_estimate'] if r['cost_estimate'] is not None else r['reservation'] for r in rows)
                    if used+reservation>budget:raise ModelError('本次保守预留会超过本应用每日金额阈值，未发起请求。')
            ticket=uuid4().hex
            db.execute('INSERT INTO chat_calls(id,day,started,fingerprint,provider,model,status,reservation) VALUES(?,?,?,?,?,?,?,?)',
                       (ticket,day,stamp,fingerprint,config.get('provider','compatible'),config['model'],'in_flight',reservation))
        return ticket

    def finish(self,ticket,metadata,status):
        metadata=metadata or {};usage=metadata.get('usage') or {};cost=metadata.get('cost_estimate') or {}
        amount=cost.get('amount') if cost.get('currency')=='USD' else None
        if type(amount) not in (int,float) or not math.isfinite(amount) or amount<0:amount=None
        integer=lambda key:usage.get(key) if type(usage.get(key)) is int and usage[key]>=0 else None
        count=lambda a,b:integer(a) if integer(a) is not None else integer(b)
        with self.store.connect() as db:
            db.execute('UPDATE chat_calls SET finished=?,status=?,cost_estimate=?,input_tokens=?,output_tokens=? WHERE id=?',
                       (time.time(),status,amount,count('input_tokens','prompt_tokens'),
                        count('output_tokens','completion_tokens'),ticket))
