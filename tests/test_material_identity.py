import hashlib
import json
import uuid
from pathlib import Path
import pytest
import db
import material_service as service
from material_fixtures import Vectors

@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', str(tmp_path/'registry.db'))
    db.init_db()
    return tmp_path/'uploads', Vectors()

@pytest.fixture
def hierarchy():
    return dict(course='B.Tech CSE', semester='Semester 5', subject='Machine Learning', unit='Unit Test')

def upload(storage, hierarchy, data=b'synthetic A', name='notes.pdf', **kwargs):
    root, vectors = storage
    return service.upload_material(data, name, hierarchy, uploads=root, vectors=vectors, extractor=kwargs.pop('extractor', lambda _: 'Synthetic PCA material. '*40), **kwargs)

def test_identity(storage,hierarchy):
    out=upload(storage,hierarchy); assert out['success']; m=out['material']
    assert uuid.UUID(m['material_id']).version==4
    assert m['file_hash']==hashlib.sha256(b'synthetic A').hexdigest()
    assert m['original_filename']=='notes.pdf'
    assert m['managed_filename']==m['material_id']+'.pdf'
    assert (storage[0]/m['managed_filename']).is_file()
    ids=json.loads(m['chunk_ids']);assert ids==[f"{m['material_id']}_chunk_{i}" for i in range(len(ids))]
    saved=db.get_material(m['material_id']);assert all(saved[k]==v for k,v in hierarchy.items())
    assert all(row['metadata']==dict(material_id=m['material_id'],source='notes.pdf',**hierarchy) for row in storage[1].rows.values())

@pytest.mark.parametrize('name',['notes.pdf','other.pdf'])
def test_duplicate(storage,hierarchy,name):
    first=upload(storage,hierarchy);before=dict(storage[1].rows)
    out=upload(storage,hierarchy,name=name)
    assert not out['success'] and out['duplicate'];assert out['existing_material']['material_id']==first['material']['material_id']
    assert storage[1].rows==before and len(db.list_materials())==1
    assert len(list(storage[0].iterdir()))==1

def test_same_filename_different_bytes(storage,hierarchy):
    a=upload(storage,hierarchy)['material'];b=upload(storage,hierarchy,data=b'synthetic B')['material']
    assert a['material_id']!=b['material_id']
    assert not set(json.loads(a['chunk_ids']))&set(json.loads(b['chunk_ids']))
    assert len(db.list_materials())==2

@pytest.mark.parametrize('name',['../evil.pdf','/evil.pdf','nested/evil.pdf','nested\\evil.pdf','C:\\evil.pdf','bad\x00.pdf','notes.txt'])
def test_bad_filename(storage,hierarchy,name):
    with pytest.raises(service.MaterialError):upload(storage,hierarchy,name=name)
    assert not storage[0].exists() and not db.list_materials()

def test_unicode_filename(storage,hierarchy):
    out=upload(storage,hierarchy,name='講義 — PCA.pdf');assert out['success']
    assert out['material']['original_filename']=='講義 — PCA.pdf'
    assert (storage[0]/out['material']['managed_filename']).resolve().parent==storage[0].resolve()

@pytest.mark.parametrize('key',['course','semester','subject','unit'])
def test_blank_hierarchy(storage,hierarchy,key):
    hierarchy[key]='  '
    with pytest.raises(service.MaterialError):upload(storage,hierarchy)

def test_trim_hierarchy(storage,hierarchy):
    hierarchy['unit']='  Unit Test  '
    assert upload(storage,hierarchy)['material']['unit']=='Unit Test'

def test_legacy_migration(storage):
    db.add_course_if_new('Legacy');db.add_document_record('PCA','Legacy','Unit 1','PCA.pdf')
    db.init_db();db.init_db()
    old=db.get_documents_for_course('Legacy')[0]; assert old['source_name']=='PCA'
    row=db.legacy_materials('Legacy')[0]
    assert row['semester']==row['subject']=='Unassigned' and row['unit']=='Unit 1'
    assert not row['managed']
    assert not service.delete_material(str(row['id']),uploads=storage[0],vectors=storage[1])['success']

def test_hash():
    assert service.content_hash(b'same')==service.content_hash(b'same')
    assert service.content_hash(b'same')!=service.content_hash(b'other')


def test_old_schema_additive(tmp_path,monkeypatch):
    import sqlite3
    path=tmp_path/'old.db'
    with sqlite3.connect(path) as conn:
        conn.executescript("CREATE TABLE courses (id INTEGER PRIMARY KEY, course_name TEXT UNIQUE NOT NULL, created_at TEXT); CREATE TABLE documents (id INTEGER PRIMARY KEY, source_name TEXT NOT NULL, course TEXT, unit TEXT, filename TEXT, uploaded_at TEXT); CREATE TABLE activity_log (id INTEGER PRIMARY KEY, action TEXT NOT NULL, details TEXT, timestamp TEXT);")
        conn.execute("INSERT INTO courses VALUES (1,'Legacy','2020')")
        conn.execute("INSERT INTO documents VALUES (1,'PCA','Legacy',NULL,'PCA.pdf','2020')")
        conn.execute("INSERT INTO activity_log VALUES (1,'old','preserved','2020')")
    monkeypatch.setattr(db,'DB_PATH',str(path));db.init_db();db.init_db()
    assert db.get_all_courses()==['Legacy']
    assert db.legacy_materials('Legacy')[0]['unit']=='Unassigned'
    assert db.get_recent_activity()[0]['details']=='preserved'
    assert db.list_materials()==[]
