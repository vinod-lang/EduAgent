from dataclasses import replace
import pytest
from assessment_spec import AssessmentScope,AssessmentError,BLOOMS
from assessment_fixtures import spec,ID_A,ID_B

def test_valid_deterministic_plan():
    s=spec();assert [q.marks for q in s.plan]==[3,2]
    assert [(q.question_type,q.difficulty,q.bloom_level) for q in s.plan]==[('MCQ','Easy','Remember'),('Descriptive','Medium','Understand')]
    assert sum(q.marks for q in s.plan)==s.total_marks

@pytest.mark.parametrize('changes',[
 {'total_questions':0},{'total_questions':-1},{'total_questions':True},{'total_questions':2.0},
 {'question_types':{'MCQ':-1,'Descriptive':3}}, {'question_types':{'MCQ':1.0,'Descriptive':1}},
 {'question_types':{'MCQ':True,'Descriptive':1}}, {'question_types':{'MCQ':1,'Descriptive':0}},
 {'question_types':{'MCQ':2,'Essay':0}}, {'difficulties':{'Easy':1,'Medium':0,'Hard':0}},
 {'difficulties':{'Easy':1,'Medium':-1,'Hard':2}}, {'blooms':{**{k:0 for k in BLOOMS},'Recall':2}},
 {'blooms':{k:0 for k in BLOOMS}}, {'total_marks':0},{'total_marks':-5},{'total_marks':1},
 {'total_marks':5.0},{'total_marks':True},{'assessment_type':'Unknown'},{'title':' '},{'topic':''},{'scope':None}
])
def test_invalid_spec_rejected(changes):
    with pytest.raises(AssessmentError):spec(**changes)

@pytest.mark.parametrize('marks',[2,3,5,100,9999])
def test_exact_integer_marks(marks):
    s=spec(total_marks=marks)
    assert all(type(q.marks) is int and q.marks>0 for q in s.plan)
    assert sum(q.marks for q in s.plan)==marks

@pytest.mark.parametrize('changes',[{'course':''},{'semester':' '},{'subject':None},{'units':()},{'units':('U1','U1')},{'units':'U1'},{'material_ids':('legacy',)},{'material_ids':(ID_A,ID_A)}])
def test_invalid_scope(changes):
    values=dict(course='C',semester='S',subject='ML',units=('U1',));values.update(changes)
    with pytest.raises(AssessmentError):AssessmentScope(**values)

def test_multi_scope_trim_and_freeze():
    scope=AssessmentScope(' C ',' S ',' ML ',('U2','U1'),(ID_B,ID_A))
    assert scope.units==('U1','U2') and scope.material_ids==(ID_A,ID_B)
    assert scope.base_filters()==dict(course='C',semester='S',subject='ML')
    values={'MCQ':1,'Descriptive':1};s=spec(question_types=values);values['MCQ']=9
    assert s.question_types['MCQ']==1
    with pytest.raises(TypeError):s.question_types['MCQ']=8

@pytest.mark.parametrize('level',BLOOMS)
def test_all_bloom_levels_supported(level):
    s=spec(blooms={k:2 if k==level else 0 for k in BLOOMS})
    assert all(q.bloom_level==level for q in s.plan)
