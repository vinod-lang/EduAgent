"""Explicit draft persistence; never touches legacy documents/material tables."""
import uuid
import json
from dataclasses import asdict
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

    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute("""CREATE TABLE IF NOT EXISTS document_versions (
        version_id TEXT PRIMARY KEY, document_id TEXT NOT NULL,
        version_number INTEGER NOT NULL CHECK(version_number>0),
        source TEXT NOT NULL CHECK(source IN ('generated','professor_edit','ai_refinement','restored','legacy_current')),
        snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL, restored_from TEXT,
        UNIQUE(document_id,version_number), UNIQUE(version_id,document_id),
        FOREIGN KEY(document_id) REFERENCES document_drafts(document_id),
        FOREIGN KEY(restored_from,document_id) REFERENCES document_versions(version_id,document_id)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS document_preferences (
        preference_id TEXT PRIMARY KEY, category TEXT NOT NULL, instruction TEXT NOT NULL,
        scope TEXT NOT NULL, document_type TEXT, template_id TEXT, tone TEXT, rule_key TEXT NOT NULL,
        source_document_id TEXT, source_before_id TEXT, source_after_id TEXT,
        approved INTEGER NOT NULL DEFAULT 0 CHECK(approved IN (0,1)),
        active INTEGER NOT NULL DEFAULT 0 CHECK(active IN (0,1)), created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        FOREIGN KEY(source_document_id) REFERENCES document_drafts(document_id),
        FOREIGN KEY(source_before_id,source_document_id) REFERENCES document_versions(version_id,document_id),
        FOREIGN KEY(source_after_id,source_document_id) REFERENCES document_versions(version_id,document_id)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS document_feedback (
        feedback_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, version_id TEXT NOT NULL,
        rating TEXT NOT NULL CHECK(rating IN ('Good','Needs Changes')), note TEXT NOT NULL, created_at TEXT NOT NULL,
        FOREIGN KEY(version_id,document_id) REFERENCES document_versions(version_id,document_id)
    )""")

    conn.execute("""CREATE TABLE IF NOT EXISTS document_fact_expectations (
        version_id TEXT NOT NULL, fact_id TEXT NOT NULL, field TEXT NOT NULL,
        source TEXT NOT NULL, value TEXT NOT NULL, required INTEGER NOT NULL CHECK(required IN (0,1)),
        created_at TEXT NOT NULL, PRIMARY KEY(version_id,fact_id),
        FOREIGN KEY(version_id) REFERENCES document_versions(version_id)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS document_generation_provenance (
        version_id TEXT PRIMARY KEY, metadata_json TEXT NOT NULL,
        FOREIGN KEY(version_id) REFERENCES document_versions(version_id)
    )""")


def read_reliability(conn,identity):
    from document_facts import DocumentFactExpectation
    from generation_diagnostics import GenerationProvenance
    try:
        facts=tuple(DocumentFactExpectation(r['fact_id'],r['field'],r['source'],r['value'],bool(r['required']),r['created_at']) for r in conn.execute('SELECT * FROM document_fact_expectations WHERE version_id=? ORDER BY rowid',(identity,))) if has_table(conn,'document_fact_expectations') else ()
        row=conn.execute('SELECT metadata_json FROM document_generation_provenance WHERE version_id=?',(identity,)).fetchone() if has_table(conn,'document_generation_provenance') else None
        provenance=GenerationProvenance(**json.loads(row[0])) if row else None
        return facts,provenance
    except (ValueError,TypeError,KeyError) as exc:
        raise DocumentStorageError('Saved document reliability metadata is invalid. The document was not changed.') from exc


def has_table(conn,name):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone())


def persist_versions(conn,document_id,versions):
    existing=conn.execute('SELECT * FROM document_versions WHERE document_id=? ORDER BY version_number',(document_id,)).fetchall()
    if len(existing)>len(versions.history):raise DocumentStorageError('Newer saved history exists; reload before saving.')
    for index,row in enumerate(existing):
        facts,provenance=read_reliability(conn,row['version_id'])
        if facts!=versions.expectation_snapshots[index] or provenance!=versions.provenance_snapshots[index]:raise DocumentStorageError('Saved fact/provenance history cannot be overwritten; reload before saving.')
        if (row['version_id'],parse_draft(row['snapshot_json']),row['source'],row['restored_from'],row['created_at'])!=(versions.version_ids[index],versions.history[index],versions.sources[index],versions.restored_from[index],versions.timestamps[index]):
            raise DocumentStorageError('Saved history cannot be overwritten; reload before saving.')
    for index in range(len(existing),len(versions.history)):
        conn.execute('INSERT INTO document_versions VALUES (?,?,?,?,?,?,?)',(versions.version_ids[index],document_id,index+1,versions.sources[index],versions.history[index].to_json(),versions.timestamps[index],versions.restored_from[index]))
        for fact in versions.expectation_snapshots[index]:
            conn.execute('INSERT INTO document_fact_expectations VALUES (?,?,?,?,?,?,?)',(versions.version_ids[index],fact.fact_id,fact.field,fact.source,fact.value,int(fact.required),fact.created_at))
        provenance=versions.provenance_snapshots[index]
        if provenance is not None:conn.execute('INSERT INTO document_generation_provenance VALUES (?,?)',(versions.version_ids[index],json.dumps(asdict(provenance))))
        conn.execute('INSERT INTO activity_log (action,details,timestamp) VALUES (?,?,?)',('document_version_created','',versions.timestamps[index]))


def save_draft(versions,document_id=None,status='Draft',*,ownership=None):
    if not isinstance(versions,DocumentVersions) or status not in ('Draft','Final'):raise DocumentError('Invalid draft/status.')
    now=datetime.now(timezone.utc).isoformat()
    try:
        with db.material_connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            init_document_schema(conn)
            if document_id is None:
                document_id=str(uuid.uuid4())
                conn.execute('INSERT INTO document_drafts VALUES (?,?,?,?,?,?,?)',(document_id,versions.template_id,versions.original.to_json(),versions.current.to_json(),now,now,status))
                if ownership is not None:
                    from security.repository import SecurityRepository
                    SecurityRepository.attach_ownership(conn,'document',document_id,ownership)
            else:
                row=conn.execute('SELECT original_json,template_id FROM document_drafts WHERE document_id=?',(document_id,)).fetchone()
                if row is None:raise DocumentStorageError('Saved draft no longer exists.')
                if parse_draft(row['original_json'])!=versions.original or row['template_id']!=versions.template_id:raise DocumentStorageError('This saved draft belongs to a different original version.')
                conn.execute('UPDATE document_drafts SET current_json=?,updated_at=?,status=? WHERE document_id=?',(versions.current.to_json(),now,status,document_id))
            persist_versions(conn,document_id,versions)
            conn.execute('INSERT INTO activity_log (action,details,timestamp) VALUES (?,?,?)',('document_saved','',now))
        return document_id
    except sqlite3.Error as exc:raise DocumentStorageError('Draft could not be saved to local storage.') from exc


def list_drafts(*, authorized_ids=None, include_content_metadata=False):
    try:
        with db.material_connection() as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='document_drafts'").fetchone():return []
            if authorized_ids is not None and not authorized_ids:return []
            where=' WHERE document_id IN ('+','.join('?' for _ in authorized_ids)+')' if authorized_ids is not None else ''
            rows=[dict(row) for row in conn.execute('SELECT document_id,template_id,created_at,updated_at,status'+(',current_json' if include_content_metadata else '')+' FROM document_drafts'+where+' ORDER BY updated_at DESC',tuple(authorized_ids) if authorized_ids is not None else ())]
            if include_content_metadata:
                for row in rows:
                    draft=parse_draft(row.pop('current_json'))
                    row.update(title=draft.title or draft.subject,document_type=draft.document_type)
                    row['version_count']=len(load_draft(row['document_id']).history)
            return rows
    except sqlite3.Error as exc:raise DocumentStorageError('Saved drafts could not be listed.') from exc


def load_draft(document_id):
    try:
        with db.material_connection() as conn:
            row=conn.execute('SELECT * FROM document_drafts WHERE document_id=?',(document_id,)).fetchone()
            stored=conn.execute('SELECT * FROM document_versions WHERE document_id=? ORDER BY version_number',(document_id,)).fetchall() if has_table(conn,'document_versions') else []
            reliability=[read_reliability(conn,v['version_id']) for v in stored]
        if row is None:raise DocumentStorageError('Saved draft not found.')
        original=parse_draft(row['original_json']);current=parse_draft(row['current_json'])
        if stored:
            if [v['version_number'] for v in stored]!=list(range(1,len(stored)+1)):raise DocumentStorageError('Saved version numbering is invalid.')
            versions=DocumentVersions(original,tuple(parse_draft(v['snapshot_json']) for v in stored),row['template_id'],tuple(v['version_id'] for v in stored),tuple(v['source'] for v in stored),tuple(v['restored_from'] for v in stored),tuple(v['created_at'] for v in stored),expectation_snapshots=tuple(f for f,_ in reliability),provenance_snapshots=tuple(p for _,p in reliability))
            if versions.current!=current:raise DocumentStorageError('Saved current version disagrees with history.')
            return versions
        # Build 9 recorded original/current but not how the current value arose.
        history=(original,) if original==current else (original,current)
        return DocumentVersions(original,history,row['template_id'],sources=('generated',) if len(history)==1 else ('generated','legacy_current'),timestamps=(row['created_at'],) if len(history)==1 else (row['created_at'],row['updated_at']))
    except sqlite3.Error as exc:raise DocumentStorageError('Saved draft could not be loaded.') from exc


def list_versions(document_id):
    versions=load_draft(document_id)
    return tuple(dict(version_id=identity,document_id=document_id,version_number=i+1,source=versions.sources[i],created_at=versions.timestamps[i],restored_from=versions.restored_from[i],draft=versions.history[i]) for i,identity in enumerate(versions.version_ids))
