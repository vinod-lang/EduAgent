"""Synthetic bounded indexing and exact rollback; no live embeddings or storage."""
import json,logging
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import db,material_service
from vector_indexing import insert_chunks
from indexing_diagnostics import diagnostic_scope,observe
from test_material_identity import storage,hierarchy
from material_fixtures import Vectors

class Collection:
 def __init__(self,maximum=5,fail=None,fail_delete=False):
  self._client=SimpleNamespace(get_max_batch_size=lambda:maximum)
  self.rows={};self.batches=[];self.fail=fail;self.fail_delete=fail_delete
 def add(self,ids,documents,metadatas):
  self.batches.append(list(ids))
  for key,text,meta in zip(ids,documents,metadatas):self.rows[key]={'document':text,'metadata':dict(meta)}
  if len(self.batches)==self.fail:raise RuntimeError('PRIVATE document path /private/professor')
 def get(self,ids):
  present=[i for i in ids if i in self.rows]
  return dict(ids=present,documents=[self.rows[i]['document'] for i in present],metadatas=[self.rows[i]['metadata'] for i in present])
 def delete(self,ids):
  if self.fail_delete:raise RuntimeError('PRIVATE rollback details')
  for key in ids:self.rows.pop(key,None)

class Adapter:
 def __init__(self,c):self.c=c
 def add_material_chunks(self,ids,chunks,metadata):return insert_chunks(self.c,ids,chunks,metadata)
 def get_material_chunks(self,ids):return self.c.get(ids)
 def delete_material_chunks(self,ids):return self.c.delete(ids)

@pytest.mark.parametrize('count,expected',[(1,[1]),(4,[4]),(5,[4,1]),(9,[4,4,1])])
def test_boundaries_and_final_batch(monkeypatch,count,expected):
 monkeypatch.setenv('EDUAGENT_INDEX_BATCH_SIZE','500');c=Collection()
 ids=[f'owned_{i}' for i in range(count)];chunks=['synthetic']*count
 insert_chunks(c,ids,chunks,{'owner_professor_id':'synthetic-owner'})
 assert [len(b) for b in c.batches]==expected
 assert list(c.rows)==ids and all(v['metadata']['owner_professor_id']=='synthetic-owner' for v in c.rows.values())

@pytest.mark.parametrize('failure',[1,2,3])
def test_failed_batches_complete_rollback_and_safe_retry(storage,hierarchy,monkeypatch,failure):
 c=Collection(fail=failure);adapter=Adapter(c)
 monkeypatch.setattr(material_service,'chunk_text',lambda text:['synthetic']*9)
 c.rows['unrelated']={'document':'other','metadata':{'owner_professor_id':'other'}}
 spy=Mock(wraps=db.register_material);monkeypatch.setattr(db,'register_material',spy)
 args=(b'synthetic upload','notes.pdf',hierarchy)
 result=material_service.upload_material(*args,uploads=storage[0],vectors=adapter,extractor=lambda path:'PRIVATE extracted content')
 assert not result['success'] and not result['warnings']
 assert set(c.rows)=={'unrelated'} and not db.list_materials() and not list(storage[0].iterdir())
 assert spy.call_count==0
 c.fail=None
 good=material_service.upload_material(*args,uploads=storage[0],vectors=adapter,extractor=lambda path:'synthetic')
 assert good['success'] and spy.call_count==1
 assert len(c.rows)==10
 ids=json.loads(good['material']['chunk_ids']);assert len(set(ids))==9
 assert adapter.get_material_chunks(ids)['documents']==['synthetic']*9
 duplicate=material_service.upload_material(*args,uploads=storage[0],vectors=adapter,extractor=lambda path:'synthetic')
 assert duplicate['duplicate'] and len(c.rows)==10


def test_failed_rollback_explicit_private_logs(storage,hierarchy,monkeypatch,caplog):
 c=Collection(fail=2,fail_delete=True);monkeypatch.setattr(material_service,'chunk_text',lambda text:['PRIVATE text']*9)
 with caplog.at_level(logging.INFO,logger='eduagent.indexing'):
  result=material_service.upload_material(b'synthetic','PRIVATE_NAME.pdf',hierarchy,uploads=storage[0],vectors=Adapter(c),extractor=lambda path:'PRIVATE content')
 assert not result['success'] and result['warnings'] and not db.list_materials()
 assert not list(storage[0].iterdir())
 log=caplog.text
 assert '"vector_rollback": "fail"' in log and '"inserted_batches": 1' in log
 assert 'PRIVATE' not in log and '/private/' not in log and 'PRIVATE_NAME' not in log


def test_configurable_size(monkeypatch):
 monkeypatch.setenv('EDUAGENT_INDEX_BATCH_SIZE','2');c=Collection(10)
 insert_chunks(c,list('abcde'),['x']*5,{})
 assert [len(b) for b in c.batches]==[2,2,1]


def test_no_premature_registration(storage,hierarchy,monkeypatch):
 c=Collection();original=c.add
 def add(**kwargs):
  assert not db.list_materials()
  original(**kwargs)
 c.add=add
 monkeypatch.setattr(material_service,'chunk_text',lambda text:['x']*9)
 result=material_service.upload_material(b'synthetic','notes.pdf',hierarchy,uploads=storage[0],vectors=Adapter(c),extractor=lambda path:'x')
 assert result['success'] and len(db.list_materials())==1

@pytest.mark.parametrize('value',['0','-1','bad','5001'])
def test_invalid_configuration(monkeypatch,value):
 from config import ConfigurationError
 monkeypatch.setenv('EDUAGENT_INDEX_BATCH_SIZE',value)
 with pytest.raises(ConfigurationError):insert_chunks(Collection(),['a'],['b'],{})


def test_web_and_default_adapter_share_batching(monkeypatch):
 import vector_store
 from application.runtime import ConfiguredVectors
 c=Collection();monkeypatch.setattr(vector_store,'get_collection',lambda *args:c)
 ConfiguredVectors('synthetic').add_material_chunks(list('abcdef'),['x']*6,{})
 vector_store.add_material_chunks(list('ghijkl'),['y']*6,{},collection=c)
 assert [len(b) for b in c.batches]==[4,2,4,2]


def test_batch_rejection_classification_and_no_exception_message(caplog):
 c=Collection()
 def reject(**kwargs):raise RuntimeError('Batch size exceeds maximum: PRIVATE text /private/owner')
 c.add=reject
 with caplog.at_level(logging.INFO,logger='eduagent.indexing'):
  with diagnostic_scope():
   with pytest.raises(RuntimeError):insert_chunks(c,['a'],['PRIVATE document'],{})
   observe(failed=True)
 assert 'batch_size_rejection' in caplog.text and 'PRIVATE' not in caplog.text and '/private/' not in caplog.text


def test_missing_capability_conservative_fallback(monkeypatch):
 c=Collection();c._client=object()
 insert_chunks(c,[str(i) for i in range(101)],['synthetic']*101,{})
 assert [len(b) for b in c.batches]==[100,1]


def test_success_aggregate_diagnostics(storage,hierarchy,caplog):
 with caplog.at_level(logging.INFO,logger='eduagent.indexing'):
  out=material_service.upload_material(b'synthetic','secret.pdf',hierarchy,uploads=storage[0],vectors=Adapter(Collection()),extractor=lambda path:'PRIVATE '*400)
 assert out['success']
 for field in ('chunk_count','extracted_characters','maximum_batch_size','attempted_batch_size','inserted_batches','duration_seconds'):
  assert field in caplog.text
 assert 'PRIVATE' not in caplog.text and 'secret.pdf' not in caplog.text
