"""Actor-filtered cursor history never projects private audit internals."""
import pytest
from test_api import web,client
from test_security import secured,services,ctx

def populate(s,actor,action='material_uploaded',count=25):
 for _ in range(count):s.repo.audit(actor,action)

def test_actor_scoped_cursor_order_and_filter(web,secured):
 s=secured;populate(s,s.a,count=25);populate(s,s.b,'document_saved',3);c=client(web);page=c.get('/api/v1/activity/page').json();assert len(page['items'])==20 and page['next_cursor'];older=c.get('/api/v1/activity/page',params={'before':page['next_cursor']}).json();assert len(older['items'])==5 and older['next_cursor'] is None
 assert all(set(i)=={'action','timestamp','category'} for i in page['items']);assert [i['timestamp'] for i in page['items']]==sorted([i['timestamp'] for i in page['items']],reverse=True)
 assert c.get('/api/v1/activity/page?category=Documents').json()['items']==[]
 assert len(client(web,'b').get('/api/v1/activity/page').json()['items'])==3

def test_private_admin_has_no_professor_activity(services,secured):
 populate(secured,secured.a);assert services[0].activity.page(context=ctx(secured.admin))['items']==[]

def test_unknown_event_and_private_timestamp_never_echo(web,secured):
 with secured.repo.connection() as c:c.execute('INSERT INTO security_activity(actor_professor_id,action,timestamp) VALUES (?,?,?)',(secured.a.professor_id,'RAW student marks private /secret','PRIVATE DATE'))
 r=client(web).get('/api/v1/activity/page');assert r.json()['items']==[dict(action='Recorded activity',timestamp='Time unavailable',category='Workspace')];assert 'private' not in r.text and 'PRIVATE DATE' not in r.text

@pytest.mark.parametrize('query',['category=SQL','limit=0','limit=51','before=0','before=-1','professor_id=foreign'])
def test_query_boundaries(web,query):
 r=client(web).get('/api/v1/activity/page?'+query)
 if query.startswith('professor_id'):assert r.json()['items']==[]
 else:assert r.status_code==422

def test_cursor_stable_under_new_insertion(web,secured):
 populate(secured,secured.a,count=21);c=client(web);first=c.get('/api/v1/activity/page').json();populate(secured,secured.a,'document_saved',1);older=c.get('/api/v1/activity/page',params={'before':first['next_cursor']}).json();assert len(older['items'])==1 and older['items'][0]['action']=='Material uploaded'

def test_activity_empty_and_unauthorized(web):
 from fastapi.testclient import TestClient
 assert client(web).get('/api/v1/activity/page').json()['items']==[];assert TestClient(web).get('/api/v1/activity/page').status_code==401
