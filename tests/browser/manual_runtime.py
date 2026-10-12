"""Explicit synthetic browser runtime. No imports initialize production storage.
Run from repository: .venv-rebuild/bin/python tests/browser/manual_runtime.py
Stop with Ctrl-C; the temporary SQLite/uploads directory is then discarded.
"""
import json,sys,tempfile,os,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]

def main():
 import uvicorn,ai_provider
 from fpdf import FPDF
 from openpyxl import Workbook
 assets=Path(tempfile.gettempdir())
 pdf=FPDF();pdf.add_page();pdf.set_font('Helvetica',size=12)
 pdf.multi_cell(0,8,'Synthetic PCA projects data onto directions of greatest variance. '*30)
 (assets/'eduagent-manual-readable.pdf').write_bytes(bytes(pdf.output()))
 book=Workbook();book.active.title='Student Data';book.active.append(['roll_no','attendance','marks'])
 for i in range(50):book.active.append([f'SYN{i:03}',80,20+i%10])
 book.save(assets/'eduagent-manual-students.xlsx');book.close()
 from api.bootstrap import bootstrap
 from api.settings import APISettings
 from api import create_api_app
 from security.repository import SecurityRepository
 from security.sessions import SessionService
 from application import create_application_services
 from application.materials import MaterialService
 from test_security import SecureVectors
 calls=[]
 def mock(messages,**kwargs):
  text=str(messages)
  assert not any(s in text for s in ('STUDENTMARKER27','IDMARKER27','83.456','47.123'))
  calls.append('mock')
  time.sleep(float(os.environ.get('EDUAGENT_SYNTHETIC_DELAY','0')))
  if 'Synthetic provider unavailable' in text:raise ai_provider.AIConnectionError('Synthetic private client failure')
  try:p=json.loads(messages[-1]['content'])
  except ValueError:return 'PCA projects data onto directions of greatest variance. [E1]'
  if 'request' in p:
   return json.dumps({'unsupported':False,'actions':[{'action_id':'draft','action_type':'CREATE_DOCUMENT','parameters':{'document_type':'notice','description':'Announce a synthetic seminar.','title':'Synthetic assistant notice'},'depends_on':[]}]})
  if 'slots' in p:
   if len(p['slots'])==15:time.sleep(float(os.environ.get('EDUAGENT_SYNTHETIC_ASSESSMENT_DELAY','0')))
   return json.dumps({'questions':[{**s,'question_text':f'Synthetic PCA question {s["question_number"]}?','options':{'A':'Projection','B':'Deletion','C':'Storage','D':'Attendance'} if s['question_type']=='MCQ' else {},'correct_answer':'A' if s['question_type']=='MCQ' else '', 'model_answer':'PCA projects data.','evidence_ids':['E1']} for s in p['slots']]})
  if 'current' in p:
   current=p['current']
   if 'Synthetic contradictory' in p.get('instruction',''):current['recipient']='Invented administrator'
   elif 'longer' in p.get('instruction','').lower():current['body']=current['body']+['We respectfully request your consideration and guidance on the necessary next steps.']
   return json.dumps(current)
  body=['I am writing to request financial approval for a welcome event for first-year students.','The proposed event would offer an opportunity for students to become acquainted. Kindly consider this request and advise on the necessary next steps.'] if p.get('document_type') in ('financial_approval','official_letter') else ['Synthetic seminar tutorial. Please review the proposed academic communication.']
  return json.dumps({k:p.get(k,'') for k in ('document_type','title','date','reference_number','recipient','sender','subject','signature')}|{'salutation':'Dear Dean,' if p.get('document_type') in ('financial_approval','official_letter') else '', 'closing':'Respectfully,' if p.get('document_type') in ('financial_approval','official_letter') else '', 'body':body})
 ai_provider.generate_chat=mock
 with tempfile.TemporaryDirectory(prefix='eduagent-manual-') as directory:
  dbpath=Path(directory)/'isolated.sqlite3';identities=bootstrap(dbpath)
  repo=SecurityRepository(database_path=dbpath);vectors=SecureVectors()
  api=create_application_services(materials=MaterialService(uploads=Path(directory)/'uploads',vectors=vectors,extractor=None),security_repository=repo,collection_factory=lambda:vectors)
  cfg=APISettings(mode='development',dev_auth_enabled=True,dev_access_key='synthetic-development-key-build27-000000',dev_identities=identities,database_path=str(dbpath),cors_origins=('http://127.0.0.1:3000',))
  app=create_api_app(settings=cfg,services=api,sessions=SessionService(repo))
  try:uvicorn.run(app,host='127.0.0.1',port=8000,access_log=False,log_level='warning')
  finally:
   print('Mocked calls:',len(calls),'Live inference: 0')
   for name in ('eduagent-manual-readable.pdf','eduagent-manual-students.xlsx'):(assets/name).unlink(missing_ok=True)
if __name__=='__main__':main()
