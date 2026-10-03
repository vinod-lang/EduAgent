import json
from pathlib import Path
import pytest
import db
import material_service as service
from test_material_identity import storage, hierarchy, upload


def test_full_delete_preserves_other(storage,hierarchy):
    a=upload(storage,hierarchy)['material'];b=upload(storage,hierarchy,data=b'B',name='notes-copy.pdf')['material']
    out=service.delete_material(a['material_id'],uploads=storage[0],vectors=storage[1])
    assert out['success'] and out['sqlite_deleted'] and out['file_deleted']
    assert out['vectors_deleted']==len(json.loads(a['chunk_ids']))
    assert not db.get_material(a['material_id']) and not (storage[0]/a['managed_filename']).exists()
    assert db.get_material(b['material_id']) and (storage[0]/b['managed_filename']).exists()
    assert set(storage[1].rows)==set(json.loads(b['chunk_ids']))
    assert {row['action'] for row in db.get_recent_activity()} >= {'material_uploaded','material_deleted'}

@pytest.mark.parametrize('kind',['extraction','empty','vectors','registry'])
def test_upload_rollback(storage,hierarchy,monkeypatch,kind):
    extractor=lambda _:'synthetic'
    if kind=='extraction':
        def extractor(_): raise RuntimeError('synthetic extraction error')
    if kind=='empty':extractor=lambda _: '   '
    if kind=='vectors':storage[1].fail_add=True
    if kind=='registry':monkeypatch.setattr(db,'register_material',lambda _:(_ for _ in ()).throw(RuntimeError('synthetic registry error')))
    out=upload(storage,hierarchy,extractor=extractor)
    assert not out['success'] and out['error']
    assert not db.list_materials() and not storage[1].rows and not list(storage[0].iterdir())

@pytest.mark.parametrize('kind',['vectors','file','sqlite'])
def test_delete_failure_retry(storage,hierarchy,monkeypatch,kind):
    m=upload(storage,hierarchy)['material']; original_unlink=Path.unlink
    with monkeypatch.context() as patch:
        if kind=='vectors':storage[1].fail_delete=True
        if kind=='file':patch.setattr(Path,'unlink',lambda *a,**k:(_ for _ in ()).throw(OSError('synthetic denied')))
        if kind=='sqlite':patch.setattr(db,'remove_material_record',lambda _:(_ for _ in ()).throw(RuntimeError('synthetic db failure')))
        out=service.delete_material(m['material_id'],uploads=storage[0],vectors=storage[1])
    assert not out['success'] and not out['sqlite_deleted'] and db.get_material(m['material_id'])
    if kind=='vectors':assert (storage[0]/m['managed_filename']).exists() and storage[1].rows
    storage[1].fail_delete=False
    assert service.delete_material(m['material_id'],uploads=storage[0],vectors=storage[1])['success']

@pytest.mark.parametrize('missing',['file','vectors','both'])
def test_already_missing(storage,hierarchy,missing):
    m=upload(storage,hierarchy)['material']
    if missing in ['file','both']:(storage[0]/m['managed_filename']).unlink()
    if missing in ['vectors','both']:storage[1].rows.clear()
    assert service.delete_material(m['material_id'],uploads=storage[0],vectors=storage[1])['success']

@pytest.mark.parametrize('kind',['path','symlink','shared_ids','shared_file','wrong_vector_owner','bad_json'])
def test_ownership_safety(storage,hierarchy,kind,tmp_path):
    a=upload(storage,hierarchy)['material'];b=upload(storage,hierarchy,data=b'B')['material']
    outside=tmp_path/'outside.pdf';outside.write_bytes(b'protected')
    if kind=='symlink':
        path=storage[0]/a['managed_filename'];path.unlink();path.symlink_to(outside)
    if kind=='path':
        with db.get_connection() as conn:conn.execute('UPDATE materials SET managed_filename=? WHERE material_id=?',(str(outside),a['material_id']))
    if kind=='shared_ids':
        with db.get_connection() as conn:conn.execute('UPDATE materials SET chunk_ids=? WHERE material_id=?',(a['chunk_ids'],b['material_id']))
    if kind=='shared_file':
        # Test the defensive guard directly; schema uniqueness also prevents this corruption.
        original=db.list_materials
        from unittest.mock import patch
        with patch.object(db,'list_materials',return_value=[a,dict(b,managed_filename=a['managed_filename'])]):
            assert not service.delete_material(a['material_id'],uploads=storage[0],vectors=storage[1])['success']
        return
    if kind=='wrong_vector_owner':storage[1].rows[json.loads(a['chunk_ids'])[0]]['metadata']['material_id']=b['material_id']
    if kind=='bad_json':
        with db.get_connection() as conn:conn.execute('UPDATE materials SET chunk_ids=? WHERE material_id=?',('not JSON',a['material_id']))
    before=set(storage[1].rows)
    out=service.delete_material(a['material_id'],uploads=storage[0],vectors=storage[1])
    assert not out['success'] and db.get_material(a['material_id'])
    assert set(storage[1].rows)==before and outside.read_bytes()==b'protected'


def test_edit_identity(storage,hierarchy):
    m=upload(storage,hierarchy)['material']; updated=dict(course='New Course',semester='Semester 6',subject='New Subject',unit='Unit 2')
    assert service.edit_hierarchy(m['material_id'],updated,vectors=storage[1])['success']
    after=db.get_material(m['material_id'])
    for key in ('material_id','file_hash','managed_filename','chunk_ids','original_filename'):assert after[key]==m[key]
    assert all(after[k]==v for k,v in updated.items())
    assert all(all(row['metadata'][k]==v for k,v in updated.items()) for row in storage[1].rows.values())
    assert db.get_recent_activity()[0]['action']=='material_hierarchy_updated'

@pytest.mark.parametrize('kind',['vectors','sqlite','missing'])
def test_edit_failure(storage,hierarchy,monkeypatch,kind):
    m=upload(storage,hierarchy)['material']
    if kind=='vectors':storage[1].fail_update=True
    if kind=='sqlite':monkeypatch.setattr(db,'update_material_hierarchy',lambda *a:(_ for _ in ()).throw(RuntimeError('synthetic sqlite error')))
    if kind=='missing':storage[1].rows.clear()
    out=service.edit_hierarchy(m['material_id'],dict(hierarchy,unit='Changed'),vectors=storage[1])
    assert not out['success'] and db.get_material(m['material_id'])['unit']==hierarchy['unit']
    assert all(row['metadata']['unit']==hierarchy['unit'] for row in storage[1].rows.values())


def test_rollback_failure_explicit(storage,hierarchy,monkeypatch):
    storage[1].fail_add=storage[1].fail_delete=True
    out=upload(storage,hierarchy)
    assert not out['success'] and out['warnings'] and out['chunk_ids']


def test_silent_vector_insertion_refused(storage,hierarchy,monkeypatch):
    monkeypatch.setattr(storage[1],'add_material_chunks',lambda *a:None)
    out=upload(storage,hierarchy)
    assert not out['success'] and not db.list_materials()
    assert not list(storage[0].iterdir())


def test_silent_delete_refused(storage,hierarchy,monkeypatch):
    m=upload(storage,hierarchy)['material']
    monkeypatch.setattr(storage[1],'delete_material_chunks',lambda *a:None)
    out=service.delete_material(m['material_id'],uploads=storage[0],vectors=storage[1])
    assert not out['success'] and db.get_material(m['material_id'])
    assert (storage[0]/m['managed_filename']).exists()


def test_silent_update_refused(storage,hierarchy,monkeypatch):
    m=upload(storage,hierarchy)['material']
    monkeypatch.setattr(storage[1],'update_material_chunks',lambda *a:None)
    out=service.edit_hierarchy(m['material_id'],dict(hierarchy,unit='Changed'),vectors=storage[1])
    assert not out['success'] and db.get_material(m['material_id'])['unit']==hierarchy['unit']


def test_existing_uuid_file_never_overwritten(storage,hierarchy,monkeypatch):
    import uuid
    m=upload(storage,hierarchy)['material'];path=storage[0]/m['managed_filename'];before=path.read_bytes()
    monkeypatch.setattr(service.uuid,'uuid4',lambda:uuid.UUID(m['material_id']))
    out=upload(storage,hierarchy,data=b'different')
    assert not out['success'] and path.read_bytes()==before and len(db.list_materials())==1


def test_existing_chunk_ids_never_overwritten(storage,hierarchy,monkeypatch):
    import uuid
    identity=str(uuid.uuid4());key=identity+'_chunk_0'
    storage[1].rows[key]={'document':'protected','metadata':{'material_id':'other'}}
    monkeypatch.setattr(service.uuid,'uuid4',lambda:uuid.UUID(identity))
    out=upload(storage,hierarchy,extractor=lambda _:'synthetic')
    assert not out['success'] and storage[1].rows[key]['document']=='protected'
    assert not db.list_materials() and not list(storage[0].iterdir())
