"""Build 20 synthetic HTTP chain, session lifecycle and import/storage safety."""
from dataclasses import replace
import hashlib,json,sqlite3,subprocess,sys,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
import db
from test_security import secured,services,upload,ctx,own
from security.models import Scope,Status
from security.sessions import SessionService,digest
from api import create_api_app
from api.settings import APISettings

KEY='synthetic-development-access-key-0000000000'
@pytest.fixture
def web(secured,services):
    s=secured;api,_,_=services
    cfg=APISettings(mode='development',dev_auth_enabled=True,dev_access_key=KEY,dev_identities={n:getattr(s,n).professor_id for n in ('a','b','c','d')},database_path=db.DB_PATH,cors_origins=('http://frontend.test',))
    sessions=SessionService(s.repo);sessions.initialize()
    app=create_api_app(settings=cfg,services=api,sessions=sessions)
    return app

def client(web,alias='a'):
    c=TestClient(web,raise_server_exceptions=False)
    r=c.post('/api/v1/auth/dev-login',json={'identity':alias},headers={'X-Development-Key':KEY})
    assert r.status_code==200,r.text
    c.headers['X-CSRF-Token']=r.json()['csrf_token']
    return c


def test_factory_routes_and_openapi(web):
    c=TestClient(web)
    schema=c.get('/api/v1/openapi.json').json()
    assert '/api/v1/knowledge/answer' in schema['paths']
    assert len(schema['paths'])>=30
    assert 'ProfessorContext' not in str(schema)
    assert 'dev_access_key' not in str(schema)
    assert c.get('/api/v1/health').json()=={'status':'ok'}
    assert c.get('/api/v1/readiness').json()['production_ready'] is False


def test_login_profile_cookie_session_hashed(web,secured):
    c=client(web);profile=c.get('/api/v1/auth/me')
    assert profile.status_code==200 and profile.json()['professor_id']==secured.a.professor_id
    assert set(profile.json())=={'professor_id','display_name','institution_id','department_id'}
    token=c.cookies.get('eduagent_session')
    with secured.repo.connection() as conn:
        row=dict(conn.execute('SELECT * FROM auth_sessions').fetchone())
    assert row['token_hash']==digest(token) and token not in str(row)
    assert 'csrf_token' not in profile.text
    r=TestClient(web).post('/api/v1/auth/dev-login',json={'identity':'a'},headers={'X-Development-Key':KEY})
    cookie=r.headers['set-cookie'].lower()
    assert 'httponly' in cookie and 'samesite=strict' in cookie and 'max-age=3600' in cookie and 'secure' not in cookie

@pytest.mark.parametrize('body',[{'identity':'unknown'},{'identity':'a','professor_id':'fake'},{'professor_id':'fake'}])
def test_login_unknown_and_injected_claims(web,body):
    response=TestClient(web).post('/api/v1/auth/dev-login',json=body,headers={'X-Development-Key':KEY})
    assert response.status_code in (401,422)
    assert 'fake' not in response.text


def test_development_auth_refused_without_key_and_origin(web):
    c=TestClient(web)
    assert c.post('/api/v1/auth/dev-login',json={'identity':'a'}).status_code==401
    assert c.post('/api/v1/auth/dev-login',json={'identity':'a'},headers={'X-Development-Key':KEY,'Origin':'https://evil.test'}).status_code==403


def test_production_auth_disabled(services):
    api,_,_=services
    app=create_api_app(settings=APISettings(),services=api)
    c=TestClient(app)
    assert c.post('/api/v1/auth/dev-login',json={'identity':'a'},headers={'X-Development-Key':KEY}).status_code==401
    assert c.get('/api/v1/openapi.json').status_code==404
    with pytest.raises(ValueError):APISettings(mode='production',dev_auth_enabled=True,dev_access_key=KEY)
    assert APISettings().secure_cookie

@pytest.mark.parametrize('token',[None,'invalid','x'*50])
def test_missing_invalid_auth(web,token):
    c=TestClient(web)
    if token:c.cookies.set('eduagent_session',token,path='/api/v1')
    assert c.get('/api/v1/materials').status_code==401
    assert c.get('/api/v1/auth/me').status_code==401


def test_inactive_unknown_professor_sessions(web,secured,monkeypatch):
    c=client(web);secured.repo.update_professor(replace(secured.a,status=Status.INACTIVE))
    assert c.get('/api/v1/auth/me').status_code==401
    assert c.post('/api/v1/auth/dev-login',json={'identity':'a'},headers={'X-Development-Key':KEY}).status_code==401
    monkeypatch.setattr(secured.repo,'get_professor',lambda _:None)
    assert c.get('/api/v1/auth/me').status_code==401


def test_expiry_revocation_logout_and_workspace_cleanup(web):
    c=client(web);p=web.state.sessions.authenticate(c.cookies.get('eduagent_session'))
    handle=web.state.workspaces.put(p,'synthetic','private')
    assert c.post('/api/v1/auth/logout').status_code==200
    assert c.get('/api/v1/auth/me').status_code==401 and handle not in web.state.workspaces.rows
    c=client(web);web.state.sessions.clock=lambda:time.time()+4000
    assert c.get('/api/v1/materials').status_code==401


def test_login_rotation_revokes_old_session(web):
    c=client(web);old=c.cookies.get('eduagent_session')
    assert c.post('/api/v1/auth/dev-login',json={'identity':'a'},headers={'X-Development-Key':KEY}).status_code==200
    other=TestClient(web);other.cookies.set('eduagent_session',old,path='/api/v1')
    assert other.get('/api/v1/auth/me').status_code==401

@pytest.mark.parametrize('method,path',[('post','/knowledge/answer'),('patch','/materials/unknown'),('delete','/materials/unknown'),('post','/auth/logout')])
def test_csrf_mutations_rejected(web,method,path):
    c=client(web);del c.headers['X-CSRF-Token']
    assert getattr(c,method)('/api/v1'+path,json={} if method!='delete' else None).status_code==403 if method!='delete' else c.delete('/api/v1'+path).status_code==403
    assert c.get('/api/v1/materials').status_code==200


def test_csrf_rotation_and_session_binding(web):
    a,b=client(web),client(web,'b');old=a.headers['X-CSRF-Token']
    new=a.get('/api/v1/auth/csrf').json()['csrf_token']
    assert a.post('/api/v1/auth/logout').status_code==403
    a.headers['X-CSRF-Token']=b.headers['X-CSRF-Token'];assert a.post('/api/v1/auth/logout').status_code==403
    a.headers['X-CSRF-Token']=new;assert a.post('/api/v1/auth/logout').status_code==200


def test_http_private_material_and_guessed_ids(web,secured,services):
    api,_,_=services;a=upload(api,secured,secured.a,'PRIVATE A')
    ca,cb=client(web),client(web,'b');path='/api/v1/materials/'+a['material_id']
    assert ca.get(path).status_code==200
    assert cb.get(path).status_code==404
    assert cb.get('/api/v1/materials').json()==[]
    assert cb.patch(path,json={'course':'C','semester':'S','subject':'ML','unit':'U'}).status_code==404
    assert cb.delete(path).status_code==404
    assert api.materials.get(a['material_id'],context=ctx(secured.a))

@pytest.mark.parametrize('scope,alias,expected',[(Scope.COURSE,'b',False),(Scope.DEPARTMENT,'b',True),(Scope.DEPARTMENT,'c',False),(Scope.INSTITUTE,'c',True),(Scope.INSTITUTE,'d',False)])
def test_http_scopes(web,secured,services,scope,alias,expected):
    api,_,_=services;owner=secured.admin if scope in (Scope.DEPARTMENT,Scope.INSTITUTE) else secured.a
    a=upload(api,secured,owner,'SHARED '+scope.value,own(owner,scope,secured.course if scope==Scope.COURSE else None))
    c=client(web,alias);assert (c.get('/api/v1/materials/'+a['material_id']).status_code==200)==expected


def test_http_membership_revocation(web,secured,services):
    api,_,_=services;a=upload(api,secured,secured.a,'COURSE',own(secured.a,Scope.COURSE,secured.course));c=client(web,'b');path='/api/v1/materials/'+a['material_id']
    assert c.get(path).status_code==404
    secured.repo.set_membership(secured.b.professor_id,secured.course);assert c.get(path).status_code==200
    secured.repo.set_membership(secured.b.professor_id,secured.course,member=False);assert c.get(path).status_code==404


def test_http_cross_professor_rag_never_reaches_provider(web,secured,services,monkeypatch):
    import ai_provider
    api,vectors,_=services;upload(api,secured,secured.a,'A_PUBLIC_PCA');b=upload(api,secured,secured.b,'B_PRIVATE_PCA_SECRET')
    provider=Mock(return_value='PCA explains synthetic material.');monkeypatch.setattr(ai_provider,'generate_chat',provider)
    c=client(web);answer=c.post('/api/v1/knowledge/answer',json={'question':'Explain PCA'})
    assert answer.status_code==200,answer.text
    assert 'B_PRIVATE' not in answer.text and 'B_PRIVATE' not in str(provider.call_args)
    assert all('$in' in str(q) for q in vectors.queries)
    assert c.post('/api/v1/knowledge/answer',json={'question':'PCA','filters':{'material_id':b['material_id']}}).status_code==404
    assert provider.call_count==1


def test_http_no_evidence_gate(web,services,monkeypatch):
    import ai_provider
    provider=Mock();monkeypatch.setattr(ai_provider,'generate_chat',provider)
    c=client(web);response=c.post('/api/v1/knowledge/answer',json={'question':'PCA'})
    assert response.status_code==200 and response.json()['grounded'] is False
    provider.assert_not_called();services[2].assert_not_called()


def test_upload_update_delete_through_http(web,services):
    c=client(web);response=c.post('/api/v1/materials',files={'file':('synthetic.pdf',b'Synthetic PDF','application/pdf')},data=dict(course='ML',semester='S1',subject='ML',unit='Unit 1'))
    assert response.status_code==200,response.text
    assert response.json()['success'];identity=response.json()['material']['material_id']
    assert 'managed_filename' not in response.text
    assert c.patch('/api/v1/materials/'+identity,json=dict(course='ML',semester='S1',subject='ML',unit='Unit 2')).status_code==200
    assert c.get('/api/v1/materials/'+identity).json()['unit']=='Unit 2'
    assert c.delete('/api/v1/materials/'+identity).json()['success']


def test_request_validation_and_errors_are_private(web,services,monkeypatch):
    c=client(web)
    r=c.post('/api/v1/knowledge/answer',json={'question':{'secret':'PRIVATE STUDENT'}})
    assert r.status_code==422 and 'PRIVATE STUDENT' not in r.text
    monkeypatch.setattr(services[0].materials,'list_materials',Mock(side_effect=RuntimeError('/private/path SQL secret TOKEN')))
    r=c.get('/api/v1/materials');assert r.status_code==500
    assert all(v not in r.text for v in ('/private/path','SQL','TOKEN','Traceback'))
    assert r.json()['error']['request_id']==r.headers['X-Request-ID']


def test_headers_cors_and_no_inference_status(web,monkeypatch):
    import ai_provider
    provider=Mock();monkeypatch.setattr(ai_provider,'generate_chat',provider)
    c=client(web);r=c.get('/api/v1/system/ai')
    assert r.status_code==200 and 'base_url' not in r.text
    assert r.json()['preferred_model']=='qwen2.5:3b'
    assert r.headers['X-Content-Type-Options']=='nosniff' and r.headers['Cache-Control']=='no-store'
    allowed=c.options('/api/v1/materials',headers={'Origin':'http://frontend.test','Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'X-CSRF-Token'})
    assert allowed.status_code==200 and allowed.headers['access-control-allow-origin']=='http://frontend.test'
    denied=c.options('/api/v1/materials',headers={'Origin':'http://evil.test','Access-Control-Request-Method':'POST'})
    assert denied.status_code==400 and 'access-control-allow-origin' not in denied.headers
    provider.assert_not_called()


def test_sqlite_context_is_thread_local_and_foreign_keys(secured,tmp_path):
    paths=[tmp_path/f'local-{i}.db' for i in range(2)]
    def run(path):
        with db.storage_context(path):
            db.init_db()
            with db.material_connection() as conn:
                assert conn.execute('PRAGMA foreign_keys').fetchone()[0]==1
                assert conn.execute('PRAGMA busy_timeout').fetchone()[0]==5000
            return db.get_all_courses()
    with ThreadPoolExecutor(max_workers=2) as pool:assert list(pool.map(run,paths))==[[],[]]
    assert Path(db.DB_PATH)!=paths[0]


def test_concurrent_membership_changes_are_coherent(secured):
    s=secured
    def change(i):s.repo.set_membership(s.b.professor_id,s.course,member=bool(i%2))
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(change,range(20)))
    with s.repo.connection() as conn:assert conn.execute('SELECT COUNT(*) FROM professor_course_memberships WHERE professor_id=?',(s.b.professor_id,)).fetchone()[0]<=1


def test_api_import_and_factory_do_not_create_storage(tmp_path):
    root=Path(__file__).resolve().parents[1]
    script='''
import sys
sys.path.insert(0,sys.argv[1])
import api
from api.settings import APISettings
app=api.create_api_app(settings=APISettings(database_path='must-not-exist.db'))
from pathlib import Path
assert not list(Path('.').iterdir())
'''
    result=subprocess.run([sys.executable,'-B','-c',script,str(root)],cwd=tmp_path,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr


def test_document_http_lifecycle_private_facts_and_exports(web,secured,services,monkeypatch):
    from test_security import document_draft
    import document_studio
    monkeypatch.setattr(document_studio,'generate_draft',lambda *a,**k:document_draft())
    c=client(web);b=client(web,'b')
    response=c.post('/api/v1/documents/generate',json={'document_type':'notice','description':'Synthetic notice'})
    assert response.status_code==200,response.text
    handle=response.json()['handle'];base='/api/v1/document-workspaces/'+handle
    assert b.get(base+'/facts').status_code==404
    assert c.get(base+'/facts').json()[0]['value']=='10 October 2026'
    assert c.post(base+'/save',json={}).status_code==200
    identity=c.post(base+'/save',json={}).json()['document_id']
    assert b.get('/api/v1/documents/'+identity).status_code==404
    assert b.get('/api/v1/documents/'+identity+'/versions').status_code==404
    assert b.get('/api/v1/documents').json()==[]
    assert c.get('/api/v1/documents/'+identity+'/versions').json()[0]['version_number']==1
    current={k:response.json()[k] for k in ('title','recipient','sender','date','reference_number','subject','salutation','body','closing','signature')}
    current['date']='12 October 2026'
    assert c.patch(base,json=current).status_code==409
    assert c.post(base+'/resolve-edit',json={'draft':current,'update_confirmed':False}).json()['date']=='10 October 2026'
    assert c.post(base+'/resolve-edit',json={'draft':current,'update_confirmed':True}).json()['date']=='12 October 2026'
    assert c.post(base+'/restore',json={'index':0}).json()['date']=='10 October 2026'
    assert c.post(base+'/save',json={}).status_code==200
    assert c.post(base+'/feedback',json={'rating':'Good','note':'Synthetic private note'}).status_code==200
    for format,signature in [('docx',b'PK'),('pdf',b'%PDF')]:
        result=c.get(base+'/export',params={'format':format});assert result.status_code==200,result.text
        assert result.content.startswith(signature)
    assert c.post(base+'/facts',json={'operation':'add','field':'body','value':'Synthetic'}).status_code==200
    facts=c.get(base+'/facts').json();fact=next(f for f in facts if f['value']=='Synthetic')
    assert c.post(base+'/facts',json={'operation':'update','fact_id':fact['fact_id'],'value':'Synthetic'}).status_code==200
    assert c.post(base+'/facts',json={'operation':'remove','fact_id':fact['fact_id']}).status_code==200


def test_document_failed_refinement_preserves_current(web,monkeypatch):
    from test_security import document_draft
    import document_studio
    from application.errors import ConflictError
    monkeypatch.setattr(document_studio,'generate_draft',lambda *a,**k:document_draft())
    c=client(web);r=c.post('/api/v1/documents/generate',json={'document_type':'notice','description':'Synthetic notice'});handle=r.json()['handle']
    monkeypatch.setattr(document_studio,'refine_draft',Mock(side_effect=ConflictError()))
    assert c.post('/api/v1/document-workspaces/'+handle+'/refine',json={'instruction':'Shorten'}).status_code==409
    assert c.get('/api/v1/document-workspaces/'+handle+'/facts').json()[0]['value']=='10 October 2026'


def test_private_preference_http_and_activity_sanitized(web,secured):
    a,b=client(web),client(web,'b')
    response=a.post('/api/v1/preferences',json={'instruction':'SYNTHETIC PRIVATE STYLE','scope':'general'});assert response.status_code==200,response.text
    identity=response.json()['handle']
    assert b.get('/api/v1/preferences').json()==[]
    assert b.delete('/api/v1/preferences/'+identity).status_code==404
    assert a.patch('/api/v1/preferences/'+identity,json={'active':False}).status_code==200
    assert 'SYNTHETIC PRIVATE STYLE' not in a.get('/api/v1/activity').text
    assert a.delete('/api/v1/preferences/'+identity).status_code==200


def assessment_body(identity):
    return dict(assessment_type='Quiz',course='ML',semester='S1',subject='ML',units=['Unit 1'],material_ids=[identity],question_types={'MCQ':1,'Descriptive':0},difficulties={'Easy':1,'Medium':0,'Hard':0},blooms={'Remember':1,'Understand':0,'Apply':0,'Analyze':0,'Evaluate':0,'Create':0},total_questions=1,total_marks=1)


def test_assessment_http_authorization_validation_and_export(web,secured,services,monkeypatch):
    import ai_provider
    api,_,_=services;a=upload(api,secured,secured.a,'PCA');b=upload(api,secured,secured.b,'PRIVATE PCA')
    content=json.dumps({'questions':[dict(question_number=1,question_type='MCQ',question_text='What is the synthetic PCA purpose?',options={'A':'Dimension reduction','B':'Database deletion','C':'Disk formatting','D':'Attendance storage'},correct_answer='A',model_answer='Dimension reduction',difficulty='Easy',bloom_level='Remember',marks=1,evidence_ids=['E1'])]})
    provider=Mock(return_value=content);monkeypatch.setattr(ai_provider,'generate_chat',provider)
    c=client(web)
    assert c.post('/api/v1/assessments/generate',json=assessment_body(b['material_id'])).status_code==404
    provider.assert_not_called()
    result=c.post('/api/v1/assessments/generate',json=assessment_body(a['material_id']))
    assert result.status_code==200,result.text
    handle=result.json()['handle']
    assert result.json()['questions'][0]['correct_answer']=='A'
    assert client(web,'b').get('/api/v1/assessments/'+handle+'/export').status_code==404
    assert c.get('/api/v1/assessments/'+handle+'/export').content.startswith(b'%PDF')
    malformed=assessment_body(a['material_id']);malformed['total_questions']=2
    assert c.post('/api/v1/assessments/generate',json=malformed).status_code==422


def test_student_http_ephemeral_local_ownership_and_cleanup(web,monkeypatch,caplog):
    import ai_provider
    provider=Mock();monkeypatch.setattr(ai_provider,'generate_chat',provider)
    c=client(web);r=c.post('/api/v1/students/upload',files={'file':('synthetic.csv',b'ID,Name,Attendance,Quiz\n001,Synthetic Student,90,80\n','text/csv')})
    assert r.status_code==200,r.text
    handle=r.json()['handle'];sheet=r.json()['sheets'][0]
    mapping=dict(sheet=sheet,header_row=1,student_id='ID',student_name='Name',attendance='Attendance',assessments=[dict(column='Quiz',name='Quiz')])
    normalized=c.post('/api/v1/students/'+handle+'/normalize',json=mapping)
    assert normalized.status_code==200,normalized.text
    data=normalized.json()['handle'];base='/api/v1/students/'+data
    assert client(web,'b').post(base+'/analyze',json={}).status_code==404
    result=c.post(base+'/analyze',json={});assert result.status_code==200,result.text
    assert result.json()['summary']['total_students']==1
    assert c.post(base+'/export',json={}).status_code==200
    assert 'Synthetic Student' not in caplog.text
    assert c.post(base+'/analyze',json={'attendance_threshold':101}).status_code==422
    assert c.delete(base).status_code==200
    assert c.post(base+'/analyze',json={}).status_code==404
    provider.assert_not_called()


def test_assistant_server_plan_confirmation_and_foreign_session(web,monkeypatch):
    import assistant_planner
    from assistant_models import parse_plan
    plan=parse_plan('{"unsupported":false,"actions":[{"action_id":"a","action_type":"NAVIGATE","parameters":{"page":"Professor Dashboard"},"depends_on":[]}]}','Synthetic navigation')
    monkeypatch.setattr(assistant_planner,'plan_request',lambda *a,**k:plan)
    c=client(web);r=c.post('/api/v1/assistant/plan',json={'request':'Open dashboard'});assert r.status_code==200,r.text
    handle=r.json()['handle'];base='/api/v1/assistant/'+handle
    assert c.get(base+'/preview').json()['valid']
    assert client(web,'b').get(base+'/preview').status_code==404
    assert c.post(base+'/execute',json={'confirmed':False}).status_code==422
    assert c.post(base+'/execute',json={'confirmed':True,'actions':[{'shell':'unsafe'}]}).status_code==422
    result=c.post(base+'/execute',json={'confirmed':True});assert result.status_code==200,result.text
    assert result.json()['status']=='completed'
    assert c.post(base+'/execute',json={'confirmed':True}).status_code==422
    assert c.post(base+'/execute',json={'confirmed':True,'retry':True}).status_code==200


def test_body_limit_and_request_id_are_safe(web):
    c=client(web);r=c.post('/api/v1/knowledge/answer',content=b'x'*(11*1024*1024+1),headers={'Content-Type':'application/json','X-Request-ID':'PRIVATE FACT'})
    assert r.status_code==413
    assert r.headers['X-Content-Type-Options']=='nosniff'
    assert 'PRIVATE FACT' not in r.text


def test_atomic_ownership_audit_failure_rolls_back(secured,services,monkeypatch):
    from security.repository import SecurityRepository
    api,vectors,_=services
    monkeypatch.setattr(SecurityRepository,'_audit',Mock(side_effect=sqlite3.OperationalError('Synthetic audit unavailable')))
    result=api.materials.upload(__import__('application.models',fromlist=['MaterialUpload']).MaterialUpload(b'Synthetic isolated text. '*20,'synthetic.pdf',dict(course='ML',semester='S1',subject='ML',unit='Unit 1')),context=ctx(secured.a))
    assert result['success'] is False and not vectors.rows
    assert api.materials.list_materials(context=ctx(secured.a))==[]


def test_offline_bootstrap_is_separate_and_explicit(tmp_path):
    from api.bootstrap import bootstrap
    path=tmp_path/'isolated-api.sqlite3';aliases=bootstrap(path)
    assert len(aliases)==2
    with pytest.raises(ValueError):bootstrap(tmp_path/'eduagent.db')

@pytest.mark.parametrize('mode',['production','institutional'])
def test_non_development_auth_never_available(services,mode):
    app=create_api_app(settings=APISettings(mode=mode),services=services[0])
    response=TestClient(app).post('/api/v1/auth/dev-login',json={'identity':'a'},headers={'X-Development-Key':KEY})
    assert response.status_code==401


def test_trusted_metadata_reload_not_client_claims(web,secured):
    c=client(web);c.headers.update({'X-Professor-ID':secured.b.professor_id,'X-Institution-ID':secured.d.institution_id,'X-Role':'INSTITUTE_ADMIN'})
    assert c.get('/api/v1/auth/me').json()['professor_id']==secured.a.professor_id
    assert c.post('/api/v1/knowledge/answer',json={'question':'PCA','context':{'professor_id':secured.b.professor_id}}).status_code==422


def test_unknown_http_errors_share_envelope(web):
    c=TestClient(web);r=c.get('/api/v1/does-not-exist')
    assert r.status_code==404 and set(r.json())=={'error'}
    assert set(r.json()['error'])=={'code','message','request_id'}


def test_provider_error_http_is_sanitized(web,services,secured,monkeypatch):
    import ai_provider
    from ai_provider import AIProviderError
    upload(services[0],secured,secured.a,'PCA')
    monkeypatch.setattr(ai_provider,'generate_chat',Mock(side_effect=AIProviderError('PRIVATE PROMPT /path SQL')))
    response=client(web).post('/api/v1/knowledge/answer',json={'question':'PCA'})
    assert response.status_code==503 and 'PRIVATE' not in response.text and '/path' not in response.text


def test_assessment_qwen_shape_normalization_preserved_http(web,secured,services,monkeypatch):
    import ai_provider
    a=upload(services[0],secured,secured.a,'PCA')
    question=dict(question_number=1,question_type='MCQ',question_text='What does PCA accomplish?',options=[{'A':'Dimension reduction'},{'B':'Database deletion'},{'C':'Disk formatting'},{'D':'Attendance storage'}],correct_answer='A',model_answer='Dimension reduction',difficulty='Easy',bloom_level='Remember',marks=1,evidence_ids=['E1'])
    monkeypatch.setattr(ai_provider,'generate_chat',Mock(return_value=json.dumps({'questions':[question]})))
    body=assessment_body(a['material_id']);body['assessment_type']='Question Paper'
    response=client(web).post('/api/v1/assessments/generate',json=body)
    assert response.status_code==200,response.text
    assert response.json()['questions'][0]['options']['A']=='Dimension reduction'


def test_pyq_guidance_handle_is_session_private(web,services,monkeypatch):
    api=services[0];monkeypatch.setattr(api.assessments,'extract_pyq',lambda *a,**k:'Synthetic private PYQ style')
    c=client(web);r=c.post('/api/v1/assessments/pyq',files={'file':('synthetic.pdf',b'synthetic','application/pdf')})
    assert r.status_code==200 and 'private PYQ' not in r.text
    p=web.state.sessions.authenticate(c.cookies.get('eduagent_session'))
    other=client(web,'b');q=web.state.sessions.authenticate(other.cookies.get('eduagent_session'))
    from application.errors import NotFoundError
    with pytest.raises(NotFoundError):
        with web.state.workspaces.item(q,r.json()['handle'],'pyq'):pass


def test_session_no_tokens_or_student_payload_in_logs(web,caplog):
    c=client(web);token=c.cookies.get('eduagent_session');csrf=c.headers['X-CSRF-Token']
    c.get('/api/v1/auth/me');c.post('/api/v1/knowledge/answer',json={'question':{'private':'SYNTHETIC STUDENT MARKS'}})
    assert token not in caplog.text and csrf not in caplog.text and 'SYNTHETIC STUDENT MARKS' not in caplog.text


def test_api_architecture_no_raw_sql_streamlit_or_ollama():
    import ast
    root=Path(__file__).resolve().parents[1]
    for path in (root/'api').glob('*.py'):
        tree=ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):assert all(n.name.split('.')[0] not in ('sqlite3','streamlit','ollama','chromadb','vector_store') for n in node.names)
            if isinstance(node,ast.ImportFrom):assert (node.module or '').split('.')[0] not in ('sqlite3','streamlit','ollama','chromadb','vector_store')
        assert 'ProfessorContext(' not in path.read_text() and 'ProfessorContext.from_identity' not in path.read_text()


def test_membership_and_ownership_audit_failure_atomic(secured,services,monkeypatch):
    from security.repository import SecurityRepository
    s=secured;api=services[0];a=upload(api,s,s.a,'PCA');old=s.repo.ownership('material',a['material_id'])
    monkeypatch.setattr(SecurityRepository,'_audit',Mock(side_effect=sqlite3.OperationalError('Synthetic audit failure')))
    with pytest.raises(sqlite3.Error):api.identities.membership(s.b.professor_id,s.course,context=ctx(s.admin))
    assert not s.repo.is_member(s.b.professor_id,s.course)
    with pytest.raises(Exception):api.materials.share(a['material_id'],own(s.a,Scope.COURSE,s.course),context=ctx(s.a))
    assert s.repo.ownership('material',a['material_id'])==old


def test_explicit_api_vector_path_is_lazy_and_isolated(monkeypatch,tmp_path):
    from application.runtime import ConfiguredVectors
    import vector_store
    getter=Mock();monkeypatch.setattr(vector_store,'get_collection',getter)
    v=ConfiguredVectors(tmp_path/'api-vectors');getter.assert_not_called()
    v.get_material_chunks(['synthetic-id']);getter.assert_called_once_with(tmp_path/'api-vectors')


def test_workspace_expiry_and_cross_session_bound(web):
    from api.workspaces import Workspaces
    from application.errors import NotFoundError,ConflictError
    c=client(web);p=web.state.sessions.authenticate(c.cookies.get('eduagent_session'))
    clock=[time.time()];vault=Workspaces(maximum=1,clock=lambda:clock[0]);key=vault.put(p,'synthetic','private')
    with pytest.raises(ConflictError):vault.put(p,'synthetic','other')
    clock[0]=p.expires_at+1
    with pytest.raises(NotFoundError):
        with vault.item(p,key,'synthetic'):pass
    assert vault.rows=={}


def test_successful_document_refinement_http_keeps_facts(web,monkeypatch):
    from test_security import document_draft
    import document_studio
    monkeypatch.setattr(document_studio,'generate_draft',lambda *a,**k:document_draft())
    monkeypatch.setattr(document_studio,'refine_draft',lambda current,*a,**k:replace(current,body=('Synthetic INR 2500 allocation. Professor review required.',)))
    c=client(web);response=c.post('/api/v1/documents/generate',json={'document_type':'notice','description':'Synthetic notice'})
    base='/api/v1/document-workspaces/'+response.json()['handle']
    refined=c.post(base+'/refine',json={'instruction':'Make this formal.'})
    assert refined.status_code==200,refined.text
    assert refined.json()['date']=='10 October 2026' and refined.json()['version_count']==2
    assert 'fact_expectations' not in refined.text and 'response_hash' not in refined.text


def test_assistant_partial_failure_and_dependents_http(web,monkeypatch):
    import assistant_planner
    from assistant_models import parse_plan
    plan=parse_plan(json.dumps({'unsupported':False,'actions':[
        {'action_id':'a','action_type':'ASK_KNOWLEDGE','parameters':{'question':'PCA'},'depends_on':[]},
        {'action_id':'b','action_type':'NAVIGATE','parameters':{'page':'Professor Dashboard'},'depends_on':[]}]}),'Synthetic tasks')
    monkeypatch.setattr(assistant_planner,'plan_request',lambda *a,**k:plan)
    from application.errors import ProviderUnavailableError
    monkeypatch.setattr(web.state.services.knowledge,'ask',Mock(side_effect=ProviderUnavailableError()))
    c=client(web);handle=c.post('/api/v1/assistant/plan',json={'request':'PCA and dashboard'}).json()['handle']
    result=c.post('/api/v1/assistant/'+handle+'/execute',json={'confirmed':True})
    assert result.status_code==200 and result.json()['status']=='partial_failure'
    assert [r['status'] for r in result.json()['results']]==['failed','completed']


def test_professor_metadata_audit_failure_rolls_back(secured,monkeypatch):
    from security.repository import SecurityRepository
    from security.policy import IdentityService
    s=secured;service=IdentityService(s.repo,s.policy)
    monkeypatch.setattr(SecurityRepository,'_audit',Mock(side_effect=sqlite3.OperationalError('Synthetic audit failure')))
    with pytest.raises(sqlite3.Error):service.update(replace(s.b,status=Status.INACTIVE),context=ctx(s.admin))
    assert s.repo.get_professor(s.b.professor_id).status==Status.ACTIVE


def test_csrf_rejection_precedes_material_mutation(web,services,monkeypatch):
    c=client(web);operation=Mock();monkeypatch.setattr(services[0].materials,'delete',operation)
    c.headers['X-CSRF-Token']='invalid'
    assert c.delete('/api/v1/materials/synthetic-id').status_code==403
    operation.assert_not_called()


def test_production_rejects_existing_development_session(web,services):
    dev=client(web);token=dev.cookies.get('eduagent_session')
    production=create_api_app(settings=APISettings(),services=services[0],sessions=web.state.sessions)
    c=TestClient(production);c.cookies.set('eduagent_session',token,path='/api/v1')
    assert c.get('/api/v1/auth/me').status_code==401
    assert c.get('/api/v1/materials').status_code==401
