"""Build 24 synthetic document web contracts; isolated storage and mocked inference."""
import io,json,sqlite3
from unittest.mock import Mock
import pytest
import ai_provider,db
from test_api import web,client
from test_security import secured,services,own

REQUEST=dict(document_type='notice',description='Announce a synthetic tutorial.',title='Synthetic tutorial notice',date='14 October 2026',reference_number='SYN/2026/01',recipient='Synthetic students',sender='Synthetic department',subject='Tutorial',signature='Synthetic professor')
def response(request=REQUEST):
    return dict(document_type=request['document_type'],title=request.get('title',''),date=request.get('date',''),reference_number=request.get('reference_number',''),recipient=request.get('recipient',''),sender=request.get('sender',''),subject=request.get('subject',''),signature=request.get('signature',''),salutation='',closing='',body=['Synthetic tutorial for students. Budget ₹2500.'])
@pytest.fixture
def document(web,monkeypatch):
    provider=Mock(return_value=json.dumps(response(),ensure_ascii=False));monkeypatch.setattr(ai_provider,'generate_chat',provider);c=client(web)
    r=c.post('/api/v1/documents/generate',json=REQUEST);assert r.status_code==200,r.text
    return c,r.json(),provider

def edit(doc):return {k:doc[k] for k in ('title','date','reference_number','recipient','sender','subject','signature','salutation','closing','body')}
def path(doc):return '/api/v1/document-workspaces/'+doc['handle']

def test_catalog_authoritative_and_import_safe(web):
    from document_models import CATALOG,TONES
    c=client(web);r=c.get('/api/v1/documents/catalog');assert r.status_code==200
    assert {t['value'] for t in r.json()['types']}==set(CATALOG) and len(CATALOG)==17
    assert r.json()['tones']==list(TONES)
    with db.material_connection() as conn:assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='document_drafts'").fetchone()

def test_generation_safe_provenance_and_unsaved_workspace(document):
    c,d,provider=document;assert not d['saved'] and d['document_id'] is None
    assert d['versions'][0]['source']=='generated' and d['provenance']['validation_status']=='Validated'
    assert any(f['value']=='14 October 2026' for f in d['facts'])
    assert not any(k in json.dumps(d) for k in ('response_hash','system_prompt','base_url','expectation_snapshots','source_before_id'))
    assert c.get(path(d)).json()==d and c.get('/api/v1/documents').json()==[]
    assert provider.call_count==1

def test_save_title_list_reload_and_no_title_migration(document):
    c,d,_=document;saved=c.post(path(d)+'/save',json={'status':'Draft'}).json();assert saved['saved']
    rows=c.get('/api/v1/documents').json();assert rows[0]['title']==REQUEST['title'] and rows[0]['document_type']=='notice' and rows[0]['version_count']==1
    loaded=c.get('/api/v1/documents/'+saved['document_id']).json();assert loaded['saved'] and loaded['facts']==d['facts']
    with db.material_connection() as conn:assert 'title' not in [r[1] for r in conn.execute('PRAGMA table_info(document_drafts)')]

@pytest.mark.parametrize('operation',['load','versions','review','edit','save','facts','manage_fact','diff','conflicts','resolve','restore','refine','feedback','export','discard'])
def test_private_document_operations_and_guessed_handles(document,web,operation):
    c,d,provider=document;saved=c.post(path(d)+'/save',json={}).json();other=client(web,'b');p=path(d)
    calls={
      'load':lambda:other.get('/api/v1/documents/'+saved['document_id']),
      'versions':lambda:other.get('/api/v1/documents/'+saved['document_id']+'/versions'),
      'review':lambda:other.get(p),'edit':lambda:other.patch(p,json=edit(d)),
      'save':lambda:other.post(p+'/save',json={}), 'facts':lambda:other.get(p+'/facts'),
      'manage_fact':lambda:other.post(p+'/facts',json={'operation':'add','field':'body','value':'PRIVATE synthetic'}),
      'diff':lambda:other.get(p+'/diff?before=0&after=0'),
      'conflicts':lambda:other.post(p+'/conflicts',json=edit(d)),
      'resolve':lambda:other.post(p+'/resolve-edit',json={'draft':edit(d),'update_confirmed':True}),
      'restore':lambda:other.post(p+'/restore',json={'index':0}),
      'refine':lambda:other.post(p+'/refine',json={'instruction':'Make concise'}),
      'feedback':lambda:other.post(p+'/feedback',json={'rating':'Good','note':'private'}),
      'export':lambda:other.get(p+'/export'), 'discard':lambda:other.delete(p)}
    assert calls[operation]().status_code==404
    assert other.get('/api/v1/documents').json()==[]
    assert other.get('/api/v1/document-workspaces/guessed').status_code==404
    assert provider.call_count==1

def test_same_professor_different_session_cannot_use_workspace(document,web):
    _,d,_=document;assert client(web,'a').get(path(d)).status_code==404

def test_explicit_edit_save_and_refinement_history(document):
    c,d,provider=document;draft=edit(d);draft['body']=['Professor concise synthetic tutorial. Budget ₹2500.']
    revised=c.patch(path(d),json=draft);assert revised.status_code==200,revised.text
    revised=revised.json();assert revised['version_count']==2 and not revised['saved'] and revised['provenance']['professor_edited']
    assert provider.call_count==1
    c.post(path(d)+'/save',json={'status':'Final'})
    provider.return_value=json.dumps(dict(response(),body=['Refined synthetic tutorial. Budget ₹2500.']),ensure_ascii=False)
    refined=c.post(path(d)+'/refine',json={'instruction':'Make more concise'});assert refined.status_code==200,refined.text
    a=refined.json();assert a['date']==d['date'] and a['facts']==d['facts'] and a['version_count']==3 and not a['saved']
    assert a['versions'][-1]['source']=='ai_refinement'
    assert a['provenance']['generation_type']=='document refinement'

@pytest.mark.parametrize('raw',['RAW PRIVATE /secret invalid JSON',json.dumps(dict(response(),date='Invented date'))])
def test_failed_refinement_preserves_current_and_safe_diagnostic(document,raw):
    c,d,provider=document;provider.return_value=raw
    r=c.post(path(d)+'/refine',json={'instruction':'Make concise'});assert r.status_code==422
    assert 'diagnostic' in r.json()['error'] and 'RAW PRIVATE' not in r.text and '/secret' not in r.text
    assert c.get(path(d)).json()==d

def test_conflict_inspection_explicit_resolution_and_restore(document):
    c,d,_=document;draft=edit(d);draft['date']='16 October 2026'
    assert c.patch(path(d),json=draft).status_code==409;assert c.get(path(d)).json()==d
    facts=c.post(path(d)+'/conflicts',json=draft).json();assert len(facts)==1 and facts[0]['field']=='date'
    kept=c.post(path(d)+'/resolve-edit',json={'draft':draft,'update_confirmed':False}).json();assert kept==d
    updated=c.post(path(d)+'/resolve-edit',json={'draft':draft,'update_confirmed':True}).json();assert updated['date']=='16 October 2026' and updated['version_count']==2
    assert next(f['value'] for f in updated['facts'] if f['field']=='date')=='16 October 2026'
    compared=c.get(path(d)+'/diff?before=0&after=1').json();assert compared==[{'field':'date','action':'changed','before':['14 October 2026'],'after':['16 October 2026']}]
    restored=c.post(path(d)+'/restore',json={'index':0}).json();assert restored['version_count']==3 and restored['date']==d['date'] and restored['facts']==d['facts']
    assert restored['versions'][-1]['source']=='restored' and restored['provenance']==d['provenance']

@pytest.mark.parametrize('index',[-1,12])
def test_bad_diff_or_restore_indexes_are_controlled(document,index):
    c,d,_=document;assert c.get(path(d)+f'/diff?before={index}&after=0').status_code==422
    assert c.post(path(d)+'/restore',json={'index':index}).status_code==422
    assert c.get(path(d)).json()==d

def test_fact_management_unicode_boundary_and_body_conflict(document):
    c,d,_=document;p=path(d)
    assert c.post(p+'/facts',json={'operation':'add','field':'body','value':'₹2500'}).status_code==200
    a=c.get(p).json();f=next(f for f in a['facts'] if f['field']=='body')
    assert a['version_count']==2
    draft=edit(a);draft['body']=['Synthetic budget ₹25000.']
    assert c.patch(p,json=draft).status_code==409
    assert c.post(p+'/resolve-edit',json={'draft':draft,'update_confirmed':True,'replacements':{f['fact_id']:'₹25000'}}).status_code==200
    assert c.post(p+'/facts',json={'operation':'update','fact_id':f['fact_id'],'value':'₹2500'}).status_code==409
    assert c.post(p+'/facts',json={'operation':'remove','fact_id':f['fact_id']}).status_code==200
    assert not any(f['field']=='body' for f in c.get(p).json()['facts'])

def test_expected_invalid_manual_content_is_not_500(document):
    c,d,_=document;draft=edit(d);draft['body']=[''];r=c.patch(path(d),json=draft);assert r.status_code==422 and 'Traceback' not in r.text
    assert c.get(path(d)).json()==d

def test_preferences_isolation_explicit_approval_and_provenance(document,web):
    c,d,provider=document;other=client(web,'b')
    preference=c.post('/api/v1/preferences',json={'instruction':'Use short natural paragraphs.','scope':'general'}).json()['handle']
    own=c.get('/api/v1/preferences').json();assert own[0]['approved'] and own[0]['active'] and own[0]['document_type'] is None
    assert other.get('/api/v1/preferences').json()==[]
    assert other.patch('/api/v1/preferences/'+preference,json={'active':False}).status_code==404
    assert other.delete('/api/v1/preferences/'+preference).status_code==404
    a=c.post('/api/v1/documents/generate',json=REQUEST).json();assert a['provenance']['preferences_applied']
    assert 'Use short natural paragraphs.' in provider.call_args.kwargs['messages'][-1]['content']
    assert c.patch('/api/v1/preferences/'+preference,json={'active':False}).status_code==200
    assert not c.post('/api/v1/documents/generate',json=REQUEST).json()['provenance']['preferences_applied']
    assert c.delete('/api/v1/preferences/'+preference).status_code==200

def test_feedback_requires_saved_current_version_and_logs_remain_empty(document):
    c,d,_=document;p=path(d);assert c.post(p+'/feedback',json={'rating':'Good'}).status_code==422
    c.post(p+'/save',json={});assert c.post(p+'/feedback',json={'rating':'Good','note':'Synthetic private feedback'}).status_code==200
    with db.material_connection() as conn:
        assert conn.execute('SELECT note FROM document_feedback').fetchone()[0]=='Synthetic private feedback'
        assert not any(row[0] for row in conn.execute('SELECT details FROM activity_log'))
    assert 'Synthetic private feedback' not in c.get('/api/v1/activity').text

def test_exports_contain_current_valid_content_without_private_metadata(document):
    from docx import Document
    c,d,_=document;p=path(d);draft=edit(d);draft['body']=['Professor reviewed synthetic body. Budget 2500.']
    assert c.patch(p,json=draft).status_code==200
    data=c.get(p+'/export?format=docx');assert data.status_code==200
    text='\n'.join(p.text for p in Document(io.BytesIO(data.content)).paragraphs)
    assert draft['body'][0] in text and 'qwen2.5' not in text and 'fact_id' not in text
    assert c.get(p+'/export?format=pdf').content.startswith(b'%PDF')

def test_discard_keeps_saved_document_and_logout_invalidates_handles(document):
    c,d,_=document;saved=c.post(path(d)+'/save',json={}).json();assert c.delete(path(d)).status_code==200
    assert c.get('/api/v1/documents/'+saved['document_id']).status_code==200
    assert c.get(path(d)).status_code==404
    c.post('/api/v1/auth/logout');assert c.get('/api/v1/documents').status_code==401

@pytest.mark.parametrize('suffix,method,body',[('', 'patch',{'body':['Synthetic']}),('/save','post',{}),('/facts','post',{'operation':'remove','fact_id':'unknown'}),('/resolve-edit','post',{'draft':{'body':['Synthetic']},'update_confirmed':True})])
def test_document_csrf_mutations_rejected(document,suffix,method,body):
    c,d,_=document;del c.headers['X-CSRF-Token'];assert getattr(c,method)(path(d)+suffix,json=body).status_code==403

def test_legacy_list_projects_supplied_subject_without_inventing_title(web,secured):
    from document_models import DocumentDraft
    from document_repository import init_document_schema
    from security.repository import SecurityRepository
    import uuid
    identity=str(uuid.uuid4());draft=DocumentDraft('notice',subject='Synthetic legacy subject',body=('Synthetic legacy paragraph.',))
    with db.material_connection() as conn:
        init_document_schema(conn);conn.execute('INSERT INTO document_drafts VALUES (?,?,?,?,?,?,?)',(identity,'standard_academic',draft.to_json(),draft.to_json(),'2026-10-01T00:00:00+00:00','2026-10-01T00:00:00+00:00','Draft'))
        SecurityRepository.attach_ownership(conn,'document',identity,own(secured.a))
    c=client(web);rows=c.get('/api/v1/documents').json();assert rows[0]['title']=='Synthetic legacy subject' and rows[0]['version_count']==1
    legacy=c.get('/api/v1/documents/'+identity).json();assert legacy['facts']==[] and legacy['provenance'] is None


def test_pdf_missing_font_returns_actionable_safe_error(document,monkeypatch):
    c,d,_=document;monkeypatch.setenv('EDUAGENT_DOCUMENT_FONT','/private/synthetic-missing-font.ttf')
    r=c.get(path(d)+'/export?format=pdf');assert r.status_code==422
    assert r.json()['error']['code']=='PDF_FONT_UNAVAILABLE' and 'export DOCX' in r.json()['error']['message']
    assert '/private/' not in r.text


def test_feedback_rejects_applied_unsaved_version_before_storage_write(document):
    c,d,_=document;p=path(d);c.post(p+'/save',json={})
    draft=edit(d);draft['body']=['Professor revised synthetic tutorial.']
    assert c.patch(p,json=draft).status_code==200
    assert c.post(p+'/feedback',json={'rating':'Good','note':'Do not save yet'}).status_code==422
    with db.material_connection() as conn:assert conn.execute('SELECT COUNT(*) FROM document_feedback').fetchone()[0]==0
