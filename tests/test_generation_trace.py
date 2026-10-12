"""Terminal trace contracts only. Mock providers, isolated API fixtures, no live AI."""
import json
from unittest.mock import Mock
from dataclasses import replace
import pytest
import ai_provider
from generation_trace import development_trace,event,stage,assessment_checks
from structured_generation import generate_structured,Failure
from structured_contracts import document_schema
from document_models import DocumentRequest,DocumentDraft,DocumentError
from document_studio import generate_draft
from assessment_fixtures import spec,evidence,output
from test_api import web,client
from test_security import secured,services

REQUEST=DocumentRequest('official_letter','Request financial approval.',tone='Detailed Official')
PRIVATE='PRIVATE_STUDENT_PROMPT /private/path https://secret.example credentials'
def draft(**kwargs):return DocumentDraft('official_letter',body=('Please consider this request.',),**kwargs)

@pytest.mark.parametrize('enabled',[False,True])
def test_scope_mode_gate_and_no_context_leak(enabled,capsys):
 with development_trace(enabled,'DOC_GEN',document_type='official_letter'):
  stage('parse');event(prompt=PRIVATE,model=PRIVATE,failure_field=PRIVATE,failure_rule=PRIVATE,expected=PRIVATE,actual=PRIVATE)
 output=capsys.readouterr().out
 assert bool(output)==enabled and PRIVATE not in output
 stage('parse',False);assert capsys.readouterr().out==''

@pytest.mark.parametrize('case,category,rule,field',[
 ('recipient',Failure.FACT_PRESERVATION_FAILED,'protected_fact_changed','recipient'),
 ('quality',Failure.DOCUMENT_QUALITY_FAILED,'incomplete_sentence','body'),
 ('amount',Failure.FACT_PRESERVATION_FAILED,'unsupported_factual_value','body'),
 ('parse',Failure.INVALID_JSON,'structured_output_invalid',None),
 ('schema',Failure.SCHEMA_INVALID,'type','body'),
 ('provider',Failure.PROVIDER_ERROR,'provider_failure',None),
])
def test_safe_document_stage_failure(case,category,rule,field,monkeypatch,capsys):
 candidate=draft().to_dict()
 if case=='recipient':candidate['recipient']=PRIVATE
 elif case=='quality':candidate['body']=['The budget is']
 elif case=='amount':candidate['body']=['The budget is ₹75000.']
 elif case=='schema':candidate['body']=PRIVATE
 provider=Mock(return_value=PRIVATE if case=='parse' else json.dumps(candidate))
 if case=='provider':provider.side_effect=ai_provider.AIConnectionError(PRIVATE)
 monkeypatch.setattr(ai_provider,'generate_chat',provider)
 with development_trace(True,'DOC_GEN',document_type='official_letter'):
  with pytest.raises((DocumentError,ai_provider.AIProviderError)) as error:generate_draft(REQUEST,approved_preferences=())
 assert error.value.generation_diagnostic.category==category.value
 logs=capsys.readouterr().out
 assert '[DOC_GEN]' in logs and f'failure_code={category.value}' in logs and f'failure_rule={rule}' in logs
 if field:assert f'failure_field={field}' in logs
 assert PRIVATE not in logs and '75000' not in logs and 'Please consider' not in logs
 assert provider.call_count==(2 if case=='amount' else 1)


def test_success_stages_and_model_without_network(monkeypatch,capsys):
 monkeypatch.setattr(ai_provider,'generate_chat',Mock(return_value=draft().to_json()))
 with development_trace(True,'DOC_GEN',document_type='official_letter'):assert generate_draft(REQUEST,approved_preferences=()).body==draft().body
 logs=capsys.readouterr().out
 for status in ('provider_completed=pass','parse=pass','schema=pass','quality=pass','fact_validation=pass','product_validation=pass','failure_code=NONE'):assert status in logs
 assert 'model=' in logs and 'elapsed_seconds=' in logs


@pytest.mark.parametrize('field,stage_name', [('marks','marks_validation'),('difficulty','difficulty_validation'),('bloom_level','bloom_validation'),('evidence_ids','evidence_validation'),('question_text','duplicate_validation')])
def test_assessment_observation_has_only_safe_counts(field,stage_name,capsys):
 data=output();data['questions'][0][field]=99 if field=='marks' else [PRIVATE] if field=='evidence_ids' else data['questions'][1]['question_text'] if field=='question_text' else PRIVATE
 with development_trace(True,'ASSESSMENT_GEN',question_count=2,target_marks=5):assessment_checks(data,spec(),evidence())
 logs=capsys.readouterr().out
 assert stage_name+'=fail' in logs and PRIVATE not in logs and 'Synthetic question' not in logs


def test_assessment_schema_slot_trace_keeps_error_mapping(monkeypatch,capsys):
 from structured_contracts import assessment_schema
 data=output();data['questions'][0]['marks']=99
 monkeypatch.setattr(ai_provider,'generate_chat',Mock(return_value=json.dumps(data)))
 with development_trace(True,'ASSESSMENT_GEN',question_count=2,target_marks=5):
  result=generate_structured([{'role':'user','content':PRIVATE}],assessment_schema(spec(),evidence()),lambda raw:None,trace_observer=lambda data:assessment_checks(data,spec(),evidence()))
 assert result.failure==Failure.PRODUCT_VALIDATION_FAILED
 logs=capsys.readouterr().out;assert 'schema=fail' in logs and 'failure_field=marks' in logs and 'expected=3 actual=99' in logs and PRIVATE not in logs


def test_actual_document_api_uses_development_gate(web,monkeypatch,capsys):
 monkeypatch.setattr(ai_provider,'generate_chat',Mock(return_value=draft(recipient=PRIVATE).to_json()))
 c=client(web);response=c.post('/api/v1/documents/generate',json={'document_type':'official_letter','description':'Request financial approval.'})
 assert response.status_code==422 and response.json()['error']['diagnostic']['category']=='FACT_PRESERVATION_FAILED'
 logs=capsys.readouterr().out;assert 'request_received=true document_type=official_letter' in logs or 'request_received=true' in logs
 assert 'failure_field=recipient' in logs and PRIVATE not in logs and PRIVATE not in response.text
 # Keep the authenticated isolated session, but use actual production settings gate.
 web.state.settings=replace(web.state.settings,mode='production',dev_auth_enabled=False)
 response=c.post('/api/v1/documents/generate',json={'document_type':'official_letter','description':'Request financial approval.'})
 assert response.status_code==401 and capsys.readouterr().out==''


def test_isolated_request_contexts(capsys):
 from concurrent.futures import ThreadPoolExecutor
 def run(kind):
  with development_trace(True,kind):stage('parse')
 with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(run,('DOC_GEN','ASSESSMENT_GEN')))
 logs=capsys.readouterr().out;assert '[DOC_GEN] parse=pass' in logs and '[ASSESSMENT_GEN] parse=pass' in logs
 event(failure_rule='provider_failure');assert capsys.readouterr().out==''
