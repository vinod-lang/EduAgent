"""Deterministic assessment contract and slot arithmetic, independent of AI/storage."""
from dataclasses import dataclass
from types import MappingProxyType
from collections.abc import Mapping
import uuid

TYPES=('MCQ','Descriptive')
DIFFICULTIES=('Easy','Medium','Hard')
BLOOMS=('Remember','Understand','Apply','Analyze','Evaluate','Create')

class AssessmentError(ValueError):
    """Expected specification, evidence or output failure; safe to display."""

class NoAssessmentEvidence(AssessmentError):
    pass


def required_text(value, label, maximum=200):
    if not isinstance(value,str) or not value.strip() or len(value)>maximum or any((ord(c)<32 and c not in '\n\t') or 0xD800<=ord(c)<=0xDFFF for c in value):
        raise AssessmentError(f'{label} requires nonblank text (up to {maximum} characters).')
    return value.strip()


def integer(value,label,minimum=0,maximum=10000):
    if type(value) is not int or not minimum<=value<=maximum:
        raise AssessmentError(f'{label} must be an integer from {minimum} to {maximum}.')
    return value


def counts(value, labels, label):
    if not isinstance(value,Mapping) or set(value)!=set(labels):
        raise AssessmentError(f'{label} must specify exactly: {", ".join(labels)}.')
    return MappingProxyType({key:integer(value[key],f'{label}: {key}',maximum=100) for key in labels})

@dataclass(frozen=True)
class AssessmentScope:
    course: str
    semester: str
    subject: str
    units: tuple[str,...]
    material_ids: tuple[str,...]=()

    def __post_init__(self):
        for key in ('course','semester','subject'):
            object.__setattr__(self,key,required_text(getattr(self,key),key.capitalize()))
        if not isinstance(self.units,(tuple,list)) or not self.units:
            raise AssessmentError('Select at least one Unit.')
        units=tuple(sorted({required_text(v,'Unit') for v in self.units}))
        if len(units)!=len(self.units):raise AssessmentError('Units must be unique.')
        if not isinstance(self.material_ids,(tuple,list)):raise AssessmentError('Materials must be a sequence of UUIDs.')
        ids=[]
        for identity in self.material_ids:
            try:
                if not isinstance(identity,str) or str(uuid.UUID(identity))!=identity:raise ValueError()
            except (ValueError,TypeError,AttributeError) as exc:
                raise AssessmentError('Selected managed materials require canonical UUIDs; legacy IDs are not invented.') from exc
            ids.append(identity)
        if len(set(ids))!=len(ids):raise AssessmentError('Material IDs must be unique.')
        if len(units)*max(1,len(ids))>64:raise AssessmentError('Select fewer Units/materials (maximum 64 scoped retrieval branches).')
        object.__setattr__(self,'units',units);object.__setattr__(self,'material_ids',tuple(sorted(ids)))

    def base_filters(self):
        return dict(course=self.course,semester=self.semester,subject=self.subject)

@dataclass(frozen=True)
class QuestionSlot:
    question_number:int
    question_type:str
    difficulty:str
    bloom_level:str
    marks:int

    def to_dict(self):
        return dict(vars(self))

@dataclass(frozen=True)
class AssessmentSpec:
    assessment_type:str
    scope:AssessmentScope
    question_types:Mapping
    difficulties:Mapping
    blooms:Mapping
    total_questions:int
    total_marks:int
    title:str='Academic Assessment'
    institution:str=''
    instructions:str='Answer all questions.'
    topic:str='Key concepts and applications'

    def __post_init__(self):
        if self.assessment_type not in ('Quiz','Question Paper'):raise AssessmentError('Choose Quiz or Question Paper.')
        if not isinstance(self.scope,AssessmentScope):raise AssessmentError('A validated academic scope is required.')
        integer(self.total_questions,'Total questions',1,100)
        integer(self.total_marks,'Total marks',self.total_questions,10000)
        for field,labels,label in [('question_types',TYPES,'Question types'),('difficulties',DIFFICULTIES,'Difficulty'),('blooms',BLOOMS,'Bloom')]:
            values=counts(getattr(self,field),labels,label)
            if sum(values.values())!=self.total_questions:
                raise AssessmentError(f'{label} total = {sum(values.values())}; expected {self.total_questions} questions.')
            object.__setattr__(self,field,values)
        for field in ('title','topic','instructions'):
            object.__setattr__(self,field,required_text(getattr(self,field),field.capitalize(),1000 if field=='instructions' else 200))
        if not isinstance(self.institution,str) or len(self.institution)>200:raise AssessmentError('Institution must be text up to 200 characters.')
        object.__setattr__(self,'institution',required_text(self.institution,'Institution') if self.institution.strip() else '')

    @property
    def plan(self):
        types=[k for k,n in self.question_types.items() for _ in range(n)]
        difficulty=[k for k,n in self.difficulties.items() for _ in range(n)]
        blooms=[k for k,n in self.blooms.items() for _ in range(n)]
        base,remainder=divmod(self.total_marks,self.total_questions)
        return tuple(QuestionSlot(i+1,t,d,b,base+int(i<remainder)) for i,(t,d,b) in enumerate(zip(types,difficulty,blooms)))
