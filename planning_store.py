"""Local decisions and append-only history, independent of CRM snapshots."""
import json
from datetime import datetime, timezone
from database import db


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def read_records(scope):
    conn = db.get_connection()
    try:
        return [{**json.loads(row['data']), 'revision': row['revision'], '_kind': row['kind']}
                for row in conn.execute('SELECT kind, data, revision FROM planning_local_records WHERE scope=?', (scope,))]
    finally:
        conn.close()


def audit(scope, program_id):
    conn = db.get_connection()
    try:
        return [{'kind': row['kind'], 'record_id': row['record_id'], 'at': row['changed_at'],
                 'actor': json.loads(row['actor']) if row['actor'] else None,
                 'before': json.loads(row['before_data']) if row['before_data'] else None,
                 'after': json.loads(row['after_data'])} for row in conn.execute(
                     'SELECT * FROM planning_local_audit WHERE scope=? AND program_id=? ORDER BY id', (scope, program_id))]
    finally:
        conn.close()


def save(scope, kind, document, revision, actor):
    conn = db.get_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT data, revision FROM planning_local_records WHERE scope=? AND kind=? AND record_id=?',
                           (scope, kind, document['id'])).fetchone()
        if (row and revision != row['revision']) or (not row and revision not in (0, None)):
            raise ValueError('این اطلاعات توسط کاربر دیگری تغییر کرده است؛ صفحه را بازخوانی کنید.')
        old = json.loads(row['data']) if row else None
        if old and old.get('program_id') != document['program_id']:
            raise ValueError('رکورد محلی متعلق به برنامه دیگری است.')
        document = dict(document)
        if kind == 'followup':
            document['original_due'] = (old or {}).get('original_due') or document.get('due')
        new_revision = row['revision'] + 1 if row else 1
        serialized = json.dumps(document, ensure_ascii=False)
        conn.execute('INSERT INTO planning_local_records(scope,kind,record_id,program_id,data,revision) VALUES(?,?,?,?,?,?) '
                     'ON CONFLICT(scope,kind,record_id) DO UPDATE SET data=excluded.data,revision=excluded.revision',
                     (scope, kind, document['id'], document['program_id'], serialized, new_revision))
        conn.execute('INSERT INTO planning_local_audit(scope,program_id,kind,record_id,changed_at,actor,before_data,after_data) VALUES(?,?,?,?,?,?,?,?)',
                     (scope, document['program_id'], kind, document['id'], now_iso(),
                      json.dumps(actor, ensure_ascii=False) if actor else None, row['data'] if row else None, serialized))
        conn.commit()
        return {**document, 'revision': new_revision}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
