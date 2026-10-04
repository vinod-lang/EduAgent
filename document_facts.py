"""Explicit version-linked document facts; no prose inference or storage at import."""
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import uuid
import re
from document_models import DocumentError, clean

FIELDS=('date','reference_number','recipient','sender','title','subject','signature','body')
SOURCES=('structured_request','professor_confirmed')

@dataclass(frozen=True)
class DocumentFactExpectation:
    fact_id: str
    field: str
    source: str
    value: str
    required: bool
    created_at: str

    def __post_init__(self):
        try:uuid.UUID(self.fact_id);datetime.fromisoformat(self.created_at)
        except (ValueError,TypeError,AttributeError) as exc:raise DocumentError('Invalid fact identity/timestamp.') from exc
        if self.field not in FIELDS or self.source not in SOURCES or type(self.required) is not bool:raise DocumentError('Invalid confirmed fact.')
        object.__setattr__(self,'value',clean(self.value,'Confirmed fact',2000,True))


def fact(field,value,source='professor_confirmed'):
    return DocumentFactExpectation(str(uuid.uuid4()),field,source,value,True,datetime.now(timezone.utc).isoformat())


def request_facts(request, body_facts=()):
    return tuple(fact(k,getattr(request,k),'structured_request') for k in FIELDS if k!='body' and getattr(request,k,'')) + tuple(fact('body',v,'professor_confirmed') for v in body_facts)


def check_expectations(expectations):
    if not isinstance(expectations,tuple) or len(expectations)>50 or not all(isinstance(f,DocumentFactExpectation) for f in expectations) or len({f.fact_id for f in expectations})!=len(expectations):raise DocumentError('Invalid confirmed fact expectations.')
    fields=[f.field for f in expectations if f.field!='body' and f.required]
    if len(fields)!=len(set(fields)):raise DocumentError('Only one required fact per structured field is allowed.')
    return expectations


def conflicts(draft, expectations):
    check_expectations(expectations)
    body=' '.join(' '.join(draft.body).split())
    return tuple(f for f in expectations if f.required and (not re.search(r'(?<!\w)'+re.escape(' '.join(f.value.split()))+r'(?!\w)',body) if f.field=='body' else getattr(draft,f.field)!=f.value))

class DocumentFactConflict(DocumentError):
    def __init__(self, count):
        self.count=count
        super().__init__('Your edit changed a previously confirmed fact. Resolve the conflict before applying or saving.')


def enforce(draft, expectations):
    changed=conflicts(draft,expectations)
    if changed:raise DocumentFactConflict(len(changed))


def update_fact(expectations,identity,value):
    check_expectations(expectations)
    if not any(f.fact_id==identity for f in expectations):raise DocumentError('Confirmed fact no longer exists.')
    return tuple(replace(f,value=value,source='professor_confirmed',created_at=datetime.now(timezone.utc).isoformat()) if f.fact_id==identity else f for f in expectations)


def remove_fact(expectations,identity):
    if not any(f.fact_id==identity for f in expectations):raise DocumentError('Confirmed fact no longer exists.')
    return tuple(f for f in expectations if f.fact_id!=identity)


def confirm_edit(draft,expectations,body_replacements=None):
    """Explicit professor decision only. Body facts require explicitly supplied replacements."""
    changed=conflicts(draft,expectations)
    updated=expectations
    for f in changed:
        value=(body_replacements or {}).get(f.fact_id) if f.field=='body' else getattr(draft,f.field)
        if not value:raise DocumentError('Enter a replacement confirmed fact or explicitly remove it in fact management.')
        updated=update_fact(updated,f.fact_id,value)
    enforce(draft,updated)
    return updated
