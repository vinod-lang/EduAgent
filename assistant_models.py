"""Strict immutable assistant plans. Status and confirmation belong to local policy."""
from dataclasses import dataclass, field
import json
import re
import uuid

MAX_ACTIONS=5
ACTION_TYPES=('ASK_KNOWLEDGE','CREATE_ASSESSMENT','CREATE_DOCUMENT','ANALYZE_STUDENTS','NAVIGATE')

class PlanError(ValueError):
    pass

class UnsupportedPlanError(PlanError):
    pass


def strict_json(raw):
    if not isinstance(raw,str) or len(raw)>30000:raise PlanError('Plan must be JSON text up to 30,000 characters.')
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise PlanError('Duplicate JSON field.')
            result[key]=value
        return result
    try:return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(PlanError('Nonfinite JSON value.')))
    except (ValueError,RecursionError) as exc:raise PlanError('Planner returned malformed or unsupported JSON.') from exc


@dataclass(frozen=True)
class PlannedAction:
    action_id:str
    action_type:str
    parameters_json:str
    depends_on:tuple=()

    def __post_init__(self):
        if not isinstance(self.action_id,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,31}',self.action_id):raise PlanError('Invalid action ID.')
        if self.action_type not in ACTION_TYPES:raise PlanError('Unsupported action type.')
        if not isinstance(self.depends_on,tuple) or any(not isinstance(v,str) for v in self.depends_on) or len(set(self.depends_on))!=len(self.depends_on):raise PlanError('Invalid dependencies.')
        if not isinstance(strict_json(self.parameters_json),dict):raise PlanError('Parameters must be an object.')

    @property
    def parameters(self):return strict_json(self.parameters_json)

    @property
    def requires_confirmation(self):
        # Registry exposes no persistent mutations; planner cannot supply this field.
        from assistant_services import REGISTRY
        return REGISTRY[self.action_type].confirmation


@dataclass(frozen=True)
class ActionPlan:
    plan_id:str
    original_request:str
    actions:tuple
    unsupported:bool=False
    provenance:object=field(default=None,compare=False,repr=False)

    def __post_init__(self):
        try:uuid.UUID(self.plan_id)
        except (ValueError,TypeError,AttributeError) as exc:raise PlanError('Invalid plan ID.') from exc
        if not isinstance(self.original_request,str) or not self.original_request.strip() or len(self.original_request)>4000:raise PlanError('Request requires 1–4,000 characters.')
        if type(self.unsupported)is not bool or not isinstance(self.actions,tuple) or len(self.actions)>MAX_ACTIONS or not all(isinstance(a,PlannedAction) for a in self.actions):raise PlanError('Invalid plan; maximum five actions.')
        if self.unsupported and self.actions or not self.unsupported and not self.actions:raise PlanError('Unsupported plans cannot contain executable actions.')
        seen=set()
        for action in self.actions:
            if action.action_id in seen:raise PlanError('Duplicate action ID.')
            if any(d not in seen for d in action.depends_on):raise PlanError('Dependency must refer to an earlier action; missing/self/forward/cyclic dependencies are rejected.')
            seen.add(action.action_id)

    @property
    def fingerprint(self):
        import hashlib
        return hashlib.sha256(json.dumps([(a.action_id,a.action_type,a.parameters,a.depends_on) for a in self.actions],sort_keys=True).encode()).hexdigest()

    @property
    def execution_order(self):return self.actions # strict earlier-only dependencies give a stable topological order


@dataclass(frozen=True)
class Clarification:
    action_id:str
    missing_fields:tuple


@dataclass(frozen=True)
class ActionResult:
    action_id:str
    status:str
    result_type:str
    safe_summary:str
    payload:object=None
    error:str=''

    def __post_init__(self):
        if self.status not in ('completed','failed','blocked','cancelled'):raise PlanError('Invalid action result status.')
        if self.result_type not in ACTION_TYPES:raise PlanError('Invalid action result type.')
        if self.safe_summary not in ('Completed; professor review required.','Completed locally.','Failed.','Blocked by dependency.','Cancelled.'):raise PlanError('Result summary must use local privacy-safe labels.')


@dataclass(frozen=True)
class ExecutionReport:
    plan_id:str
    results:tuple
    fingerprint:str=''
    @property
    def status(self):
        if all(r.status=='completed' for r in self.results):return 'completed'
        return 'partial_failure' if any(r.status=='completed' for r in self.results) else 'failed'


def parse_plan(raw,request):
    data=strict_json(raw)
    if not isinstance(data,dict) or set(data)!={'actions','unsupported'} or not isinstance(data['actions'],list):raise PlanError('Plan requires exactly actions and unsupported.')
    actions=[]
    for item in data['actions']:
        if not isinstance(item,dict) or set(item)!={'action_id','action_type','parameters','depends_on'} or not isinstance(item['parameters'],dict) or not isinstance(item['depends_on'],list):raise PlanError('Action has missing/unsupported fields.')
        actions.append(PlannedAction(item['action_id'],item['action_type'],json.dumps(item['parameters']),tuple(item['depends_on'])))
    return ActionPlan(str(uuid.uuid4()),request,tuple(actions),data['unsupported'])
