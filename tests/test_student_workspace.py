"""Synthetic HTTP student workflow: no AI, persistence or production storage."""
import io
from unittest.mock import Mock
import pytest
from test_api import web,client
from test_security import secured,services
from openpyxl import Workbook
BASE='/api/v1/students/'
ROWS=b'Roll Number,Name,Attendance,Quiz\n001,Synthetic Alpha,90,80\n002,Synthetic Beta,,40\n003,Synthetic Gamma,95,broken\n'
MAP=dict(sheet='CSV',header_row=1,student_id='Roll Number',student_name='Name',attendance='Attendance',assessments=[dict(column='Quiz',name='Quiz')])
def upload(c,data=ROWS,name='synthetic.csv'):
 r=c.post(BASE+'upload',files={'file':(name,data)});assert r.status_code==200,r.text;return r.json()['handle']
def normalized(c):
 h=upload(c);r=c.post(BASE+h+'/normalize',json=MAP);assert r.status_code==200,r.text;return r.json()
def test_complete_zero_ai_workflow(web,monkeypatch,caplog):
 import ai_provider
 spy=Mock(side_effect=AssertionError('Student workflow must never call AI'));monkeypatch.setattr(ai_provider,'generate_chat',spy)
 c=client(web);h=upload(c)
 p=c.post(BASE+h+'/preview',json={'sheet':'CSV','header_row':1});assert p.status_code==200
 assert p.json()['suggestions']['student_id']['candidates']==['Roll Number']
 d=c.post(BASE+h+'/normalize',json=MAP).json();assert d['validation']['invalid_rows']==1 and d['validation']['incomplete_rows']==1
 h=d['handle'];a=c.post(BASE+h+'/analyze',json={});assert a.json()['summary']['total_students']==2
 f=c.post(BASE+h+'/analyze',json={'view':'Incomplete'});assert len(f.json()['students'])==1
 detail=c.post(BASE+h+'/detail',json={'index':1});assert detail.status_code==200 and detail.json()['history'][0]['attendance_percent'] is None
 export=c.post(BASE+h+'/export',json={'view':'Incomplete'});assert 'Synthetic Beta' in export.text and 'Synthetic Alpha' not in export.text
 assert c.delete(BASE+h).status_code==200
 assert c.post(BASE+h+'/analyze',json={}).status_code==404
 spy.assert_not_called();assert 'Synthetic Beta' not in caplog.text

def test_preview_bounded(web):
 c=client(web);data=('Roll Number,Name,Attendance,Quiz\n'+''.join(f'{i},'+('x'*500)+',90,80\n' for i in range(30))).encode();h=upload(c,data)
 p=c.post(BASE+h+'/preview',json={'sheet':'CSV'}).json();assert len(p['rows'])==10 and p['total_rows']==30 and len(p['rows'][0]['Name'])==200

@pytest.mark.parametrize('operation',['preview','normalize'])
def test_book_cross_professor_and_session(web,operation):
 a=client(web);h=upload(a);body={'sheet':'CSV'} if operation=='preview' else MAP
 for b in [client(web,'b'),client(web,'a')]:assert b.post(BASE+h+'/'+operation,json=body).status_code==404
@pytest.mark.parametrize('operation',['analyze','detail','export'])
def test_data_cross_professor_and_session(web,operation):
 a=client(web);h=normalized(a)['handle'];body={'index':0} if operation=='detail' else {}
 for b in [client(web,'b'),client(web,'a')]:assert b.post(BASE+h+'/'+operation,json=body).status_code==404
@pytest.mark.parametrize('operation',['preview','analyze','detail','export'])
def test_guessed_handles(web,operation):
 c=client(web);body={'sheet':'CSV'} if operation=='preview' else {'index':0} if operation=='detail' else {}
 assert c.post(BASE+'guessed/'+operation,json=body).status_code==404

def test_clear_unmapped_book(web):
 c=client(web);h=upload(c);assert c.delete(BASE+h).status_code==200;assert c.post(BASE+h+'/preview',json={'sheet':'CSV'}).status_code==404

def test_logout_invalidates_student_data(web):
 c=client(web);h=normalized(c)['handle'];assert c.post('/api/v1/auth/logout',json={}).status_code==200
 assert not web.state.workspaces.rows
 assert c.post(BASE+h+'/analyze',json={}).status_code==401

def test_formula_export(web):
 c=client(web);h=upload(c,b'Roll Number,Name,Attendance,Quiz\n001,+Synthetic,90,80\n');h=c.post(BASE+h+'/normalize',json=MAP).json()['handle']
 assert "'+Synthetic" in c.post(BASE+h+'/export',json={}).text

def test_xlsx_preview_and_mapping(web):
 w=Workbook();w.active.title='Class';w.active.append(['Roll Number','Name','Attendance','Quiz']);w.active.append(['001','Synthetic',90,80]);b=io.BytesIO();w.save(b)
 c=client(web);h=upload(c,b.getvalue(),'synthetic.xlsx');p=c.post(BASE+h+'/preview',json={'sheet':'Class'});assert p.json()['total_rows']==1
 m={**MAP,'sheet':'Class'};assert c.post(BASE+h+'/normalize',json=m).status_code==200

@pytest.mark.parametrize('body',[{'sheet':'Unknown'},{'sheet':'CSV','header_row':0},{'sheet':'CSV','header_row':100}])
def test_safe_bad_preview(web,body):
 c=client(web);h=upload(c);r=c.post(BASE+h+'/preview',json=body);assert r.status_code==422;assert 'Synthetic Alpha' not in r.text

def test_all_invalid_visible_normalization(web):
 c=client(web);h=upload(c,b'Roll Number,Name,Attendance,Quiz\n001,Synthetic,broken,bad\n');r=c.post(BASE+h+'/normalize',json=MAP);assert r.json()['validation']['eligible_rows']==0
 assert set(r.json()['issues'][0])=={'row','code','severity'}

def test_detail_index_bound(web):
 c=client(web);h=normalized(c)['handle'];assert c.post(BASE+h+'/detail',json={'index':999}).status_code==404

def test_trend_detail_authoritative(web):
 c=client(web);h=upload(c,b'Roll Number,Name,Attendance,Quiz,Assessment Number\n001,Synthetic,90,80,1\n001,Synthetic,65,40,2\n');m={**MAP,'assessment_number':'Assessment Number'};h=c.post(BASE+h+'/normalize',json=m).json()['handle']
 d=c.post(BASE+h+'/detail',json={'index':0}).json();assert d['mode']=='trend' and len(d['history'])==2 and d['student']['marks_trend']=='Declining'

def test_expiry(web):
 c=client(web);h=upload(c);web.state.workspaces.clock=lambda:10**20
 assert c.post(BASE+h+'/preview',json={'sheet':'CSV'}).status_code==404


def test_clear_invalidates_dependent_plan(web):
 from types import SimpleNamespace
 c=client(web);h=normalized(c)['handle'];rows=web.state.workspaces.rows;session,_,expires,dataset=rows[h]
 rows['synthetic-plan']=(session,'plan',expires,(None,SimpleNamespace(student_dataset=dataset),None))
 rows['unrelated-plan']=(session,'plan',expires,(None,SimpleNamespace(student_dataset=None),None))
 assert c.delete(BASE+h).status_code==200
 assert 'synthetic-plan' not in rows and 'unrelated-plan' in rows

def test_no_student_persistence_or_activity(web,secured):
 c=client(web);h=normalized(c)['handle'];c.post(BASE+h+'/analyze',json={});c.post(BASE+h+'/detail',json={'index':0});c.post(BASE+h+'/export',json={});c.delete(BASE+h)
 with secured.repo.connection() as conn:
  for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
   values=list(conn.execute('SELECT * FROM "'+row[0].replace('"','""')+'"'))
   assert 'Synthetic Alpha' not in str([tuple(v) for v in values])
   assert 'Synthetic Beta' not in str([tuple(v) for v in values])

def test_student_mutations_require_csrf(web):
 c=client(web);h=upload(c);c.headers.pop('X-CSRF-Token')
 assert c.post(BASE+h+'/preview',json={'sheet':'CSV'}).status_code==403
 assert c.delete(BASE+h).status_code==403
