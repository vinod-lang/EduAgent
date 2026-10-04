"""Explicit draft persistence; never touches legacy documents/material tables."""
import uuid
from datetime import datetime,timezone
import sqlite3
import db
from document_models import DocumentVersions,DocumentError,parse_draft

class DocumentStorageError(DocumentError):pass


def init_document_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS document_drafts (
        document_id TEXT PRIMARY KEY, template_id TEXT NOT NULL,
        original_json TEXT NOT NULL, current_json TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, status TEXT NOT NULL
    )""")


def save_draft(versions,document_id=None,status='Draft'):
    if not isinstance(versions,DocumentVersions) or status not in ('Draft','Final'):raise DocumentError('Invalid draft/status.')
    now=datetime.now(timezone.utc).isoformat()
    try:
        with db.material_connection() as conn:
            init_document_schema(conn)
            if document_id is None:
                document_id=str(uuid.uuid4())
                conn.execute('INSERT INTO document_drafts VALUES (?,?,?,?,?,?,?)',(document_id,versions.template_id,versions.original.to_json(),versions.current.to_json(),now,now,status))
            else:
                row=conn.execute('SELECT original_json,template_id FROM document_drafts WHERE document_id=?',(document_id,)).fetchone()
                if row is None:raise DocumentStorageError('Saved draft no longer exists.')
                if parse_draft(row['original_json'])!=versions.original or row['template_id']!=versions.template_id:raise DocumentStorageError('This saved draft belongs to a different original version.')
                conn.execute('UPDATE document_drafts SET current_json=?,updated_at=?,status=? WHERE document_id=?',(versions.current.to_json(),now,status,document_id))
            conn.execute('INSERT INTO activity_log (action,details,timestamp) VALUES (?,?,?)',('document_saved','',now))
        return document_id
    except sqlite3.Error as exc:raise DocumentStorageError('Draft could not be saved to local storage.') from exc


def list_drafts():
    try:
        with db.material_connection() as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='document_drafts'").fetchone():return []
            return [dict(row) for row in conn.execute('SELECT document_id,template_id,created_at,updated_at,status FROM document_drafts ORDER BY updated_at DESC')]
    except sqlite3.Error as exc:raise DocumentStorageError('Saved drafts could not be listed.') from exc


def load_draft(document_id):
    try:
        with db.material_connection() as conn:
            row=conn.execute('SELECT * FROM document_drafts WHERE document_id=?',(document_id,)).fetchone()
        if row is None:raise DocumentStorageError('Saved draft not found.')
        original=parse_draft(row['original_json']);current=parse_draft(row['current_json'])
        return DocumentVersions(original,(original,) if original==current else (original,current),row['template_id'])
    except sqlite3.Error as exc:raise DocumentStorageError('Saved draft could not be loaded.') from exc
