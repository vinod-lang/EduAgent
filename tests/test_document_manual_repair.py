"""Synthetic, mocked document reliability checks. Never use production storage."""
import json,io
from dataclasses import replace
from unittest.mock import Mock
import pytest
from docx import Document
import pdfplumber
import document_studio as studio
from document_models import DocumentRequest,DocumentDraft,DocumentVersions,DocumentError,CATALOG
from document_quality import body_fact_present,validate_quality
from document_facts import fact,enforce
from document_export import document_docx_bytes,document_pdf_bytes

def letter(**kwargs):
    return DocumentDraft('financial_approval',recipient='Dean',salutation='Dear Dean,',body=('I am writing to request financial approval for a welcome event for first-year students.','The proposed event would provide an opportunity for students to become acquainted. Kindly consider this request and advise on the necessary next steps.'),closing='Respectfully,',**kwargs)

@pytest.mark.parametrize('kind',CATALOG)
def test_type_guidance_not_institutional_template(kind):
    text=studio.drafting_guidance(kind)
    assert text and 'NIT' not in text


def test_generated_prose_and_missing_optional_values(monkeypatch):
    request=DocumentRequest('financial_approval','Request financial approval for a welcome event for first-year students.',recipient='Dean')
    chat=Mock(return_value=letter().to_json());monkeypatch.setattr(studio.ai_provider,'generate_chat',chat)
    result=studio.generate_draft(request,approved_preferences=())
    assert result.body==letter().body and result.date==result.reference_number==result.sender==''
    payload=json.loads(chat.call_args.kwargs['messages'][1]['content'])
    assert payload['drafting_guidance'] and 'FACTUAL RESTRAINT IS NOT PROSE RESTRAINT' in chat.call_args.kwargs['messages'][0]['content']

@pytest.mark.parametrize('body',['The event is scheduled to take place on','The budget is','[Insert date]','...','As an AI, I will draft your letter.'])
def test_incomplete_draft_rejected(monkeypatch,body):
    monkeypatch.setattr(studio.ai_provider,'generate_chat',Mock(return_value=replace(letter(),body=(body,)).to_json()))
    with pytest.raises(DocumentError):studio.generate_draft(DocumentRequest('financial_approval','Request welcome event approval.',recipient='Dean'),approved_preferences=())

@pytest.mark.parametrize('body',['The budget is ₹75,000.','The event will be held on 15 October 2026.','The venue is Main Auditorium.','Approval has been granted.'])
def test_unsupported_fact_rejected(monkeypatch,body):
    monkeypatch.setattr(studio.ai_provider,'generate_chat',Mock(return_value=replace(letter(),body=(body,)).to_json()))
    with pytest.raises(DocumentError):studio.generate_draft(DocumentRequest('financial_approval','Request welcome event approval.',recipient='Dean'),approved_preferences=())

@pytest.mark.parametrize('body',['We request approval for the proposed event. The budget of ₹2,500 is submitted for consideration.','The budget is INR 2500. We respectfully seek consideration of the proposed event.'])
def test_refinement_natural_fact_formatting_and_restructure(monkeypatch,body):
    d=replace(letter(),body=('Budget 2500. Request approval.',),fact_expectations=(fact('body','Budget 2500'),fact('recipient','Dean')))
    monkeypatch.setattr(studio.ai_provider,'generate_chat',Mock(return_value=replace(d,body=(body,)).to_json()))
    # Required phrase is supported as a narrow financial fact, not arbitrary synonyms.
    result=studio.refine_draft(d,'Make this longer and more formal.')
    assert result.body==(body,) and result.fact_expectations==d.fact_expectations

@pytest.mark.parametrize('body',['Budget 25000. Request approval.','No budget 2500 is requested.','The budget is 3000.','Budget 2500. The event is on 15 October 2026.'])
def test_bad_refinement_keeps_previous(monkeypatch,body):
    d=replace(letter(),body=('Budget 2500. Request approval.',),fact_expectations=(fact('body','Budget 2500'),))
    versions=DocumentVersions.generated(d)
    monkeypatch.setattr(studio.ai_provider,'generate_chat',Mock(return_value=replace(d,body=(body,)).to_json()))
    with pytest.raises(DocumentError):studio.refine_draft(d,'Make it longer.')
    assert versions.current==d and len(versions.history)==1


def test_structural_number_not_a_confirmed_fact(monkeypatch):
    d=replace(letter(),body=('1. We respectfully request consideration of the proposal.',))
    candidate=replace(d,body=('We respectfully request consideration of this proposal. Thank you for reviewing it.',))
    monkeypatch.setattr(studio.ai_provider,'generate_chat',Mock(return_value=candidate.to_json()))
    assert studio.refine_draft(d,'Remove numbering and improve wording.')==candidate


def test_exports_clean_content_not_reliability_metadata():
    d=replace(letter(),fact_expectations=(fact('recipient','Dean'),))
    doc=Document(io.BytesIO(document_docx_bytes(d)))
    with pdfplumber.open(io.BytesIO(document_pdf_bytes(d))) as pdf:text='\n'.join(p.extract_text() or '' for p in pdf.pages)
    docx='\n'.join(p.text for p in doc.paragraphs)
    for output in (text,docx):
        assert 'Dear Dean,' in output and 'first-year students' in output
        assert d.fact_expectations[0].fact_id not in output and 'response_hash' not in output
