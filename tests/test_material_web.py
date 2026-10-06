"""Build 22 material transport contracts; isolated fixtures only."""
from unittest.mock import Mock
from test_api import web,client
from test_security import secured,services,upload,ctx,own
from security.models import Scope

def test_detail_visibility_owner_and_private_isolation(web,services,secured):
    item=upload(services[0],secured,secured.a,'PRIVATE detail')
    owner=client(web);r=owner.get('/api/v1/materials/'+item['material_id'])
    assert r.status_code==200 and r.json()['visibility']=='PRIVATE' and r.json()['can_manage']
    assert all(k not in r.json() for k in ('chunk_ids','managed_filename','file_hash','owner_professor_id'))
    assert client(web,'b').get('/api/v1/materials/'+item['material_id']).status_code==404

def test_shared_detail_is_read_only_without_membership_bypass(web,services,secured):
    item=upload(services[0],secured,secured.a,'COURSE detail',own(secured.a,Scope.COURSE,secured.course))
    path='/api/v1/materials/'+item['material_id'];other=client(web,'b')
    assert other.get(path).status_code==404
    secured.repo.set_membership(secured.b.professor_id,secured.course)
    result=other.get(path).json();assert result['visibility']=='COURSE' and not result['can_manage']
    assert other.patch(path,json=dict(course='X',semester='S',subject='X',unit='U')).status_code==404
    assert other.delete(path).status_code==404

def test_update_incomplete_does_not_claim_success(web,services,secured,monkeypatch):
    item=upload(services[0],secured,secured.a,'edit failure');monkeypatch.setattr(services[0].materials.base,'edit_hierarchy',Mock(return_value={'success':False,'error':'/private/raw secret','warnings':['secret']}))
    r=client(web).patch('/api/v1/materials/'+item['material_id'],json=dict(course='X',semester='S',subject='X',unit='U'))
    assert r.json()=={'status':'incomplete','success':False};assert 'secret' not in r.text

def test_update_success_contract(web,services,secured):
    item=upload(services[0],secured,secured.a,'edit success');c=client(web);path='/api/v1/materials/'+item['material_id']
    assert c.patch(path,json=dict(course='X',semester='S',subject='X',unit='U')).json()=={'status':'updated','success':True}
    assert c.get(path).json()['unit']=='U'

def test_delete_partial_does_not_claim_success(web,services,secured,monkeypatch):
    item=upload(services[0],secured,secured.a,'delete failure');monkeypatch.setattr(services[0].materials.base,'delete',Mock(return_value=dict(success=False,sqlite_deleted=False,vectors_deleted=1,file_deleted=False,error='/private secret')))
    r=client(web).delete('/api/v1/materials/'+item['material_id']);assert not r.json()['success'];assert 'secret' not in r.text

def test_metadata_browsing_does_not_initialize_vectors_or_inference(web,services,secured,monkeypatch):
    import ai_provider
    item=upload(services[0],secured,secured.a,'metadata only');factory=services[2];factory.reset_mock();provider=Mock();monkeypatch.setattr(ai_provider,'generate_chat',provider)
    c=client(web)
    assert c.get('/api/v1/materials').status_code==200
    assert c.get('/api/v1/materials/'+item['material_id']).status_code==200
    assert c.get('/api/v1/dashboard').status_code==200
    factory.assert_not_called();provider.assert_not_called()
