"""Explicit approved local style guidance, deterministic scope selection; no embeddings."""
from dataclasses import dataclass
from datetime import datetime,timezone
import uuid
import sqlite3
import db
from document_models import CATALOG,TONES,DocumentError,clean
from document_diff import REUSABLE_CATEGORIES
from document_repository import init_document_schema,has_table,DocumentStorageError

SCOPES=('document_type','general','template')
RULE_KEYS=('other','opening','paragraph_length','ceremonial_language','subject_placement','signature_layout')

@dataclass(frozen=True)
class Preference:
    preference_id: str
    category: str
    instruction: str
    scope: str
    document_type: str | None = None
    template_id: str | None = None
    tone: str | None = None
    rule_key: str = 'other'
    source_document_id: str | None = None
    source_before_id: str | None = None
    source_after_id: str | None = None
    approved: bool = True
    active: bool = True
    created_at: str = ''
    updated_at: str = ''

    def __post_init__(self):
        object.__setattr__(self,'instruction',clean(self.instruction,'Preference instruction',2000,True))
        if self.category not in REUSABLE_CATEGORIES:raise DocumentError('Factual/unknown corrections are not reusable style preferences. Write a reviewed style instruction instead.')
        if self.scope not in SCOPES or self.rule_key not in RULE_KEYS:raise DocumentError('Invalid preference scope/rule.')
        if self.document_type is not None and (not isinstance(self.document_type,str) or self.document_type not in CATALOG):raise DocumentError('Invalid preference document type.')
        if self.scope=='document_type' and self.document_type is None:raise DocumentError('Document-type scope needs a document type.')
        if self.scope=='general' and (self.document_type is not None or self.template_id is not None):raise DocumentError('General scope cannot carry narrower filters.')
        if self.scope=='template' and self.template_id!='standard_academic':raise DocumentError('Template scope requires an available template.')
        if self.scope!='template' and self.template_id is not None:raise DocumentError('Only template scope may specify a template.')
        if self.tone is not None and self.tone not in TONES:raise DocumentError('Invalid preference tone.')
        if type(self.active) is not bool or type(self.approved) is not bool:raise DocumentError('Invalid preference state.')
        references=(self.source_document_id,self.source_before_id,self.source_after_id)
        if any(value is not None for value in references) and not all(isinstance(value,str) and value for value in references):raise DocumentError('Provenance requires one document and two version references.')


def _event(conn,action):conn.execute('INSERT INTO activity_log (action,details,timestamp) VALUES (?,?,?)',(action,'',datetime.now(timezone.utc).isoformat()))

def infer_rule(instruction):
    text=instruction.lower()
    if 'opening' in text:return 'opening'
    if 'paragraph' in text and any(w in text for w in ('short','long','length','five','two','concise')):return 'paragraph_length'
    if 'ceremonial' in text:return 'ceremonial_language'
    if 'subject' in text and any(w in text for w in ('before','after','place')):return 'subject_placement'
    if 'signature' in text:return 'signature_layout'
    return 'other'


def approve_preference(instruction,category='tone_style',scope='document_type',document_type=None,template_id=None,tone=None,rule_key=None,source_document_id=None,source_before_id=None,source_after_id=None):
    now=datetime.now(timezone.utc).isoformat();identity=str(uuid.uuid4())
    preference=Preference(identity,category,instruction,scope,document_type,template_id,tone,rule_key or infer_rule(clean(instruction,'Preference instruction',2000,True)),source_document_id,source_before_id,source_after_id,True,True,now,now)
    try:
        with db.material_connection() as conn:
            init_document_schema(conn)
            if source_document_id:
                for version in (source_before_id,source_after_id):
                    if not conn.execute('SELECT 1 FROM document_versions WHERE document_id=? AND version_id=?',(source_document_id,version)).fetchone():raise DocumentStorageError('Preference source versions do not belong to the selected document. Save history first.')
            values=tuple(getattr(preference,key) for key in preference.__dataclass_fields__)
            conn.execute('INSERT INTO document_preferences VALUES ('+','.join('?' for _ in values)+')',values)
            _event(conn,'preference_approved')
        return identity
    except sqlite3.Error as exc:raise DocumentStorageError('Preference could not be approved.') from exc


def list_preferences():
    try:
        with db.material_connection() as conn:
            if not has_table(conn,'document_preferences'):return ()
            result=[]
            for row in conn.execute('SELECT * FROM document_preferences ORDER BY updated_at DESC,preference_id'):
                data=dict(row);data['approved']=bool(data['approved']);data['active']=bool(data['active']);result.append(Preference(**data))
            return tuple(result)
    except sqlite3.Error as exc:raise DocumentStorageError('Preferences could not be read.') from exc


def update_preference(identity,instruction=None,active=None):
    found=next((p for p in list_preferences() if p.preference_id==identity),None)
    if found is None:raise DocumentStorageError('Preference not found.')
    if active is not None and type(active) is not bool:raise DocumentError('Active state must be boolean.')
    text=found.instruction if instruction is None else clean(instruction,'Preference instruction',2000,True)
    state=found.active if active is None else active
    try:
        with db.material_connection() as conn:
            if conn.execute('UPDATE document_preferences SET instruction=?,active=?,rule_key=?,updated_at=? WHERE preference_id=?',(text,state,infer_rule(text),datetime.now(timezone.utc).isoformat(),identity)).rowcount!=1:raise DocumentStorageError('Preference no longer exists.')
            _event(conn,'preference_disabled' if not state else 'preference_updated')
    except sqlite3.Error as exc:raise DocumentStorageError('Preference update failed.') from exc


def delete_preference(identity):
    try:
        with db.material_connection() as conn:
            if not has_table(conn,'document_preferences'):raise DocumentStorageError('Preference not found.')
            if conn.execute('DELETE FROM document_preferences WHERE preference_id=?',(identity,)).rowcount!=1:raise DocumentStorageError('Preference not found.')
            _event(conn,'preference_deleted')
    except sqlite3.Error as exc:raise DocumentStorageError('Preference deletion failed.') from exc


def relevant_preferences(request):
    matches=[p for p in list_preferences() if p.approved and p.active and (p.document_type is None or p.document_type==request.document_type) and (p.template_id is None or p.template_id==request.template_id) and (p.tone is None or p.tone==request.tone)]
    # Specific scope first; tone/type specificity then newest explicit approval.
    matches.sort(key=lambda p:({'template':3,'document_type':2,'general':1}[p.scope],bool(p.document_type),bool(p.tone),p.updated_at,p.preference_id),reverse=True)
    selected=[];seen=set();texts=set()
    for p in matches:
        key=p.rule_key
        if key!='other' and key in seen:continue
        normalized=p.instruction.casefold()
        if normalized in texts:continue
        texts.add(normalized);seen.add(key);selected.append(p)
        if len(selected)==8:break
    return tuple(selected)


def save_feedback(document_id,version_id,rating,note=''):
    if rating not in ('Good','Needs Changes'):raise DocumentError('Invalid feedback rating.')
    note=clean(note,'Feedback note',4000);identity=str(uuid.uuid4())
    try:
        with db.material_connection() as conn:
            init_document_schema(conn)
            if not conn.execute('SELECT 1 FROM document_versions WHERE document_id=? AND version_id=?',(document_id,version_id)).fetchone():raise DocumentStorageError('Feedback version must belong to this saved document.')
            conn.execute('INSERT INTO document_feedback VALUES (?,?,?,?,?,?)',(identity,document_id,version_id,rating,note,datetime.now(timezone.utc).isoformat()))
            _event(conn,'document_feedback_saved')
        return identity
    except sqlite3.Error as exc:raise DocumentStorageError('Feedback could not be saved.') from exc
