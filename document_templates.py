"""Safe ordered placeholders; content remains independent of layout."""
from dataclasses import dataclass
from document_models import DocumentDraft,DocumentError,CATALOG,FIELDS

ALLOWED=frozenset((*FIELDS,'body'))
@dataclass(frozen=True)
class DocumentTemplate:
    template_id: str
    label: str
    placeholders: tuple
    margin_inches: float = .85

    def __post_init__(self):
        if not isinstance(self.placeholders,tuple) or any(not isinstance(p,str) or p not in ALLOWED for p in self.placeholders) or len(set(self.placeholders))!=len(self.placeholders) or 'body' not in self.placeholders:
            raise DocumentError('Template contains unsupported, duplicated or missing body placeholders.')
        if not isinstance(self.margin_inches,(int,float)) or not .5<=self.margin_inches<=1.5: raise DocumentError('Invalid template margin.')

    def blocks(self,draft):
        if not isinstance(draft,DocumentDraft): raise DocumentError('Template needs a validated draft.')
        style=CATALOG[draft.document_type][1]
        result=[]
        for field in self.placeholders:
            if field=='title' and style=='email': continue
            if field in ('salutation','closing') and style not in ('letter','email'): continue
            if field=='body': result.extend(('body',paragraph) for paragraph in draft.body)
            elif getattr(draft,field): result.append((field,getattr(draft,field)))
        return tuple(result)

STANDARD=DocumentTemplate('standard_academic','Standard Academic / Institutional',('title','reference_number','date','recipient','sender','subject','salutation','body','closing','signature'))
TEMPLATES={STANDARD.template_id:STANDARD}

def get_template(template_id='standard_academic'):
    try:return TEMPLATES[template_id]
    except (KeyError,TypeError) as exc:raise DocumentError('Unsupported document template.') from exc
