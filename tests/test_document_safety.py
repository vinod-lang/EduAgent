"""Bounded document safety only; providers mocked, no runtime storage or live AI."""
from dataclasses import replace
from unittest.mock import Mock
import pytest
import document_studio as studio
from document_models import DocumentDraft,DocumentRequest,DocumentError,DocumentVersions
from document_facts import fact
from document_quality import validate_quality
from structured_generation import DocumentQualityFailure
from generation_trace import development_trace

INSTRUCTION='Draft a letter to the Dean requesting financial approval for organizing a fresher party for first-year students.'
BODY=('I respectfully request financial approval for a fresher party for first-year students.','The gathering would help students become acquainted and build a sense of community. Subject to approval, the event may be scheduled after administrative arrangements are finalized.','Kindly consider this request. Additional budgetary details can be provided separately if required.')
def draft(body=BODY,**kwargs):return DocumentDraft('official_letter',salutation='Dear Dean,',closing='Respectfully,',body=body,**kwargs)
def request(**kwargs):return DocumentRequest('official_letter',INSTRUCTION,tone='Detailed Official',**kwargs)

@pytest.mark.parametrize('text',[
 'The party is scheduled to take place on the evening of [specific date].',
 'The event will be held at [venue].','The date is TBD.',
 'Please quote [reference number].','The amount is [amount].',
 'The event is on <date>.','The date is {{date}}.',
 'Please [insert the institution name here].',
])
@pytest.mark.parametrize('workflow',['generation','refinement'])
def test_unresolved_embedded_placeholders_rejected(monkeypatch,text,workflow):
 monkeypatch.setattr(studio.ai_provider,'generate_chat',Mock(return_value=draft((text,)).to_json()))
 with pytest.raises(DocumentError) as error:
  studio.generate_draft(request(),approved_preferences=()) if workflow=='generation' else studio.refine_draft(draft(),'Make this more detailed and professional.')
 assert error.value.generation_diagnostic.category=='DOCUMENT_QUALITY_FAILED'

@pytest.mark.parametrize('text',[
 'The event will be held on 10 October 2026.',
 'We request an allocation of ₹75000.',
 "The party will proceed with all expenses covered by the university's annual budget for student events.",
 'I have already prepared a detailed budget and a plan for the event, which I will attach for your review.',
 'We have attached the detailed report.',
 'Reference number: FRESH/2026/001.',
 'Approval has been granted.',
])
@pytest.mark.parametrize('workflow',['generation','refinement'])
def test_unsupported_explicit_assertions_rejected(monkeypatch,text,workflow):
 monkeypatch.setattr(studio.ai_provider,'generate_chat',Mock(return_value=draft((text,)).to_json()))
 previous=DocumentVersions.generated(draft())
 with pytest.raises(DocumentError) as error:
  studio.generate_draft(request(),approved_preferences=()) if workflow=='generation' else studio.refine_draft(previous.current,'Make this more detailed and professional.')
 assert error.value.generation_diagnostic.category=='FACT_PRESERVATION_FAILED'
 assert previous.current.body==BODY and len(previous.history)==1

@pytest.mark.parametrize('body',[
 BODY,
 ('We respectfully seek consideration of the proposal [for first-year students].','Any additional details needed for approval can be provided separately.'),
 ('Subject to approval, the necessary financial arrangements can be processed under applicable institutional procedures.','The gathering could encourage a sense of community.'),
])
@pytest.mark.parametrize('workflow',['generation','refinement'])
def test_professional_conditional_prose_and_legitimate_brackets_accepted(monkeypatch,body,workflow):
 provider=Mock(return_value=draft(body).to_json());monkeypatch.setattr(studio.ai_provider,'generate_chat',provider)
 value=studio.generate_draft(request(),approved_preferences=()) if workflow=='generation' else studio.refine_draft(draft(),'Make this more detailed and professional.')
 assert value.body==body and value.date==value.reference_number==value.recipient==''
 prompt=provider.call_args.kwargs['messages'][0]['content']
 assert 'FACTUAL RESTRAINT IS NOT PROSE RESTRAINT' in prompt
 assert 'funding sources' in prompt and 'prepared attachments' in prompt and 'unresolved placeholders' in prompt


def test_supplied_date_amount_reference_generation_and_refinement(monkeypatch):
 req=request(date='10 October 2026',reference_number='SYN/2026/01',additional_context='The authorized amount is ₹2500.')
 candidate=draft(('The event is on 10 October 2026. The proposed amount is ₹2500. Reference number: SYN/2026/01.',),date=req.date,reference_number=req.reference_number)
 monkeypatch.setattr(studio.ai_provider,'generate_chat',Mock(return_value=candidate.to_json()))
 generated=studio.generate_draft(req,approved_preferences=())
 assert generated.body==candidate.body
 assert studio.refine_draft(generated,'Make this more detailed and professional.').body==candidate.body


@pytest.mark.parametrize('claim',[
 'I have already prepared a detailed budget and a plan for the event.',
 "All expenses covered by the university's annual budget for student events.",
])
def test_explicitly_supplied_assertions_remain_usable(monkeypatch,claim):
 candidate=draft((claim,'Please consider the financial approval request.'))
 monkeypatch.setattr(studio.ai_provider,'generate_chat',Mock(return_value=candidate.to_json()))
 assert studio.generate_draft(request(additional_context=claim),approved_preferences=()).body==candidate.body
 assert studio.refine_draft(candidate,'Make this more detailed and professional.').body==candidate.body


def test_confirmed_structured_contradiction_still_rejected(monkeypatch):
 current=draft(date='10 October 2026');current=replace(current,fact_expectations=(fact('date',current.date),))
 monkeypatch.setattr(studio.ai_provider,'generate_chat',Mock(return_value=replace(current,date='12 October 2026').to_json()))
 with pytest.raises(DocumentError):studio.refine_draft(current,'Make this more detailed and professional.')


def test_explicit_wording_edit_cannot_bypass_factual_safety(monkeypatch):
 monkeypatch.setattr(studio.ai_provider,'generate_chat',Mock(return_value=draft(('We have attached the detailed report.',)).to_json()))
 with pytest.raises(DocumentError):studio.refine_draft(draft(),'Update the wording to be more professional.')


def test_placeholder_in_metadata_rejected():
 with pytest.raises(DocumentQualityFailure):validate_quality(draft(title='Event on [specific date]'))


def test_safe_development_trace_still_reports_rejection_without_content(monkeypatch,capsys):
 text='The PRIVATE_INSTITUTION event will take place on [specific date].'
 monkeypatch.setattr(studio.ai_provider,'generate_chat',Mock(return_value=draft((text,)).to_json()))
 with development_trace(True,'DOC_GEN',document_type='official_letter'):
  with pytest.raises(DocumentError):studio.generate_draft(request(),approved_preferences=())
 logs=capsys.readouterr().out
 assert 'quality=fail' in logs and 'failure_rule=placeholder' in logs
 assert 'PRIVATE_INSTITUTION' not in logs and text not in logs and INSTRUCTION not in logs
