"""Deterministic structured diffs and advisory categories. Never approves anything."""
from dataclasses import dataclass
from difflib import SequenceMatcher
import hashlib
import re
from document_models import DocumentDraft,DocumentError,FIELDS

CATEGORIES=('factual','tone_style','structural','formatting','wording','unknown')
REUSABLE_CATEGORIES=('tone_style','structural','formatting','wording')

@dataclass(frozen=True)
class DocumentChange:
    field: str
    action: str
    before: tuple
    after: tuple
    category: str
    @property
    def candidate_instruction(self):
        # Generic guidance only; never copy source prose/facts into preferences.
        return {'tone_style':'Use concise, natural official wording.','structural':'Use a clear document structure and short paragraphs.','formatting':'Use a clear heading and signature arrangement.','wording':'Use professional, respectful greetings and closings.'}.get(self.category,'')


def category(field,before,after):
    if field in ('recipient','sender','date','reference_number','signature'):return 'factual'
    text=' '.join((*before,*after))
    if re.search(r'\d|[₹$€£]|\b(?:HOD|Dean|November|December|January|February|March|April|May|June|July|August|September|October)\b',text,re.I):return 'factual'
    if field in ('salutation','closing'):return 'wording'
    # Body rewriting can contain names/events with no numbers. Do not infer style.
    return 'unknown'


def document_diff(before,after):
    if not isinstance(before,DocumentDraft) or not isinstance(after,DocumentDraft):raise DocumentError('Diff requires validated drafts.')
    changes=[]
    for field in FIELDS:
        old,new=getattr(before,field),getattr(after,field)
        if old!=new:
            a=(old,) if old else ();b=(new,) if new else ()
            changes.append(DocumentChange(field,'added' if not a else 'removed' if not b else 'changed',a,b,category(field,a,b)))
    for tag,i,j,k,l in SequenceMatcher(None,before.body,after.body,autojunk=False).get_opcodes():
        if tag=='equal':continue
        a,b=before.body[i:j],after.body[k:l]
        changes.append(DocumentChange(f'body[{i}:{j}]','added' if tag=='insert' else 'removed' if tag=='delete' else 'changed',a,b,category('body',a,b)))
    return tuple(changes)


def comparison_key(document_id,before_id,after_id):
    # Version UUIDs identify the comparison even before its first explicit save.
    return hashlib.sha256(f'{before_id}:{after_id}'.encode()).hexdigest()
