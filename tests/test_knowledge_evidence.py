"""Synthetic textbook-like context; no model or runtime storage."""
from types import SimpleNamespace
import pytest
from retrieval import EvidenceChunk,RetrievalError
from knowledge_evidence import expand_context
from api.presentation import knowledge_evidence
from api.schemas import Answer
from security.retrieval import AuthorizedCollection
from application.errors import ValidationError

class Store:
 configuration={'hnsw':{'space':'cosine'}}
 def __init__(self):self.rows={};self.calls=[]
 def get(self,*,ids,where=None,include=None):
  self.calls.append(where)
  rows=[(i,v) for i,v in self.rows.items() if i in ids]
  return dict(ids=[i for i,v in rows],documents=[v[0] for i,v in rows],metadatas=[v[1] for i,v in rows])

def chunk(index,text='synthetic',material='A'):
 return EvidenceChunk(f'{material}_chunk_{index}',text,.1,material,'synthetic.pdf','C','S','ML','U')

def test_comparison_context_preserves_both_algorithms():
 s=Store();s.rows['A_chunk_1']=('Merge sort requires O(n log n) time.',{'material_id':'A','source':'synthetic.pdf','course':'C'})
 result=expand_context((chunk(0,'Insertion sort requires O(n^2) time.'),),s,{'course':'C'})
 assert [v.chunk_id for v in result]==['A_chunk_0','A_chunk_1']
 assert 'n^2' in result[0].text and 'n log n' in result[1].text
 assert result[1].selection=='adjacent' and result[1].distance is None


def test_boundary_dedup_and_order():
 s=Store();s.rows['A_chunk_1']=('neighbor',{'material_id':'A','source':'synthetic.pdf'})
 result=expand_context((chunk(0),chunk(1,'neighbor'),chunk(2,'different')),s,{})
 assert [v.chunk_id for v in result]==['A_chunk_0','A_chunk_1','A_chunk_2']
 assert len({v.chunk_id for v in result})==3
 assert all('chunk_-1' not in str(call) for call in s.calls)


def test_budget(monkeypatch):
 monkeypatch.setenv('EDUAGENT_KNOWLEDGE_CONTEXT_CHARS','500');s=Store()
 s.rows['A_chunk_1']=('x'*300,{'material_id':'A'})
 result=expand_context((chunk(0,'y'*300),),s,{})
 assert len(result)==1 and sum(len(v.text) for v in result)<=500

@pytest.mark.parametrize('metadata',[{'material_id':'B'},{'material_id':'A','course':'Other'}])
def test_adjacent_cross_boundary_rejected(metadata):
 s=Store();s.rows['A_chunk_1']=('other',metadata)
 with pytest.raises(RetrievalError):expand_context((chunk(0),),s,{'course':'C'})


def test_authorized_exact_reads_defense():
 s=Store();s.rows['A_chunk_1']=('private',{'material_id':'B'})
 wrapper=AuthorizedCollection(['A'],lambda:s)
 with pytest.raises(ValidationError):wrapper.get(ids=['A_chunk_1'],where={'course':'C'},include=['documents','metadatas'])
 assert s.calls[0]=={'$and':[{'material_id':{'$in':['A']}},{'course':'C'}]}


def test_excerpt_api_backward_compatibility():
 result=SimpleNamespace(evidence=(chunk(0,'x'*500),))
 data=knowledge_evidence(result)[0]
 assert data['reference']=='E1' and data['rank']==1 and len(data['excerpt'])==300 and data['page'] is None
 assert data['chunk_id']=='A_chunk_0' and 'distance' not in data
 assert Answer(answer='synthetic',grounded=True,sources=[]).evidence==[]


def test_no_legacy_guessing():
 result=expand_context((EvidenceChunk('filename_chunk_1','x',.1,None),),Store(),{})
 assert len(result)==1
