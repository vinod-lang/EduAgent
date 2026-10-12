"""Build 27 isolated HTTP security, lazy browsing and stale revision checks."""
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
import pytest
import ai_provider
from test_api import web,client
from test_security import secured,services
from test_document_workspace import document,edit,path
from test_assessment_workspace import assessment

@pytest.mark.parametrize('url',['/dashboard','/materials','/documents','/documents/catalog','/preferences','/students/workspaces','/activity/page','/system/ai'])
def test_browsing_remains_lazy(web,monkeypatch,url):
    spy=Mock(side_effect=AssertionError('Browsing must not use inference'))
    monkeypatch.setattr(ai_provider,'generate_chat',spy)
    factory=Mock(side_effect=AssertionError('Browsing must not initialize vectors'))
    web.state.services.knowledge.collection_factory=factory
    assert client(web).get('/api/v1'+url).status_code==200
    spy.assert_not_called();factory.assert_not_called()

@pytest.mark.parametrize('method,url,body',[
 ('post','/knowledge/answer',{'question':'Synthetic'}),
 ('post','/assistant/plan',{'request':'Open dashboard'}),
 ('post','/students/guessed/analyze',{}),
 ('delete','/materials/guessed',None),
 ('patch','/document-workspaces/guessed',{'body':['Synthetic']}),
 ('post','/preferences',{'instruction':'Synthetic style'}),
 ('post','/auth/logout',{})])
def test_mutations_reject_missing_csrf_before_work(web,method,url,body):
    c=client(web);c.headers.pop('X-CSRF-Token')
    r=getattr(c,method)('/api/v1'+url,**({'json':body} if body is not None else {}))
    assert r.status_code==403 and r.json()['error']['code']=='CSRF_REJECTED'

@pytest.mark.parametrize('url',['/dashboard','/materials','/documents','/preferences','/activity/page','/students/workspaces'])
def test_expiry_read_hides_private_content(web,url):
    c=client(web);web.state.sessions.clock=lambda:10**20
    r=c.get('/api/v1'+url);assert r.status_code==401
    assert 'Synthetic A' not in r.text

def test_document_stale_edit_and_resolution_preserve_valid_version(document):
    c,d,_=document;draft=edit(d);draft['body']=['Synthetic edit. Budget ₹2500.']
    r=c.patch(path(d),json={**draft,'expected_version':1});assert r.status_code==200
    stale={**draft,'body':['Stale edit'],'expected_version':1}
    assert c.patch(path(d),json=stale).status_code==409
    assert c.post(path(d)+'/resolve-edit',json={'draft':stale,'update_confirmed':True}).status_code==409
    assert c.get(path(d)).json()['body']==r.json()['body']

def test_near_concurrent_document_edits_cannot_overwrite(document):
    c,d,_=document;draft={**edit(d),'expected_version':1,'body':['Synthetic edit. Budget ₹2500.']}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:c.patch(path(d),json=draft).status_code,range(2)))
    assert sorted(results)==[200,409]
    assert c.get(path(d)).json()['version_count']==2

def test_fact_continuity_conflict_resolution_history_export(document):
    c,d,provider=document
    provider.return_value=__import__('json').dumps({k:d[k] for k in ('document_type','title','recipient','sender','date','reference_number','subject','signature','salutation','closing','body')})
    refined=c.post(path(d)+'/refine',json={'instruction':'Keep all facts and make concise.'});assert refined.status_code==200
    draft=edit(refined.json());draft['date']='16 October 2026'
    assert c.patch(path(d),json=draft).status_code==409
    assert c.get(path(d)).json()['date']==d['date']
    resolved=c.post(path(d)+'/resolve-edit',json={'draft':draft,'update_confirmed':True}).json()
    assert resolved['date']=='16 October 2026' and any(f['value']=='16 October 2026' for f in resolved['facts'])
    assert c.post(path(d)+'/save',json={}).status_code==200
    exported=c.get(path(d)+'/export?format=docx')
    from docx import Document
    from io import BytesIO
    text='\n'.join(p.text for p in Document(BytesIO(exported.content)).paragraphs)
    assert '16 October 2026' in text and 'expected_version' not in text


def test_assessment_invalid_edit_does_not_replace_exportable_version(assessment):
    from test_assessment_workspace import edit_body
    c,a,_,_=assessment;p='/api/v1/assessments/'+a['handle'];body=edit_body(a);body['questions'][0]['marks']=0
    assert c.patch(p,json=body).status_code==422 and c.get(p).json()==a
    assert c.get(p+'/export?format=pdf').content.startswith(b'%PDF')

def test_student_workflow_no_provider_or_log_markers(web,monkeypatch,caplog,capsys):
    from test_assistant_web import test_student_provider_boundary_full_assistant_workflow
    test_student_provider_boundary_full_assistant_workflow(web,monkeypatch)
    captured=capsys.readouterr();logs=caplog.text+captured.out+captured.err
    for marker in ('PRIVID826','SyntheticPrivacy826','83.456','47.123'):assert marker not in logs
