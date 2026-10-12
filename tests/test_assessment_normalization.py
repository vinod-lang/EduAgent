import json
from copy import deepcopy
from unittest.mock import Mock
import pytest
from assessment_normalization import normalize_assessment
from assessment_fixtures import output,spec,evidence
from assessment_spec import AssessmentError
import assessment_studio


def shaped():
    data=output();q=data['questions'][0]
    q['options']=[{k:v} for k,v in q['options'].items()]
    return data


def test_known_equivalent_shape_only():
    data=shaped();before=deepcopy(data);result=normalize_assessment(data)
    assert result.applied and result.normalization_type=='known_mcq_option_shape'
    assert result.data==output() and data==before


def test_canonical_unchanged():
    data=output();result=normalize_assessment(data)
    assert not result.applied and result.normalization_type is None and result.data==data

@pytest.mark.parametrize('options',[
 [],[{'A':'a'}],[{'A':'a'},{'B':'b'},{'C':'c'}],
 [{'A':'a'},{'B':'b'},{'C':'c'},{'D':'d'},{'E':'e'}],
 [{'A':'a'},{'A':'a2'},{'C':'c'},{'D':'d'}],
 [{'A':'a'},{'B':'b'},{'C':'c'},{'Z':'d'}],
 [{'A':'a','B':'b'},{'B':'b'},{'C':'c'},{'D':'d'}],
 [{'A':{'nested':'content'}},{'B':'b'},{'C':'c'},{'D':'d'}],
 [{'A':['content']},{'B':'b'},{'C':'c'},{'D':'d'}],
 [{'A':None},{'B':'b'},{'C':'c'},{'D':'d'}],
 [{'A':' '},{'B':'b'},{'C':'c'},{'D':'d'}],
 ['a','b','c','d'],[{}, {'B':'b'},{'C':'c'},{'D':'d'}],
 [{1:'a'},{'B':'b'},{'C':'c'},{'D':'d'}]])
def test_malformed_shape_rejected(options):
    data=output();data['questions'][0]['options']=options
    with pytest.raises(ValueError):normalize_assessment(data)


def test_reordered_labels_exact_strings_preserved():
    data=shaped();data['questions'][0]['options'].reverse()
    assert normalize_assessment(data).data==output()

@pytest.fixture
def generation(monkeypatch):
    monkeypatch.setattr(assessment_studio,'assessment_evidence',lambda *a,**kw:evidence())
    chat=Mock();monkeypatch.setattr(assessment_studio.ai_provider,'generate_chat',chat)
    return chat


def test_pipeline_pre_schema_normalization(generation):
    generation.return_value=json.dumps(shaped())
    result=assessment_studio.generate_assessment(spec())
    assert dict(result.questions[0].options)==output()['questions'][0]['options']
    assert result.provenance.normalization_applied and result.provenance.normalization_type=='known_mcq_option_shape'
    assert generation.call_count==1

@pytest.mark.parametrize('mutation',['answer','difficulty','bloom','duplicate','evidence','semantic_options','count'])
def test_product_validator_still_authority(generation,mutation):
    data=shaped()
    if mutation=='answer':data['questions'][0]['correct_answer']='Z'
    elif mutation=='difficulty':data['questions'][0]['difficulty']='Hard'
    elif mutation=='bloom':data['questions'][0]['bloom_level']='Create'
    elif mutation=='duplicate':data['questions'][1]['question_text']=data['questions'][0]['question_text']
    elif mutation=='evidence':data['questions'][0]['evidence_ids']=['E999']
    elif mutation=='count':data['questions'].pop()
    else:data['questions'][0]['options'][1]={'B':data['questions'][0]['options'][0]['A']}
    generation.return_value=json.dumps(data)
    with pytest.raises(AssessmentError):assessment_studio.generate_assessment(spec(),retry=True)
    assert generation.call_count==1


def test_malformed_json_not_repaired(generation):
    generation.return_value='{"questions": ['
    with pytest.raises(AssessmentError):assessment_studio.generate_assessment(spec())
    assert generation.call_count==1


def test_canonical_generation_provenance(generation):
    generation.return_value=json.dumps(output())
    result=assessment_studio.generate_assessment(spec())
    assert not result.provenance.normalization_applied and result.provenance.normalization_type is None


def test_unknown_fields_not_removed(generation):
    data=shaped();data['questions'][0]['debug']='Unexpected';generation.return_value=json.dumps(data)
    with pytest.raises(AssessmentError):assessment_studio.generate_assessment(spec())


def test_descriptive_options_not_normalized(generation):
    data=output();data['questions'][1]['options']=[{'A':'a'},{'B':'b'},{'C':'c'},{'D':'d'}]
    generation.return_value=json.dumps(data)
    with pytest.raises(AssessmentError):assessment_studio.generate_assessment(spec())
