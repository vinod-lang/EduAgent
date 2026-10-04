"""Synthetic orchestration contracts; all provider/service boundaries mocked."""
import json
from dataclasses import replace
from unittest.mock import Mock
import pytest
import assistant_services as services
import assistant_planner as planner
from assistant_models import *
from assessment_fixtures import spec,evidence,raw,output
from assessment_studio import validate_output
from document_models import DocumentDraft


def action(kind='NAVIGATE',params=None,identity='a',deps=()):
    return dict(action_id=identity,action_type=kind,parameters=params if params is not None else {'page':'Professor Dashboard'},depends_on=list(deps))

def plan(*actions):return parse_plan(json.dumps(dict(actions=list(actions),unsupported=False)),'Synthetic request')

def assessment_params():
    s=spec();return dict(assessment_type=s.assessment_type,scope=dict(course='C',semester='S',subject='ML',units=['U1']),question_types=dict(s.question_types),difficulties=dict(s.difficulties),blooms=dict(s.blooms),total_questions=2,total_marks=5,title=s.title)

def combined():return plan(action('CREATE_ASSESSMENT',assessment_params()),action('CREATE_DOCUMENT',dict(document_type='notice',description='Announce the quiz'),identity='b',deps=('a',)))

@pytest.mark.parametrize('raw_text',['invalid','[]','null','{}','{"actions":[],"unsupported":false}','{"actions":[],"unsupported":true,"tool":"shell"}','{"actions":[],"unsupported":true,"unsupported":false}','{"actions":NaN,"unsupported":false}'])
def test_bad_envelopes(raw_text):
    with pytest.raises(PlanError):parse_plan(raw_text,'Synthetic')

@pytest.mark.parametrize('field,value',[('action_type','shell'),('action_id','a.b'),('action_id',''),('depends_on',['a']),('parameters',[]),('requires_confirmation',False),('function','os.system')])
def test_action_schema(field,value):
    a=action();a[field]=value
    with pytest.raises(PlanError):plan(a)

@pytest.mark.parametrize('actions',[[action(),action()], [action(deps=('missing',))], [action(deps=('b',)),action(identity='b',deps=('a',))], [action(identity=str(i)) for i in range(6)]])
def test_duplicate_dependency_cycle_limits(actions):
    with pytest.raises(PlanError):plan(*actions)

@pytest.mark.parametrize('key',['function','tool','shell','path','provider','system_prompt','requires_confirmation'])
def test_injection_parameter_rejected(key):
    p=plan(action(params={'page':'Professor Dashboard',key:'malicious'}))
    with pytest.raises(PlanError):services.execute_plan(p)

@pytest.mark.parametrize('kind,params',[('NAVIGATE',{'page':'shell'}),('ASK_KNOWLEDGE',{'question':'Q','filters':{'unit':['all']}}),('CREATE_DOCUMENT',{'document_type':'unknown','description':'x'}),('ANALYZE_STUDENTS',{'view':'Send advice'}),('CREATE_ASSESSMENT',dict(assessment_params(),total_questions=10))])
def test_existing_boundary_validation(kind,params):
    context=services.ExecutionContext(object())
    with pytest.raises(PlanError):services.validate_plan(plan(action(kind,params)),context)


def test_missing_required_never_executes(monkeypatch):
    dispatch=Mock();monkeypatch.setattr(services,'dispatch',dispatch)
    p=plan(action('CREATE_ASSESSMENT',{'assessment_type':'Quiz'}))
    missing=services.validate_plan(p,services.ExecutionContext())
    assert 'scope.course' in missing[0].missing_fields
    with pytest.raises(PlanError):services.execute_plan(p)
    dispatch.assert_not_called()


def test_valid_planner_and_no_execution(monkeypatch):
    chat=Mock(return_value=json.dumps({'actions':[action()],'unsupported':False}))
    monkeypatch.setattr(planner.ai_provider,'generate_chat',chat)
    p=planner.plan_request('Open dashboard')
    assert p.actions[0].action_type=='NAVIGATE';assert chat.call_count==1
    assert p.actions[0].requires_confirmation is False


def test_unsupported_plan():
    p=parse_plan('{"actions":[],"unsupported":true}','Run shell')
    with pytest.raises(PlanError):services.execute_plan(p)


def test_policy_is_registry_not_model(monkeypatch):
    registry=dict(services.REGISTRY);registry['NAVIGATE']=replace(registry['NAVIGATE'],confirmation=True)
    monkeypatch.setattr(services,'REGISTRY',registry)
    p=plan(action());assert p.actions[0].requires_confirmation
    with pytest.raises(PlanError,match='Confirmation'):services.execute_plan(p)


def test_success_dependency_only_allowlisted_summary(monkeypatch):
    import assessment_studio,document_studio
    generated=validate_output(raw(),spec(),evidence())
    quiz=Mock(return_value=generated);doc=Mock(return_value=DocumentDraft('notice',body=('Synthetic announcement',)))
    monkeypatch.setattr(assessment_studio,'generate_assessment',quiz);monkeypatch.setattr(document_studio,'generate_draft',doc)
    report=services.execute_plan(combined());assert report.status=='completed'
    request=doc.call_args.args[0]
    assert 'question_count' in request.additional_context
    for private in ('SUGGESTED_ANSWER','owned_chunk','Synthetic lecture.pdf','E1'):
        assert private not in request.additional_context
    assert services.dependency_summary(report.results[0])=={'assessment_title':spec().title,'assessment_type':'Quiz','question_count':2}


def test_failure_blocks_dependency_independent_continues(monkeypatch):
    import assessment_studio
    monkeypatch.setattr(assessment_studio,'generate_assessment',Mock(side_effect=RuntimeError('PRIVATE PAYLOAD')))
    p=combined();p=replace(p,actions=p.actions+(PlannedAction('c','NAVIGATE',json.dumps({'page':'Professor Dashboard'})),))
    report=services.execute_plan(p)
    assert [r.status for r in report.results]==['failed','blocked','completed']
    assert report.status=='partial_failure'
    assert 'PRIVATE' not in str([(r.safe_summary,r.error) for r in report.results])


def test_partial_failure_retry_preserves_success(monkeypatch):
    import document_studio,assessment_studio
    quiz=Mock(return_value=validate_output(raw(),spec(),evidence()));doc=Mock(side_effect=[RuntimeError('private'),DocumentDraft('notice',body=('Notice',))])
    monkeypatch.setattr(assessment_studio,'generate_assessment',quiz);monkeypatch.setattr(document_studio,'generate_draft',doc)
    p=combined();first=services.execute_plan(p);assert first.status=='partial_failure'
    retry=services.execute_plan(p,previous=first,retry=True)
    assert retry.status=='completed' and quiz.call_count==1 and doc.call_count==2
    with pytest.raises(PlanError):services.execute_plan(replace(p,actions=(replace(p.actions[0],parameters_json=json.dumps(dict(assessment_params(),title='Changed'))),p.actions[1])),previous=first,retry=True)

@pytest.mark.parametrize('kind',['CREATE_DOCUMENT','CREATE_ASSESSMENT','ASK_KNOWLEDGE'])
def test_invalid_adapter_output(kind,monkeypatch):
    import document_studio,assessment_studio,student_support_agent
    names={'CREATE_DOCUMENT':(document_studio,'generate_draft',{'document_type':'notice','description':'Draft'}),'CREATE_ASSESSMENT':(assessment_studio,'generate_assessment',assessment_params()),'ASK_KNOWLEDGE':(student_support_agent,'answer_question',{'question':'PCA?'})}
    module,name,params=names[kind];monkeypatch.setattr(module,name,Mock(return_value={'arbitrary':'private'}))
    assert services.execute_plan(plan(action(kind,params))).status=='failed'

@pytest.mark.parametrize('source,target',[('ANALYZE_STUDENTS','CREATE_DOCUMENT'),('ASK_KNOWLEDGE','CREATE_DOCUMENT'),('NAVIGATE','CREATE_DOCUMENT'),('CREATE_DOCUMENT','CREATE_ASSESSMENT')])
def test_forbidden_dependencies(source,target):
    p=plan(action(source,{},identity='a'),action(target,{},identity='b',deps=('a',)))
    with pytest.raises(PlanError):services.validate_plan(p,services.ExecutionContext())


def student_context():
    from test_student_ingestion import raw as rows,mapping
    from student_ingestion import normalize_dataset
    return services.ExecutionContext(normalize_dataset(rows([('SYN01','Synthetic Private Alpha',90,80),('SYN02','Synthetic Private Beta',40,35)]),mapping()))


def test_student_local_filter_no_ai(monkeypatch):
    chat=Mock(side_effect=AssertionError('No student AI'));monkeypatch.setattr(planner.ai_provider,'generate_chat',chat)
    context=student_context();p=planner.plan_request('Show students with attendance concern.',context)
    report=services.execute_plan(p,context);assert report.status=='completed'
    frame,summary=report.results[0].payload
    assert frame.student_id.tolist()==['SYN02'];chat.assert_not_called()
    assert report.results[0].safe_summary=='Completed locally.'

@pytest.mark.parametrize('text_request',['Explain Synthetic Private Alpha marks','Explain SYN01','Send each weak student personalized AI advice','Draft a quiz using student marks','Show attendance spreadsheet'])
def test_student_identifying_requests_never_provider(text_request,monkeypatch):
    chat=Mock();monkeypatch.setattr(planner.ai_provider,'generate_chat',chat)
    with pytest.raises(PlanError):planner.plan_request(text_request,student_context())
    chat.assert_not_called()


def test_context_metadata_has_no_rows(monkeypatch):
    chat=Mock(return_value=json.dumps({'actions':[action()],'unsupported':False}));monkeypatch.setattr(planner.ai_provider,'generate_chat',chat)
    planner.plan_request('Open dashboard',student_context())
    message=str(chat.call_args)
    for token in ['SYN01','SYN02','Synthetic Private','90','35']:assert token not in message


def test_clear_student_releases_assistant_results():
    from student_hub import clear_student_data
    state={'student_validation':student_context().student_dataset,'assistant_report':object(),'assistant_plan':object(),'studio_versions':'keep'}
    clear_student_data(state)
    assert state=={'studio_versions':'keep','student_epoch':1}


def test_navigate_and_stable_order():
    p=plan(action(identity='a'),action(identity='b'))
    report=services.execute_plan(p)
    assert [r.action_id for r in report.results]==['a','b'] and report.status=='completed'


def test_immutable_parameters():
    p=plan(action());params=p.actions[0].parameters;params['page']='shell'
    assert p.actions[0].parameters['page']=='Professor Dashboard'


def test_ten_question_multitask_planner_to_services(monkeypatch):
    import assessment_studio,document_studio
    params=assessment_params();params.update(total_questions=10,total_marks=10,scope=dict(course='C',semester='S',subject='ML',units=['Unit 2']),question_types={'MCQ':10,'Descriptive':0},difficulties={'Easy':4,'Medium':4,'Hard':2},blooms={'Remember':10,'Understand':0,'Apply':0,'Analyze':0,'Evaluate':0,'Create':0})
    actions=[action('CREATE_ASSESSMENT',params),action('CREATE_DOCUMENT',{'document_type':'notice','description':'Announce the quiz'},identity='b',deps=('a',))]
    chat=Mock(return_value=json.dumps({'actions':actions,'unsupported':False}));monkeypatch.setattr(planner.ai_provider,'generate_chat',chat)
    p=planner.plan_request('Create a 10-question Unit 2 quiz with 4 easy, 4 medium, 2 hard, then draft a short announcement.')
    prepared=services.prepare(p.actions[0],services.ExecutionContext())
    generated=validate_output(raw(prepared.plan),prepared,evidence())
    quiz=Mock(return_value=generated);doc=Mock(return_value=DocumentDraft('notice',body=('Announcement',)))
    monkeypatch.setattr(assessment_studio,'generate_assessment',quiz);monkeypatch.setattr(document_studio,'generate_draft',doc)
    report=services.execute_plan(p)
    assert report.status=='completed' and len(report.results[0].payload.questions)==10
    assert dict(quiz.call_args.args[0].difficulties)=={'Easy':4,'Medium':4,'Hard':2}
    assert quiz.call_args.args[0].scope.units==('Unit 2',)
    assert chat.call_count==1


def test_rag_scope_and_sources_preserved(monkeypatch):
    import student_support_agent
    from types import SimpleNamespace
    qa=student_support_agent.QAResult('Grounded synthetic answer',['Synthetic lecture.pdf - Page 2'],SimpleNamespace())
    ask=Mock(return_value=qa);monkeypatch.setattr(student_support_agent,'answer_question',ask)
    filters=dict(course='C',semester='S',subject='ML',unit='Unit 2')
    report=services.execute_plan(plan(action('ASK_KNOWLEDGE',dict(question='What is PCA?',filters=filters))))
    assert report.results[0].payload is qa
    ask.assert_called_once_with('What is PCA?',filters=filters)


def test_document_facts_cannot_be_changed(monkeypatch):
    import document_studio
    monkeypatch.setattr(document_studio,'generate_draft',Mock(return_value=DocumentDraft('notice',date='Invented date',body=('Notice',))))
    report=services.execute_plan(plan(action('CREATE_DOCUMENT',dict(document_type='notice',description='Notice',date='10 October 2026'))))
    assert report.status=='failed'


def test_assessment_invalid_structure_cannot_bypass(monkeypatch):
    import assessment_studio
    valid=validate_output(raw(),spec(),evidence())
    invalid=replace(valid,questions=(replace(valid.questions[0],marks=99),valid.questions[1]))
    monkeypatch.setattr(assessment_studio,'generate_assessment',Mock(return_value=invalid))
    assert services.execute_plan(plan(action('CREATE_ASSESSMENT',assessment_params()))).status=='failed'


def test_thresholds_from_hub_preserved():
    from analytics_agent import Thresholds
    context=replace(student_context(),thresholds=Thresholds(attendance=30))
    report=services.execute_plan(plan(action('ANALYZE_STUDENTS',{'view':'Attendance concern'})),context)
    assert report.results[0].payload[0].empty


def test_no_activity_or_persistence(monkeypatch):
    import db
    log=Mock(side_effect=AssertionError('No raw activity'));monkeypatch.setattr(db,'log_activity',log)
    services.execute_plan(plan(action()))
    log.assert_not_called()
