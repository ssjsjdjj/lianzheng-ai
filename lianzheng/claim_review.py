"""Human review of persisted claims, separate from literal-quote validation.

This module does not call a model, infer semantic support, or change an answer.
Every judgment is bound to the stored answer, claim, and its cited source text.
"""
import hashlib
import json
import re

from .domain import InputError
from .store import now


STATUSES = {
    'pending': '待人工复核',
    'supported': '人工标记：支持',
    'partial': '人工标记：部分支持',
    'insufficient': '人工标记：证据不足',
    'conflict': '人工标记：来源冲突',
}


def _claims(answer):
    model = answer.get('model_explanation') or {}
    claims = model.get('claims') or []
    return claims if isinstance(claims, list) else []


def _fingerprint(snapshot_id, answer_id, claim_index, claim, answer):
    ids = set(claim.get('evidence_ids') or [])
    ids.update(q.get('evidence_id') for q in claim.get('quotes', []) if isinstance(q, dict))
    sources = [c for c in answer.get('citations', []) if c.get('id') in ids]
    payload = {'snapshot_id': snapshot_id, 'answer_id': answer_id, 'claim_index': claim_index,
               'claim': claim, 'sources': sources, 'facts': answer.get('facts', {})}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def _literal_check(claim, answer):
    sources = {c['id']: c for c in answer.get('citations', []) if isinstance(c, dict) and 'id' in c}
    ids = claim.get('evidence_ids') or []
    checked = []
    for quote in claim.get('quotes', []):
        if not isinstance(quote, dict):
            checked.append({'matched': False, 'reason': '摘录格式不完整'})
            continue
        source = sources.get(quote.get('evidence_id'), {})
        text, original = quote.get('quote'), source.get('text', '')
        matched = isinstance(text, str) and bool(text) and isinstance(original, str) and text in original
        start, end = quote.get('source_start'), quote.get('source_end')
        if start is not None or end is not None:
            matched = matched and type(start) is int and type(end) is int and 0 <= start < end <= len(original)
            matched = matched and original[start:end] == text
        matched = bool(matched and quote.get('evidence_id') in ids)
        checked.append({'evidence_id': quote.get('evidence_id'), 'quote': text,
                        'matched': matched, 'source_title': source.get('title', ''),
                        'source_locator': source.get('locator', ''),
                        'reason': '原句存在于当时保存的引用中' if matched else '未能逐字匹配当时保存的引用'})
    covered = {q.get('evidence_id') for q in checked if q['matched']}
    matched = bool(checked) and all(q['matched'] for q in checked) and bool(ids) and set(ids) <= covered
    return {'status': 'matched' if matched else 'mismatch' if checked else 'no_quotes',
            'label': '原文逐字匹配通过' if matched else '原文未全部匹配' if checked else '没有可逐字核对的摘录',
            'scope': '只核对原文是否存在；不代表原文足以支持结论。', 'quotes': checked}


def _hints(claim, answer):
    text = claim.get('text', '')
    ids = set(claim.get('evidence_ids') or [])
    source_text = '\n'.join(c.get('text', '') for c in answer.get('citations', []) if c.get('id') in ids)
    hints = []
    if re.search(r'已(?:经)?(?:通过|完成|修复|消除|解决)|可以(?:直接)?上线|保证|完全兼容|没有(?:任何)?风险', text):
        hints.append('结论包含完成状态或保证性措辞，请核对原文是否提供了对应的实际结果。此提示不是错误判定。')
        if re.search(r'需要|必须|要求|应当|应执行|需提供|尚未|未提供', source_text):
            hints.append('来源包含检查要求或缺项描述；“要求完成”不能单独证明“已经完成”。')
    if len(ids) > 1:
        hints.append('本项引用多份来源，请核对它们的适用版本、获取时间和支持范围是否一致。')
    return hints


class ClaimReviews:
    def __init__(self, service):
        self.store = service.store
        with self.store.connect() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS claim_reviews (
                snapshot_id TEXT NOT NULL, answer_id INTEGER NOT NULL REFERENCES history(id),
                claim_index INTEGER NOT NULL, fingerprint TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending','supported','partial','insufficient','conflict')),
                note TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                revision INTEGER NOT NULL,
                PRIMARY KEY(snapshot_id,answer_id,claim_index,fingerprint));
              CREATE TABLE IF NOT EXISTS claim_review_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id TEXT NOT NULL, answer_id INTEGER NOT NULL REFERENCES history(id),
                claim_index INTEGER NOT NULL, fingerprint TEXT NOT NULL,
                previous_status TEXT NOT NULL, status TEXT NOT NULL, note TEXT NOT NULL,
                created_at TEXT NOT NULL, revision INTEGER NOT NULL);
              CREATE INDEX IF NOT EXISTS ix_claim_review_history
                ON claim_review_events(snapshot_id,answer_id,claim_index,id);
            ''')

    @staticmethod
    def _answer(db, snapshot_id, answer_id):
        if type(answer_id) is not int or answer_id < 1:
            raise InputError('问答记录编号无效。')
        row = db.execute('SELECT answer FROM history WHERE snapshot_id=? AND id=?',
                         (snapshot_id, answer_id)).fetchone()
        if row is None:
            raise KeyError('原问答不属于当前快照')
        return json.loads(row['answer'])

    def _get(self, db, snapshot_id, answer_id, answer):
        output = []
        for index, claim in enumerate(_claims(answer)):
            if not isinstance(claim, dict):
                continue
            fingerprint = _fingerprint(snapshot_id, answer_id, index, claim, answer)
            row = db.execute('''SELECT status,note,created_at,updated_at,revision FROM claim_reviews
                                WHERE snapshot_id=? AND answer_id=? AND claim_index=? AND fingerprint=?''',
                             (snapshot_id, answer_id, index, fingerprint)).fetchone()
            review = dict(row) if row else {'status': 'pending', 'note': '', 'created_at': None,
                                           'updated_at': None, 'revision': 0}
            stale = db.execute('''SELECT COUNT(*) FROM claim_reviews WHERE snapshot_id=? AND answer_id=?
                                   AND claim_index=? AND fingerprint<>?''',
                               (snapshot_id, answer_id, index, fingerprint)).fetchone()[0]
            events = db.execute('''SELECT id,previous_status,status,note,created_at,revision,fingerprint
                                   FROM claim_review_events WHERE snapshot_id=? AND answer_id=? AND claim_index=?
                                   ORDER BY id DESC LIMIT 20''', (snapshot_id, answer_id, index)).fetchall()
            total = db.execute('''SELECT COUNT(*) FROM claim_review_events
                                 WHERE snapshot_id=? AND answer_id=? AND claim_index=?''',
                               (snapshot_id, answer_id, index)).fetchone()[0]
            output.append({'claim_index': index, 'fingerprint': fingerprint, 'text': claim.get('text', ''),
                           'literal_check': _literal_check(claim, answer), 'attention_points': _hints(claim, answer),
                           'review': {**review, 'label': STATUSES[review['status']], 'method': 'human'},
                           'stale_review_count': stale, 'event_count': total,
                           'events': [{**dict(e), 'current_content': e['fingerprint'] == fingerprint} for e in events]})
        return {'snapshot_id': snapshot_id, 'answer_id': answer_id, 'claims': output,
                'disclaimer': '语义支持由本机使用者人工标注，尚无独立专家身份认证；不改变原回答或自动证明业务安全。',
                'model_calls': 0}

    def get(self, snapshot_id, answer_id):
        with self.store.connect() as db:
            answer = self._answer(db, snapshot_id, answer_id)
            return self._get(db, snapshot_id, answer_id, answer)

    def save(self, snapshot_id, answer_id, claim_index, status, note='', expected_fingerprint=None,
             expected_revision=None):
        if type(claim_index) is not int or claim_index < 0:
            raise InputError('结论编号无效。')
        if not isinstance(status, str) or status not in STATUSES:
            raise InputError('请选择有效的人工复核状态。')
        if not isinstance(note, str) or len(note) > 1000:
            raise InputError('复核备注最多 1000 字符。')
        if not isinstance(expected_fingerprint, str) or not re.fullmatch(r'[a-f0-9]{64}', expected_fingerprint):
            raise InputError('缺少结论内容标识，请重新打开这条回答后复核。')
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 0):
            raise InputError('复核记录版本无效。')
        with self.store.connect() as db:
            # Hold a write transaction while reading the immutable-answer identity and saving its judgment.
            db.execute('BEGIN IMMEDIATE')
            answer = self._answer(db, snapshot_id, answer_id)
            claims = _claims(answer)
            if claim_index >= len(claims) or not isinstance(claims[claim_index], dict):
                raise InputError('该问答没有对应的模型结论。')
            fingerprint = _fingerprint(snapshot_id, answer_id, claim_index, claims[claim_index], answer)
            if expected_fingerprint != fingerprint:
                raise InputError('结论或引用已变化，请刷新后重新复核；旧标注未套用到新内容。')
            row = db.execute('''SELECT status,note,created_at,revision FROM claim_reviews
                                WHERE snapshot_id=? AND answer_id=? AND claim_index=? AND fingerprint=?''',
                             (snapshot_id, answer_id, claim_index, fingerprint)).fetchone()
            revision = row['revision'] if row else 0
            if expected_revision is not None and expected_revision != revision:
                raise InputError('这条复核记录已被更新，请刷新后再保存。')
            note = note.strip()
            if row and row['status'] == status and row['note'] == note:
                return self._get(db, snapshot_id, answer_id, answer)
            timestamp = now()
            db.execute('''INSERT INTO claim_reviews VALUES(?,?,?,?,?,?,?,?,?)
                          ON CONFLICT(snapshot_id,answer_id,claim_index,fingerprint) DO UPDATE SET
                          status=excluded.status,note=excluded.note,updated_at=excluded.updated_at,revision=excluded.revision''',
                       (snapshot_id, answer_id, claim_index, fingerprint, status, note,
                        row['created_at'] if row else timestamp, timestamp, revision + 1))
            db.execute('''INSERT INTO claim_review_events
                          (snapshot_id,answer_id,claim_index,fingerprint,previous_status,status,note,created_at,revision)
                          VALUES(?,?,?,?,?,?,?,?,?)''',
                       (snapshot_id, answer_id, claim_index, fingerprint, row['status'] if row else 'pending',
                        status, note, timestamp, revision + 1))
            return self._get(db, snapshot_id, answer_id, answer)
