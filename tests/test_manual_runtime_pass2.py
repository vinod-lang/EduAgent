"""Runtime pass 2: synthetic headers, native grammar and truthful generation errors."""
import io,json,copy
from unittest.mock import Mock,MagicMock
import pytest,httpx,ollama
from openpyxl import Workbook
import ai_provider,student_ingestion as si,assistant_planner
from test_api import web,client
from test_security import secured,services
from test_assessment_workspace import assessment,raw_questions
from assessment_fixtures import spec,evidence
from structured_contracts import assessment_schema
from jsonschema import Draft202012Validator

A=('roll_no','attendance','marks')
B=('Student Name','Student Roll No.','Attendance (%)','Marks (out of 100)')
def table(headers):
 rows=(('SYN001',80,40),) if headers==A else (('Synthetic One','SYN001',80,40),)
 return si.make_raw_table(si.Sheet('Student Data',False,(headers,*rows)),1)

@pytest.mark.parametrize('headers',[A,B])
def test_exact_semantic_headers(headers):
 t=table(headers);s=si.suggest_columns(t);h=si.mapping_hints(t,s)
 identity,attendance,marks=('roll_no','attendance','marks') if headers==A else ('Student Roll No.','Attendance (%)','Marks (out of 100)')
 assert s['student_id'].selected==identity and s['attendance'].selected==attendance
 assert not s['assessment_number'].candidates and s['assessments'].candidates==(marks,)
 assert h['assessment_columns']==[marks]
 assert s['student_name'].selected==(None if headers==A else 'Student Name')
 assert h['assessments'][marks]=={'scale':'raw','maximum':None if headers==A else 100}
 assert h['attendance_scale']==('auto' if headers==A else 'percentage')

@pytest.mark.parametrize('header',['assessment number','assessment no','assessment_no','exam number','test number','attempt number'])
def test_narrow_history_aliases(header):
 t=si.make_raw_table(si.Sheet('Data',False,(('roll_no','attendance','marks',header),('SYN001',80,40,1))),1)
 s=si.suggest_columns(t);assert s['assessment_number'].selected==header
 assert s['assessments'].candidates==('marks',)

@pytest.mark.parametrize('headers',[A,B])
def test_actual_xlsx_normalization_zero_ai(web,monkeypatch,headers):
 spy=Mock(side_effect=AssertionError('No AI'));monkeypatch.setattr(ai_provider,'generate_chat',spy)
 from application.runtime import ConfiguredVectors
 monkeypatch.setattr(ConfiguredVectors,'collection',Mock(side_effect=AssertionError('No embeddings')))
 w=Workbook();w.active.title='Student Data';w.active.append(headers)
 for i in range(50):w.active.append([f'SYN{i:03}',80,40] if headers==A else [f'Synthetic {i}',f'SYN{i:03}',80,40])
 b=io.BytesIO();w.save(b);w.close();c=client(web)
 h=c.post('/api/v1/students/upload',files={'file':('synthetic.xlsx',b.getvalue())}).json()['handle'];path='/api/v1/students/'+h
 p=c.post(path+'/preview',json={'sheet':'Student Data'}).json();s=p['suggestions'];hints=p['mapping_hints']
 mark=s['assessments']['candidates'][0];m={'sheet':'Student Data','header_row':1,'student_id':s['student_id']['candidates'][0],'student_name':s['student_name']['candidates'][0] if s['student_name']['candidates'] else None,'attendance':s['attendance']['candidates'][0],'attendance_scale':hints['attendance_scale'],'assessments':[{'column':mark,'name':mark,**hints['assessments'][mark]}]}
 if headers==A:
  assert c.post(path+'/normalize',json=m).json()['error']['code']=='MARKS_MAXIMUM_REQUIRED'
  m['assessments'][0]['maximum']=50
 n=c.post(path+'/normalize',json=m);assert n.status_code==200 and n.json()['validation']['eligible_rows']==50
 a=c.post('/api/v1/students/'+n.json()['handle']+'/analyze',json={});assert a.json()['summary']['total_students']==50
 spy.assert_not_called()

@pytest.mark.parametrize('column',['roll_no','attendance'])
def test_reserved_columns_cannot_be_marks(column):
 t=table(A)
 with pytest.raises(si.StudentDataError,match='cannot be marks'):
  si.normalize_dataset(t,si.Mapping('roll_no',None,'attendance',(si.Assessment(column,'Test'),)))

def test_marks_not_history():
 with pytest.raises(si.StudentDataError,match='assessment-number'):
  si.normalize_dataset(table(A),si.Mapping('roll_no',None,'attendance',(si.Assessment('marks','Marks'),),assessment_number='marks'))

@pytest.mark.parametrize('value',['marks %','marks (%)','score percent'])
def test_explicit_percentage_only(value):
 t=si.make_raw_table(si.Sheet('Data',False,(('roll_no','attendance',value),('SYN001',80,40))),1)
 assert si.mapping_hints(t)['assessments'][value]=={'scale':'percentage','maximum':None}

def test_native_schema_keeps_original_and_local_validation():
 schema=assessment_schema(spec(),evidence());before=copy.deepcopy(schema)
 native=ai_provider.native_response_schema(schema)
 assert schema==before and 'prefixItems' in schema['properties']['questions']
 assert isinstance(native['properties']['questions']['items'],dict)
 assert 'prefixItems' not in native['properties']['questions']
 assert native['properties']['questions']['items']['anyOf']==schema['properties']['questions']['prefixItems']
 # Native union does not enforce ordered slots. The original local schema still does.
 from assessment_fixtures import output
 q=output();q['questions'].reverse()
 assert not list(Draft202012Validator(native).iter_errors(q))
 assert list(Draft202012Validator(schema).iter_errors(q))

@pytest.mark.parametrize('status,structured,expected',[(400,True,ai_provider.AIStructuredRequestError),(422,True,ai_provider.AIStructuredRequestError),(404,True,ai_provider.AIModelUnavailableError),(500,True,ai_provider.AIProviderError)])
def test_real_client_error_types_mocked_boundary(monkeypatch,status,structured,expected):
 c=MagicMock();c.__enter__.return_value=c;c.list.return_value={'models':[{'model':'llama3.2:3b'}]};c.chat.side_effect=ollama.ResponseError('PRIVATE request/format',status_code=status)
 monkeypatch.setattr(ai_provider.ollama,'Client',Mock(return_value=c))
 with pytest.raises(expected) as error:ai_provider.generate_chat([{'role':'user','content':'Synthetic'}],response_format=assessment_schema(spec(),evidence()))
 assert 'PRIVATE' not in str(error.value) and not isinstance(error.value,ai_provider.AIConnectionError)
 assert c.chat.call_count==1 and ai_provider.get_last_generation_selection() is None
 assert isinstance(c.chat.call_args.kwargs['format']['properties']['questions']['items'],dict)

@pytest.mark.parametrize('failure,code,category',[
 (ai_provider.AIConnectionError('PRIVATE'),'PROVIDER_UNAVAILABLE','PROVIDER_ERROR'),
 (ai_provider.AIModelUnavailableError('PRIVATE'),'MODEL_UNAVAILABLE','PROVIDER_ERROR'),
 (ai_provider.AIStructuredRequestError('PRIVATE'),'VALIDATION_ERROR','SCHEMA_INVALID'),
 (ai_provider.AIResponseError('PRIVATE'),'VALIDATION_ERROR','INVALID_JSON'),
 (ai_provider.AIProviderError('PRIVATE'),'PROVIDER_ERROR','PROVIDER_ERROR'),
 ('malformed','VALIDATION_ERROR','INVALID_JSON'),
 ('product','VALIDATION_ERROR','PRODUCT_VALIDATION_FAILED'),
 ('timeout','PROVIDER_TIMEOUT','TIMEOUT')])
def test_assessment_truthful_errors_preserve_previous(assessment,failure,code,category):
 c,a,provider,body=assessment
 if failure=='timeout':
  failure=ai_provider.AIConnectionError('PRIVATE');failure.__cause__=httpx.ReadTimeout('PRIVATE')
 if isinstance(failure,Exception):provider.side_effect=failure
 elif failure=='malformed':provider.return_value='PRIVATE malformed output'
 else:
  data=raw_questions();data['questions'][0]['options']['B']=data['questions'][0]['options']['A'];provider.return_value=json.dumps(data)
 r=c.post('/api/v1/assessments/generate',json=body)
 assert r.status_code in (422,503) and r.json()['error']['code']==code
 assert r.json()['error']['diagnostic']['category']==category and 'PRIVATE' not in r.text
 assert c.get('/api/v1/assessments/'+a['handle']).json()==a
 assert c.get('/api/v1/assessments/'+a['handle']+'/export?format=docx').status_code==200

@pytest.mark.parametrize('prompt',["make small notice for class cancellation","make a small notice for class cancellation","draft a notice that today's class is cancelled","prepare a student notice about class cancellation"])
def test_supported_notice_still_requires_approval(web,monkeypatch,prompt):
 spy=Mock(side_effect=AssertionError('No planner inference required'));monkeypatch.setattr(ai_provider,'generate_chat',spy)
 c=client(web);r=c.post('/api/v1/assistant/plan',json={'request':prompt});assert r.status_code==200
 p=r.json();assert [a['action_type'] for a in p['actions']]==['CREATE_DOCUMENT']
 preview=c.get('/api/v1/assistant/'+p['handle']+'/preview').json();assert preview['valid']
 assert c.post('/api/v1/assistant/'+p['handle']+'/execute',json={'confirmed':False}).status_code==422
 spy.assert_not_called()

def test_notice_grammar_does_not_expand_allowlist(monkeypatch):
 from assistant_models import ACTION_TYPES
 assert len(ACTION_TYPES)==5
 spy=Mock(return_value='{"unsupported":true,"actions":[]}');monkeypatch.setattr(ai_provider,'generate_chat',spy)
 p=assistant_planner.plan_request('Make a notice and email it to everyone')
 assert p.unsupported and not p.actions;spy.assert_called_once()
