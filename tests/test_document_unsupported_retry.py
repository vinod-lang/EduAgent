"""Unsupported assertions share the existing two-attempt document budget."""
from unittest.mock import Mock
import pytest
import ai_provider
import document_studio as studio
from document_models import DocumentError
from tests.test_document_safety import draft,request,BODY
from generation_trace import development_trace
BAD=('All expenses will be covered by the university annual budget.',)
PLACEHOLDER=('Scheduled on [specific date].',)
@pytest.mark.parametrize('workflow',['draft','refine'])
@pytest.mark.parametrize('first,second,category',[(BAD,BODY,None),(BAD,BAD,'FACT_PRESERVATION_FAILED'),(BAD,PLACEHOLDER,'DOCUMENT_QUALITY_FAILED'),(PLACEHOLDER,BAD,'FACT_PRESERVATION_FAILED')])
def test_shared_correction(monkeypatch,capsys,workflow,first,second,category):
 rejected=draft(first).to_json()
 provider=Mock(side_effect=[rejected,draft(second).to_json()]);monkeypatch.setattr(ai_provider,'generate_chat',provider)
 with development_trace(True,'DOC_GEN',document_type='official_letter'):
  if category:
   with pytest.raises(DocumentError) as error:run(workflow)
   assert error.value.generation_diagnostic.category==category
  else:assert run(workflow).body==BODY
 assert provider.call_count==2
 assert rejected not in str(provider.call_args.kwargs['messages'])
 trace=capsys.readouterr().out
 assert 'corrective_retry=started reason='+('placeholder' if first==PLACEHOLDER else 'unsupported_factual_value') in trace
 assert 'corrective_retry='+('fail' if category else 'pass') in trace
 assert 'university annual budget' not in trace

def run(workflow):
 return studio.generate_draft(request(),approved_preferences=()) if workflow=='draft' else studio.refine_draft(draft(),'Make this more formal.')

@pytest.mark.parametrize('workflow',['draft','refine'])
def test_valid_one_call(monkeypatch,workflow):
 provider=Mock(return_value=draft().to_json());monkeypatch.setattr(ai_provider,'generate_chat',provider)
 assert run(workflow).body==BODY
 assert provider.call_count==1

@pytest.mark.parametrize('workflow',['draft','refine'])
def test_supplied_date_mutation_not_repairable(monkeypatch,workflow):
 provider=Mock(return_value=draft(('Scheduled on 12 October 2026.',),date='12 October 2026').to_json());monkeypatch.setattr(ai_provider,'generate_chat',provider)
 with pytest.raises(DocumentError):
  if workflow=='draft':studio.generate_draft(request(date='10 October 2026'),approved_preferences=())
  else:studio.refine_draft(draft(date='10 October 2026'),'Make this more formal.')
 assert provider.call_count==1
