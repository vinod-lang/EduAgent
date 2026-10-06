import io
import json
import sqlite3
from dataclasses import replace,asdict
from unittest.mock import Mock
import pytest
import db
import document_studio
from document_models import DocumentRequest,DocumentDraft,DocumentVersions,DocumentError
from document_facts import *
from document_repository import save_draft,load_draft,init_document_schema
from generation_diagnostics import annotate

@pytest.fixture
def storage(tmp_path,monkeypatch):
    path=tmp_path/'isolated.db';monkeypatch.setattr(db,'DB_PATH',str(path));db.init_db();return path

def draft(date='10 October 2026',body='Synthetic INR 2500 for 20 attendees.'):
    return DocumentDraft('notice',date=date,title='Synthetic notice',body=(body,))
def versions():
    d=draft();d=replace(d,fact_expectations=(fact('date',d.date,'structured_request'),fact('body','INR 2500')))
    return DocumentVersions.generated(annotate(d,'document',1))


def test_structured_request_only():
    r=DocumentRequest('notice','Some fictional person says 99999',date='10 October 2026')
    facts=request_facts(r)
    assert len(facts)==1 and facts[0].field=='date' and facts[0].source=='structured_request'
    assert not any('99999' in f.value for f in facts)


def test_persistence_reload_and_no_activity_content(storage):
    v=versions();identity=save_draft(v);loaded=load_draft(identity)
    assert loaded.expectation_snapshots==v.expectation_snapshots
    assert loaded.provenance_snapshots==v.provenance_snapshots
    assert loaded.current.fact_expectations==v.current.fact_expectations
    assert all(row['details']=='' for row in db.get_recent_activity())
    with db.material_connection() as conn:
        assert conn.execute('SELECT count(*) FROM document_fact_expectations').fetchone()[0]==2
        assert 'system prompt' not in conn.execute('SELECT metadata_json FROM document_generation_provenance').fetchone()[0]


def test_refinement_supplies_and_preserves_facts(storage,monkeypatch):
    v=load_draft(save_draft(versions()));chat=Mock(return_value=v.current.to_json())
    monkeypatch.setattr(document_studio.ai_provider,'generate_chat',chat)
    refined=document_studio.refine_draft(v.current,'Make it concise')
    assert refined.fact_expectations==v.expectation_snapshots[-1]
    payload=json.loads(chat.call_args.kwargs['messages'][1]['content'])
    assert len(payload['protected_facts'])==2

@pytest.mark.parametrize('change',[{'date':'12 October 2026'},{'body':['Synthetic INR 25000 for 20 attendees.']}])
def test_failed_refinement_retains_previous(storage,monkeypatch,change):
    v=load_draft(save_draft(versions()));data=v.current.to_dict();data.update(change)
    chat=Mock(return_value=json.dumps(data));monkeypatch.setattr(document_studio.ai_provider,'generate_chat',chat)
    with pytest.raises(DocumentError):document_studio.refine_draft(v.current,'Change the event',retry=True)
    assert v.current.date=='10 October 2026' and len(v.history)==1 and chat.call_count==1


def test_edit_conflict_explicit_confirmation(storage):
    v=versions();edited=replace(v.current,date='12 October 2026')
    with pytest.raises(DocumentFactConflict):v.update(edited)
    changed=confirm_edit(edited,v.expectation_snapshots[-1])
    next_version=v.update(edited,expectations=changed)
    assert next_version.current.date=='12 October 2026'
    assert next_version.expectation_snapshots[-1][0].source=='professor_confirmed'
    assert v.expectation_snapshots[0][0].value=='10 October 2026'
    loaded=load_draft(save_draft(next_version))
    assert loaded.expectation_snapshots==next_version.expectation_snapshots


def test_body_change_needs_explicit_replacement():
    v=versions();edited=replace(v.current,body=('Synthetic INR 3000 for 20 attendees.',))
    with pytest.raises(DocumentError):confirm_edit(edited,v.expectation_snapshots[-1])
    identity=v.expectation_snapshots[-1][1].fact_id
    changed=confirm_edit(edited,v.expectation_snapshots[-1],{identity:'INR 3000'})
    assert v.update(edited,expectations=changed).current==edited


def test_version_lifecycle_restore_snapshots(storage):
    v=versions();identity=save_draft(v)
    edited=replace(v.current,date='12 October 2026')
    v=v.update(edited,expectations=confirm_edit(edited,v.expectation_snapshots[-1]))
    refined=replace(v.current,body=('Synthetic INR 2500 for 20 attendees. Review please.',),provenance=annotate(v.current,'document refinement',1).provenance)
    v=v.update(refined,'ai_refinement');save_draft(v,identity)
    restored=v.restore(0)
    assert restored.current.date=='10 October 2026'
    assert restored.expectation_snapshots[-1]==v.expectation_snapshots[0]
    assert restored.provenance_snapshots[-1]==v.provenance_snapshots[0]
    assert len(restored.history)==4
    save_draft(restored,identity)
    assert load_draft(identity).expectation_snapshots==restored.expectation_snapshots


def test_remove_snapshot_and_history(storage):
    v=versions();date=v.expectation_snapshots[-1][0]
    removed=remove_fact(v.expectation_snapshots[-1],date.fact_id)
    v=v.update(v.current,expectations=removed)
    assert len(v.history)==2 and len(v.expectation_snapshots[-1])==1
    assert len(load_draft(save_draft(v)).expectation_snapshots[0])==2

@pytest.mark.parametrize('value,body,valid',[('2500','25000',False),('2500','12500',False),('2500','2500',True),('講義','講義 開催',True),('₹2500','₹25000',False)])
def test_numeric_unicode_boundary(value,body,valid):
    assert bool(conflicts(draft(body=body),(fact('body',value),))) != valid

@pytest.mark.parametrize('field,value,source',[('function','shell','professor_confirmed'),('date','','professor_confirmed'),('date','Synthetic','model_generated')])
def test_invalid_fact(field,value,source):
    with pytest.raises(DocumentError):fact(field,value,source)


def test_add_matching_fact_creates_version():
    v=DocumentVersions.generated(draft())
    added=v.update(v.current,expectations=(fact('date',v.current.date),))
    assert len(added.history)==2
    assert added.expectation_snapshots[0]==()


def test_saved_history_cannot_be_overwritten(storage):
    v=versions();identity=save_draft(v)
    altered=replace(v,expectation_snapshots=((),))
    with pytest.raises(DocumentError):save_draft(altered,identity)


def test_additive_idempotent_empty_schema(tmp_path):
    conn=sqlite3.connect(tmp_path/'empty.db');conn.row_factory=sqlite3.Row
    init_document_schema(conn);before=conn.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall()
    init_document_schema(conn);assert conn.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall()==before
    conn.close()


def test_build9_legacy_no_invented_facts(storage):
    with db.material_connection() as conn:
        conn.execute('CREATE TABLE document_drafts (document_id TEXT PRIMARY KEY,template_id TEXT,original_json TEXT,current_json TEXT,created_at TEXT,updated_at TEXT,status TEXT)')
        d=draft();conn.execute('INSERT INTO document_drafts VALUES (?,?,?,?,?,?,?)',('legacy','standard_academic',d.to_json(),d.to_json(),'2026-10-04T00:00:00+00:00','2026-10-04T00:00:00+00:00','Draft'))
    v=load_draft('legacy');assert v.expectation_snapshots==((),)
    save_draft(v,'legacy');assert load_draft('legacy').expectation_snapshots==((),)


def test_build10_existing_history_and_additive_migration(storage):
    v=DocumentVersions.generated(draft()).update(draft(body='Synthetic edited body'))
    identity=save_draft(v)
    with db.material_connection() as conn:
        conn.execute('DROP TABLE document_fact_expectations');conn.execute('DROP TABLE document_generation_provenance')
    loaded=load_draft(identity);assert loaded.expectation_snapshots==((),())
    save_draft(loaded,identity);assert len(load_draft(identity).history)==2


def test_exports_exclude_metadata(storage):
    from document_export import document_docx_bytes,document_pdf_bytes
    from docx import Document
    import pdfplumber
    v=versions()
    doc=Document(io.BytesIO(document_docx_bytes(v.current)))
    text=' '.join(p.text for p in doc.paragraphs)
    with pdfplumber.open(io.BytesIO(document_pdf_bytes(v.current))) as pdf:text+=' '.join(p.extract_text() or '' for p in pdf.pages)
    for private in (v.expectation_snapshots[0][0].fact_id,'llama3.2:3b','Validated','structured_request'):
        assert private not in text
    assert '10 October 2026' in text



def test_private_facts_never_go_to_chroma_or_benchmarks(storage,monkeypatch):
    import sys,types
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    benchmark_before={str(f):f.read_bytes() for f in (root/'benchmarks').glob('*.json')}
    module=types.ModuleType('vector_store');module.get_collection=Mock(side_effect=AssertionError('Fact storage must not touch Chroma'))
    monkeypatch.setitem(sys.modules,'vector_store',module)
    d=DocumentDraft('notice',recipient='Synthetic private recipient',body=('Synthetic private body fact',))
    d=replace(d,fact_expectations=(fact('recipient',d.recipient),fact('body',d.body[0])))
    load_draft(save_draft(DocumentVersions.generated(d)))
    module.get_collection.assert_not_called()
    assert all(row['details']=='' for row in db.get_recent_activity())
    assert benchmark_before=={str(f):f.read_bytes() for f in (root/'benchmarks').glob('*.json')}


def test_refused_response_and_prompts_not_persisted(storage,monkeypatch):
    private='SYNTHETIC_REJECTED_RESPONSE_MARKER'
    chat=Mock(return_value=private);monkeypatch.setattr(document_studio.ai_provider,'generate_chat',chat)
    with pytest.raises(DocumentError):document_studio.generate_draft(DocumentRequest('notice','SYNTHETIC_PROMPT_MARKER'))
    from document_repository import list_drafts
    assert not list_drafts()
    assert private.encode() not in storage.read_bytes()
    assert b'SYNTHETIC_PROMPT_MARKER' not in storage.read_bytes()



def test_restore_legacy_provenance_stays_unknown():
    v=DocumentVersions.generated(draft())
    refined=annotate(draft(body='Synthetic refined'),'document refinement',1)
    v=v.update(refined,'ai_refinement')
    assert v.provenance_snapshots[-1] is not None
    restored=v.restore(0)
    assert restored.provenance_snapshots[-1] is None


def test_identical_refinement_records_provenance_and_version():
    v=versions()
    refined=annotate(v.current,'document refinement',1)
    updated=v.update(refined,'ai_refinement')
    assert len(updated.history)==2 and updated.sources[-1]=='ai_refinement'
    assert updated.provenance_snapshots[-1].generation_type=='document refinement'
