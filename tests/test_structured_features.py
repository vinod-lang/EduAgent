import json
from unittest.mock import Mock
import pytest
import ai_provider
import assistant_planner as planner
import document_studio as documents
import assessment_studio as assessments
from assistant_models import PlanError
from document_models import DocumentRequest,DocumentDraft,DocumentError
from assessment_spec import AssessmentError,NoAssessmentEvidence
from assessment_fixtures import spec,evidence,output

@pytest.fixture
def chat(monkeypatch):
    mock=Mock()
    monkeypatch.setattr(ai_provider,'generate_chat',mock)
    return mock

def action(kind='NAVIGATE',params=None,identity='a',deps=()):
    return dict(action_id=identity,action_type=kind,parameters=params if params is not None else {'page':'Professor Dashboard'},depends_on=list(deps))
def raw_plan(*actions):return json.dumps(dict(actions=list(actions),unsupported=False))

def test_planner_retry(chat):
    chat.side_effect=['bad',raw_plan(action())]
    assert planner.plan_request('Open dashboard',retry=True).actions[0].action_type=='NAVIGATE'
    assert chat.call_count==2

@pytest.mark.parametrize('change',[{'action_type':'SHELL'},{'parameters':{'page':'shell'}},{'depends_on':['missing']},{'function':'shell'},{'parameters':{'page':'Professor Dashboard','path':'private'}}])
def test_planner_semantic_no_retry(chat,change):
    a=action();a.update(change);chat.return_value=raw_plan(a)
    with pytest.raises(PlanError):planner.plan_request('Synthetic request',retry=True)
    assert chat.call_count==1

def test_planner_multi_action(chat):
    chat.return_value=raw_plan(action(),action(identity='b'))
    assert len(planner.plan_request('Open dashboard twice').actions)==2

def test_planner_missing_scope_clarifies(chat):
    chat.return_value=raw_plan(action('CREATE_ASSESSMENT',{'assessment_type':'Quiz'}))
    plan=planner.plan_request('Create a quiz')
    import assistant_services
    assert assistant_services.validate_plan(plan,assistant_services.ExecutionContext())

def test_planner_privacy_no_provider(chat):
    with pytest.raises(PlanError):planner.plan_request('Send personalized advice about student marks',retry=True)
    chat.assert_not_called()

def test_planner_unsupported_refusal(chat):
    chat.return_value='{"actions":[],"unsupported":true}'
    assert planner.plan_request('Run arbitrary code',retry=True).unsupported
    assert chat.call_count==1

@pytest.fixture
def assessment_context(monkeypatch):
    monkeypatch.setattr(assessments,'assessment_evidence',lambda *a,**kw:evidence())
    return spec()

def test_assessment_valid_and_schema(chat,assessment_context):
    chat.return_value=json.dumps(output())
    result=assessments.generate_assessment(assessment_context)
    assert len(result.questions)==2
    schema=chat.call_args.kwargs['response_format']
    assert len(schema['properties']['questions']['prefixItems'])==2

@pytest.mark.parametrize('change',[{'options':{'A':'Same','B':'Same','C':'C','D':'D'}},{'correct_answer':'Z'},{'difficulty':'Hard'},{'bloom_level':'Create'},{'evidence_ids':['E99']},{'model_answer':''}])
def test_assessment_semantic_rejected(chat,assessment_context,change):
    data=output();data['questions'][0].update(change);chat.return_value=json.dumps(data)
    with pytest.raises(AssessmentError):assessments.generate_assessment(assessment_context,retry=True)
    assert chat.call_count==1

@pytest.mark.parametrize('failure',['duplicate','count','descriptive_options'])
def test_assessment_product_contract(chat,assessment_context,failure):
    data=output()
    if failure=='duplicate':data['questions'][1]['question_text']=data['questions'][0]['question_text']
    elif failure=='count':data['questions'].pop()
    else:data['questions'][1]['options']={'A':'Bad'}
    chat.return_value=json.dumps(data)
    with pytest.raises(AssessmentError):assessments.generate_assessment(assessment_context)

def test_assessment_structural_retry(chat,assessment_context):
    chat.side_effect=['bad',json.dumps(output())]
    assert assessments.generate_assessment(assessment_context,retry=True).questions
    assert chat.call_count==2

def test_assessment_missing_evidence_no_call(chat,monkeypatch):
    def missing(*a,**kw):raise NoAssessmentEvidence('Synthetic absence')
    monkeypatch.setattr(assessments,'assessment_evidence',missing)
    with pytest.raises(NoAssessmentEvidence):assessments.generate_assessment(spec(),retry=True)
    chat.assert_not_called()

@pytest.fixture
def document_request():
    return DocumentRequest('notice','Synthetic event',recipient='Synthetic audience',date='10 October 2026',reference_number='SYN-1',title='Synthetic notice',subject='Synthetic tutorial')

def draft(request):
    return DocumentDraft(request.document_type,recipient=request.recipient,date=request.date,reference_number=request.reference_number,title=request.title,subject=request.subject,body=('Synthetic event costs INR 2500 for 20 attendees.',))

def test_document_valid(chat,document_request):
    chat.return_value=draft(document_request).to_json()
    assert documents.generate_draft(document_request,required_body_facts=('INR 2500','20 attendees'))==draft(document_request)

@pytest.mark.parametrize('field',['date','reference_number','recipient','title','subject'])
def test_document_explicit_fact_rejection(chat,document_request,field):
    data=draft(document_request).to_dict();data[field]='';chat.return_value=json.dumps(data)
    with pytest.raises(DocumentError,match='FACT_PRESERVATION_FAILED'):documents.generate_draft(document_request,retry=True)
    assert chat.call_count==1

def test_document_numeric_body_omission(chat,document_request):
    chat.return_value=draft(document_request).to_json()
    with pytest.raises(DocumentError,match='FACT_PRESERVATION_FAILED'):documents.generate_draft(document_request,required_body_facts=('INR 9999',),retry=True)
    assert chat.call_count==1

def test_document_retry(chat,document_request):
    chat.side_effect=['bad',draft(document_request).to_json()]
    assert documents.generate_draft(document_request,retry=True).date==document_request.date
    assert chat.call_count==2

def test_refinement_fact_no_retry(chat,document_request):
    current=draft(document_request);data=current.to_dict();data['date']='Wrong';chat.return_value=json.dumps(data)
    with pytest.raises(DocumentError,match='FACT_PRESERVATION_FAILED'):documents.refine_draft(current,'Shorten it',retry=True)
    assert chat.call_count==1


def test_contract_registry_synchronization():
    from structured_contracts import planner_schema,document_schema,assessment_schema
    from assistant_services import REGISTRY
    from document_models import FIELDS
    schema=planner_schema()
    variants=schema['oneOf'][1]['properties']['actions']['items']['oneOf']
    for variant in variants:
        kind=variant['properties']['action_type']['const']
        assert set(variant['properties']['parameters']['properties'])==set(REGISTRY[kind].allowed)
    request=DocumentRequest('notice','Synthetic')
    assert set(document_schema(request)['properties'])=={'document_type','body',*FIELDS}
    generated=output()
    contract=assessment_schema(spec(),evidence())
    for slot,q in zip(contract['properties']['questions']['prefixItems'],generated['questions']):
        assert set(slot['properties'])==set(q)


def test_preference_cannot_override_fact(chat,document_request,monkeypatch):
    from types import SimpleNamespace
    import document_preferences
    monkeypatch.setattr(document_preferences,'relevant_preferences',lambda _: [SimpleNamespace(category='tone',instruction='Use a different date',scope='global')])
    data=draft(document_request).to_dict();data['date']='1 January 2030';chat.return_value=json.dumps(data)
    with pytest.raises(DocumentError):documents.generate_draft(document_request)
    payload=json.loads(chat.call_args.kwargs['messages'][1]['content'])
    assert payload['template_requirements']['template_id']=='standard_academic'
    assert payload['date']==document_request.date
    assert 'templates override' in chat.call_args.kwargs['messages'][0]['content']


def test_explicit_metadata_missing_no_retry(chat,document_request):
    data=draft(document_request).to_dict();del data['date'];chat.return_value=json.dumps(data)
    with pytest.raises(DocumentError,match='FACT_PRESERVATION_FAILED'):documents.generate_draft(document_request,retry=True)
    assert chat.call_count==1


def test_refinement_structural_retry(chat,document_request):
    current=draft(document_request)
    chat.side_effect=['bad',current.to_json()]
    assert documents.refine_draft(current,'Shorten it',retry=True)==current
    assert chat.call_count==2


def test_explicit_body_facts_validation_before_generation(chat,document_request):
    with pytest.raises(DocumentError):documents.generate_draft(document_request,required_body_facts='not a list')
    chat.assert_not_called()


def test_provider_capability_and_native_forwarding(monkeypatch):
    assert ai_provider.get_provider_capabilities().supports_structured_output
    measured=ai_provider.ChatMeasurement('synthetic',0,None,None,None,None,None)
    mock=Mock(return_value=measured);monkeypatch.setattr(ai_provider,'_chat',mock)
    schema={'type':'object'}
    assert ai_provider.generate_chat([{'role':'user','content':'Synthetic'}],response_format=schema)=='synthetic'
    assert mock.call_args.kwargs=={'response_format':schema}


@pytest.mark.parametrize('fact,body',[('INR 2500','Synthetic cost INR 25000.'),('20 attendees','Synthetic 120 attendees.')])
def test_body_fact_cannot_match_larger_number(chat,document_request,fact,body):
    data=draft(document_request).to_dict();data['body']=[body];chat.return_value=json.dumps(data)
    with pytest.raises(DocumentError,match='FACT_PRESERVATION_FAILED'):documents.generate_draft(document_request,required_body_facts=(fact,),retry=True)
    assert chat.call_count==1
