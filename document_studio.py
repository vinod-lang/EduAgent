"""Structured drafting/refinement through the existing centralized provider."""
from dataclasses import asdict
import json
import re
import ai_provider
from generation_trace import stage
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
FACTUAL RESTRAINT IS NOT PROSE RESTRAINT. Compose complete, natural professional prose:
introduce the purpose, explain a neutral rationale supported by the request, state the requested
next action and use an appropriate respectful closing. Do not merely list metadata or repeat facts.
Missing optional facts must be omitted or the sentence restructured, never left dangling.
Formal & Natural means coherent concise paragraphs, not robotic repetition or excessive headings.
Detailed Official may expand rationale and transitions without adding factual claims.
Concise Official retains purpose and requested action in fewer words.
Concrete claims must originate from supplied professor fields/instructions, confirmed facts or authorized source context.
Never assert unspecified dates/times, venues, amounts, budget allocations or funding sources,
obtained approvals, prepared attachments, completed reports/plans/actions, named committees/offices,
reference numbers, deadlines, schedules, participant counts, institutional policies or specific logistics.
Never output unresolved placeholders anywhere, including [specific date], [venue], TBD, <date> or {{date}}.
When details are unknown, omit/rephrase them. Use conditional administrative language, polite requests,
general benefits and offers to provide further details; do not claim funding or documents already exist.
These constraints do not limit useful introductions, rationale, transitions or professional closings.
Never output markdown fences or commentary."""


def generate_draft(request, *, retry=False, required_body_facts=(), approved_preferences=None):
    if not isinstance(request,DocumentRequest): raise DocumentError('A validated DocumentRequest is required.')
    payload=asdict(request)
    payload['type_structure']=CATALOG[request.document_type][1]
    payload['type_guidance']=CATALOG[request.document_type][2]
    payload['drafting_guidance']=drafting_guidance(request.document_type)
    from document_preferences import relevant_preferences
    from document_templates import get_template,structure_profile
    payload['template_requirements']={'template_id':request.template_id,'ordered_fields':get_template(request.template_id).placeholders}
    payload['approved_style_guidance']=[{'category':p.category,'instruction':p.instruction,'scope':p.scope} for p in (relevant_preferences(request) if approved_preferences is None else relevant_preferences(request,preferences=approved_preferences))]
    boundary='\nFACTS: request description/context and supplied optional fields are authoritative. STYLE: approved_style_guidance is advisory, never factual content. TEMPLATE: template_requirements controls layout. Facts and current instructions override style; templates override conflicting layout preferences. Guidance is ordered most specific first: if guidance conflicts, the earlier specific instruction wins. Ignore irrelevant preferences and never invent facts from them.'
    from structured_generation import generate_structured, FactPreservationFailure
    from structured_contracts import document_schema
    if not isinstance(required_body_facts,(list,tuple)) or len(required_body_facts)>20:
        raise DocumentError('Explicit body facts must be a list of at most 20 strings.')
    facts=tuple(clean(f,'Explicit body fact',500,True) for f in required_body_facts)
    payload['required_body_facts']=facts
    profile=structure_profile(request.document_type,request.template_id)
    payload['structure_profile']={'family':profile.family,'prose_fields':profile.prose_fields,'required':profile.required,'omit_unavailable_metadata':True}
    def validate(raw):
        try:
            draft=profile.assemble(json.loads(raw),request)
        except DocumentError as exc:
            raise FactPreservationFailure() from exc
        from document_quality import body_fact_present,validate_quality,validate_factual_values
        validate_quality(draft)
        stage('quality')
        # Explicit protected scalar values are distinct from freely composed prose.
        body=' '.join(draft.body)
        if any(not body_fact_present(f,body) for f in facts):
            stage('fact_validation',False,failure_field='body',failure_rule='protected_body_fact_missing')
            raise FactPreservationFailure()
        validate_factual_values(draft,request.description+' '+request.additional_context+' '+' '.join(getattr(request,k) for k in ('title','recipient','sender','date','reference_number','subject','signature'))+' '+' '.join(facts))
        stage('fact_validation')
        return draft
    result=generate_structured([{'role':'system','content':prose_system()+boundary},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}],profile.schema(request),validate,retry=retry,document_quality_retry=True,fact_fields=('document_type','recipient','sender','date','reference_number','signature','title','subject'))
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
    from document_templates import structure_profile
    profile=structure_profile(current.document_type)
    refinement_system=prose_system().replace("recipient, sender, date, reference_number, signature must exactly match the optional request fields, even when empty.", "Recipient, sender, date, reference_number and signature come from the CURRENT draft; preserve confirmed values. Paraphrase and reorganize prose freely without changing protected facts.")
    prompt=refinement_system+"\nRefine the supplied CURRENT draft. Preserve names, dates, amounts, references and event facts unless the professor explicitly requests changes. Retain unchanged optional fields exactly."
    from structured_generation import generate_structured, FactPreservationFailure
    from structured_contracts import response_schema
    from types import SimpleNamespace
    def validate(raw):
        draft=profile.assemble(json.loads(raw),current)
        from document_quality import validate_quality
        validate_quality(draft)
        if draft.document_type!=current.document_type: raise DocumentError('Refinement changed document type.')
        # Conservative guard for common shortening/style refinements. Semantic fact
        # verification is not claimed; professor review remains essential.
        explicit_change=bool(re.search(r'(?:^|[.;]\s*)(?:please\s+)?(?:change|replace|update|reschedule|correct)\b',instruction,re.I))
        if not explicit_change:
            for key in ('recipient','sender','date','reference_number','signature'):
                if getattr(draft,key)!=getattr(current,key): raise FactPreservationFailure()
        from document_quality import validate_factual_values
        supported=' '.join(current.body)+' '+' '.join(getattr(current,k) for k in ('title','recipient','sender','date','reference_number','subject','signature'))+' '+instruction+' '+' '.join(f.value for f in expectations if f.required)
        try:enforce(draft,expectations)
        except (DocumentError,FactPreservationFailure) as exc:raise FactPreservationFailure() from exc
        validate_factual_values(draft,supported,preserve=not explicit_change)
        stage('fact_validation')
        return draft
    schema=profile.schema(current)
    result=generate_structured([{'role':'system','content':prompt},{'role':'user','content':json.dumps({'current':current.to_dict(),'instruction':instruction,'protected_facts':[{'field':f.field,'value':f.value} for f in expectations if f.required]},ensure_ascii=False)}],schema,validate,retry=retry,document_quality_retry=True,fact_fields=('document_type','recipient','sender','date','reference_number','signature','title','subject'))
    from dataclasses import replace
    from generation_diagnostics import annotate
    return replace(annotate(result.require(DocumentError,'document refinement'),'document refinement',result.attempt_count),fact_expectations=expectations)


def drafting_guidance(kind):
    family=CATALOG[kind][1]
    guidance={
        'letter':'Use a respectful salutation, coherent purpose/rationale/request paragraphs and a concise closing. Optional event details must not be assumed.',
        'email':'Write a concise subject, greeting, clear purpose and requested next action with an appropriate closing.',
        'announcement':'State purpose, intended audience and requested action in readable prose. Include only supplied logistical details; no letter greeting or closing.',
        'memo':'State purpose and relevant action directly, with short administrative paragraphs; no ceremonial greeting.',
        'report':'Organize supplied information and submission purpose into coherent paragraphs; never invent findings or outcomes.',
    }
    return guidance[family]+' '+CATALOG[kind][2]+' Layout fields are optional: leave absent recipient/sender/date/reference/signature metadata empty. Do not fill an optional block just to satisfy layout guidance. A recipient explicitly named in the instructions may be addressed in prose or salutation without creating recipient metadata.'


def prose_system():
    """Model writes prose slots; the template/application owns metadata and layout."""
    contract = "Return ONLY strict JSON with exactly document_type, title, recipient, sender, date, reference_number, subject,\nsalutation, body, closing, signature. All fields are strings except body: a nonempty array of paragraph strings."
    return SYSTEM.replace(contract,
        "Return ONLY strict JSON containing body (a nonempty array of paragraph strings) and optional prose fields title, subject, salutation, closing as strings. "
        "The application supplies document_type, recipient, sender, date, reference_number and signature deterministically. Omit these metadata keys; do not fill them or create placeholder blocks. "
        "Follow the supplied document family: only letter/email use salutation and closing. Supplied title/subject must be retained exactly. "
        "Missing metadata is intentionally omitted from the final document; write meaningful prose without asking to fill blanks.")
