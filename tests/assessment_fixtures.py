import json
from assessment_spec import AssessmentSpec,AssessmentScope,BLOOMS
from retrieval import EvidenceChunk
from rag_fixtures import Collection,row

ID_A='11111111-1111-4111-8111-111111111111'
ID_B='22222222-2222-4222-8222-222222222222'

def spec(**changes):
    fields=dict(assessment_type='Quiz',scope=AssessmentScope('C','S','ML',('U1',)),question_types={'MCQ':1,'Descriptive':1},
        difficulties={'Easy':1,'Medium':1,'Hard':0},blooms={k:int(k in ('Remember','Understand')) for k in BLOOMS},total_questions=2,total_marks=5,title='Synthetic PCA Assessment')
    fields.update(changes);return AssessmentSpec(**fields)

def evidence():
    return (EvidenceChunk('owned_chunk','PCA projects onto directions of maximum variance; SVM uses a separating margin.',.2,ID_A,'Synthetic lecture.pdf','C','S','ML','U1',2,'PDF'),)

def output(plan=None):
    plan=spec().plan if plan is None else plan
    return {'questions':[dict(s.to_dict(),question_text=f'Synthetic question {s.question_number} about principal components?',
        options={'A':'Maximum variance','B':'Minimum variance','C':'Labels only','D':'No transformation'} if s.question_type=='MCQ' else {},
        correct_answer='A' if s.question_type=='MCQ' else '',model_answer='SUGGESTED_ANSWER: PCA preserves variance.',evidence_ids=['E1']) for s in plan]}

def raw(plan=None):return json.dumps(output(plan))

def collection():
    return Collection([row('owned_chunk','PCA projects onto directions of maximum variance.',metadata=dict(material_id=ID_A,source='Synthetic lecture.pdf',course='C',semester='S',subject='ML',unit='U1'))])
