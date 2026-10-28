import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS snapshots (
                id TEXT PRIMARY KEY, project TEXT NOT NULL, label TEXT NOT NULL,
                created TEXT NOT NULL, hash TEXT NOT NULL, demo INTEGER NOT NULL,
                raw TEXT NOT NULL, graph TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS scans (
                snapshot_id TEXT NOT NULL REFERENCES snapshots(id), ref TEXT NOT NULL,
                result TEXT NOT NULL, PRIMARY KEY(snapshot_id,ref));
              CREATE TABLE IF NOT EXISTS query_cache (
                package_key TEXT PRIMARY KEY, result TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES snapshots(id),
                body TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, snapshot_id TEXT NOT NULL,
                created TEXT NOT NULL, question TEXT NOT NULL, answer TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS knowledge_documents (
                id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES snapshots(id),
                created TEXT NOT NULL, body TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS ix_knowledge_snapshot ON knowledge_documents(snapshot_id);
              CREATE INDEX IF NOT EXISTS ix_history_snapshot ON history(snapshot_id,id);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback(); raise
        finally:
            db.close()

    def add_snapshot(self, item):
        with self.connect() as db:
            db.execute('INSERT INTO snapshots VALUES(?,?,?,?,?,?,?,?)',
                       (item['id'], item['project'], item['label'], item['created'], item['hash'],
                        int(item['demo']), json.dumps(item['raw']), json.dumps(item['graph'])))

    def get(self, identifier):
        with self.connect() as db:
            row = db.execute('SELECT * FROM snapshots WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise KeyError('快照不存在')
        item = dict(row)
        for key in ('raw', 'graph'):
            item[key] = json.loads(item[key])
        item['demo'] = bool(item['demo'])
        return item

    def list(self):
        with self.connect() as db:
            rows = db.execute('SELECT id,project,label,created,hash,demo FROM snapshots ORDER BY created,id').fetchall()
        return [dict(row) for row in rows]

    def scans(self, snapshot):
        with self.connect() as db:
            rows = db.execute('SELECT ref,result FROM scans WHERE snapshot_id=?', (snapshot,)).fetchall()
        return {r['ref']: json.loads(r['result']) for r in rows}

    def save_scans(self, snapshot, scans, documents):
        # Replace atomically so a failed rescan cannot leave mixed scan generations.
        with self.connect() as db:
            db.execute('DELETE FROM scans WHERE snapshot_id=?', (snapshot,))
            db.execute('DELETE FROM documents WHERE snapshot_id=?', (snapshot,))
            for ref, scan in scans.items():
                db.execute('INSERT INTO scans VALUES(?,?,?)', (snapshot, ref, json.dumps(scan)))
            for document in documents:
                db.execute('INSERT INTO documents VALUES(?,?,?)', (document['id'], snapshot, json.dumps(document)))

    def documents(self, snapshot, include_knowledge=True):
        with self.connect() as db:
            rows = db.execute('SELECT body FROM documents WHERE snapshot_id=?', (snapshot,)).fetchall()
        documents=[json.loads(row['body']) for row in rows]
        if include_knowledge:
            documents.extend(chunk for document in self.knowledge_documents(snapshot) for chunk in document['chunks'])
        return documents

    def add_document(self, document):
        with self.connect() as db:
            # Exact reimport is idempotent and preserves its original timestamp.
            db.execute('INSERT OR IGNORE INTO knowledge_documents VALUES(?,?,?,?)',
                       (document['id'],document['snapshot_id'],document['created'],json.dumps(document,ensure_ascii=False)))
        return self.document(document['snapshot_id'],document['id'])

    def knowledge_documents(self, snapshot):
        with self.connect() as db:
            rows=db.execute('SELECT body FROM knowledge_documents WHERE snapshot_id=? ORDER BY created,id',(snapshot,)).fetchall()
        return [json.loads(row['body']) for row in rows]

    def document(self, snapshot, identifier):
        with self.connect() as db:
            row=db.execute('SELECT body FROM knowledge_documents WHERE snapshot_id=? AND id=?',(snapshot,identifier)).fetchone()
        if not row:raise KeyError('文档不存在')
        return json.loads(row['body'])

    def remove_document(self, snapshot, identifier):
        with self.connect() as db:
            cursor=db.execute('DELETE FROM knowledge_documents WHERE snapshot_id=? AND id=?',(snapshot,identifier))
            if cursor.rowcount==0:raise KeyError('文档不存在')

    def cache_get(self, key):
        with self.connect() as db:
            row = db.execute('SELECT result FROM query_cache WHERE package_key=?', (key,)).fetchone()
        return json.loads(row['result']) if row else None

    def cache_put(self, key, value):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO query_cache VALUES(?,?)', (key, json.dumps(value)))

    def add_history(self, snapshot, question, answer):
        with self.connect() as db:
            cursor=db.execute('INSERT INTO history(snapshot_id,created,question,answer) VALUES(?,?,?,?)',
                              (snapshot, now(), question, json.dumps(answer, ensure_ascii=False)))
            answer['id']=cursor.lastrowid
            db.execute('UPDATE history SET answer=? WHERE id=?',(json.dumps(answer,ensure_ascii=False),answer['id']))
        return answer['id']

    def history_item(self,snapshot,identifier):
        with self.connect() as db:
            row=db.execute('SELECT id,created,question,answer FROM history WHERE snapshot_id=? AND id=?',
                           (snapshot,identifier)).fetchone()
        if not row:raise KeyError('原问答不属于当前快照')
        return {**dict(row),'answer':json.loads(row['answer'])}

    def history(self, snapshot):
        with self.connect() as db:
            rows = db.execute('SELECT id,created,question,answer FROM history WHERE snapshot_id=? ORDER BY id DESC LIMIT 20', (snapshot,)).fetchall()
        return [{**dict(row), 'answer':json.loads(row['answer'])} for row in rows]
