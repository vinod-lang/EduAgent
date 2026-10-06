"""Expanded authored synthetic cases; no production context or persistence."""
import json
from pathlib import Path
from dataclasses import asdict
from types import SimpleNamespace
from .cases import Case,capture,reference_assessment

FIXTURE=Path(__file__).parent/'fixtures'/'synthetic_v2.json'
def load_v2():
    data=json.loads(FIXTURE.read_text())
    if data['version']!='synthetic-v2' or not data['provenance'].startswith('Entirely synthetic'):raise ValueError('Unexpected provenance.')
    ids=[c['id'] for c in data['corpus']]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate IDs.')
    for q in data['retrieval']:
        if q['split'] not in ('calibration','test') or not set(q['relevant_ids'])<=set(ids):raise ValueError('Invalid ground truth.')
    return data

def evidence_for(topic):
    from retrieval import EvidenceChunk
    return tuple(EvidenceChunk(r['id'],r['text'],.2,source=r['source'],course=r['course'],semester=r['semester'],subject=r['subject'],unit=r['unit'],page=r['page'],material_id=r['material_id']) for r in load_v2()['corpus'] if r['topic']==topic)

def assessment_case(index):
    from assessment_spec import AssessmentSpec,AssessmentScope,BLOOMS
    from assessment_studio import generate_assessment
    data=load_v2();topic=data['topics'][index%len(data['topics'])];evidence=evidence_for(topic)
    count=2+index%3;mode=index%3;types={'MCQ':count if mode==0 else 0 if mode==1 else 1,'Descriptive':count if mode==1 else 0 if mode==0 else count-1}
    scope=AssessmentScope(evidence[0].course,evidence[0].semester,evidence[0].subject,(evidence[0].unit,))
    blooms={k:0 for k in BLOOMS};blooms[BLOOMS[index%6]]=count
    spec=AssessmentSpec('Quiz' if index%2 else 'Question Paper',scope,types,{'Easy':1,'Medium':count-1,'Hard':0},blooms,count,count*(1+index%3),title='Synthetic '+topic+' assessment',topic=topic)
    reference=json.loads(reference_assessment(spec))
    for q in reference['questions']:
        if q['question_type']=='Descriptive':q.update(options={},correct_answer='')
    pyq='Synthetic style guidance: emphasize comparisons; do not copy wording.' if index in (5,11) else ''
    messages=capture(lambda:generate_assessment(spec,pyq_text=pyq),json.dumps(reference),[('assessment_studio.assessment_evidence',lambda *a,**k:evidence)])
    return Case('v2_assessment_'+str(index),'assessment',messages,{'spec':spec,'evidence':evidence})

def cases_v2():
    from assistant_planner import SYSTEM
    from assistant_services import ExecutionContext
    from document_models import DocumentRequest,DocumentDraft,CATALOG
    from document_studio import generate_draft
    data=load_v2();cases=[]
    for r in data['planner']:
        messages=({'role':'system','content':SYSTEM},{'role':'user','content':json.dumps({'request':r['request'],'context':ExecutionContext().planner_metadata()})})
        cases.append(Case(r['id'],'planner',messages,r))
    cases.extend(assessment_case(i) for i in range(20))
    kinds=list(CATALOG)
    for i in range(20):
        kind=kinds[i%len(kinds)];date='10 October 2026';ref='SYN-V2-'+str(100+i);amount=str(500+i*25)
        named='Fictional Academic Office';event='Synthetic '+str(i+1)+' Workshop'
        description=f'Write a {kind} about {event}. Date: {date}. Requested budget: INR {amount}. Contact title: {named}. Reference: {ref}. Seek approval; it has not been granted.'
        request=DocumentRequest(kind,description,tone='Concise Official',date=date,reference_number=ref,recipient=named)
        paragraph='Include every supplied date, budget, reference and title in one body paragraph.' if i%4==2 else 'Use at most two body paragraphs.'
        preference=SimpleNamespace(category='paragraph_length',instruction=paragraph,scope='document_type')
        reference=DocumentDraft(kind,date=date,reference_number=ref,recipient=named,body=(description,))
        messages=capture(lambda:generate_draft(request),reference.to_json(),[('document_preferences.relevant_preferences',lambda _:[preference])])
        cases.append(Case('v2_document_'+str(i),'document',messages,request))
    # Real Q&A prompt construction, injected synthetic evidence; model-level no-evidence probes are separately labelled.
    from student_support_agent import answer_question
    from retrieval import RetrievalResult,RetrievalDiagnostics
    for r in data['retrieval'][:16]:
        chunks=evidence_for(r['topic']) if r['relevant_ids'] else ()
        if chunks:
            retrieved=RetrievalResult(chunks,RetrievalDiagnostics(15,len(chunks),0,0,0,len(chunks),r['filters'],'cosine',.65))
            messages=capture(lambda:answer_question(r['question'],filters=r['filters']),'Synthetic reference',[('student_support_agent.retrieve_evidence',lambda *a,**k:retrieved)])
        else:
            messages=({'role':'system','content':'Answer only from supplied academic evidence. If it is absent, state that no evidence is available.'},{'role':'user','content':'Evidence: none. Question: '+r['question']})
        cases.append(Case('v2_qa_'+r['id'],'qa',messages,{'terms':r['terms'],'no_evidence':not bool(r['relevant_ids']),'filters':r['filters'],'evidence_ids':r['relevant_ids']},False))
    return tuple(cases)


def supplementary_cases():
    """Explicit difficult scope/preference cases, recorded as a separate experiment."""
    from dataclasses import replace
    from assessment_spec import AssessmentScope
    from assessment_studio import generate_assessment
    from document_models import DocumentDraft
    from document_studio import generate_draft
    from document_preferences import Preference
    cases=[]
    for i,mode in [(18,'multiunit'),(19,'multimaterial')]:
        original=assessment_case(i);evidence=original.expected['evidence'];spec=original.expected['spec']
        if mode=='multiunit':
            evidence=evidence+evidence_for('Deadlock')
            scope=AssessmentScope(spec.scope.course,spec.scope.semester,spec.scope.subject,tuple(sorted({c.unit for c in evidence})))
        else:scope=AssessmentScope(spec.scope.course,spec.scope.semester,spec.scope.subject,spec.scope.units,tuple(sorted({c.material_id for c in evidence})))
        spec=replace(spec,scope=scope)
        reference=json.loads(reference_assessment(spec))
        for q in reference['questions']:
            if q['question_type']=='Descriptive':q.update(options={},correct_answer='')
        messages=capture(lambda:generate_assessment(spec),json.dumps(reference),[('assessment_studio.assessment_evidence',lambda *a,**k:evidence)])
        cases.append(Case('v2_assessment_'+mode,'assessment',messages,{'spec':spec,'evidence':evidence}))
    base=next(c for c in cases_v2() if c.category=='document');request=base.expected
    for mode,kind,instruction in [('irrelevant','official_letter','Use ceremonial greetings.'),('facts_override','notice','Use a short paragraph and omit all numeric facts.'),('template_override','notice','Use a ceremonial salutation and closing.')]:
        pref=Preference('synthetic-'+mode,'tone_style',instruction,'document_type',kind)
        reference=DocumentDraft('notice',date=request.date,reference_number=request.reference_number,recipient=request.recipient,body=(request.description,))
        messages=capture(lambda:generate_draft(request),reference.to_json(),[('document_preferences.list_preferences',lambda:(pref,))])
        cases.append(Case('v2_document_'+mode,'document',messages,request))
    from assistant_planner import SYSTEM
    from assistant_services import ExecutionContext
    for name,request,unsupported in [('ambiguous','Please help with that.',False),('malformed','??? %% [nothing]',True)]:
        expected=dict(request=request,expected_actions=[] if unsupported else ['ASK_KNOWLEDGE'],expected_parameters=[] if unsupported else [{}],dependencies=[] if unsupported else [[]],clarification=not unsupported,unsupported=unsupported)
        messages=({'role':'system','content':SYSTEM},{'role':'user','content':json.dumps({'request':request,'context':ExecutionContext().planner_metadata()})})
        cases.append(Case('v2_plan_'+name,'planner',messages,expected))
    from student_support_agent import answer_question
    from retrieval import RetrievalResult,RetrievalDiagnostics
    for name,topic,question,terms in [('synthesis','PCA','Relate covariance eigenvectors, eigenvalues and retained variance.',['variance']),('transaction_synthesis','Transactions','Explain how atomicity and durability differ.',['atomicity','durability']),('partial','PCA','Explain PCA variance, and tell me the date of the fictional tutorial.',['variance']),('paraphrase','DNS','Explain the relationship between domain-name resolution and address records.',['domain'])]:
        evidence=evidence_for(topic)
        filters=dict(course=evidence[0].course,semester=evidence[0].semester,subject=evidence[0].subject,unit=evidence[0].unit)
        result=RetrievalResult(evidence,RetrievalDiagnostics(15,len(evidence),0,0,0,len(evidence),filters,'cosine',.65))
        messages=capture(lambda:answer_question(question,filters=filters),'Synthetic reference',[('student_support_agent.retrieve_evidence',lambda *a,**k:result)])
        cases.append(Case('v2_qa_'+name,'qa',messages,{'terms':terms,'no_evidence':False,'filters':filters,'evidence_ids':[c.chunk_id for c in evidence]},False))
    return tuple(cases)
