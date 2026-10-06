"""Mocked plans/generation; all storage belongs to isolated fixtures."""
import json
from dataclasses import replace
from unittest.mock import Mock
import pytest
import ai_provider
from test_api import web,client
from test_security import secured,services,ctx
from test_document_workspace import document,REQUEST
from test_assessment_workspace import assessment,BODY
from assistant_models import parse_plan
from security.models import Status

def action(kind='NAVIGATE',parameters=None,id='step',dependencies=()):
 return dict(action_id=id,action_type=kind,parameters=parameters or {'page':'Professor Dashboard'},depends_on=list(dependencies))
def plan(c,monkeypatch,actions=None,unsupported=False,student=None):
 import assistant_planner
 p=parse_plan(json.dumps(dict(unsupported=unsupported,actions=[] if unsupported else actions or [action()])), 'Synthetic request')
 monkeypatch.setattr(assistant_planner,'plan_request',lambda *a,**k:p)
 r=c.post('/api/v1/assistant/plan',json={'request':'Synthetic request','student_handle':student});assert r.status_code==200,r.text;return '/api/v1/assistant/'+r.json()['handle']
def execute(c,path):
 r=c.post(path+'/execute',json={'confirmed':True});assert r.status_code==200,r.text;return c.get(path+'/results')

def test_navigation_server_results_and_discard(web,monkeypatch):
 c=client(web);path=plan(c,monkeypatch);assert c.get(path+'/results').status_code==404
 r=execute(c,path);assert r.json()['results'][0]['destination']=='/home';assert c.delete(path).status_code==200;assert c.get(path+'/results').status_code==404

@pytest.mark.parametrize('op',['preview','results','execute','handoff','discard'])
def test_plan_foreign_professor_session_and_guessed_handles(web,monkeypatch,op):
 c=client(web);path=plan(c,monkeypatch);execute(c,path)
 for other,base in [(client(web,'b'),path),(client(web,'a'),path),(c,'/api/v1/assistant/guessed')]:
  r=other.get(base+'/'+op) if op in ('preview','results') else other.delete(base) if op=='discard' else other.post(base+'/'+op,json={'confirmed':True} if op=='execute' else {'action_id':'step','destination':'DOCUMENT'})
  assert r.status_code==404

def test_confirmation_and_client_plan_replacement_rejected(web,monkeypatch):
 c=client(web);path=plan(c,monkeypatch)
 for b in [{'confirmed':False},{'confirmed':True,'actions':[{'shell':'bad'}]}]:assert c.post(path+'/execute',json=b).status_code==422
 assert c.get(path+'/results').status_code==404

def test_clarification_has_no_execution(web,monkeypatch):
 c=client(web);path=plan(c,monkeypatch,[action('CREATE_DOCUMENT',{'document_type':'notice'})]);p=c.get(path+'/preview').json();assert not p['valid'] and p['clarifications'][0]['missing_fields']==['description'];assert c.post(path+'/execute',json={'confirmed':True}).status_code==422

def test_refusal(web,monkeypatch):
 c=client(web);path=plan(c,monkeypatch,unsupported=True);assert c.get(path+'/preview').json()['unsupported'];assert c.post(path+'/execute',json={'confirmed':True}).status_code==422

def test_partial_failure_explicit_retry_retains_success(web,monkeypatch):
 from application.errors import ProviderUnavailableError
 c=client(web);path=plan(c,monkeypatch,[action('ASK_KNOWLEDGE',{'question':'Synthetic'},'ask'),action(id='nav')]);spy=Mock(side_effect=ProviderUnavailableError());monkeypatch.setattr(web.state.services.knowledge,'ask',spy)
 r=execute(c,path);assert r.json()['status']=='partial_failure';assert r.json()['results'][0]['status']=='failed';assert 'Traceback' not in r.text
 assert c.post(path+'/execute',json={'confirmed':True}).status_code==422
 assert c.post(path+'/execute',json={'confirmed':True,'retry':True}).status_code==200;assert spy.call_count==2

def test_document_handoff_uses_studio_and_preserves_facts(document,web,monkeypatch):
 c,d,provider=document;ws=web.state.workspaces.rows[d['handle']][3];monkeypatch.setattr(web.state.services.documents,'generate',Mock(return_value=ws))
 path=plan(c,monkeypatch,[action('CREATE_DOCUMENT',REQUEST)]);r=execute(c,path);assert r.json()['results'][0]['destination']=='/documents';assert 'body' not in r.text
 h=c.post(path+'/handoff',json={'action_id':'step','destination':'DOCUMENT'});assert h.status_code==200,h.text
 read=c.get('/api/v1/document-workspaces/'+h.json()['handle']);assert read.json()['body']==d['body'] and read.json()['facts']==d['facts'];assert provider.call_count==1
 assert c.post(path+'/handoff',json={'action_id':'step','destination':'ASSESSMENT'}).status_code==422
 assert c.post(path+'/handoff',json={'action_id':'missing','destination':'DOCUMENT'}).status_code==404
 assert client(web,'b').get('/api/v1/document-workspaces/'+h.json()['handle']).status_code==404


def test_assessment_handoff_and_source_revocation(assessment,web,secured,monkeypatch):
 c,a,provider,body=assessment;ws=web.state.workspaces.rows[a['handle']][3];monkeypatch.setattr(web.state.services.assessments,'generate',Mock(return_value=ws));params={k:v for k,v in body.items() if k not in ('course','semester','subject','units','material_ids')};params['scope']={k:body[k] for k in ('course','semester','subject','units','material_ids')}
 path=plan(c,monkeypatch,[action('CREATE_ASSESSMENT',params)]);execute(c,path);h=c.post(path+'/handoff',json={'action_id':'step','destination':'ASSESSMENT'});assert h.status_code==200,h.text
 url='/api/v1/assessments/'+h.json()['handle'];assert c.get(url).json()['questions']==a['questions'];assert client(web,'b').get(url).status_code==404
 secured.repo.remove_ownership('material',body['material_ids'][0]);assert c.post(path+'/handoff',json={'action_id':'step','destination':'ASSESSMENT'}).status_code==404;assert c.get(url).status_code==404


def test_handoff_expiry_and_logout(document,web,monkeypatch):
 c,d,_=document;ws=web.state.workspaces.rows[d['handle']][3];monkeypatch.setattr(web.state.services.documents,'generate',Mock(return_value=ws));path=plan(c,monkeypatch,[action('CREATE_DOCUMENT',REQUEST)]);execute(c,path);h=c.post(path+'/handoff',json={'action_id':'step','destination':'DOCUMENT'}).json()['handle'];web.state.workspaces.clock=lambda:10**20
 assert c.get('/api/v1/document-workspaces/'+h).status_code==404
 assert c.post('/api/v1/auth/logout',json={}).status_code==200;assert not web.state.workspaces.rows

def test_actor_revocation(web,secured,monkeypatch):
 c=client(web);path=plan(c,monkeypatch);secured.repo.update_professor(replace(secured.a,status=Status.INACTIVE));assert c.post(path+'/execute',json={'confirmed':True}).status_code in (401,403)


def test_student_provider_boundary_full_assistant_workflow(web,monkeypatch):
 # Distinctive synthetic values must never reach the planner/provider.
 c=client(web);b=c.post('/api/v1/students/upload',files={'file':('synthetic.csv',b'ID,Name,Attendance,Quiz\nPRIVID826,SyntheticPrivacy826,83.456,47.123\n')}).json();m=dict(sheet='CSV',header_row=1,student_id='ID',student_name='Name',attendance='Attendance',assessments=[dict(column='Quiz',name='Quiz')]);h=c.post('/api/v1/students/'+b['handle']+'/normalize',json=m).json()['handle']
 spy=Mock(side_effect=AssertionError('No student operation should invoke AI'));monkeypatch.setattr(ai_provider,'generate_chat',spy)
 p=c.post('/api/v1/assistant/plan',json={'request':'Show students with concern.','student_handle':h});assert p.status_code==200,p.text;path='/api/v1/assistant/'+p.json()['handle'];r=execute(c,path);assert r.json()['results'][0]['student_count']==1
 for marker in ('PRIVID826','SyntheticPrivacy826','83.456','47.123'):assert marker not in r.text
 assert c.get('/api/v1/students/workspaces').json()==[{'handle':h}];assert c.get('/api/v1/students/'+h+'/review').status_code==200
 rejected=c.post('/api/v1/assistant/plan',json={'request':'Write personalized advice for SyntheticPrivacy826','student_handle':h});assert rejected.status_code==400;spy.assert_not_called()
 c.delete('/api/v1/students/'+h);assert c.get(path+'/results').status_code==404

def test_student_abstract_metadata_only_for_nonstudent_plan(web,monkeypatch):
 import assistant_planner
 c=client(web);b=c.post('/api/v1/students/upload',files={'file':('synthetic.csv',b'ID,Name,Attendance,Quiz\nPRIVID826,SyntheticPrivacy826,83.456,47.123\n')}).json();h=c.post('/api/v1/students/'+b['handle']+'/normalize',json=dict(sheet='CSV',header_row=1,student_id='ID',student_name='Name',attendance='Attendance',assessments=[dict(column='Quiz',name='Quiz')])).json()['handle']
 spy=Mock(return_value=json.dumps({'actions':[action()], 'unsupported':False}));monkeypatch.setattr(ai_provider,'generate_chat',spy)
 p=c.post('/api/v1/assistant/plan',json={'request':'Open dashboard','student_handle':h});assert p.status_code==200,p.text
 capture=str(spy.call_args_list)
 for marker in ('PRIVID826','SyntheticPrivacy826','83.456','47.123'):assert marker not in capture
 assert 'student_dataset_available' in capture

@pytest.mark.parametrize('category',['INVALID_JSON','SCHEMA_INVALID','PRODUCT_VALIDATION_FAILED','PROVIDER_ERROR','TIMEOUT'])
def test_planner_diagnostics_never_raw(web,monkeypatch,category):
 import assistant_planner
 from assistant_models import PlanError
 from generation_diagnostics import failed
 error=PlanError('RAW PRIVATE /machine/path');error.generation_diagnostic=failed(category)
 monkeypatch.setattr(assistant_planner,'plan_request',Mock(side_effect=error));r=client(web).post('/api/v1/assistant/plan',json={'request':'Synthetic'});assert r.status_code==422;assert 'RAW PRIVATE' not in r.text and '/machine/path' not in r.text


def test_knowledge_scope_handoff_no_evidence_and_ownership(web,monkeypatch):
 c=client(web);path=plan(c,monkeypatch,[action('ASK_KNOWLEDGE',{'question':'Synthetic PCA','filters':{'course':'ML'}})]);spy=Mock(side_effect=AssertionError('No evidence must not generate'));monkeypatch.setattr(ai_provider,'generate_chat',spy)
 r=execute(c,path);assert r.status_code==200 and r.json()['results'][0]['grounded'] is False;spy.assert_not_called()
 h=c.post(path+'/handoff',json={'action_id':'step','destination':'KNOWLEDGE_SCOPE'});assert h.status_code==200,h.text
 url='/api/v1/knowledge-scopes/'+h.json()['handle'];assert c.get(url).json()=={'question':'Synthetic PCA','filters':{'course':'ML'}}
 assert client(web,'b').get(url).status_code==404 and client(web,'a').get(url).status_code==404

def test_failed_assessment_blocks_document_dependency(web,monkeypatch):
 from application.errors import InsufficientEvidenceError
 c=client(web);scope={k:BODY[k] for k in ('course','semester','subject','units','material_ids')};params={k:v for k,v in BODY.items() if k not in scope};params['scope']=scope
 path=plan(c,monkeypatch,[action('CREATE_ASSESSMENT',params,'quiz'),action('CREATE_DOCUMENT',REQUEST,'notice',('quiz',))]);monkeypatch.setattr(web.state.services.assessments,'generate',Mock(side_effect=InsufficientEvidenceError()));doc=Mock();monkeypatch.setattr(web.state.services.documents,'generate',doc)
 r=execute(c,path);assert [v['status'] for v in r.json()['results']]==['failed','blocked'];doc.assert_not_called();assert c.post(path+'/handoff',json={'action_id':'notice','destination':'DOCUMENT'}).status_code==404


def test_cached_knowledge_scope_rechecks_source_ownership(web,services,secured,monkeypatch):
 from test_security import upload
 record=upload(services[0],secured,secured.a,'Synthetic PCA');c=client(web);path=plan(c,monkeypatch,[action('ASK_KNOWLEDGE',{'question':'Explain PCA','filters':{'material_id':record['material_id']}})]);monkeypatch.setattr(ai_provider,'generate_chat',Mock(return_value='Synthetic grounded explanation.'));assert execute(c,path).json()['results'][0]['grounded'] is True
 h=c.post(path+'/handoff',json={'action_id':'step','destination':'KNOWLEDGE_SCOPE'}).json()['handle'];secured.repo.remove_ownership('material',record['material_id']);assert c.get('/api/v1/knowledge-scopes/'+h).status_code==404;assert c.get(path+'/results').status_code==404;assert c.post(path+'/execute',json={'confirmed':True,'retry':True}).status_code==404
