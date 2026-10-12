"""Exact synthetic manual contracts; all providers mocked, all storage isolated."""
import json
from unittest.mock import Mock
import pytest
import ai_provider
from test_api import web,client
from test_security import secured,services,upload
from assessment_spec import AssessmentSpec,AssessmentScope,BLOOMS
from assessment_fixtures import output

DESCRIPTION="Draft a letter to the Dean requesting financial approval for organizing a fresher party for first-year students."
REQUEST=dict(document_type='official_letter',tone='Detailed Official',description=DESCRIPTION)
def letter():
 return dict(document_type='official_letter',title='',recipient='',sender='',date='',reference_number='',subject='',signature='',salutation='Dear Dean,',closing='Respectfully,',body=['I respectfully request financial approval for organizing a fresher party for first-year students.','The proposed gathering would offer a welcoming introduction and encourage interaction among the new students. Kindly consider this request and advise on the necessary approval process.'])
def test_exact_direct_optional_letter_generate_edit_save_refine_export(web,monkeypatch):
 provider=Mock(return_value=json.dumps(letter()));monkeypatch.setattr(ai_provider,'generate_chat',provider);c=client(web)
 result=c.post('/api/v1/documents/generate',json=REQUEST);assert result.status_code==200,result.text
 d=result.json();assert d['recipient']==d['date']==d['reference_number']=='' and not d['facts']
 assert 'Dear Dean' in d['salutation'] and len(d['body'])==2
 path='/api/v1/document-workspaces/'+d['handle']
 assert c.post(path+'/save',json={'status':'Draft'}).status_code==200
 assert c.post(path+'/refine',json={'instruction':'Make the letter more formal.'}).status_code==200
 assert c.get(path+'/export?format=pdf').content.startswith(b'%PDF')
 assert c.get(path+'/export?format=docx').content.startswith(b'PK')
 assert provider.call_count==2

@pytest.mark.parametrize('change,category',[(('body',['The budget is ₹75000.']),'FACT_PRESERVATION_FAILED'),(('body',['The budget is']),'DOCUMENT_QUALITY_FAILED'),(('body','not an array'),'SCHEMA_INVALID'),(('recipient','Dean'),'FACT_PRESERVATION_FAILED')])
def test_document_failure_stage_safe_previous_unchanged(web,monkeypatch,change,category):
 provider=Mock(return_value=json.dumps(letter()));monkeypatch.setattr(ai_provider,'generate_chat',provider);c=client(web)
 d=c.post('/api/v1/documents/generate',json=REQUEST).json();candidate=letter();candidate[change[0]]=change[1];provider.return_value=json.dumps(candidate)
 r=c.post('/api/v1/documents/generate',json=REQUEST);assert r.status_code==422
 assert r.json()['error']['diagnostic']['category']==category
 assert all(v not in r.text for v in ('75000','Dear Dean','Traceback','/Users/'))
 assert c.get('/api/v1/document-workspaces/'+d['handle']).json()==d

def assessment_request(material):
 return dict(assessment_type='Quiz',course='ML',semester='S1',subject='ML',units=['Unit 1'],material_ids=[material],question_types={'MCQ':15,'Descriptive':0},difficulties={'Easy':8,'Medium':2,'Hard':5},blooms=dict(zip(BLOOMS,[6,3,4,1,0,1])),total_questions=15,total_marks=30,title='Synthetic fifteen-question quiz')
@pytest.mark.parametrize('shape',['dict','known_list'])
def test_exact_fifteen_mcq_api_contract(web,services,secured,monkeypatch,shape):
 item=upload(services[0],secured,secured.a,'Synthetic PCA');body=assessment_request(item['material_id'])
 spec=AssessmentSpec(assessment_type=body['assessment_type'],scope=AssessmentScope(body['course'],body['semester'],body['subject'],tuple(body['units'])),question_types=body['question_types'],difficulties=body['difficulties'],blooms=body['blooms'],total_questions=15,total_marks=30,title=body['title'])
 data=output(spec.plan)
 if shape=='known_list':
  for q in data['questions']:q['options']=[{key:value} for key,value in q['options'].items()]
 provider=Mock(return_value=json.dumps(data));monkeypatch.setattr(ai_provider,'generate_chat',provider);c=client(web)
 r=c.post('/api/v1/assessments/generate',json=body);assert r.status_code==200,r.text
 a=r.json();assert len(a['questions'])==15 and sum(q['marks'] for q in a['questions'])==30 and all(a['validation'].values())
 assert c.get('/api/v1/assessments/'+a['handle']).json()==a and provider.call_count==1

@pytest.mark.parametrize('corrupt', ['parse','schema','marks','difficulty','bloom','evidence','duplicate'])
def test_fifteen_mcq_postgeneration_failure_does_not_store(web,services,secured,monkeypatch,corrupt):
 item=upload(services[0],secured,secured.a,'Synthetic PCA');body=assessment_request(item['material_id'])
 spec=AssessmentSpec(assessment_type='Quiz',scope=AssessmentScope('ML','S1','ML',('Unit 1',)),question_types=body['question_types'],difficulties=body['difficulties'],blooms=body['blooms'],total_questions=15,total_marks=30,title=body['title'])
 data=output(spec.plan)
 if corrupt=='schema':data['questions'][0].pop('question_text')
 elif corrupt=='marks':data['questions'][0]['marks']=99
 elif corrupt=='difficulty':data['questions'][0]['difficulty']='Hard'
 elif corrupt=='bloom':data['questions'][0]['bloom_level']='Create'
 elif corrupt=='evidence':data['questions'][0]['evidence_ids']=['E999']
 elif corrupt=='duplicate':data['questions'][1]['question_text']=data['questions'][0]['question_text']
 provider=Mock(return_value='RAW PRIVATE invalid' if corrupt=='parse' else json.dumps(data));monkeypatch.setattr(ai_provider,'generate_chat',provider);c=client(web)
 response=c.post('/api/v1/assessments/generate',json=body);assert response.status_code==422,response.text
 assert response.json()['error']['diagnostic']['category'] in ('INVALID_JSON','SCHEMA_INVALID','PRODUCT_VALIDATION_FAILED')
 assert not any(row[1]=='assessment' for row in web.state.workspaces.rows.values())
 assert 'RAW PRIVATE' not in response.text and provider.call_count==1
