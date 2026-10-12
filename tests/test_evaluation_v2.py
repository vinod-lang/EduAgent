"""Synthetic fixtures/mocks only; no live models or production storage."""
import json
from dataclasses import replace
from unittest.mock import Mock,MagicMock
from pathlib import Path
import pytest
import ai_provider
from benchmarks.cases_v2 import cases_v2,load_v2
from benchmarks.contracts_v2 import extract_single_object,response_schema
from benchmarks.failures_v2 import categorize
from benchmarks.evaluation_v2 import facts,evaluate,summarize,decision,run,percentile95

@pytest.fixture(scope='module')
def cases():return cases_v2()
def get(cases,task):return next(c for c in cases if c.category==task)

def test_expanded_sizes_and_splits(cases):
    from collections import Counter
    assert Counter(c.category for c in cases)=={'planner':30,'assessment':20,'document':20,'qa':16}
    data=load_v2();assert len(data['corpus'])==60 and len(data['retrieval'])==48
    assert sum(q['split']=='calibration' for q in data['retrieval'])==24
    assert sum(q['split']=='test' for q in data['retrieval'])==24
    assert len({r['id'] for r in data['retrieval']})==48

def test_build13_compatibility():
    from benchmarks.cases import load_fixture,generative_cases
    assert load_fixture()['version']=='synthetic-v1' and len(generative_cases())==13

def test_no_real_data_or_store_reads(monkeypatch):
    import db,vector_store
    monkeypatch.setattr(db,'material_connection',Mock(side_effect=AssertionError('No SQLite')))
    monkeypatch.setattr(vector_store,'get_collection',Mock(side_effect=AssertionError('No Chroma')))
    assert len(cases_v2())==86
    text=Path('benchmarks/fixtures/synthetic_v2.json').read_text()
    assert 'Entirely synthetic' in text and 'student_id' not in text and 'attendance_percent' not in text

@pytest.mark.parametrize('raw',['{}','```json\n{}\n```','Here is the result:\n{}'])
def test_single_extraction(raw):assert extract_single_object(raw)=='{}'
@pytest.mark.parametrize('raw',['{} {}','[]','null','Run shell: {}','```python\nprint(1)\n```','{broken','prefix {} suffix','{"x":1,"x":2}'])
def test_ambiguous_extraction_rejected(raw):
    with pytest.raises(ValueError):extract_single_object(raw)

@pytest.mark.parametrize('task',['planner','assessment','document'])
def test_schema_is_closed_object(cases,task):
    schema=response_schema(get(cases,task));assert schema['type']=='object' and schema['additionalProperties'] is False
    assert set(schema['required'])==set(schema['properties'])

def test_provider_format_optin(monkeypatch):
    client=MagicMock();client.__enter__.return_value=client;client.chat.return_value={'message':{'content':'{}'}}
    monkeypatch.setattr(ai_provider.ollama,'Client',Mock(return_value=client))
    client.list.return_value={'models':[{'model':ai_provider.get_default_model_name()}]}
    schema={'type':'object','properties':{}}
    ai_provider.generate_chat_measured([{'role':'user','content':'Synthetic'}],response_format=schema)
    assert client.chat.call_args.kwargs['format']==schema
    client.reset_mock();ai_provider.generate_chat([{'role':'user','content':'Synthetic'}]);assert 'format' not in client.chat.call_args.kwargs
@pytest.mark.parametrize('schema',['json',[],{}, {'type':'array'},{'type':'object','bad':float('nan')}])
def test_bad_provider_format_controlled(schema):
    with pytest.raises(ai_provider.AIProviderError):ai_provider.generate_chat_measured([{'role':'user','content':'Synthetic'}],response_format=schema)

@pytest.mark.parametrize('raw,expected',[('bad','invalid_json'),('[]','wrong_type'),('{}','missing_required_fields'),('{"actions":[],"unsupported":true,"extra":1}','extra_forbidden_fields'),('{"actions":[{"action_id":"a","action_type":"SHELL","parameters":{},"depends_on":[]}],"unsupported":false}','invalid_action_type'),('{"actions":[{"action_id":"a","action_type":"ASK_KNOWLEDGE","parameters":{},"depends_on":["b"]}],"unsupported":false}','invalid_dependency')])
def test_failure_labels(cases,raw,expected):assert expected in categorize(get(cases,'planner'),raw)

def test_truncation_requires_cap_evidence(cases):
    c=get(cases,'planner');assert 'truncated_output' not in categorize(c,'bad')
    assert 'truncated_output' in categorize(c,'bad',output_tokens=10,token_limit=10)

def test_document_facts_independent_of_metadata(cases):
    from document_models import DocumentDraft
    c=get(cases,'document');draft=DocumentDraft(c.expected.document_type,date=c.expected.date,reference_number=c.expected.reference_number,recipient=c.expected.recipient,body=(c.expected.description,))
    assert facts(c,draft.to_json())['facts_complete']==1
    incomplete=replace(draft,body=('A workshop is planned.',));assert facts(c,incomplete.to_json())['facts_complete']==0
    extra=replace(draft,body=(c.expected.description+' An extra fee is 99999.',));assert facts(c,extra.to_json())['unsupported_numeric_count']==1

def test_failure_does_not_remove_attempt(tmp_path,cases):
    call=Mock(side_effect=ai_provider.AIConnectionError('Unavailable'))
    result=run(['llama3.2:3b'],['schema_constrained'],tmp_path,call=call,selected=[get(cases,'planner')])
    row=result['summary'][0];assert row['attempts']==row['provider_failures']==1
    assert row['metrics']['schema_valid']=={'sum':0,'attempts':1}
    assert call.call_count==1

def test_report_subjective_columns_blank(tmp_path,cases):
    call=Mock(return_value=ai_provider.ChatMeasurement('{"actions":[],"unsupported":true}',.01,None,None,None,None,None))
    result=run(['llama3.2:3b'],['prompt_only'],tmp_path,call=call,selected=[get(cases,'planner')])
    import csv
    row=next(csv.DictReader((tmp_path/'human_review.csv').open()))
    assert row['correctness_0_2']==row['hallucination_flag']==''
    assert result['decision']['outcome']=='F'

def test_p95_requires_coverage():
    assert percentile95([1,2]) is None and percentile95(list(range(1,21)))==19

def test_product_validators_unmodified(cases):
    from assistant_models import parse_plan
    with pytest.raises(ValueError):parse_plan('{"actions":[],"unsupported":true,"extra":1}','Synthetic')

def test_calibration_heldout_excluded():
    from benchmarks.retrieval import calibrate_threshold
    rows=[dict(split='calibration',relevant_ids=['a'],candidates=[{'id':'a','distance':.2}]),dict(split='calibration',relevant_ids=[],candidates=[{'id':'b','distance':.8}])]
    a=calibrate_threshold(rows);b=calibrate_threshold(rows+[dict(split='test',relevant_ids=[],candidates=[{'id':'x','distance':0}])]);assert a==b

def test_decision_no_automatic_promotion():assert decision([])['production_change'] is False


def test_timeout_is_explicit_and_not_retried(tmp_path,cases):
    error=ai_provider.AIConnectionError('Synthetic timeout');error.__cause__=TimeoutError()
    call=Mock(side_effect=error)
    result=run(['llama3.2:3b'],['prompt_only'],tmp_path,call=call,selected=[get(cases,'document')])
    assert result['rows'][0]['status']=='timeout' and call.call_count==1
    assert result['summary'][0]['metrics']['facts_complete']=={'sum':0,'attempts':1}

def test_irrelevant_approved_preference_is_filtered(monkeypatch):
    from document_preferences import Preference,relevant_preferences
    from document_models import DocumentRequest
    irrelevant=Preference('synthetic','tone_style','Use ceremonial language.','document_type','official_letter')
    relevant=Preference('synthetic2','tone_style','Use two short paragraphs.','document_type','notice')
    monkeypatch.setattr('document_preferences.list_preferences',lambda:(irrelevant,relevant))
    assert relevant_preferences(DocumentRequest('notice','Synthetic tutorial'))==(relevant,)

def test_fact_template_priority_is_in_actual_prompt(cases):
    prompt=get(cases,'document').messages[0]['content']
    assert 'Facts and current instructions override style' in prompt
    assert 'templates override conflicting layout preferences' in prompt

def test_retrieval_v2_split_has_negatives_and_distinct_text():
    data=json.loads(Path('benchmarks/fixtures/retrieval_synthetic_v2.json').read_text())
    calibration=[q for q in data['retrieval'] if q['split']=='calibration'];test=[q for q in data['retrieval'] if q['split']=='test']
    assert len(calibration)==len(test)==24
    assert sum(not q['relevant_ids'] for q in calibration)==sum(not q['relevant_ids'] for q in test)==3
    positive_a={q['question'] for q in calibration if q['relevant_ids']};positive_b={q['question'] for q in test if q['relevant_ids']}
    assert not positive_a&positive_b


def test_unavailable_model_is_controlled_result(tmp_path,cases):
    cause=Exception('Synthetic missing model');cause.status_code=404
    error=ai_provider.AIResponseError('Unavailable');error.__cause__=cause
    call=Mock(side_effect=error)
    result=run(['llama3.2:3b'],['prompt_only'],tmp_path,call=call,selected=[get(cases,'planner')])
    assert result['rows'][0]['status']=='unavailable' and call.call_count==1


def test_student_filter_uses_local_route_not_ai(monkeypatch):
    from assistant_planner import plan_request
    provider=Mock(side_effect=AssertionError('Student filter must be local'))
    monkeypatch.setattr(ai_provider,'generate_chat',provider)
    plan=plan_request('Show all students')
    assert plan.actions[0].action_type=='ANALYZE_STUDENTS'
    provider.assert_not_called()

def test_synthetic_identifiable_request_never_reaches_ai(monkeypatch):
    from assistant_planner import plan_request
    from assistant_services import ExecutionContext
    from types import SimpleNamespace
    import pandas as pd
    provider=Mock(side_effect=AssertionError('No student data to AI'))
    monkeypatch.setattr(ai_provider,'generate_chat',provider)
    context=ExecutionContext(student_dataset=SimpleNamespace(frame=pd.DataFrame({'student_name':['Synthetic Learner V2']})))
    with pytest.raises(ValueError):plan_request('Draft advice for Synthetic Learner V2',context)
    provider.assert_not_called()


def test_supplementary_scope_and_preference_cases():
    from benchmarks.cases_v2 import supplementary_cases
    cases=supplementary_cases();assert len(cases)==11
    unit=next(c for c in cases if c.case_id.endswith('multiunit'));assert len(unit.expected['spec'].scope.units)==2
    material=next(c for c in cases if c.case_id.endswith('multimaterial'));assert len(material.expected['spec'].scope.material_ids)==2
    irrelevant=next(c for c in cases if c.case_id.endswith('irrelevant'));payload=json.loads(irrelevant.messages[-1]['content']);assert payload['approved_style_guidance']==[]

def test_insufficient_evidence_avoids_assessment_generation(monkeypatch):
    from assessment_studio import generate_assessment
    from benchmarks.cases import assessment_spec
    from assessment_spec import NoAssessmentEvidence
    from retrieval import RetrievalResult,RetrievalDiagnostics
    empty=RetrievalResult((),RetrievalDiagnostics(15,0,0,0,0,0,{},'cosine',.65))
    monkeypatch.setattr('assessment_studio.retrieve_evidence',lambda *a,**k:empty)
    provider=Mock(side_effect=AssertionError('No generation without evidence'));monkeypatch.setattr(ai_provider,'generate_chat',provider)
    with pytest.raises(NoAssessmentEvidence):generate_assessment(assessment_spec())
    provider.assert_not_called()


def test_strict_contract_schema_preserves_validation_boundaries(cases):
    from benchmarks.contracts_v2 import strict_contract_schema
    assessment=strict_contract_schema(get(cases,'assessment'))['properties']['questions']
    assert assessment['items'] is False and len(assessment['prefixItems'])==2
    assert set(assessment['prefixItems'][0]['properties']['options']['required'])==set('ABCD')
    document=strict_contract_schema(get(cases,'document'))['properties']
    assert document['date']=={'const':get(cases,'document').expected.date} and document['salutation']=={'const':''}
    planner=strict_contract_schema(get(cases,'planner'))
    assert planner['oneOf'][0]['properties']['actions']['maxItems']==0
    assert planner['oneOf'][1]['properties']['actions']['minItems']==1


def test_offline_recovery_preserves_source_and_never_calls_model(tmp_path,cases,monkeypatch):
    from benchmarks.evaluation_v2 import finalize_existing
    case=get(cases,'planner');raw='{"actions":[],"unsupported":true}'
    row=dict(model='llama3.2:3b',mode='prompt_only',task='planner',case_id=case.case_id,status='ok',metrics={'schema_valid':1},failure_categories=[],latency_seconds=1,measurement={'text':raw})
    source=tmp_path/'progress.json';source.write_text(json.dumps([row]));original=source.read_bytes()
    provider=Mock(side_effect=AssertionError('No live calls'));monkeypatch.setattr(ai_provider,'generate_chat_measured',provider)
    result=finalize_existing(source,tmp_path/'out')
    assert source.read_bytes()==original and result['additional_live_calls']==0 and result['rows'][0]['measurement']['text']==raw
    assert result['rows'][0]['original_metrics']==row['metrics']
    assert 'policy_refusal_failure' not in result['rows'][0]['failure_categories']
    provider.assert_not_called()

def test_gate_rejects_schema_success_without_exact_planning():
    groups=[dict(model='m',mode='schema_constrained',task='planner',attempts=30,provider_failures=0,metrics={'schema_valid':{'sum':30,'attempts':30},'exact_plan_success':{'sum':15,'attempts':30},'policy_valid':{'sum':7,'attempts':7}})]
    result=decision(groups);assert not result['checks'][0]['deterministic_pass']
    assert result['production_change'] is False and result['outcome']=='F'

def test_recovery_rejects_production_path():
    from benchmarks.evaluation_v2 import finalize_existing
    with pytest.raises(ValueError):finalize_existing(Path('eduagent.db'),Path('benchmarks/results/x'))


def test_plain_text_facts_do_not_become_structured_success(cases):
    case=get(cases,'document');result=facts(case,case.expected.description)
    assert result['numeric_facts_retained']==result['dates_retained']==result['references_retained']==result['named_entities_retained']==1
    assert result['structured_body_available']==result['facts_complete']==0
    assert result['preference_followed'] is None

def test_mcq_score_not_applicable_to_descriptive_only(cases):
    case=next(c for c in cases if c.category=='assessment' and c.expected['spec'].question_types['MCQ']==0)
    assert evaluate(case,'bad')['mcq_structure_valid'] is None


def test_mcq_and_key_failure_categories_are_separate(cases):
    from benchmarks.cases import reference_assessment
    case=get(cases,'assessment');data=json.loads(reference_assessment(case.expected['spec']))
    data['questions'][0]['options']={'A':'Only one option'};data['questions'][0]['correct_answer']='Z'
    labels=categorize(case,json.dumps(data));assert 'invalid_mcq_structure' in labels and 'invalid_answer_key' in labels
