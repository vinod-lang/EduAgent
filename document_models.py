"""Validated content and session versions; no storage or model work at import."""
from dataclasses import dataclass, replace, asdict
import json

class DocumentError(ValueError):
    pass

# Guidance defines structure, never institutional facts.
CATALOG = {
    'notice': ('Notice', 'announcement', 'State the purpose and action clearly; no letter salutation.'),
    'circular': ('Circular', 'announcement', 'Communicate to an audience with concise instructions.'),
    'official_email': ('Official Email', 'email', 'Use an email subject, recipient, greeting and concise closing.'),
    'official_letter': ('Official Letter', 'letter', 'Use recipient block, subject, salutation and signature.'),
    'request_application': ('Request / Application', 'letter', 'State the request and supporting reasons.'),
    'permission_request': ('Permission Request', 'letter', 'Seek permission; never imply permission was granted.'),
    'financial_approval': ('Financial Approval Request', 'letter', 'Seek approval for supplied costs; never invent amounts or granted approval.'),
    'procurement_request': ('Purchase / Procurement Request', 'letter', 'Describe supplied items and justification; do not invent vendors or prices.'),
    'forwarding_letter': ('Forwarding Letter', 'letter', 'Identify only supplied enclosures and forwarding purpose.'),
    'recommendation': ('Recommendation / Reference', 'letter', 'Use only supplied achievements and relationship facts.'),
    'memo': ('Memo', 'memo', 'Use subject and recipient/sender; no letter salutation or ceremonial closing.'),
    'meeting': ('Meeting Communication', 'announcement', 'Use supplied meeting details and requested action.'),
    'student_communication': ('Student Communication', 'announcement', 'Address the supplied student audience clearly.'),
    'attendance_warning': ('Attendance Warning', 'letter', 'Use supplied attendance facts; do not invent penalties or institutional rules.'),
    'exam_announcement': ('Exam Announcement', 'announcement', 'Use only supplied exam schedule and instructions.'),
    'report_submission': ('Report / Submission', 'report', 'Organize factual paragraphs; do not invent outcomes or findings.'),
    'custom': ('Custom Official Document', 'report', 'Follow professor instructions without inventing institutional facts.')
}
TONES=('Formal & Natural','Concise Official','Detailed Official')
FIELDS=('title','recipient','sender','date','reference_number','subject','salutation','closing','signature')

def clean(value,label,limit=2000,required=False):
    if not isinstance(value,str): raise DocumentError(f'{label} must be text.')
    value=value.strip()
    if required and not value: raise DocumentError(f'{label} is required.')
    if len(value)>limit: raise DocumentError(f'{label} exceeds {limit} characters.')
    if any((ord(c)<32 and c not in '\n\t') or 0xD800<=ord(c)<=0xDFFF for c in value):
        raise DocumentError(f'{label} contains unsupported control characters.')
    return value

@dataclass(frozen=True)
class DocumentRequest:
    document_type: str
    description: str
    tone: str = TONES[0]
    template_id: str = 'standard_academic'
    recipient: str = ''
    sender: str = ''
    title: str = ''
    date: str = ''
    reference_number: str = ''
    subject: str = ''
    signature: str = ''
    additional_context: str = ''

    def __post_init__(self):
        if not isinstance(self.document_type,str) or self.document_type not in CATALOG: raise DocumentError('Unsupported document type.')
        if self.tone not in TONES: raise DocumentError('Unsupported tone.')
        if self.template_id!='standard_academic': raise DocumentError('Unsupported template.')
        for key in ('description','additional_context','recipient','sender','title','date','reference_number','subject','signature'):
            object.__setattr__(self,key,clean(getattr(self,key),key,20000 if key in ('description','additional_context') else 2000,key=='description'))

@dataclass(frozen=True)
class DocumentDraft:
    document_type: str
    title: str = ''
    recipient: str = ''
    sender: str = ''
    date: str = ''
    reference_number: str = ''
    subject: str = ''
    salutation: str = ''
    body: tuple = ()
    closing: str = ''
    signature: str = ''

    def __post_init__(self):
        if not isinstance(self.document_type,str) or self.document_type not in CATALOG: raise DocumentError('Unsupported document type.')
        for key in FIELDS: object.__setattr__(self,key,clean(getattr(self,key),key))
        if not isinstance(self.body,(list,tuple)) or not self.body or len(self.body)>100:
            raise DocumentError('Body must contain 1–100 nonblank paragraphs.')
        paragraphs=tuple(clean(p,'Body paragraph',10000,True) for p in self.body)
        if sum(map(len,paragraphs))>60000: raise DocumentError('Document body exceeds 60000 characters.')
        object.__setattr__(self,'body',paragraphs)
        style=CATALOG[self.document_type][1]
        if style in ('announcement','memo','report') and (self.salutation or self.closing):
            raise DocumentError('This document type does not use a letter salutation or closing.')

    def to_dict(self): return asdict(self)
    def to_json(self): return json.dumps(self.to_dict(),ensure_ascii=False)


def parse_draft(raw,request=None):
    def pairs(items):
        obj={}
        for key,value in items:
            if key in obj: raise DocumentError('Duplicate JSON field.')
            obj[key]=value
        return obj
    try:
        data=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _: (_ for _ in ()).throw(DocumentError('Invalid JSON constant.')))
    except (ValueError,TypeError) as exc: raise DocumentError('AI output must be strict document JSON.') from exc
    expected={'document_type','body',*FIELDS}
    if not isinstance(data,dict) or set(data)!=expected: raise DocumentError('Document JSON has missing or unsupported fields.')
    draft=DocumentDraft(**data)
    if request:
        if draft.document_type!=request.document_type: raise DocumentError('AI changed the document type.')
        for key in ('recipient','sender','date','reference_number','signature'):
            if getattr(draft,key)!=getattr(request,key): raise DocumentError(f'AI changed or invented {key}; use only the supplied optional field.')
        for key in ('title','subject'):
            if getattr(request,key) and getattr(draft,key)!=getattr(request,key): raise DocumentError(f'AI changed supplied {key}.')
    return draft

@dataclass(frozen=True)
class DocumentVersions:
    original: DocumentDraft
    history: tuple
    template_id: str = 'standard_academic'

    def __post_init__(self):
        if not isinstance(self.original,DocumentDraft) or self.template_id!='standard_academic' or not isinstance(self.history,tuple) or not self.history or not all(isinstance(d,DocumentDraft) and d.document_type==self.original.document_type for d in self.history):
            raise DocumentError('Invalid document version history.')
    @classmethod
    def generated(cls,draft,template_id='standard_academic'): return cls(draft,(draft,),template_id)
    @property
    def current(self): return self.history[-1]
    def update(self,draft):
        if draft.document_type!=self.original.document_type: raise DocumentError('Editing cannot change document type.')
        return replace(self,history=self.history+(draft,)) if draft!=self.current else self
    def undo(self): return replace(self,history=self.history[:-1]) if len(self.history)>1 else self
