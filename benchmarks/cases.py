"""Synthetic-only fixtures and exact existing feature prompts, captured without storage."""
import json
from pathlib import Path
from dataclasses import asdict,dataclass
from types import SimpleNamespace
from unittest.mock import patch

FIXTURE_PATH=Path(__file__).parent/'fixtures'/'synthetic_v1.json'


def load_fixture():
    data=json.loads(FIXTURE_PATH.read_text())
    if data['version']!='synthetic-v1' or 'Entirely synthetic' not in data['provenance']:raise ValueError('Unknown fixture provenance.')
    ids=[r['id'] for r in data['corpus']]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate corpus IDs.')
    for q in data['retrieval']:
        if not set(q['relevant_ids'])<=set(ids) or q['split'] not in ('calibration','test'):raise ValueError('Invalid ground truth.')
    return data

@dataclass(frozen=True)
class Case:
    case_id:str
    category:str
    messages:tuple
    expected:object
    structured:bool=True


def assessment_spec(count=2):
    from assessment_spec import AssessmentSpec,AssessmentScope,BLOOMS
    return AssessmentSpec('Quiz',AssessmentScope('Benchmark CSE','Semester 7','Machine Learning',('Unit 1',)),{'MCQ':count,'Descriptive':0},{'Easy':count//2,'Medium':count-count//2,'Hard':0},{k:count if k=='Understand' else 0 for k in BLOOMS},count,count,title='Synthetic PCA Quiz',topic='PCA concepts')


def teaching_evidence():
    from retrieval import EvidenceChunk
    return tuple(EvidenceChunk(r['id'],r['text'],.2,source=r['source'],course=r['course'],semester=r['semester'],subject=r['subject'],unit=r['unit'],page=r['page']) for r in load_fixture()['corpus'][:4])


def reference_assessment(spec):
    return json.dumps({'questions':[dict(s.to_dict(),question_text=f'Which PCA concept describes synthetic property {s.question_number}?',options={'A':'Maximum variance','B':'Class labels','C':'Minimum variance','D':'No projection'},correct_answer='A',model_answer='PCA preserves variance.',evidence_ids=['E1']) for s in spec.plan]})


def capture(call,reference,patches):
    captured=[]
    def chat(*,messages,**kwargs):captured.extend(messages);return reference
    from contextlib import ExitStack
    with ExitStack() as stack:
        stack.enter_context(patch('ai_provider.generate_chat',side_effect=chat))
        for name,value in patches:stack.enter_context(patch(name,value))
        call()
    if not captured:raise ValueError('Expected a captured generation prompt.')
    return tuple(captured)


def generative_cases():
    from assistant_planner import SYSTEM
    from assistant_services import ExecutionContext
    from student_support_agent import answer_question,NO_EVIDENCE
    from retrieval import RetrievalResult,RetrievalDiagnostics
    from assessment_studio import generate_assessment
    from document_models import DocumentRequest,DocumentDraft
    from document_studio import generate_draft
    data=load_fixture();cases=[]
    for row in data['planner']:
        messages=({'role':'system','content':SYSTEM},{'role':'user','content':json.dumps({'request':row['request'],'context':ExecutionContext().planner_metadata()})})
        cases.append(Case(row['id'],'planner',messages,row))
    evidence=teaching_evidence()
    retrieval=RetrievalResult(evidence,RetrievalDiagnostics(15,4,0,0,0,4,{'unit':'Unit 1'},'cosine',.65))
    for identity,question,terms in [('qa_pca','What is the main goal of PCA?',['variance']),('qa_scope','Does PCA require class labels?',['unsupervised'])]:
        messages=capture(lambda:answer_question(question,filters={'unit':'Unit 1'}),'Reference answer',[('student_support_agent.retrieve_evidence',lambda *a,**k:retrieval)])
        cases.append(Case(identity,'qa',messages,{'terms':terms,'no_evidence':False,'evidence_ids':[e.chunk_id for e in evidence],'filters':{'unit':'Unit 1'}},False))
    # Model-level abstention stress probe: the application normally returns early
    # without generation on no evidence. This is deliberately labelled separately.
    messages=list(cases[-1].messages)
    messages[1]={'role':'user','content':'Course material:\n\nStudent\'s question: What is the tuition fee?'}
    cases.append(Case('qa_no_evidence_stress','qa',tuple(messages),{'no_evidence':True,'terms':[], 'application_gate':'Production Q&A makes no model call when retrieval is empty.'},False))
    for count in (2,4):
        spec=assessment_spec(count)
        messages=capture(lambda:generate_assessment(spec),reference_assessment(spec),[('assessment_studio.assessment_evidence',lambda *a,**k:evidence)])
        cases.append(Case('assessment_'+str(count),'assessment',messages,{'spec':spec,'evidence':evidence}))
    for identity,kind,description,extra in [('doc_notice','notice','Notify a fictional tutorial on 10 October 2026 at 3:00 PM in Fictional Lab 2.',{'date':'10 October 2026'}),('doc_request','financial_approval','Request approval for a synthetic teaching workshop costing INR 500. Approval has not been granted.',{'recipient':'Fictional Academic Office','reference_number':'SYN-BENCH-01'})]:
        request=DocumentRequest(kind,description,tone='Concise Official',**extra)
        draft=DocumentDraft(kind,body=('Synthetic reference',),**extra)
        preference=SimpleNamespace(category='paragraph_length',instruction='Use at most two short body paragraphs.',scope='document_type')
        messages=capture(lambda:generate_draft(request),draft.to_json(),[('document_preferences.relevant_preferences',lambda _: [preference])])
        cases.append(Case(identity,'document',messages,request))
    return tuple(cases)
