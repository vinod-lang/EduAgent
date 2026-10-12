import copy
import json
from unittest.mock import Mock
import pytest
import assessment_studio as studio
from assessment_spec import AssessmentScope,AssessmentError,NoAssessmentEvidence,BLOOMS
from assessment_fixtures import spec,evidence,output,raw,collection,ID_A,ID_B
from rag_fixtures import Collection,row
from retrieval import RetrievalError

def test_valid_output_and_all_distributions():
    result=studio.validate_output(raw(),spec(),evidence())
    assert result.validation_summary==dict(questions=2,question_types={'MCQ':1,'Descriptive':1},difficulties={'Easy':1,'Medium':1},blooms={'Remember':1,'Understand':1},total_marks=5)
    assert result.questions[0].sources==('Synthetic lecture.pdf (U1) - Page 2',)
    assert result.questions[0].evidence_ids==('E1',)

@pytest.mark.parametrize('value',['invalid','```json\n{}\n```','{}','[]','null','{"questions": []}','{"questions": [], "extra": 1}','{"questions": [], "questions": []}'])
def test_bad_json_and_envelope(value):
    with pytest.raises(AssessmentError):studio.validate_output(value,spec(),evidence())

@pytest.mark.parametrize('key,value',[
 ('question_number',2),('question_number',True),('question_type','Essay'),('question_type','Descriptive'),
 ('difficulty','Impossible'),('difficulty','Hard'),('bloom_level','Recall'),('bloom_level','Create'),
 ('marks',0),('marks',-1),('marks',3.0),('marks',True),('marks',4),('question_text',' '),('question_text',None),
 ('model_answer',''),('model_answer',[]),('options',{}),('options',{'A':'One','B':'Two'}),
 ('options',{'A':'Same','B':'same','C':'Other','D':'Fourth'}),('options',{'A':'One','B':'Two','C':'Three','D':None}),
 ('correct_answer','Z'),('correct_answer',['A','B']),('correct_answer',''),
 ('evidence_ids',[]),('evidence_ids',['FAKE']),('evidence_ids',['E1','E1']),('evidence_ids','E1')])
def test_untrusted_fields_rejected(key,value):
    data=output();data['questions'][0][key]=value
    with pytest.raises(AssessmentError):studio.validate_output(json.dumps(data),spec(),evidence())

@pytest.mark.parametrize('key',list(output()['questions'][0]))
def test_every_required_field(key):
    data=output();del data['questions'][0][key]
    with pytest.raises(AssessmentError):studio.validate_output(json.dumps(data),spec(),evidence())

@pytest.mark.parametrize('key,value',[('options',{'A':'Fake MCQ'}),('options',None),('correct_answer','A')])
def test_descriptive_structure(key,value):
    data=output();data['questions'][1][key]=value
    with pytest.raises(AssessmentError):studio.validate_output(json.dumps(data),spec(),evidence())

def test_duplicate_question_text():
    data=output();data['questions'][1]['question_text']=data['questions'][0]['question_text']
    with pytest.raises(AssessmentError):studio.validate_output(json.dumps(data),spec(),evidence())

def test_extra_fields_and_nonfinite():
    data=output();data['questions'][0]['source']='invented.pdf'
    with pytest.raises(AssessmentError):studio.validate_output(json.dumps(data),spec(),evidence())
    with pytest.raises(AssessmentError):studio.validate_output('{"questions": NaN}',spec(),evidence())

def test_pyq_copy_rejected():
    with pytest.raises(AssessmentError,match='copies PYQ'):
        studio.validate_output(raw(),spec(),evidence(),pyq_text=output()['questions'][0]['question_text'])

def test_generation_provider_prompt_and_pyq(monkeypatch):
    chat=Mock(return_value=raw());monkeypatch.setattr(studio.ai_provider,'generate_chat',chat)
    result=studio.generate_assessment(spec(),pyq_text='Synthetic old style: compare ideas.',collection=collection())
    assert len(result.questions)==2;chat.assert_called_once()
    payload=json.loads(chat.call_args.kwargs['messages'][1]['content'])
    assert payload['slots']==[s.to_dict() for s in spec().plan]
    assert payload['pyq_style_guidance']=='Synthetic old style: compare ideas.'
    assert payload['teaching_evidence'][0]['evidence_id']=='E1'
    assert 'do not copy' in chat.call_args.kwargs['messages'][0]['content']

@pytest.mark.parametrize('distance',[.66,1.9])
def test_no_relevant_evidence_never_calls_model(monkeypatch,distance):
    chat=Mock();monkeypatch.setattr(studio.ai_provider,'generate_chat',chat)
    c=collection();c.rows[0]['distance']=distance
    with pytest.raises(NoAssessmentEvidence):studio.generate_assessment(spec(),collection=c)
    chat.assert_not_called()

def test_no_evidence_and_bad_spec(monkeypatch):
    chat=Mock();monkeypatch.setattr(studio.ai_provider,'generate_chat',chat)
    with pytest.raises(NoAssessmentEvidence):studio.generate_assessment(spec(),collection=Collection())
    with pytest.raises(AssessmentError):studio.generate_assessment(None,collection=Collection())
    chat.assert_not_called()

def test_single_call_no_unbounded_repair(monkeypatch):
    chat=Mock(return_value='bad');monkeypatch.setattr(studio.ai_provider,'generate_chat',chat)
    with pytest.raises(AssessmentError):studio.generate_assessment(spec(),collection=collection())
    chat.assert_called_once()

@pytest.mark.parametrize('units,ids',[(('U1',),()),(('U1','U2'),()),(('U1',),(ID_A,)),(('U1','U2'),(ID_A,ID_B))])
def test_exact_multi_unit_material_scope(units,ids):
    metadata=lambda unit,identity:dict(material_id=identity,source='Synthetic.png' if unit=='U2' else 'Synthetic.pdf',course='C',semester='S',subject='ML',unit=unit)
    c=Collection([row('a','Synthetic teaching A',metadata=metadata('U1',ID_A)),row('b','Synthetic teaching B',metadata=metadata('U2',ID_B)),
                  row('other','Unrelated material',metadata=dict(metadata('U1',ID_B),course='OTHER'))])
    result=studio.assessment_evidence(spec(scope=AssessmentScope('C','S','ML',units,ids)),collection=c)
    assert {e.unit for e in result}==set(units)
    assert all(e.course=='C' and e.semester=='S' and e.subject=='ML' for e in result)
    if ids:assert {e.material_id for e in result}==set(ids)
    assert all(call['where'] and call['n_results']==15 for call in c.calls)
    assert 'other' not in {e.chunk_id for e in result}
    if 'U2' in units:assert next(e for e in result if e.unit=='U2').content_type=='Image/OCR'

@pytest.mark.parametrize('field',['course','semester','subject','unit','material_id'])
def test_out_of_scope_returns_no_evidence(field):
    c=collection();c.rows[0]['metadata'][field]='wrong'
    s=spec(scope=AssessmentScope('C','S','ML',('U1',),(ID_A,)))
    with pytest.raises(NoAssessmentEvidence):studio.assessment_evidence(s,collection=c)

def test_legacy_compatible_no_invented_identity():
    meta=dict(source='Legacy',course='C',semester='S',subject='ML',unit='U1')
    c=Collection([row('legacy','Legacy academic text',metadata=meta)])
    found=studio.assessment_evidence(spec(),collection=c)
    assert found[0].material_id is None
    del c.rows[0]['metadata']['subject']
    with pytest.raises(NoAssessmentEvidence):studio.assessment_evidence(spec(),collection=c)

def test_cross_branch_deduplication():
    c=collection();c.rows.extend([copy.deepcopy(c.rows[0]),row('dup','PCA projects onto directions of maximum variance.',metadata=c.rows[0]['metadata'])])
    assert len(studio.assessment_evidence(spec(),collection=c))==1

def test_missing_selected_unit_fails_closed():
    with pytest.raises(NoAssessmentEvidence):studio.assessment_evidence(spec(scope=AssessmentScope('C','S','ML',('U1','U2'))),collection=collection())

def test_unknown_metric_refused():
    c=collection();c.configuration={'hnsw':{'space':'l2'}}
    with pytest.raises(RetrievalError):studio.assessment_evidence(spec(),collection=c)


@pytest.mark.parametrize('count',[1,3])
def test_wrong_nonzero_count(count):
    data=output();data['questions']=(data['questions']*2)[:count]
    with pytest.raises(AssessmentError):studio.validate_output(json.dumps(data),spec(),evidence())

@pytest.mark.parametrize('difficulty',['Easy','Medium','Hard'])
def test_valid_difficulty_counts(difficulty):
    s=spec(difficulties={k:2 if k==difficulty else 0 for k in ('Easy','Medium','Hard')})
    result=studio.validate_output(raw(s.plan),s,evidence())
    assert result.validation_summary['difficulties']=={difficulty:2}

@pytest.mark.parametrize('bloom',BLOOMS)
def test_valid_bloom_counts(bloom):
    s=spec(blooms={k:2 if k==bloom else 0 for k in BLOOMS})
    assert studio.validate_output(raw(s.plan),s,evidence()).validation_summary['blooms']=={bloom:2}

@pytest.mark.parametrize('kind',['MCQ','Descriptive'])
def test_single_type_distribution(kind):
    s=spec(question_types={k:2 if k==kind else 0 for k in ('MCQ','Descriptive')})
    assert studio.validate_output(raw(s.plan),s,evidence()).validation_summary['question_types']=={kind:2}

def test_metadata_defense_even_when_adapter_ignores_filter(monkeypatch):
    from types import SimpleNamespace
    bad=copy.copy(evidence()[0])
    from dataclasses import replace
    monkeypatch.setattr(studio,'retrieve_evidence',lambda *args,**kwargs:SimpleNamespace(evidence=(replace(bad,course='WRONG'),)))
    with pytest.raises(NoAssessmentEvidence):studio.assessment_evidence(spec())

def test_context_budget_fails_closed():
    c=collection();c.rows[0]['text']='x'*60001
    with pytest.raises(AssessmentError,match='budget'):studio.assessment_evidence(spec(),collection=c)


def test_two_materials_in_one_unit_are_both_scoped():
    c=collection();meta=dict(c.rows[0]['metadata'],material_id=ID_B,source='Other.pdf')
    c.rows.append(row('b','Distinct second material context',metadata=meta))
    selected=spec(scope=AssessmentScope('C','S','ML',('U1',),(ID_A,ID_B)))
    found=studio.assessment_evidence(selected,collection=c)
    assert {chunk.material_id for chunk in found}=={ID_A,ID_B}
    assert len(c.calls)==2


@pytest.mark.parametrize('field,value',[('question_text','bad\x00text'),('question_text','bad\ud800text'),('model_answer','bad\x01text'),('options',{'A':'bad\x00text','B':'Two','C':'Three','D':'Four'})])
def test_control_characters_rejected(field,value):
    data=output();data['questions'][0][field]=value
    with pytest.raises(AssessmentError):studio.validate_output(json.dumps(data),spec(),evidence())
