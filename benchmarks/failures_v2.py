"""Deterministic, multi-label diagnostics. Categories never repair/relax contracts."""
from assistant_models import strict_json,parse_plan
from assistant_services import validate_plan,ExecutionContext
from document_models import FIELDS,parse_draft,CATALOG
from assessment_studio import validate_output
from .contracts_v2 import response_schema

CATEGORIES=('invalid_json','wrong_schema','missing_required_fields','extra_forbidden_fields','wrong_enum','wrong_type','invalid_counts_distributions','invalid_action_type','invalid_planner_parameters','invalid_dependency','evidence_reference_violation','factual_preservation_violation','truncated_output','policy_refusal_failure','clarification_failure','wrong_action_selection','invalid_mcq_structure','invalid_answer_key','duplicate_question','other')


def structural_labels(value,schema):
    labels=set();kind=schema.get('type')
    valid={'object':isinstance(value,dict),'array':isinstance(value,list),'string':isinstance(value,str),'integer':type(value)is int,'boolean':type(value)is bool}
    if kind in valid and not valid[kind]:return {'wrong_type'}
    if 'enum' in schema and value not in schema['enum']:labels.add('wrong_enum')
    if isinstance(value,dict) and kind=='object':
        props=schema.get('properties',{})
        if set(schema.get('required',()))-set(value):labels.add('missing_required_fields')
        if schema.get('additionalProperties') is False and set(value)-set(props):labels.add('extra_forbidden_fields')
        for key in set(value)&set(props):labels.update(structural_labels(value[key],props[key]))
    if isinstance(value,list) and kind=='array':
        if len(value)<schema.get('minItems',0) or len(value)>schema.get('maxItems',10**9):labels.add('invalid_counts_distributions')
        for item in value:labels.update(structural_labels(item,schema.get('items',{})))
    return labels

def categorize(case,text,*,output_tokens=None,token_limit=None):
    labels=set()
    try:data=strict_json(text)
    except ValueError:
        labels.add('invalid_json')
        # Explicit cap exhaustion only: never label arbitrary malformed JSON truncated.
        if token_limit and output_tokens is not None and output_tokens>=token_limit:labels.add('truncated_output')
        return sorted(labels)
    if not isinstance(data,dict):return ['wrong_schema','wrong_type']
    labels.update(structural_labels(data,response_schema(case) or {}))
    if case.category=='assessment' and isinstance(data.get('questions'),list):
        from assessment_studio import normalized
        texts=[]
        for q in data['questions']:
            if not isinstance(q,dict):continue
            if q.get('question_type')=='MCQ':
                options=q.get('options')
                if not isinstance(options,dict) or set(options)!=set('ABCD') or not all(isinstance(v,str) and v.strip() for v in options.values()) or len(set(options.values()))!=4:labels.add('invalid_mcq_structure')
                if q.get('correct_answer') not in ('A','B','C','D'):labels.add('invalid_answer_key')
            elif q.get('question_type')=='Descriptive' and q.get('correct_answer')!='':labels.add('invalid_answer_key')
            if isinstance(q.get('question_text'),str):texts.append(normalized(q['question_text']))
        if len(set(texts))!=len(texts):labels.add('duplicate_question')
    expected={'planner':{'actions','unsupported'},'assessment':{'questions'},'document':{'document_type','body',*FIELDS}}.get(case.category)
    if expected:
        if expected-set(data):labels.add('missing_required_fields')
        if set(data)-expected:labels.add('extra_forbidden_fields')
    try:
        if case.category=='planner':
            plan=parse_plan(text,case.expected['request']);validate_plan(plan,ExecutionContext())
        elif case.category=='assessment':validate_output(text,case.expected['spec'],case.expected['evidence'])
        elif case.category=='document':parse_draft(text,case.expected)
    except (ValueError,TypeError,KeyError) as exc:
        msg=str(exc).casefold();labels.add('wrong_schema')
        if any(w in msg for w in ('missing','requires exactly','must specify exactly')):labels.add('missing_required_fields')
        if any(w in msg for w in ('unknown','unsupported fields')):labels.add('extra_forbidden_fields')
        if any(w in msg for w in ('integer','boolean','must be text','must be an object','sequence','array','nonblank','action id')):labels.add('wrong_type')
        if any(w in msg for w in ('distribution','count','question_number','marks does not','deterministic plan')):labels.add('invalid_counts_distributions')
        if 'evidence' in msg:labels.add('evidence_reference_violation')
        if 'dependency' in msg or 'dependencies' in msg:labels.add('invalid_dependency')
        if 'action type' in msg:labels.add('invalid_action_type')
        if any(w in msg for w in ('changed','invented')):labels.add('factual_preservation_violation')
        if any(w in msg for w in ('unsupported document','unsupported tone','choose','enum')):labels.add('wrong_enum')
        if case.category=='planner' and 'wrong_schema' in labels and not labels&{'invalid_action_type','invalid_dependency','missing_required_fields','extra_forbidden_fields','wrong_type'}:labels.add('invalid_planner_parameters')
    return sorted(labels)
