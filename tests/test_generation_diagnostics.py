import json
from dataclasses import asdict
from unittest.mock import Mock
import pytest
import httpx
import ai_provider
from structured_generation import Failure,StructuredGenerationResult
from generation_diagnostics import *

@pytest.mark.parametrize('category',list(Failure))
def test_all_categories_private_and_actionable(category):
    d=failed(category,2)
    assert d.status=='rejected' and d.category==category.value and not d.saved
    assert d.attempts_used==2 and d.professor_message and d.suggested_action
    text=json.dumps(asdict(d))
    for secret in ('SECRET','/Users/','Traceback','student_id','system prompt','schema internals'):
        assert secret not in text

@pytest.mark.parametrize('category',list(Failure))
def test_structured_error_attaches_safe_category(category):
    result=StructuredGenerationResult(None,category,2,category)
    with pytest.raises((ValueError,ai_provider.AIProviderError)) as error:result.require(ValueError,'synthetic result')
    assert from_error(error.value)==failed(category,2)

@pytest.mark.parametrize('error',[ValueError('PRIVATE student SYN001 marks 33'),ai_provider.AIProviderError('SECRET /private/file')])
def test_error_mapping_ignores_exception_payload(error):
    text=str(from_error(error))
    for private in ('PRIVATE','SECRET','SYN001','/private/file','33'):assert private not in text

def test_timeout_mapping():
    error=ai_provider.AIConnectionError('PRIVATE');error.__cause__=httpx.ReadTimeout('PRIVATE')
    assert from_error(error).category=='TIMEOUT'

def test_evidence_mapping():
    from assessment_spec import NoAssessmentEvidence
    assert from_error(NoAssessmentEvidence('PRIVATE')).category=='INSUFFICIENT_EVIDENCE'

def test_success_not_accuracy_claim():
    d=validated()
    assert 'review' in d.professor_message and 'Factually correct' not in str(d)
    assert clarification().status=='clarification'

def test_annotation_only_safe_metadata():
    from document_models import DocumentDraft
    d=annotate(DocumentDraft('notice',body=('PRIVATE CONTENT',)),'document',2)
    assert 'PRIVATE' not in str(asdict(d.provenance))
    assert 'provenance' not in d.to_dict()
