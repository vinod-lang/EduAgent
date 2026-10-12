"""Explicit synthetic browser runtime. No imports initialize production storage.
Run from repository: .venv-rebuild/bin/python tests/browser/build27_runtime.py
Stop with Ctrl-C; the temporary SQLite/uploads directory is then discarded.
"""
import json,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]

def main():
 import uvicorn,ai_provider
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
  try:p=json.loads(messages[-1]['content'])
  except ValueError:return 'PCA projects data onto directions of greatest variance. [E1]'
  if 'request' in p:
   return json.dumps({'unsupported':False,'actions':[{'action_id':'draft','action_type':'CREATE_DOCUMENT','parameters':{'document_type':'notice','description':'Announce a synthetic seminar.','title':'Synthetic assistant notice'},'depends_on':[]}]})
  if 'slots' in p:
   return json.dumps({'questions':[{**s,'question_text':f'Synthetic PCA question {s["question_number"]}?','options':{'A':'Projection','B':'Deletion','C':'Storage','D':'Attendance'} if s['question_type']=='MCQ' else {},'correct_answer':'A' if s['question_type']=='MCQ' else '', 'model_answer':'PCA projects data.','evidence_ids':['E1']} for s in p['slots']]})
  if 'current' in p:return json.dumps(p['current'])
  return json.dumps({k:p.get(k,'') for k in ('document_type','title','date','reference_number','recipient','sender','subject','signature')}|{'salutation':'','closing':'','body':['Synthetic seminar tutorial. Budget 2500.']})
 ai_provider.generate_chat=mock
 with tempfile.TemporaryDirectory(prefix='eduagent-build27-') as directory:
  dbpath=Path(directory)/'isolated.sqlite3';identities=bootstrap(dbpath)
  repo=SecurityRepository(database_path=dbpath);vectors=SecureVectors()
  api=create_application_services(materials=MaterialService(uploads=Path(directory)/'uploads',vectors=vectors,extractor=lambda p:p.read_bytes().decode()),security_repository=repo,collection_factory=lambda:vectors)
  cfg=APISettings(mode='development',dev_auth_enabled=True,dev_access_key='synthetic-development-key-build27-000000',dev_identities=identities,database_path=str(dbpath),cors_origins=('http://127.0.0.1:3000',))
  app=create_api_app(settings=cfg,services=api,sessions=SessionService(repo))
  try:uvicorn.run(app,host='127.0.0.1',port=8000,access_log=False,log_level='warning')
  finally:print('Mocked calls:',len(calls),'Live inference: 0')
if __name__=='__main__':main()
