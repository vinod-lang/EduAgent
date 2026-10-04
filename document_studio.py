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


def generate_draft(request):
    if not isinstance(request,DocumentRequest): raise DocumentError('A validated DocumentRequest is required.')
    payload=asdict(request)
    payload['type_structure']=CATALOG[request.document_type][1]
    payload['type_guidance']=CATALOG[request.document_type][2]
    return parse_draft(ai_provider.generate_chat(messages=[{'role':'system','content':SYSTEM},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}]),request)


def refine_draft(current,instruction):
    if not isinstance(current,DocumentDraft): raise DocumentError('A validated current draft is required.')
    instruction=clean(instruction,'Refinement instruction',20000,True)
    refinement_system=SYSTEM.replace("recipient, sender, date, reference_number, signature must exactly match the optional request fields, even when empty.", "Recipient, sender, date, reference_number and signature come from the CURRENT draft; preserve them unless an explicit change is requested.")
    prompt=refinement_system+"\nRefine the supplied CURRENT draft. Preserve names, dates, amounts, references and event facts unless the professor explicitly requests changes. Retain unchanged optional fields exactly."
    raw=ai_provider.generate_chat(messages=[{'role':'system','content':prompt},{'role':'user','content':json.dumps({'current':current.to_dict(),'instruction':instruction},ensure_ascii=False)}])
    draft=parse_draft(raw)
    if draft.document_type!=current.document_type: raise DocumentError('Refinement changed document type.')
    # Conservative guard for common shortening/style refinements. Semantic fact
    # verification is not claimed; professor review remains essential.
    explicit_change=bool(re.search(r'(?:^|[.;]\s*)(?:please\s+)?(?:change|replace|update|reschedule|correct)\b',instruction,re.I))
    if not explicit_change:
        for key in ('recipient','sender','date','reference_number','signature'):
            if getattr(draft,key)!=getattr(current,key): raise DocumentError(f'Refinement changed {key}. Previous draft retained.')
        numbers=set(re.findall(r'\d+(?:[.,]\d+)*',current.to_json()))
        if not numbers<=set(re.findall(r'\d+(?:[.,]\d+)*',draft.to_json())):
            raise DocumentError('Refinement removed or changed numeric facts. Previous draft retained.')
    return draft
