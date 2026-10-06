"""Synthetic-only benchmark infrastructure; live models never required by pytest."""
import json
from pathlib import Path
from dataclasses import replace
from unittest.mock import Mock
import pytest
import numpy as np
import ai_provider
from benchmarks.cases import load_fixture,generative_cases,reference_assessment
from benchmarks.scoring import score,aggregate,HUMAN
from benchmarks.retrieval import retrieval_metrics,calibrate_threshold,MemoryCollection,evaluate_collection
from benchmarks.runner import run_models
from benchmarks.report import write_report,gate
from benchmarks.models import GENERATIVE,download_gate,RESERVE_BYTES

@pytest.fixture
def cases():return generative_cases()


def by_id(cases,identity):return next(c for c in cases if c.case_id==identity)


def plan_output(case):
    if case.expected.get('unsupported'):return '{"actions":[],"unsupported":true}'
    if case.case_id=='plan_missing':params={'assessment_type':'Quiz'}
    else:
        params=dict(case.expected['expected_parameters'][0]);term=params.pop('question_contains',None)
        if term:params['question']='Explain '+term
    return json.dumps({'unsupported':False,'actions':[{'action_id':'a','action_type':case.expected['expected_actions'][0],'parameters':params,'depends_on':[]}]})


def test_fixture_provenance_and_no_production_reads():
    data=load_fixture();assert data['version']=='synthetic-v1'
    assert len(data['corpus'])==18 and len(data['retrieval'])==15
    text=Path('benchmarks/fixtures/synthetic_v1.json').read_text()
    for token in ('student_name','student_id','attendance_percent','eduagent.db','uploads/'):assert token not in text
    assert 'Entirely synthetic' in data['provenance']


def test_case_prompts_capture_existing_services(cases):
    assert len(cases)==13
    assert 'Follow every slot exactly' in by_id(cases,'assessment_2').messages[0]['content']
    doc=json.loads(by_id(cases,'doc_notice').messages[1]['content'])
    assert doc['approved_style_guidance'][0]['instruction']=='Use at most two short body paragraphs.'
    assert 'ONLY the course material' in by_id(cases,'qa_pca').messages[0]['content']

@pytest.mark.parametrize('identity',['plan_question','plan_document','plan_missing','plan_refusal','plan_privacy'])
def test_planner_scoring(cases,identity):
    case=by_id(cases,identity)
    raw=plan_output(case)
    if identity=='plan_document':
        data=json.loads(raw);data['actions'][0]['parameters']['description']='Synthetic notice';raw=json.dumps(data)
    result=score(case,raw)
    assert result['json_valid']==1 and result['schema_valid']==1
    assert result['actions_correct']==1 and result['clarification_correct']==1

@pytest.mark.parametrize('bad',['invalid','[]','null','{}','{"actions": [],"unsupported": false}','{"actions":[],"unsupported":true,"function":"shell"}'])
def test_malformed_planner_scores_not_crash(cases,bad):
    result=score(by_id(cases,'plan_question'),bad)
    assert result['schema_valid']==0 and result['actions_correct']==0


def test_parameter_loss_detected(cases):
    case=by_id(cases,'plan_question');data=json.loads(plan_output(case));data['actions'][0]['parameters']['filters']['unit']='Wrong'
    assert score(case,json.dumps(data))['parameters_correct']==0


def test_assessment_exact_scoring(cases):
    case=by_id(cases,'assessment_2');result=score(case,reference_assessment(case.expected['spec']))
    assert result['schema_valid']==result['question_count_exact']==result['difficulty_exact']==result['bloom_exact']==result['evidence_refs_valid']==1
    assert result['human_answer_key_correctness']==HUMAN

@pytest.mark.parametrize('mutation',['count','difficulty','bloom','options','evidence','duplicate'])
def test_assessment_failures_measured(cases,mutation):
    case=by_id(cases,'assessment_2');data=json.loads(reference_assessment(case.expected['spec']))
    if mutation=='count':data['questions'].pop()
    if mutation=='difficulty':data['questions'][0]['difficulty']='Hard'
    if mutation=='bloom':data['questions'][0]['bloom_level']='Invented'
    if mutation=='options':data['questions'][0]['options']={'A':'Only one'}
    if mutation=='evidence':data['questions'][0]['evidence_ids']=['E99']
    if mutation=='duplicate':data['questions'][1]['question_text']=data['questions'][0]['question_text']
    assert score(case,json.dumps(data))['schema_valid']==0


def test_document_structural_and_factual_scoring(cases):
    from document_models import DocumentDraft
    case=by_id(cases,'doc_notice');draft=DocumentDraft('notice',date=case.expected.date,body=('Tutorial on 10 October 2026 at 3:00 PM in Fictional Lab 2.',))
    result=score(case,draft.to_json());assert result['schema_valid']==result['supplied_numeric_tokens_present']==1
    assert result['human_professionalism']==HUMAN
    bad=replace(draft,date='Invented');assert score(case,bad.to_json())['factual_fields_preserved']==0

@pytest.mark.parametrize('text,expected',[("I don't have that information in the course material",1),('The tuition fee is 5000.',0)])
def test_abstention_scoring(cases,text,expected):assert score(by_id(cases,'qa_no_evidence_stress'),text)['abstention_correct']==expected


def test_aggregation_failures_not_removed():
    rows=[dict(model='m',category='planner',status='ok',elapsed_seconds=2,scores={'schema_valid':1}),dict(model='m',category='planner',status='timeout',elapsed_seconds=10,scores={})]
    summary=aggregate(rows)[0];assert summary['runs']==2 and summary['failures']==1 and summary['metrics']['schema_valid']==.5


def test_unavailable_models_are_results():
    call=Mock(side_effect=AssertionError('Never call absent model'))
    result=run_models(['llama3.2:3b'],set(),call=call)
    assert len(result['runs'])==23 and all(r['status']=='unavailable' for r in result['runs']);call.assert_not_called()


def test_timeout_results_and_no_silent_retry():
    failure=ai_provider.AIConnectionError('controlled');failure.__cause__=TimeoutError('synthetic')
    call=Mock(side_effect=failure)
    result=run_models(['llama3.2:3b'],{'llama3.2:3b'},call=call,repeats=1)
    assert len(result['runs'])==13 and call.call_count==13
    assert all(r['status']=='timeout' for r in result['runs'])
    assert all(r['error']=='AIConnectionError' for r in result['runs'])


def test_model_allowlist_and_repeats():
    with pytest.raises(ValueError):run_models(['arbitrary'],set())
    with pytest.raises(ValueError):run_models(['llama3.2:3b'],set(),repeats=0)


def test_disk_reserve():
    model=GENERATIVE[1]
    assert not download_gate(model,RESERVE_BYTES)['allowed']
    assert download_gate(model,RESERVE_BYTES+2_000_000_000)['allowed']


def test_retrieval_metrics_exact():
    queries=[{'relevant_ids':['a','b'],'filters':{}},{'relevant_ids':[],'filters':{}}]
    result=retrieval_metrics([[{'id':'x'},{'id':'a'},{'id':'b'}],[]],queries,k=2)
    assert result['hit_at_1']==0 and result['hit_at_3']==1 and result['hit_at_5']==1
    assert result['recall_at_k']==.5 and result['mrr']==.5 and result['no_evidence_false_positive_rate']==0


def test_false_positive_and_scope_violation():
    result=retrieval_metrics([[{'id':'x','unit':'Other'}]],[{'relevant_ids':[],'filters':{'unit':'Unit 1'}}])
    assert result['no_evidence_false_positive_rate']==1 and result['hierarchy_filter_correctness']==0


def test_calibration_never_uses_heldout():
    rows=[dict(split='calibration',relevant_ids=['a'],candidates=[dict(id='a',distance=.2)]),dict(split='calibration',relevant_ids=[],candidates=[dict(id='x',distance=.6)]),dict(split='test',relevant_ids=[],candidates=[dict(id='x',distance=.01)])]
    calibration=calibrate_threshold(rows,[.1,.3,.7]);assert calibration['recommended_threshold']==.3
    assert calibration['curve'][1]['no_evidence_fpr']==0


def test_calibration_insufficient_data_rejected():
    with pytest.raises(ValueError):calibrate_threshold([dict(split='calibration',relevant_ids=[],candidates=[])])


def test_memory_store_runs_existing_rag_and_filters():
    encoder=Mock();encoder.encode.side_effect=lambda texts,**kw:np.array([[1.,0.] if 'positive' in t else [0.,1.] for t in texts])
    rows=[dict(id='a',text='positive',unit='Unit 1',source='Synthetic'),dict(id='b',text='positive',unit='Unit 2',source='Synthetic'),dict(id='c',text='other',unit='Unit 1',source='Synthetic')]
    collection=MemoryCollection(rows,encoder)
    queries=[dict(id='q',question='positive query',relevant_ids=['a'],filters={'unit':'Unit 1'},split='test')]
    result=evaluate_collection(collection,queries)
    assert [r['id'] for r in result['rankings'][0]]==['a'] and result['metrics']['mrr']==1
    assert result['settings']=={'candidate_k':15,'final_k':5,'max_distance':.65}


def test_reranker_changes_order_without_scope_loss():
    encoder=Mock();encoder.encode.side_effect=lambda texts,**kw:np.array([[1.,0.] for _ in texts])
    rows=[dict(id='a',text='One',unit='Unit 1'),dict(id='b',text='Two',unit='Unit 1')]
    collection=MemoryCollection(rows,encoder);reranker=Mock();reranker.predict.return_value=np.array([0.,1.])
    result=evaluate_collection(collection,[dict(id='q',question='query',relevant_ids=['b'],filters={'unit':'Unit 1'},split='test')],reranker=reranker)
    assert result['metrics']['hit_at_1']==1 and result['metrics']['hierarchy_filter_correctness']==1


def test_reports_generated_only_in_temp(tmp_path):
    result=run_models(['llama3.2:3b'],set(),repeats=1)
    report=write_report(result,tmp_path)
    assert {p.name for p in tmp_path.iterdir()}=={'results.json','metrics.csv','human_review.csv','summary.md'}
    assert 'REQUIRES_HUMAN_REVIEW' in (tmp_path/'human_review.csv').read_text()
    assert report['quality_gates']['llama3.2:3b']['recommendation']=='NO CHANGE RECOMMENDED YET'


def test_measured_provider_optin(monkeypatch):
    from unittest.mock import MagicMock
    client=MagicMock();client.__enter__.return_value=client
    client.chat.return_value={'message':{'content':'Synthetic'},'eval_count':3,'total_duration':100}
    factory=Mock(return_value=client);monkeypatch.setattr(ai_provider.ollama,'Client',factory)
    result=ai_provider.generate_chat_measured([{'role':'user','content':'Synthetic'}],model='candidate',options={'temperature':0,'seed':17},timeout_seconds=3,think=False)
    assert result.text=='Synthetic' and result.output_tokens==3 and result.total_duration_ns==100
    client.chat.assert_called_once_with(model='candidate',messages=[{'role':'user','content':'Synthetic'}],options={'temperature':0,'seed':17},think=False)

@pytest.mark.parametrize('kwargs',[dict(options={'tool':'shell'}),dict(options={'temperature':float('nan')}),dict(options={'num_ctx':True}),dict(timeout_seconds=0),dict(think='yes')])
def test_invalid_instrumentation_controlled(kwargs):
    with pytest.raises(ai_provider.AIProviderError):ai_provider.generate_chat_measured([{'role':'user','content':'Synthetic'}],**kwargs)


def test_output_cannot_target_production_storage():
    with pytest.raises(ValueError):write_report({'runs':[]},Path(__file__).resolve().parents[1]/'uploads')


def test_even_latency_uses_true_median():
    rows=[dict(model='m',category='qa',status='ok',elapsed_seconds=n,scores={}) for n in (1,5,8,12)]
    assert aggregate(rows)[0]['latency_median_seconds']==6.5


def test_human_failures_not_assigned_fake_scores():
    rows=[dict(model='m',category='qa',status='ok',elapsed_seconds=1,scores={'human_groundedness':HUMAN}),dict(model='m',category='qa',status='timeout',elapsed_seconds=2,scores={})]
    assert aggregate(rows)[0]['metrics']['human_groundedness'] is None


def test_prompt_capture_cannot_read_production_stores(monkeypatch):
    import db,vector_store
    monkeypatch.setattr(db,'material_connection',Mock(side_effect=AssertionError('No production SQLite')))
    monkeypatch.setattr(vector_store,'get_collection',Mock(side_effect=AssertionError('No production Chroma')))
    assert len(generative_cases())==13


def test_pipeline_no_evidence_abstains_without_generation(monkeypatch):
    from benchmarks.pipeline import run_pipeline
    encoder=Mock();encoder.encode.side_effect=lambda texts,**kw:np.array([[-1.,0.] if 'weather' in t else [1.,0.] for t in texts])
    measured=ai_provider.ChatMeasurement('Synthetic answer',.1,2,2,1,0,1)
    call=Mock(return_value=measured);monkeypatch.setattr(ai_provider,'generate_chat_measured',call)
    rows=run_pipeline(encoder,'sentence-transformers/all-MiniLM-L6-v2','llama3.2:3b')
    assert [r['model_calls'] for r in rows]==[1,1,0]
    assert not rows[-1]['sources'] and not rows[-1]['retrieved_ids']
    assert call.call_count==2


def test_embedding_evaluation_has_heldout_and_no_production_store():
    from benchmarks.embedding_runner import evaluate_encoder
    encoder=Mock();encoder.encode.side_effect=lambda texts,**kw:np.array([[1.,0.] for t in texts])
    result=evaluate_encoder(encoder,'sentence-transformers/all-MiniLM-L6-v2')
    assert result['calibrated_heldout']['metrics']['positive_queries']==6
    assert result['calibrated_heldout']['metrics']['negative_queries']==2
    assert 'in-memory' in result['store'].lower()


@pytest.mark.parametrize('vectors',[np.array([[float('nan'),0]]),np.array([[0.,0.]])])
def test_invalid_embedding_vectors_are_failures(vectors):
    encoder=Mock();encoder.encode.return_value=vectors
    with pytest.raises(ValueError):MemoryCollection([{'id':'a','text':'Synthetic'}],encoder)


def test_invalid_query_vector_is_not_a_good_no_evidence_score():
    encoder=Mock();encoder.encode.side_effect=[np.array([[1.,0.]]),np.array([[float('nan'),0.]])]
    store=MemoryCollection([{'id':'a','text':'Synthetic'}],encoder)
    with pytest.raises(ValueError):store.query(['Synthetic question'],15)
