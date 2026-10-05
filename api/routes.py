"""Routes convert explicit transports and delegate all domain work to services."""
from dataclasses import replace
import secrets
from fastapi import APIRouter,Depends,Request,Response,UploadFile,File,Form
from application.errors import ValidationError,NotFoundError
from application.models import MaterialUpload,KnowledgeRequest
from security.sessions import AuthenticationError,CSRFError
from . import schemas as S,presentation as P
from .dependencies import principal,services,invoke

router=APIRouter()

def binary(data,format):
    types={'pdf':'application/pdf','docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','csv':'text/csv; charset=utf-8'}
    if format not in types:raise ValidationError()
    return Response(data,media_type=types[format],headers={'Content-Disposition':f'attachment; filename="eduagent-export.{format}"'})

def upload_bytes(file,limit=10*1024*1024):
    data=file.file.read(limit+1)
    if len(data)>limit:raise ValidationError()
    return data

@router.get('/health',tags=['System'],response_model=S.StatusResponse,summary='Process health without storage or inference')
def health():return {'status':'ok'}
@router.get('/readiness',tags=['System'],summary='Safe configuration readiness without opening storage',response_model=S.ReadinessResponse)
def readiness(request:Request):return {'status':'configured','authentication':'development-only' if request.app.state.settings.development_auth else 'unavailable','storage_probe':'not performed','production_ready':False}
@router.post('/auth/dev-login',tags=['Authentication'],summary='DEVELOPMENT AUTH ONLY: sign in to a configured seeded identity',response_model=S.LoginResponse)
def login(body:S.DevLogin,request:Request,response:Response):
    cfg=request.app.state.settings
    if not cfg.development_auth:raise AuthenticationError()
    key=request.headers.get('X-Development-Key','')
    if not secrets.compare_digest(key.encode(),cfg.dev_access_key.encode()):raise AuthenticationError()
    # Login CSRF: require JSON, a custom header and configured browser origin.
    origin=request.headers.get('Origin')
    if origin and origin not in cfg.cors_origins:raise CSRFError()
    identity=cfg.dev_identities.get(body.identity)
    if not identity:raise AuthenticationError()
    token,csrf=invoke(request,request.app.state.sessions.issue,identity)
    old=request.cookies.get(cfg.cookie_name)
    if old:
        try:
            previous=request.app.state.sessions.authenticate(old)
            request.app.state.sessions.revoke(previous);request.app.state.workspaces.clear(previous)
        except AuthenticationError:pass
    response.set_cookie(cfg.cookie_name,token,httponly=True,secure=cfg.secure_cookie,samesite='strict',max_age=cfg.session_seconds,path='/api/v1')
    return {'status':'signed_in','authentication':'DEVELOPMENT AUTH ONLY','csrf_token':csrf}
@router.get('/auth/me',tags=['Authentication'],response_model=S.Profile,summary='Current trusted professor identity')
def me(request:Request,p=Depends(principal),api=Depends(services)):
    return P.profile(invoke(request,api.identities.get,p.context.professor_id,context=p.context))
@router.get('/auth/csrf',tags=['Authentication'],summary='Rotate session-bound CSRF token',response_model=S.CSRFResponse)
def csrf(request:Request,p=Depends(principal)):
    return {'csrf_token':invoke(request,request.app.state.sessions.csrf,request.cookies[request.app.state.settings.cookie_name])}
@router.post('/auth/logout',tags=['Authentication'],response_model=S.StatusResponse,summary='Revoke session and clear its ephemeral workspaces')
def logout(request:Request,response:Response,p=Depends(principal)):
    invoke(request,request.app.state.sessions.revoke,p);request.app.state.workspaces.clear(p)
    response.delete_cookie(request.app.state.settings.cookie_name,path='/api/v1',httponly=True,secure=request.app.state.settings.secure_cookie,samesite='strict')
    return {'status':'signed_out'}
@router.get('/system/ai',tags=['System'],summary='Configured AI profile; no model calls',response_model=S.AIStatus)
def ai_status(request:Request,p=Depends(principal)):
    from config import get_ai_profile
    a=invoke(request,get_ai_profile)
    return dict(provider=a.provider,preferred_model=a.preferred_model,effective_model=None,fallback_active=None,embedding=a.embedding_model,candidate_k=a.candidate_k,final_k=a.final_k,threshold=a.distance_threshold,reranker=a.reranker_enabled,router=a.router_enabled)
@router.get('/materials',tags=['Materials'],response_model=list[S.MaterialResponse],summary='List authorized materials')
def materials(request:Request,p=Depends(principal),api=Depends(services)):
    return [P.material(m) for m in invoke(request,api.materials.list_materials,context=p.context)]
@router.get('/materials/hierarchy',tags=['Materials'],summary='Browse authorized academic hierarchy')
def hierarchy(request:Request,p=Depends(principal),api=Depends(services)):
    return invoke(request,api.materials.hierarchy,context=p.context)
@router.get('/materials/{identity}',tags=['Materials'],response_model=S.MaterialDetailResponse,summary='Get one authorized material')
def get_material(identity:str,request:Request,p=Depends(principal),api=Depends(services)):
    record=invoke(request,api.materials.describe,identity,context=p.context)
    return dict(P.material(record),visibility=record['visibility'],can_manage=record['can_manage'])
@router.post('/materials',tags=['Materials'],summary='Upload a private professor material',response_model=S.UploadResponse)
def upload(request:Request,file:UploadFile=File(...),course:str=Form(...),semester:str=Form(...),subject:str=Form(...),unit:str=Form(...),p=Depends(principal),api=Depends(services)):
    h=S.Hierarchy(course=course,semester=semester,subject=subject,unit=unit)
    result=invoke(request,api.materials.upload,MaterialUpload(upload_bytes(file),file.filename or '',h.model_dump()),context=p.context)
    return {'success':result.get('success',False),'duplicate':result.get('duplicate',False),'material':P.material(result['material']) if result.get('success') else None,'message':'Material registered.' if result.get('success') else 'Material was not registered. Review the upload or duplicate selection.'}
@router.patch('/materials/{identity}',tags=['Materials'],response_model=S.MaterialUpdateResponse,summary='Update authorized material hierarchy')
def update_material(identity:str,body:S.Hierarchy,request:Request,p=Depends(principal),api=Depends(services)):
    result=invoke(request,api.materials.edit_hierarchy,identity,body.model_dump(),context=p.context)
    return {'status':'updated' if result.get('success') else 'incomplete','success':bool(result.get('success'))}
@router.delete('/materials/{identity}',tags=['Materials'],summary='Delete authorized material across storage',response_model=S.DeletionResponse)
def delete_material(identity:str,request:Request,p=Depends(principal),api=Depends(services)):
    result=invoke(request,api.materials.delete,identity,context=p.context)
    return {key:result.get(key) for key in ('success','sqlite_deleted','vectors_deleted','file_deleted')}
@router.post('/knowledge/answer',tags=['Knowledge'],response_model=S.Answer,summary='Answer using authorized course evidence')
def answer(body:S.Knowledge,request:Request,p=Depends(principal),api=Depends(services)):
    a=invoke(request,api.knowledge.ask,KnowledgeRequest(body.question,body.filters,body.final_k),context=p.context)
    return dict(answer=a.answer,grounded=bool(a.retrieval.evidence),sources=P.sources(a.retrieval))
@router.post('/knowledge/retrieve',tags=['Knowledge'],summary='Authorized evidence references, without chunk text/distances',response_model=S.RetrievalResponse)
def retrieve(body:S.Knowledge,request:Request,p=Depends(principal),api=Depends(services)):
    a=invoke(request,api.knowledge.retrieve,KnowledgeRequest(body.question,body.filters,body.final_k),context=p.context)
    return {'status':a.status,'sources':P.sources(a),'evidence_count':len(a.evidence)}
@router.post('/assessments/pyq',tags=['Assessments'],response_model=S.Handle,summary='Extract ephemeral session-owned PYQ guidance')
def pyq(request:Request,file:UploadFile=File(...),p=Depends(principal),api=Depends(services)):
    text=invoke(request,api.assessments.extract_pyq,upload_bytes(file),file.filename or '',context=p.context)
    return {'handle':request.app.state.workspaces.put(p,'pyq',text)}
@router.post('/assessments/generate',tags=['Assessments'],summary='Generate validated quiz or question paper',response_model=S.AssessmentResponse)
def assessment(body:S.AssessmentRequest,request:Request,p=Depends(principal),api=Depends(services)):
    from assessment_spec import AssessmentSpec,AssessmentScope
    data=body.model_dump();handle=data.pop('pyq_handle');scope=invoke(request,AssessmentScope,data.pop('course'),data.pop('semester'),data.pop('subject'),tuple(data.pop('units')),tuple(data.pop('material_ids')))
    spec=invoke(request,AssessmentSpec,scope=scope,**data);text=''
    if handle:
        with request.app.state.workspaces.item(p,handle,'pyq') as text:pass
    a=invoke(request,api.assessments.generate,spec,context=p.context,pyq_text=text)
    key=request.app.state.workspaces.put(p,'assessment',a);return P.assessment(a,key)
@router.get('/assessments/{handle}',tags=['Assessments'],response_model=S.AssessmentResponse,summary='Review a session-owned validated assessment')
def assessment_review(handle:str,request:Request,p=Depends(principal),api=Depends(services)):
    with request.app.state.workspaces.item(p,handle,'assessment') as a:
        return P.assessment(invoke(request,api.assessments.review,a,context=p.context),handle)
@router.patch('/assessments/{handle}',tags=['Assessments'],response_model=S.AssessmentResponse,summary='Revalidate explicit professor edits; preserve previous result on failure')
def assessment_edit(handle:str,body:S.AssessmentEdit,request:Request,p=Depends(principal),api=Depends(services)):
    with request.app.state.workspaces.item(p,handle,'assessment') as a:
        updated=invoke(request,api.assessments.edit,a,[q.model_dump() for q in body.questions],body.revision,context=p.context)
        request.app.state.workspaces.update(p,handle,'assessment',updated)
        return P.assessment(updated,handle)
@router.delete('/assessments/{handle}',tags=['Assessments'],response_model=S.StatusResponse,summary='Discard only this session assessment workspace')
def assessment_discard(handle:str,request:Request,p=Depends(principal)):
    request.app.state.workspaces.remove(p,handle,'assessment');return {'status':'discarded'}
@router.get('/assessments/{handle}/export',tags=['Assessments'],summary='Export authorized session assessment')
def assessment_export(handle:str,request:Request,format:str='pdf',answer_key:bool=False,p=Depends(principal),api=Depends(services)):
    with request.app.state.workspaces.item(p,handle,'assessment') as a:return binary(invoke(request,api.assessments.export,a,format,context=p.context,answer_key=answer_key),format)
@router.get('/documents',tags=['Documents'],summary='List private saved draft metadata',response_model=list[S.DraftMetadata])
def documents(request:Request,p=Depends(principal),api=Depends(services)):
    return invoke(request,api.documents.list_drafts,context=p.context)
@router.post('/documents/generate',tags=['Documents'],summary='Generate private validated document workspace',response_model=S.DocumentResponse)
def generate_document(body:S.DocumentRequest,request:Request,p=Depends(principal),api=Depends(services)):
    from document_models import DocumentRequest
    a=invoke(request,api.documents.generate,invoke(request,DocumentRequest,**body.model_dump()),context=p.context)
    handle=request.app.state.workspaces.put(p,'document',a);return P.document(a,handle)
@router.get('/documents/catalog',tags=['Documents'],summary='Authoritative document choices; no storage initialization')
def document_catalog(p=Depends(principal)):
    from document_models import CATALOG,TONES,FIELDS
    from document_facts import FIELDS as FACT_FIELDS
    from document_preferences import SCOPES
    from document_diff import REUSABLE_CATEGORIES
    return dict(types=[dict(value=k,label=v[0],style=v[1]) for k,v in CATALOG.items()],tones=list(TONES),fields=list(FIELDS),fact_fields=list(FACT_FIELDS),preference_scopes=list(SCOPES),preference_categories=list(REUSABLE_CATEGORIES))
@router.get('/documents/{identity}',tags=['Documents'],summary='Load private saved draft into current session',response_model=S.DocumentResponse)
def load_document(identity:str,request:Request,p=Depends(principal),api=Depends(services)):
    a=invoke(request,api.documents.load,identity,context=p.context);key=request.app.state.workspaces.put(p,'document',a);return P.document(a,key)
@router.get('/documents/{identity}/versions',tags=['Documents'],summary='Private version identifiers and timestamps',response_model=list[S.VersionResponse])
def versions(identity:str,request:Request,p=Depends(principal),api=Depends(services)):
    rows=invoke(request,api.documents.history,identity,context=p.context)
    return [{k:r.get(k) for k in ('version_id','version_number','source','created_at')} for r in rows]
@router.get('/document-workspaces/{handle}',tags=['Documents'],response_model=S.DocumentResponse,summary='Read current authorized session document')
def document_review(handle:str,request:Request,p=Depends(principal),api=Depends(services)):
    with request.app.state.workspaces.item(p,handle,'document') as a:
        return P.document(invoke(request,api.documents.review,a,context=p.context),handle)
@router.delete('/document-workspaces/{handle}',tags=['Documents'],response_model=S.StatusResponse,summary='Discard session workspace, preserving any saved document')
def discard_document(handle:str,request:Request,p=Depends(principal)):
    request.app.state.workspaces.remove(p,handle,'document');return {'status':'discarded'}
@router.get('/document-workspaces/{handle}/diff',tags=['Documents'],summary='Deterministic private version comparison')
def document_comparison(handle:str,request:Request,before:int,after:int,p=Depends(principal),api=Depends(services)):
    with request.app.state.workspaces.item(p,handle,'document') as a:
        changes=invoke(request,api.documents.compare,a,before,after,context=p.context)
        return [dict(field=c.field,action=c.action,before=list(c.before),after=list(c.after)) for c in changes]
@router.post('/document-workspaces/{handle}/conflicts',tags=['Documents'],response_model=list[S.FactResponse],summary='Inspect explicit proposed edit conflicts; do not mutate')
def document_conflicts(handle:str,body:S.DocumentEdit,request:Request,p=Depends(principal),api=Depends(services)):
    with request.app.state.workspaces.item(p,handle,'document') as a:
        data=body.model_dump();data['body']=tuple(data['body']);draft=invoke(request,replace,a.versions.current,**data)
        return [dict(fact_id=f.fact_id,field=f.field,value=f.value,source=f.source) for f in invoke(request,api.documents.conflicts,a,draft,context=p.context)]
@router.post('/document-workspaces/{handle}/save',tags=['Documents'],summary='Save private current content and fact history',response_model=S.DocumentResponse)
def save_document(handle:str,body:S.Save,request:Request,p=Depends(principal),api=Depends(services)):
    with request.app.state.workspaces.item(p,handle,'document') as a:
        a=invoke(request,api.documents.save,a,context=p.context,status=body.status);request.app.state.workspaces.update(p,handle,'document',a);return P.document(a,handle)
@router.patch('/document-workspaces/{handle}',tags=['Documents'],summary='Apply explicit professor edits with fact validation',response_model=S.DocumentResponse)
def edit_document(handle:str,body:S.DocumentEdit,request:Request,p=Depends(principal),api=Depends(services)):
    with request.app.state.workspaces.item(p,handle,'document') as a:
        draft=invoke(request,replace,a.versions.current,**body.model_dump(exclude={'body'}),body=tuple(body.body))
        a=invoke(request,api.documents.edit,a,draft,context=p.context);request.app.state.workspaces.update(p,handle,'document',a);return P.document(a,handle)
@router.post('/document-workspaces/{handle}/refine',tags=['Documents'],summary='Refine while protecting confirmed facts',response_model=S.DocumentResponse)
def refine_document(handle:str,body:S.Refine,request:Request,p=Depends(principal),api=Depends(services)):
    with request.app.state.workspaces.item(p,handle,'document') as a:
        a=invoke(request,api.documents.refine,a,body.instruction,context=p.context);request.app.state.workspaces.update(p,handle,'document',a);return P.document(a,handle)
@router.post('/document-workspaces/{handle}/restore',tags=['Documents'],summary='Restore coherent private version and facts',response_model=S.DocumentResponse)
def restore_document(handle:str,body:S.Restore,request:Request,p=Depends(principal),api=Depends(services)):
    with request.app.state.workspaces.item(p,handle,'document') as a:
        a=invoke(request,api.documents.restore,a,body.index,context=p.context);request.app.state.workspaces.update(p,handle,'document',a);return P.document(a,handle)
@router.get('/document-workspaces/{handle}/facts',tags=['Documents'],summary='Explicitly confirmed private document facts',response_model=list[S.FactResponse])
def facts(handle:str,request:Request,p=Depends(principal),api=Depends(services)):
    with request.app.state.workspaces.item(p,handle,'document') as a:
        return [{'fact_id':f.fact_id,'field':f.field,'value':f.value,'source':f.source} for f in invoke(request,api.documents.facts,a,context=p.context)]
@router.post('/document-workspaces/{handle}/facts',tags=['Documents'],summary='Explicitly add, update or remove confirmed facts')
def manage_facts(handle:str,body:S.Fact,request:Request,p=Depends(principal),api=Depends(services)):
    with request.app.state.workspaces.item(p,handle,'document') as a:
        data=body.model_dump();operation=data.pop('operation');identity=data.pop('fact_id');values={'field':body.field,'value':body.value} if operation=='add' else {'fact_id':identity,**({'value':body.value} if operation=='update' else {})}
        a=invoke(request,api.documents.manage_fact,a,operation,context=p.context,**values);request.app.state.workspaces.update(p,handle,'document',a);return {'status':'updated'}
@router.post('/document-workspaces/{handle}/feedback',tags=['Documents'],response_model=S.StatusResponse,summary='Save feedback for an owned saved document version')
def feedback(handle:str,body:S.Feedback,request:Request,p=Depends(principal),api=Depends(services)):
    with request.app.state.workspaces.item(p,handle,'document') as a:invoke(request,api.documents.feedback,a,body.rating,body.note,context=p.context)
    return {'status':'saved'}
@router.get('/document-workspaces/{handle}/export',tags=['Documents'],summary='Export current private professor-reviewed content')
def document_export(handle:str,request:Request,format:str='pdf',p=Depends(principal),api=Depends(services)):
    with request.app.state.workspaces.item(p,handle,'document') as a:return binary(invoke(request,api.documents.export,a,context=p.context,format=format),format)
@router.get('/preferences',tags=['Documents'],summary='List private approved preferences',response_model=list[S.PreferenceResponse])
def preferences(request:Request,p=Depends(principal),api=Depends(services)):
    return [{k:getattr(a,k) for k in ('preference_id','instruction','category','scope','active','approved','document_type','template_id','tone')} for a in invoke(request,api.documents.list_preferences,context=p.context)]
@router.post('/preferences',tags=['Documents'],response_model=S.Handle,summary='Explicitly approve a private preference')
def preference(body:S.Preference,request:Request,p=Depends(principal),api=Depends(services)):
    data=body.model_dump();text=data.pop('instruction');return {'handle':invoke(request,api.documents.approve_preference,text,context=p.context,**data)}
@router.delete('/preferences/{identity}',tags=['Documents'],response_model=S.StatusResponse,summary='Delete private preference')
def delete_preference(identity:str,request:Request,p=Depends(principal),api=Depends(services)):
    invoke(request,api.documents.delete_preference,identity,context=p.context);return {'status':'deleted'}
@router.post('/students/upload',tags=['Students'],summary='Parse ephemeral student file; return sheet names only',response_model=S.BookResponse)
def students_upload(request:Request,file:UploadFile=File(...),p=Depends(principal),api=Depends(services)):
    book=invoke(request,api.students.parse,upload_bytes(file),file.filename or '',context=p.context)
    return {'handle':request.app.state.workspaces.put(p,'student-book',book),'sheets':[s.name for s in book.sheets]}
@router.post('/students/{handle}/normalize',tags=['Students'],response_model=S.Handle,summary='Normalize local student data with explicit mapping')
def student_normalize(handle:str,body:S.StudentMapping,request:Request,p=Depends(principal),api=Depends(services)):
    from student_ingestion import Mapping,Assessment
    with request.app.state.workspaces.item(p,handle,'student-book') as book:
        sheet=next((s for s in book.sheets if s.name==body.sheet),None)
        if sheet is None:raise ValidationError()
        table=invoke(request,api.students.table,sheet,body.header_row,context=p.context)
        mapping=Mapping(body.student_id,body.student_name,body.attendance,tuple(Assessment(**a.model_dump()) for a in body.assessments),body.attendance_scale,body.assessment_number)
        a=invoke(request,api.students.normalize,table,mapping,context=p.context)
        key=request.app.state.workspaces.put(p,'student-data',a)
        request.app.state.workspaces.remove(p,handle,'student-book')
        return {'handle':key}
@router.post('/students/{handle}/analyze',tags=['Students'],summary='Deterministic local student analytics; no persistence or AI',response_model=S.StudentResponse)
def student_analyze(handle:str,body:S.Analyze,request:Request,p=Depends(principal),api=Depends(services)):
    from analytics_agent import Thresholds
    with request.app.state.workspaces.item(p,handle,'student-data') as a:
        result=invoke(request,api.students.analyze,a,Thresholds(body.marks_threshold,body.attendance_threshold),context=p.context,view=body.view,search=body.search)
        return result.to_dict()
@router.post('/students/{handle}/export',tags=['Students'],summary='Export exactly the selected local student view')
def student_export(handle:str,body:S.Analyze,request:Request,p=Depends(principal),api=Depends(services)):
    from analytics_agent import Thresholds
    with request.app.state.workspaces.item(p,handle,'student-data') as a:return binary(invoke(request,api.students.export,a,context=p.context,thresholds=Thresholds(body.marks_threshold,body.attendance_threshold),view=body.view,search=body.search),'csv')
@router.delete('/students/{handle}',tags=['Students'],response_model=S.StatusResponse,summary='Discard an ephemeral student workspace')
def student_clear(handle:str,request:Request,p=Depends(principal)):
    request.app.state.workspaces.clear_student(p,handle)
    return {'status':'cleared'}
@router.post('/assistant/plan',tags=['Assistant'],summary='Plan through the centralized provider and deterministic privacy gates',response_model=S.PlanResponse)
def assistant_plan(body:S.PlanRequest,request:Request,p=Depends(principal),api=Depends(services)):
    from assistant_services import ExecutionContext
    data=None
    if body.student_handle:
        with request.app.state.workspaces.item(p,body.student_handle,'student-data') as data:pass
    ec=ExecutionContext(data);a=invoke(request,api.assistant.plan,body.request,ec,context=p.context)
    handle=request.app.state.workspaces.put(p,'plan',(a,ec,None));return P.plan(a,handle)
@router.get('/assistant/{handle}/preview',tags=['Assistant'],summary='Preview stored plan; client cannot replace plan JSON',response_model=S.PreviewResponse)
def assistant_preview(handle:str,request:Request,p=Depends(principal),api=Depends(services)):
    with request.app.state.workspaces.item(p,handle,'plan') as (a,ec,_):
        result=invoke(request,api.assistant.preview,a,ec,context=p.context)
        return dict(**P.plan(a,handle),valid=not result.unsupported and not result.clarifications,clarifications=[{'action_id':c.action_id,'missing_fields':list(c.missing_fields)} for c in result.clarifications])
@router.post('/assistant/{handle}/execute',tags=['Assistant'],summary='Explicitly execute the stored server-authorized plan',response_model=S.ExecutionResponse)
def assistant_execute(handle:str,body:S.Execute,request:Request,p=Depends(principal),api=Depends(services)):
    if not body.confirmed:raise ValidationError()
    with request.app.state.workspaces.item(p,handle,'plan') as (a,ec,prior):
        if prior and not body.retry:raise ValidationError()
        result=invoke(request,api.assistant.execute,a,ec,context=p.context,previous=prior,retry=body.retry)
        request.app.state.workspaces.update(p,handle,'plan',(a,ec,result));return P.execution(result)
@router.get('/dashboard',tags=['Dashboard'],summary='Authorized deterministic professor workspace',response_model=S.DashboardResponse)
def dashboard(request:Request,p=Depends(principal),api=Depends(services)):
    a=invoke(request,api.dashboard.workspace,context=p.context)
    return dict(material_count=a['material_count'],courses=a['courses'],materials=[P.material(m) for m in a['materials']],saved_drafts=a['saved_drafts'],activity=a['activity'])
@router.get('/activity',tags=['Activity'],summary='Actor-scoped sanitized activity',response_model=list[S.ActivityResponse])
def activity(request:Request,p=Depends(principal),api=Depends(services)):
    return invoke(request,api.activity.recent,context=p.context)

@router.post('/document-workspaces/{handle}/resolve-edit',tags=['Documents'],response_model=S.DocumentResponse,summary='Explicitly resolve changed confirmed facts')
def resolve_edit(handle:str,body:S.ResolveEdit,request:Request,p=Depends(principal),api=Depends(services)):
    with request.app.state.workspaces.item(p,handle,'document') as a:
        data=body.draft.model_dump();data['body']=tuple(data['body']);draft=invoke(request,replace,a.versions.current,**data)
        a=invoke(request,api.documents.resolve_conflict,a,draft,context=p.context,update_confirmed=body.update_confirmed,replacements=body.replacements)
        request.app.state.workspaces.update(p,handle,'document',a);return P.document(a,handle)
@router.patch('/preferences/{identity}',tags=['Documents'],response_model=S.StatusResponse,summary='Update private preference explicitly')
def update_preference(identity:str,body:S.PreferenceUpdate,request:Request,p=Depends(principal),api=Depends(services)):
    invoke(request,api.documents.update_preference,identity,context=p.context,**body.model_dump(exclude_none=True));return {'status':'updated'}
