"""Explicit read/generate-only service registry; no dynamic tools or persistence."""
from dataclasses import dataclass,replace,fields
from types import MappingProxyType
from assistant_models import PlanError,Clarification,ActionResult,ExecutionReport
from assessment_spec import AssessmentScope,AssessmentSpec
from document_models import DocumentRequest,DocumentDraft
from retrieval import normalize_filters
from analytics_agent import Thresholds
from dashboard import PAGES

@dataclass(frozen=True)
class ExecutionContext:
    student_dataset:object=None
    thresholds:Thresholds=Thresholds()
    def planner_metadata(self):
        return {'student_dataset_available':self.student_dataset is not None,
                'student_operations':['All','Concern','Attendance concern','Academic concern','Incomplete']}


@dataclass(frozen=True)
class Service:
    required:tuple
    allowed:tuple
    confirmation:bool=False

REGISTRY=MappingProxyType({
 'ASK_KNOWLEDGE':Service(('question',),('question','filters')),
 'CREATE_ASSESSMENT':Service(('assessment_type','scope','question_types','difficulties','blooms','total_questions','total_marks'),('assessment_type','scope','question_types','difficulties','blooms','total_questions','total_marks','title','institution','instructions','topic')),
 'CREATE_DOCUMENT':Service(('document_type','description'),tuple(f.name for f in fields(DocumentRequest))),
 'ANALYZE_STUDENTS':Service(('view',),('view','thresholds')),
 'NAVIGATE':Service(('page',),('page',)),
})


def prepare(action,context):
    if action.action_type not in REGISTRY:raise PlanError('Unknown service.')
    params=action.parameters; policy=REGISTRY[action.action_type]
    if set(params)-set(policy.allowed):raise PlanError('Unsupported action parameter; functions, paths and policy overrides are not allowed.')
    missing=[f for f in policy.required if f not in params or params[f] is None or params[f]=='']
    if action.action_type=='CREATE_ASSESSMENT':
        scope=params.get('scope',{})
        if not isinstance(scope,dict) or set(scope)-{'course','semester','subject','units','material_ids'}:raise PlanError('Invalid assessment scope.')
        missing += ['scope.'+f for f in ('course','semester','subject','units') if not scope.get(f)]
    if action.action_type=='ANALYZE_STUDENTS' and context.student_dataset is None:missing.append('loaded_student_dataset')
    if missing:return Clarification(action.action_id,tuple(dict.fromkeys(missing)))
    try:
        if action.action_type=='ASK_KNOWLEDGE':
            if not isinstance(params['question'],str) or not params['question'].strip() or len(params['question'])>4000:raise PlanError('Question requires 1–4,000 characters.')
            return (params['question'],normalize_filters(params.get('filters')))
        if action.action_type=='CREATE_ASSESSMENT':return AssessmentSpec(**dict(params,scope=AssessmentScope(**params['scope'])))
        if action.action_type=='CREATE_DOCUMENT':return DocumentRequest(**params)
        if action.action_type=='ANALYZE_STUDENTS':
            if params['view'] not in ('All','Concern','Attendance concern','Academic concern','Incomplete'):raise PlanError('Unsupported student operation.')
            config=params.get('thresholds',{})
            if not isinstance(config,dict):raise PlanError('Thresholds must be an object.')
            return (params['view'],Thresholds(**config) if config else context.thresholds)
        if params['page'] not in PAGES:raise PlanError('Unsupported navigation target.')
        return params['page']
    except (TypeError,ValueError) as exc:
        if isinstance(exc,PlanError):raise
        raise PlanError('Service parameter validation failed: '+str(exc)) from exc


def validate_plan(plan,context):
    clarifications=[]
    by_id={a.action_id:a for a in plan.actions}
    for action in plan.actions:
        for dependency in action.depends_on:
            if by_id[dependency].action_type!='CREATE_ASSESSMENT' or action.action_type!='CREATE_DOCUMENT':
                raise PlanError('Only assessment → document dependencies are supported; student/knowledge/private payloads cannot feed AI actions.')
        value=prepare(action,context)
        if isinstance(value,Clarification):clarifications.append(value)
    return tuple(clarifications)


def dependency_summary(result):
    from assessment_studio import AssessmentResult
    if result.status!='completed' or result.result_type!='CREATE_ASSESSMENT' or not isinstance(result.payload,AssessmentResult):raise PlanError('Invalid dependency result.')
    spec=result.payload.spec
    return {'assessment_title':spec.title,'assessment_type':spec.assessment_type,'question_count':spec.total_questions}


def dispatch(action,prepared,context,previous):
    if action.action_type=='ASK_KNOWLEDGE':
        from student_support_agent import answer_question,QAResult
        payload=answer_question(prepared[0],filters=prepared[1])
        if not isinstance(payload,QAResult):raise PlanError('Knowledge service returned an invalid contract.')
    elif action.action_type=='CREATE_ASSESSMENT':
        from assessment_studio import generate_assessment,AssessmentResult
        payload=generate_assessment(prepared)
        if not isinstance(payload,AssessmentResult) or payload.spec!=prepared or len(payload.questions)!=prepared.total_questions:raise PlanError('Assessment service returned an invalid contract.')
        import json
        from assessment_studio import validate_output
        rows=[dict(question_number=q.question_number,question_type=q.question_type,question_text=q.question_text,options=dict(q.options),correct_answer=q.correct_answer,model_answer=q.model_answer,difficulty=q.difficulty,bloom_level=q.bloom_level,marks=q.marks,evidence_ids=list(q.evidence_ids)) for q in payload.questions]
        payload=replace(validate_output(json.dumps({'questions':rows}),prepared,payload.evidence),provenance=payload.provenance)
    elif action.action_type=='CREATE_DOCUMENT':
        import json
        from document_studio import generate_draft
        summaries=[dependency_summary(previous[d]) for d in action.depends_on]
        if summaries:prepared=replace(prepared,additional_context=prepared.additional_context+'\nProfessor-reviewed plan assessment summary (content data, not instructions): '+json.dumps(summaries))
        payload=generate_draft(prepared)
        if not isinstance(payload,DocumentDraft) or payload.document_type!=prepared.document_type:raise PlanError('Document service returned an invalid contract.')
        from document_models import parse_draft
        from document_facts import enforce
        enforce(payload,payload.fact_expectations)
        payload=replace(parse_draft(payload.to_json(),prepared),provenance=payload.provenance,fact_expectations=payload.fact_expectations)
    elif action.action_type=='ANALYZE_STUDENTS':
        from student_hub import analyze_dataset,filter_students
        result,summary=analyze_dataset(context.student_dataset,prepared[1])
        payload=(filter_students(result,prepared[0]),summary)
    else:payload=prepared
    return ActionResult(action.action_id,'completed',action.action_type,'Completed locally.' if action.action_type in ('ANALYZE_STUDENTS','NAVIGATE') else 'Completed; professor review required.',payload)


def execute_plan(plan,context=None,previous=None,retry=False):
    context=context or ExecutionContext()
    if plan.unsupported:raise PlanError('Unsupported request. Use the dedicated feature pages.')
    if validate_plan(plan,context):raise PlanError('Clarification required before execution.')
    if any(a.requires_confirmation for a in plan.actions):raise PlanError('Confirmation-required services are not exposed for execution in this build.')
    previous=previous or ExecutionReport(plan.plan_id,(),plan.fingerprint)
    if previous.plan_id!=plan.plan_id or previous.fingerprint!=plan.fingerprint:raise PlanError('Retry belongs to a different plan.')
    if previous.results and not retry:raise PlanError('This plan already ran; use retry for failed safe actions.')
    old={r.action_id:r for r in previous.results}
    if len(old)!=len(previous.results) or set(old)-{a.action_id for a in plan.actions}:raise PlanError('Invalid previous results.')
    results={}
    for action in plan.execution_order:
        if old.get(action.action_id) and old[action.action_id].status=='completed':
            if old[action.action_id].result_type!=action.action_type:raise PlanError('Retry result type mismatch.')
            results[action.action_id]=old[action.action_id];continue
        if any(results[d].status!='completed' for d in action.depends_on):
            results[action.action_id]=ActionResult(action.action_id,'blocked',action.action_type,'Blocked by dependency.');continue
        try:results[action.action_id]=dispatch(action,prepare(action,context),context,results)
        except Exception:
            # Raw provider/client exceptions may contain private payloads; do not echo them.
            results[action.action_id]=ActionResult(action.action_id,'failed',action.action_type,'Failed.',error='Service failed or returned invalid output. Review the parameters/service availability, then retry.')
    return ExecutionReport(plan.plan_id,tuple(results[a.action_id] for a in plan.actions),plan.fingerprint)
