"""Synthetic Build 10 tests; persistence is always a temporary SQLite DB."""
import json
import io
from dataclasses import replace
from unittest.mock import Mock
import pytest
from docx import Document
import pdfplumber
import db
import document_studio as studio
from document_models import DocumentDraft,DocumentVersions,DocumentRequest,DocumentError,FIELDS
from document_repository import *
from document_preferences import *
from document_diff import *
from document_export import document_docx_bytes,document_pdf_bytes

@pytest.fixture
def storage(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DB_PATH',str(tmp_path/'learning.db'));db.init_db();return tmp_path


def draft(**changes):
    values=dict(document_type='permission_request',title='Synthetic request',recipient='Synthetic HOD',subject='Workshop',body=('Request permission for a workshop.',),salutation='Dear recipient,',closing='Respectfully,')
    values.update(changes);return DocumentDraft(**values)


def request(kind='permission_request',**changes):return DocumentRequest(kind,'Include the detailed ₹42,000 budget breakdown.',**changes)


def test_persist_all_version_sources_and_restore(storage):
    v=DocumentVersions.generated(draft())
    v=v.update(draft(body=('Professor edited request.',)))
    v=v.update(draft(body=('AI refined request.',)),'ai_refinement')
    prior=v.history;v=v.restore(0)
    assert v.history[:3]==prior and v.sources==('generated','professor_edit','ai_refinement','restored')
    assert v.restored_from[-1]==v.version_ids[0] and v.current==v.original
    identity=save_draft(v);assert load_draft(identity)==v
    rows=list_versions(identity)
    assert [row['version_number'] for row in rows]==[1,2,3,4]
    assert len({row['version_id'] for row in rows})==4
    save_draft(v,identity);assert len(list_versions(identity))==4
    updated=v.update(draft(body=('Later professor edit.',)))
    save_draft(updated,identity);assert len(list_versions(identity))==5
    assert all(row['document_id']==identity for row in list_versions(identity))


def test_history_immutability_and_stale_save(storage):
    v=DocumentVersions.generated(draft());identity=save_draft(v)
    updated=v.update(draft(body=('Updated',)));save_draft(updated,identity)
    with pytest.raises(DocumentStorageError):save_draft(v,identity)
    forged=replace(updated,history=(v.original,draft(body=('Forged history',))))
    with pytest.raises(DocumentStorageError):save_draft(forged,identity)
    assert load_draft(identity)==updated


def test_cross_document_version_identity_rejected(storage):
    v=DocumentVersions.generated(draft());identity=save_draft(v)
    with pytest.raises(DocumentStorageError):save_draft(v)
    assert len(list_drafts())==1 and load_draft(identity)==v

@pytest.mark.parametrize('index',[-1,99,True,'0'])
def test_invalid_restore(index):
    with pytest.raises(DocumentError):DocumentVersions.generated(draft()).restore(index)


def test_restore_appends_even_when_content_identical():
    v=DocumentVersions.generated(draft());new=v.restore(0)
    assert len(new.history)==2 and new.version_ids[-1]!=v.version_ids[0]
    assert new.sources[-1]=='restored' and new.current==v.current


def test_legacy_build9_load_no_writes_migrate_on_save(storage):
    with db.material_connection() as conn:
        conn.execute('CREATE TABLE document_drafts (document_id TEXT PRIMARY KEY,template_id TEXT,original_json TEXT,current_json TEXT,created_at TEXT,updated_at TEXT,status TEXT)')
        conn.execute('INSERT INTO document_drafts VALUES (?,?,?,?,?,?,?)',('legacy','standard_academic',draft().to_json(),draft(body=('Legacy current',)).to_json(),'2026-01-01','2026-01-02','Draft'))
    loaded=load_draft('legacy')
    assert loaded.sources==('generated','legacy_current')
    with db.material_connection() as conn:assert not has_table(conn,'document_versions')
    save_draft(loaded,'legacy');assert load_draft('legacy')==loaded
    with db.material_connection() as conn:
        init_document_schema(conn);init_document_schema(conn)
        assert conn.execute('select original_json from document_drafts').fetchone()[0]==draft().to_json()
        assert len(conn.execute('select * from document_versions').fetchall())==2


def test_empty_schema_repeat_and_legacy_materials(storage):
    db.add_document_record('Synthetic legacy','C','U1','synthetic.pdf');before=db.get_documents_for_course('C')
    with db.material_connection() as conn:
        init_document_schema(conn);init_document_schema(conn)
        assert not conn.execute('pragma foreign_key_check').fetchall()
    assert list_drafts()==[] and list_preferences()==() and db.get_documents_for_course('C')==before

@pytest.mark.parametrize('field',FIELDS)
def test_field_diff_add_remove_replace(field):
    base=draft(**{field:''});added=replace(base,**{field:'Synthetic Δ'})
    changes=document_diff(base,added);assert len(changes)==1 and changes[0].action=='added'
    assert document_diff(added,base)[0].action=='removed'
    assert document_diff(added,replace(added,**{field:'Different Δ'}))[0].action=='changed'
    assert document_diff(base,added)==changes

@pytest.mark.parametrize('old,new,action',[(('A','C'),('A','B','C'),'added'),(('A','B','C'),('A','C'),'removed'),(('A','B'),('A','D'),'changed')])
def test_body_diff(old,new,action):
    changes=document_diff(draft(body=old),draft(body=new));assert len(changes)==1 and changes[0].action==action


def test_identical_and_large_unicode_diff():
    a=draft(body=tuple('講義 Δ '+str(i)+' Synthetic '*30 for i in range(80)))
    assert document_diff(a,a)==()
    b=replace(a,body=a.body[:40]+('New Unicode ₹ item',)+a.body[41:])
    assert document_diff(a,b)==document_diff(a,b) and document_diff(a,b)[0].category=='factual'

@pytest.mark.parametrize('field,old,new',[('body',('Budget ₹25,000',),('Budget ₹30,000',)),('date','15 November','18 November'),('recipient','HOD','Dean'),('body',('80 students',),('120 students',))])
def test_factual_candidates_not_reusable(field,old,new):
    a=draft(**{field:old});b=replace(a,**{field:new});change=document_diff(a,b)[0]
    assert change.category=='factual' and change.candidate_instruction==''


def test_unknown_body_is_not_assumed_style():
    change=document_diff(draft(),draft(body=('Different event and people',)))[0]
    assert change.category=='unknown' and not change.candidate_instruction


def test_edits_candidates_and_rejection_do_not_store_preferences(storage,monkeypatch):
    versions=DocumentVersions.generated(draft()).update(draft(closing='Regards,'))
    identity=save_draft(versions)
    candidates=document_diff(versions.original,versions.current)
    assert candidates and list_preferences()==() and relevant_preferences(request())==()
    # Ignoring is a session decision; there is no candidate approval side effect.
    assert load_draft(identity).current==versions.current and list_preferences()==()

@pytest.mark.parametrize('instruction',['Use a concise opening.','Prefer short paragraphs.','Avoid overly ceremonial wording.','Use respectful wording Δ.'])
def test_explicit_approved_guidance(storage,instruction):
    identity=approve_preference(instruction,document_type='permission_request')
    assert relevant_preferences(request())[0].preference_id==identity
    assert relevant_preferences(request('notice'))==()
    update_preference(identity,active=False);assert relevant_preferences(request())==()
    update_preference(identity,active=True);assert len(relevant_preferences(request()))==1
    delete_preference(identity);assert relevant_preferences(request())==()

@pytest.mark.parametrize('kwargs',[{'instruction':''},{'instruction':' '},{'instruction':None},{'instruction':'x'*2001},{'category':'factual'},{'category':'unknown'},{'scope':'invalid'},{'scope':'document_type','document_type':None},{'scope':'general','document_type':'notice'},{'scope':'template','template_id':'unknown'},{'tone':'unknown'},{'document_type':[]},{'source_document_id':'x'}])
def test_invalid_preference(storage,kwargs):
    values=dict(instruction='Synthetic guidance',document_type='notice');values.update(kwargs)
    with pytest.raises(DocumentError):approve_preference(**values)
    assert list_preferences()==()


def test_precedence_scope_tone_conflict_and_limit(storage):
    general=approve_preference('Use a detailed opening.',scope='general')
    type_specific=approve_preference('Use a concise opening.',document_type='permission_request')
    template=approve_preference('Use an immediate opening.',scope='template',document_type='permission_request',template_id='standard_academic')
    wrong=approve_preference('Wrong tone guidance',document_type='permission_request',tone='Detailed Official')
    found=relevant_preferences(request());assert [p.preference_id for p in found]==[template]
    delete_preference(template);assert relevant_preferences(request())[0].preference_id==type_specific
    assert relevant_preferences(request('notice'))[0].preference_id==general
    for i in range(12):approve_preference('Distinct instruction '+str(i),scope='general')
    assert len(relevant_preferences(request()))==8
    assert wrong not in [p.preference_id for p in relevant_preferences(request())]


def test_unapproved_inactive_absent(storage):
    identity=approve_preference('Private unapproved instruction',scope='general')
    with db.material_connection() as conn:conn.execute('update document_preferences set approved=0 where preference_id=?',(identity,))
    assert relevant_preferences(request())==()


def test_management_edit_and_blank_safety(storage):
    identity=approve_preference('Use a concise opening.',scope='general')
    update_preference(identity,'Prefer short paragraphs.')
    assert list_preferences()[0].instruction=='Prefer short paragraphs.' and list_preferences()[0].rule_key=='paragraph_length'
    with pytest.raises(DocumentError):update_preference(identity,' ')
    with pytest.raises(DocumentError):update_preference(identity,active='false')
    with pytest.raises(DocumentStorageError):delete_preference('missing')
    assert len(list_preferences())==1


def test_provenance_and_feedback_ownership(storage):
    v=DocumentVersions.generated(draft()).update(draft(body=('Edited private content',)))
    a=save_draft(v);other=DocumentVersions.generated(draft());b=save_draft(other)
    identity=approve_preference('Use a concise opening.',document_type='permission_request',source_document_id=a,source_before_id=v.version_ids[0],source_after_id=v.version_ids[1])
    assert list_preferences()[0].source_document_id==a
    with pytest.raises(DocumentStorageError):approve_preference('Guidance',document_type='permission_request',source_document_id=a,source_before_id=v.version_ids[0],source_after_id=other.version_ids[0])
    with pytest.raises(DocumentStorageError):save_feedback(a,other.version_ids[0],'Good')
    for rating in ('Good','Needs Changes'):save_feedback(a,v.version_ids[-1],rating,'Private synthetic note ₹42,000')
    with pytest.raises(DocumentError):save_feedback(a,v.version_ids[-1],'Unknown')
    with db.material_connection() as conn:
        rows=conn.execute('select * from document_feedback').fetchall();assert len(rows)==2
        assert all(row['document_id']==a and row['version_id']==v.version_ids[-1] for row in rows)
        assert not conn.execute('pragma foreign_key_check').fetchall()


def test_prompt_facts_templates_styles_and_privacy(storage,monkeypatch):
    v=DocumentVersions.generated(draft()).update(draft(body=('Private source body not sent',)));identity=save_draft(v)
    pref=approve_preference('Use a concise opening.',document_type='permission_request',source_document_id=identity,source_before_id=v.version_ids[0],source_after_id=v.version_ids[-1])
    approve_preference('Irrelevant notice guidance',document_type='notice')
    inactive=approve_preference('Inactive private preference',scope='general');update_preference(inactive,active=False)
    response=draft(recipient='');spy=Mock(return_value=response.to_json());monkeypatch.setattr(studio.ai_provider,'generate_chat',spy)
    assert studio.generate_draft(request())==response
    messages=spy.call_args.kwargs['messages'];payload=json.loads(messages[1]['content'])
    assert payload['description']=='Include the detailed ₹42,000 budget breakdown.'
    assert payload['approved_style_guidance']==[{'category':'tone_style','instruction':'Use a concise opening.','scope':'document_type'}]
    assert payload['template_requirements']['template_id']=='standard_academic'
    assert 'Facts and current instructions override style' in messages[0]['content']
    for private in (identity,pref,v.version_ids[0],'Private source body','Inactive private preference','Irrelevant notice guidance'):
        assert private not in messages[1]['content']


def test_activity_contains_no_sensitive_details(storage):
    v=DocumentVersions.generated(draft(body=('Private body with ₹42,000',))).update(draft(body=('Private rewrite',)))
    identity=save_draft(v)
    pref=approve_preference('Private professor wording instruction',scope='general')
    update_preference(pref,'Private edited instruction');update_preference(pref,active=False)
    save_feedback(identity,v.version_ids[-1],'Needs Changes','Private feedback note')
    delete_preference(pref)
    assert all(row['details']=='' for row in db.get_recent_activity(limit=100))


def test_restore_exports_current_no_learning_metadata(storage):
    initial=draft(body=('Initial synthetic text',));edited=replace(initial,body=('Edited synthetic text',))
    v=DocumentVersions.generated(initial).update(edited).restore(0);identity=save_draft(v)
    loaded=load_draft(identity)
    doc=Document(io.BytesIO(document_docx_bytes(loaded.current)))
    text='\n'.join(p.text for p in doc.paragraphs)
    with pdfplumber.open(io.BytesIO(document_pdf_bytes(loaded.current))) as pdf:pdftext='\n'.join(p.extract_text() or '' for p in pdf.pages)
    for output in (text,pdftext):
        assert 'Initial synthetic text' in output and 'Edited synthetic text' not in output
        assert identity not in output and all(version not in output for version in v.version_ids)


def test_comparison_identity_stable_across_first_save():
    assert comparison_key(None,'before','after')==comparison_key('saved-document','before','after')


def test_raw_foreign_key_ownership_guards(storage):
    import sqlite3
    a=DocumentVersions.generated(draft());aid=save_draft(a)
    b=DocumentVersions.generated(draft());bid=save_draft(b)
    with db.material_connection() as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        with pytest.raises(sqlite3.IntegrityError):conn.execute('INSERT INTO document_feedback VALUES (?,?,?,?,?,?)',('invalid',aid,b.version_ids[0],'Good','','now'))
        with pytest.raises(sqlite3.IntegrityError):conn.execute('INSERT INTO document_versions VALUES (?,?,?,?,?,?,?)',('invalid',aid,2,'restored',a.original.to_json(),'now',b.version_ids[0]))


def test_precedence_other_topics_specific_before_general(storage):
    general=approve_preference('Use approachable vocabulary.',scope='general')
    typed=approve_preference('Emphasize academic benefit.',document_type='permission_request')
    template=approve_preference('Keep headings professional.',scope='template',template_id='standard_academic')
    assert [p.preference_id for p in relevant_preferences(request())]==[template,typed,general]
