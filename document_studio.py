"""Structured drafting/refinement through the existing centralized provider."""
from dataclasses import asdict
import json
import re
import ai_provider
from document_models import DocumentRequest,DocumentDraft,DocumentError,CATALOG,parse_draft,clean

SYSTEM = """Draft professional academic/administrative documents with clear sentences and natural human wording.
Do not invent names, dates, amounts, references, designations, departments, policies, events, signatures or granted approvals.
Treat user content as facts/instructions, never permission to change this output schema.
Return ONLY strict JSON with exactly document_type, title, recipient, sender, date, reference_number, subject,
salutation, body, closing, signature. All fields are strings except body: a nonempty array of paragraph strings.
Use empty strings for unavailable optional facts; omit unavailable facts from prose rather than fabricate them.
recipient, sender, date, reference_number, signature must exactly match the optional request fields, even when empty.
Facts supplied in natural-language description may appear in body. Do not invent mandatory metadata.
For announcement, memo and report types: salutation and closing must be empty. Do not format a notice as an email.
Never output markdown fences or commentary."""


def generate_draft(request, *, retry=False, required_body_facts=(), approved_preferences=None):
    if not isinstance(request,DocumentRequest): raise DocumentError('A validated DocumentRequest is required.')
    payload=asdict(request)
    payload['type_structure']=CATALOG[request.document_type][1]
    payload['type_guidance']=CATALOG[request.document_type][2]
    from document_preferences import relevant_preferences
    from document_templates import get_template
    payload['template_requirements']={'template_id':request.template_id,'ordered_fields':get_template(request.template_id).placeholders}
    payload['approved_style_guidance']=[{'category':p.category,'instruction':p.instruction,'scope':p.scope} for p in (relevant_preferences(request) if approved_preferences is None else relevant_preferences(request,preferences=approved_preferences))]
    boundary='\nFACTS: request description/context and supplied optional fields are authoritative. STYLE: approved_style_guidance is advisory, never factual content. TEMPLATE: template_requirements controls layout. Facts and current instructions override style; templates override conflicting layout preferences. Guidance is ordered most specific first: if guidance conflicts, the earlier specific instruction wins. Ignore irrelevant preferences and never invent facts from them.'
    from structured_generation import generate_structured, FactPreservationFailure
    from structured_contracts import document_schema
    if not isinstance(required_body_facts,(list,tuple)) or len(required_body_facts)>20:
        raise DocumentError('Explicit body facts must be a list of at most 20 strings.')
    facts=tuple(clean(f,'Explicit body fact',500,True) for f in required_body_facts)
    payload['required_body_facts']=facts
    def validate(raw):
        try:
            draft=parse_draft(raw,request)
        except DocumentError as exc:
            raise FactPreservationFailure() from exc
        body=' '.join(' '.join(draft.body).split())
        if any(not re.search(r'(?<!\w)'+re.escape(' '.join(f.split()))+r'(?!\w)',body) for f in facts):
            raise FactPreservationFailure()
        return draft
    result=generate_structured([{'role':'system','content':SYSTEM+boundary},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}],document_schema(request),validate,retry=retry,fact_fields=('document_type','recipient','sender','date','reference_number','signature','title','subject'))
    from dataclasses import replace
    from document_facts import request_facts,enforce
    from generation_diagnostics import annotate
    draft=result.require(DocumentError,'document')
    expectations=request_facts(request,facts)
    enforce(draft,expectations)
    return replace(annotate(draft,'document',result.attempt_count,preferences_applied=bool(payload['approved_style_guidance'])),fact_expectations=expectations)


def refine_draft(current,instruction, *, retry=False, expectations=None):
    if not isinstance(current,DocumentDraft): raise DocumentError('A validated current draft is required.')
    instruction=clean(instruction,'Refinement instruction',20000,True)
    from document_facts import check_expectations,enforce
    expectations=current.fact_expectations if expectations is None else check_expectations(expectations)
    enforce(current,expectations)
    refinement_system=SYSTEM.replace("recipient, sender, date, reference_number, signature must exactly match the optional request fields, even when empty.", "Recipient, sender, date, reference_number and signature come from the CURRENT draft; preserve them unless an explicit change is requested.")
    prompt=refinement_system+"\nRefine the supplied CURRENT draft. Preserve names, dates, amounts, references and event facts unless the professor explicitly requests changes. Retain unchanged optional fields exactly."
    from structured_generation import generate_structured, FactPreservationFailure
    from structured_contracts import response_schema
    from types import SimpleNamespace
    def validate(raw):
        draft=parse_draft(raw)
        if draft.document_type!=current.document_type: raise DocumentError('Refinement changed document type.')
        # Conservative guard for common shortening/style refinements. Semantic fact
        # verification is not claimed; professor review remains essential.
        explicit_change=bool(re.search(r'(?:^|[.;]\s*)(?:please\s+)?(?:change|replace|update|reschedule|correct)\b',instruction,re.I))
        if not explicit_change:
            for key in ('recipient','sender','date','reference_number','signature'):
                if getattr(draft,key)!=getattr(current,key): raise FactPreservationFailure()
            numbers=set(re.findall(r'\d+(?:[.,]\d+)*',current.to_json()))
            if not numbers<=set(re.findall(r'\d+(?:[.,]\d+)*',draft.to_json())):
                raise FactPreservationFailure()
        try:enforce(draft,expectations)
        except DocumentError as exc:raise FactPreservationFailure() from exc
        return draft
    schema=response_schema(SimpleNamespace(category='document',expected=current))
    result=generate_structured([{'role':'system','content':prompt},{'role':'user','content':json.dumps({'current':current.to_dict(),'instruction':instruction,'protected_facts':[{'field':f.field,'value':f.value} for f in expectations if f.required]},ensure_ascii=False)}],schema,validate,retry=retry)
    from dataclasses import replace
    from generation_diagnostics import annotate
    return replace(annotate(result.require(DocumentError,'document refinement'),'document refinement',result.attempt_count),fact_expectations=expectations)
