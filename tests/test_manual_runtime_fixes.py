"""Synthetic real-format uploads, runtime errors and deterministic student mapping."""
import io,json
from unittest.mock import Mock
import pytest,httpx
from fpdf import FPDF
from openpyxl import Workbook
import ai_provider,db
from test_api import web,client
from test_security import secured,services,upload
from test_document_workspace import REQUEST
from test_assessment_workspace import BODY
from vector_store import EmbeddingUnavailableError

def pdf_bytes():
 p=FPDF();p.add_page();p.set_font('Helvetica',size=12);p.multi_cell(0,8,'Synthetic PCA lecture. PCA projects data onto directions of greatest variance. '*30)
 return bytes(p.output())

def send_pdf(c):
 return c.post('/api/v1/materials',files={'file':('Synthetic readable.pdf',pdf_bytes(),'application/pdf')},data=dict(course='ML',semester='S1',subject='ML',unit='Unit 1'))

def test_readable_pdf_http_registration(web,services):
 services[0].materials.base.extractor=None
 c=client(web);r=send_pdf(c);assert r.status_code==200 and r.json()['success']
 assert c.get('/api/v1/materials').json()[0]['unit']=='Unit 1'

@pytest.mark.parametrize('failure,code',[(EmbeddingUnavailableError('PRIVATE PATH'),'EMBEDDING_UNAVAILABLE'),(RuntimeError('PRIVATE CLIENT'),'VECTOR_STORAGE_UNAVAILABLE')])
def test_vector_failure_rolls_back_and_classifies(web,services,secured,failure,code):
 services[0].materials.base.extractor=None
 v=services[1];original=v.add_material_chunks
 def partial(ids,chunks,metadata):
  original(ids,chunks,metadata);raise failure
 v.add_material_chunks=partial
 c=client(web);r=send_pdf(c)
 assert r.status_code==503 and r.json()['error']['code']==code and 'PRIVATE' not in r.text
 assert not v.rows and not list(services[0].materials.base.uploads.glob('*'))
 assert c.get('/api/v1/materials').json()==[]
 with secured.repo.connection() as conn:
  assert not conn.execute("SELECT * FROM resource_ownership WHERE resource_type='material'").fetchall()

@pytest.mark.parametrize('feature',['document','assistant','assessment'])
@pytest.mark.parametrize('failure,code',[(ai_provider.AIConnectionError('PRIVATE'),'PROVIDER_UNAVAILABLE'),(ai_provider.AIModelUnavailableError('PRIVATE'),'MODEL_UNAVAILABLE')])
def test_provider_failures_across_features(web,services,secured,monkeypatch,feature,failure,code):
 c=client(web)
 if feature=='assessment':
  m=upload(services[0],secured,secured.a,'Synthetic PCA');body=dict(BODY,material_ids=[m['material_id']]);url='/assessments/generate'
 elif feature=='document':body=REQUEST;url='/documents/generate'
 else:body={'request':'Draft a synthetic notice.'};url='/assistant/plan'
 spy=Mock(side_effect=failure);monkeypatch.setattr(ai_provider,'generate_chat',spy)
 r=c.post('/api/v1'+url,json=body)
 assert r.status_code==503 and r.json()['error']['code']==code and 'PRIVATE' not in r.text
 assert not web.state.workspaces.rows

@pytest.mark.parametrize('feature',['document','assistant'])
def test_timeout_retains_specific_classification(web,monkeypatch,feature):
 exc=ai_provider.AIConnectionError('PRIVATE');exc.__cause__=httpx.ReadTimeout('PRIVATE URL')
 monkeypatch.setattr(ai_provider,'generate_chat',Mock(side_effect=exc));c=client(web)
 url,body=('/documents/generate',REQUEST) if feature=='document' else ('/assistant/plan',{'request':'Draft a synthetic notice.'})
 r=c.post('/api/v1'+url,json=body);assert r.json()['error']['code']=='PROVIDER_TIMEOUT'

def test_xlsx_50_mapping_scale_and_zero_ai(web,monkeypatch):
 spy=Mock(side_effect=AssertionError('No AI'));monkeypatch.setattr(ai_provider,'generate_chat',spy)
 from application.runtime import ConfiguredVectors
 monkeypatch.setattr(ConfiguredVectors,'collection',Mock(side_effect=AssertionError('No embeddings')))
 w=Workbook();w.active.title='Student Data';w.active.append(['roll_no','attendance','marks'])
 for i in range(50):w.active.append([f'SYN{i:03}',80,20+i%10])
 b=io.BytesIO();w.save(b);w.close();c=client(web)
 h=c.post('/api/v1/students/upload',files={'file':('synthetic.xlsx',b.getvalue())}).json()['handle'];url='/api/v1/students/'+h
 p=c.post(url+'/preview',json={'sheet':'Student Data'}).json();assert p['total_rows']==50
 for role,column in [('student_id','roll_no'),('attendance','attendance'),('assessments','marks')]:assert p['suggestions'][role]['candidates']==[column]
 body=dict(sheet='Student Data',header_row=1,student_id='roll_no',attendance='attendance',assessments=[dict(column='marks',name='marks',scale='raw')])
 bad=c.post(url+'/normalize',json=body);assert bad.status_code==422 and bad.json()['error']['code']=='MARKS_MAXIMUM_REQUIRED'
 body['assessments'][0]['maximum']=50
 good=c.post(url+'/normalize',json=body);assert good.status_code==200 and good.json()['validation']['eligible_rows']==50
 a=c.post('/api/v1/students/'+good.json()['handle']+'/analyze',json={}).json();assert a['summary']['total_students']==50
 spy.assert_not_called()
