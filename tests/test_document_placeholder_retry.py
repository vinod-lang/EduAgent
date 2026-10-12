"""Deterministic two-call document correction budget; no live inference."""
from unittest.mock import Mock
import pytest
import ai_provider
import document_studio as studio
from document_models import DocumentError
from tests.test_document_safety import draft,request,BODY
from generation_trace import development_trace

@pytest.mark.parametrize('workflow',['draft','refine'])
@pytest.mark.parametrize('second,category',[(BODY,None),(('Scheduled on [specific date].',),'DOCUMENT_QUALITY_FAILED'),(('Scheduled on 15 October 2026.',),'FACT_PRESERVATION_FAILED')])
def test_placeholder_correction(monkeypatch,workflow,second,category,capsys):
 first=draft(('Scheduled on [specific date].',)).to_json()
 provider=Mock(side_effect=[first,draft(second).to_json()])
 monkeypatch.setattr(ai_provider,'generate_chat',provider)
 with development_trace(True,'DOC_GEN',document_type='official_letter'):
  if category:
   with pytest.raises(DocumentError) as error:run(workflow)
   assert error.value.generation_diagnostic.category==category
  else:
   result=run(workflow)
   assert result.body==BODY and result.provenance.attempts_used==2
 assert provider.call_count==2
 messages=provider.call_args.kwargs['messages']
 assert first not in str(messages)
 assert 'Regenerate the complete document' in messages[-1]['content']
 trace=capsys.readouterr().out
 assert 'generation_attempt=2' in trace and 'corrective_retry=started' in trace
 assert 'corrective_retry='+('fail' if category else 'pass') in trace
 assert '[specific date]' not in trace

def run(workflow,retry=False):
 return studio.generate_draft(request(),approved_preferences=(),retry=retry) if workflow=='draft' else studio.refine_draft(draft(),'Make this more formal.',retry=retry)

@pytest.mark.parametrize('workflow',['draft','refine'])
def test_valid_no_retry(monkeypatch,workflow):
 provider=Mock(return_value=draft().to_json());monkeypatch.setattr(ai_provider,'generate_chat',provider)
 assert run(workflow).body==BODY
 assert provider.call_count==1

@pytest.mark.parametrize('workflow',['draft','refine'])
def test_nonrepairable_fact_failure(monkeypatch,workflow):
 provider=Mock(return_value=draft(('Scheduled on 15 October 2026.',)).to_json());monkeypatch.setattr(ai_provider,'generate_chat',provider)
 with pytest.raises(DocumentError):
  if workflow=='draft':studio.generate_draft(request(date='10 October 2026'),approved_preferences=())
  else:studio.refine_draft(draft(date='10 October 2026'),'Make this more formal.')
 assert provider.call_count==1

@pytest.mark.parametrize('workflow',['draft','refine'])
@pytest.mark.parametrize('initial',['invalid json','schema'])
def test_structural_retry_shares_budget(monkeypatch,workflow,initial):
 if initial=='schema':
  import json
  value=json.loads(draft().to_json());value['body']=17;initial=json.dumps(value)
 provider=Mock(side_effect=[initial,draft(('Scheduled on [specific date].',)).to_json()]);monkeypatch.setattr(ai_provider,'generate_chat',provider)
 with pytest.raises(DocumentError):run(workflow,retry=True)
 assert provider.call_count==2

@pytest.mark.parametrize('workflow',['draft','refine'])
def test_provider_failure_no_retry(monkeypatch,workflow):
 provider=Mock(side_effect=ai_provider.AIConnectionError('private details'));monkeypatch.setattr(ai_provider,'generate_chat',provider)
 with pytest.raises(ai_provider.AIProviderError):run(workflow,retry=True)
 assert provider.call_count==1
