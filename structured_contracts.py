"""Production grammars synchronized with product enums, registries and slots."""
from document_models import FIELDS,CATALOG
from assistant_models import ACTION_TYPES
from assessment_spec import TYPES,DIFFICULTIES,BLOOMS
from types import SimpleNamespace

def obj(properties,required=None):
    return dict(type='object',properties=properties,required=list(properties) if required is None else required,additionalProperties=False)
def arr(items,**limits):return dict(type='array',items=items,**limits)
TEXT={'type':'string'}

def response_schema(case):
    if case.category=='document':
        return obj(dict(document_type={'const':case.expected.document_type},**{k:TEXT for k in FIELDS},body=arr(TEXT,minItems=1,maxItems=100)))
    if case.category=='assessment':
        props=dict(question_number={'type':'integer'},question_type={'enum':list(TYPES)},question_text=TEXT,options={'type':'object'},correct_answer=TEXT,model_answer=TEXT,difficulty={'enum':list(DIFFICULTIES)},bloom_level={'enum':list(BLOOMS)},marks={'type':'integer','minimum':1},evidence_ids=arr({'enum':[f'E{i+1}' for i in range(len(case.expected['evidence']))]},minItems=1))
        return obj({'questions':arr(obj(props),minItems=case.expected['spec'].total_questions,maxItems=case.expected['spec'].total_questions)})
    if case.category=='planner':
        return obj(dict(actions=arr(obj(dict(action_id={'type':'string','pattern':'^[A-Za-z][A-Za-z0-9_]{0,31}$'},action_type={'enum':list(ACTION_TYPES)},parameters={'type':'object'},depends_on=arr(TEXT))),maxItems=5),unsupported={'type':'boolean'}))
    return None

def strict_contract_schema(case):
    """Stronger generic grammar, never a substitute for product/semantic validation."""
    from assistant_services import REGISTRY
    if case.category=='document':
        schema=response_schema(case)
        for k in ('recipient','sender','date','reference_number','signature'):
            schema['properties'][k]={'const':getattr(case.expected,k)}
        for k in ('title','subject'):
            if getattr(case.expected,k):schema['properties'][k]={'const':getattr(case.expected,k)}
        if CATALOG[case.expected.document_type][1] in ('announcement','memo','report'):
            for k in ('salutation','closing'):schema['properties'][k]={'const':''}
        return schema
    if case.category=='assessment':
        schema=response_schema(case);base=schema['properties']['questions']['items'];slots=[]
        for slot in case.expected['spec'].plan:
            import copy
            q=copy.deepcopy(base)
            for key,value in slot.to_dict().items():q['properties'][key]={'const':value}
            q['properties']['question_text']={'type':'string','minLength':1,'maxLength':6000}
            q['properties']['model_answer']={'type':'string','minLength':1,'maxLength':6000}
            q['properties']['options']=obj({k:{'type':'string','minLength':1,'maxLength':2000} for k in 'ABCD'}) if slot.question_type=='MCQ' else obj({})
            q['properties']['correct_answer']={'enum':list('ABCD')} if slot.question_type=='MCQ' else {'const':''}
            slots.append(q)
        # Standard JSON Schema tuple validation; unsupported runtimes fail visibly.
        schema['properties']['questions'].update(prefixItems=slots,items=False)
        return schema
    if case.category=='planner':
        from dashboard import PAGES
        from document_models import TONES
        num={'type':'integer','minimum':0,'maximum':100}
        scope=obj(dict(course=TEXT,semester=TEXT,subject=TEXT,units=arr(TEXT),material_ids=arr(TEXT)),[])
        parameter_schemas={
            'ASK_KNOWLEDGE':obj(dict(question=TEXT,filters=obj({k:TEXT for k in ('course','semester','subject','unit','material_id','source')},[])),[]),
            'CREATE_ASSESSMENT':obj(dict(assessment_type={'enum':['Quiz','Question Paper']},scope=scope,question_types=obj({k:num for k in TYPES}),difficulties=obj({k:num for k in DIFFICULTIES}),blooms=obj({k:num for k in BLOOMS}),total_questions={'type':'integer','minimum':1},total_marks={'type':'integer','minimum':1},**{k:TEXT for k in ('title','institution','instructions','topic')}),[]),
            'CREATE_DOCUMENT':obj({k:TEXT for k in REGISTRY['CREATE_DOCUMENT'].allowed},[]),
            'ANALYZE_STUDENTS':obj(dict(view={'enum':['All','Concern','Attendance concern','Academic concern','Incomplete']},thresholds=obj({k:{'type':'number','minimum':0} for k in ('marks','attendance','marks_decline','attendance_decline')},[])),[]),
            'NAVIGATE':obj(dict(page={'enum':list(PAGES)}),[])}
        parameter_schemas['CREATE_DOCUMENT']['properties'].update(document_type={'enum':list(CATALOG)},tone={'enum':list(TONES)},template_id={'const':'standard_academic'})
        action_base=response_schema(case)['properties']['actions']['items'];variants=[]
        import copy
        for kind in ACTION_TYPES:
            action=copy.deepcopy(action_base);action['properties']['action_type']={'const':kind};action['properties']['parameters']=parameter_schemas[kind];variants.append(action)
        return dict(type='object',oneOf=[obj(dict(unsupported={'const':True},actions=arr({'oneOf':variants},maxItems=0))),obj(dict(unsupported={'const':False},actions=arr({'oneOf':variants},minItems=1,maxItems=5)))])
    return None


def planner_schema():
    return strict_contract_schema(SimpleNamespace(category='planner'))


def assessment_schema(spec, evidence):
    return strict_contract_schema(SimpleNamespace(category='assessment', expected={'spec':spec,'evidence':evidence}))


def document_schema(request):
    return strict_contract_schema(SimpleNamespace(category='document', expected=request))
