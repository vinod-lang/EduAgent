"""Protected application entry points. Every operation needs an explicit caller context."""
from dataclasses import dataclass,replace,field
from .errors import call,NotFoundError,ValidationError,StorageError,UnsupportedOperationError
from ._dependencies import dependency
from .models import KnowledgeRequest,StudentAnalysis
from security.models import Action,Ownership,Scope,DocumentWorkspace,StudentWorkspace,ScopedExecutionReport
from security.policy import AuthorizationPolicy,IdentityService,AccessDeniedError
from security.repository import SecurityRepository
from security.retrieval import AuthorizedCollection

class Protected:
    def __init__(self,policy):self.policy=policy;self.security=policy.repository
    def actor(self,context):return self.policy.actor(context)
    def private(self,context,action=Action.CREATE,kind='document'):
        own=self.policy.private(context);self.policy.require(context,action,own,kind=kind);return own

class ScopedMaterials(Protected):
    def __init__(self,base,policy):super().__init__(policy);self.base=base
    def list_materials(self,course=None,*,context=None):
        ids=self.policy.visible_ids(context,'material')
        return call(self.base._repo().list_materials,course,authorized_ids=ids)
    def get(self,identity,*,context=None):
        self.policy.resource(context,Action.READ,'material',identity)
        return self.base.get(identity)
    def describe(self,identity,*,context=None):
        ownership=self.policy.resource(context,Action.READ,'material',identity)
        record=self.base.get(identity)
        return dict(record,visibility=ownership.visibility_scope.value,
                    can_manage=self.policy.allows(context,Action.UPDATE,ownership) and self.policy.allows(context,Action.DELETE,ownership))
    def courses(self,*,context=None):return sorted({m['course'] for m in self.list_materials(context=context)})
    def hierarchy(self,*,context=None):
        from dashboard import build_material_tree
        return build_material_tree(self.list_materials(context=context),self.courses(context=context))
    def scope_records(self,*,context=None):return self.list_materials(context=context)
    def upload(self,request,*,context=None,ownership=None):
        ownership=self.private(context,kind='material') if ownership is None else ownership
        self.policy.require(context,Action.CREATE,ownership)
        # Policy-generated typed metadata; caller cannot override hierarchy/chunk IDs.
        result=self.base._outcome(call(self.base._lifecycle().upload_material,request.content,request.filename,request.hierarchy,
            uploads=self.base.uploads,vectors=self.base.vectors,extractor=self.base.extractor,ownership_metadata=ownership.vector_metadata()))
        if result.get('duplicate'):
            record=result.get('existing_material',{})
            if not self.policy.allows(context,Action.READ,self.security.ownership('material',record.get('material_id'))):
                return {'success':False,'error':'Upload could not be registered.','warnings':[]}
        return result
    def edit_hierarchy(self,identity,hierarchy,*,context=None):
        self.policy.resource(context,Action.UPDATE,'material',identity)
        return self.base.edit_hierarchy(identity,hierarchy)
    def delete(self,identity,*,context=None):
        self.policy.resource(context,Action.DELETE,'material',identity)
        result=self.base.delete(identity)
        if result.get('success'):call(self.security.remove_ownership,'material',identity)
        return result
    def share(self,identity,ownership,*,context=None):
        old=self.policy.resource(context,Action.SHARE,'material',identity)
        if ownership.owner_professor_id!=old.owner_professor_id:raise AccessDeniedError()
        self.policy.require(context,Action.CREATE,ownership)
        # Authoritative companion ownership is changed atomically; vector labels are
        # informational creation metadata and never permission authority.
        call(self.security.change_ownership,'material',identity,old,ownership)

class ScopedKnowledge(Protected):
    def __init__(self,base,policy,collection_factory):super().__init__(policy);self.base=base;self.collection_factory=collection_factory
    def review_scope(self,workspace,*,context=None):
        from .models import KnowledgeHandoff
        if not isinstance(workspace,KnowledgeHandoff):raise AccessDeniedError()
        self.policy.require(context,Action.READ,workspace.ownership,kind='document')
        if workspace.request.filters.get('material_id'):self.policy.resource(context,Action.READ,'material',workspace.request.filters['material_id'])
        return workspace.request
    def collection(self,context,filters=None):
        ids=self.policy.visible_ids(context,'material')
        if filters and filters.get('material_id'):
            self.policy.resource(context,Action.READ,'material',filters['material_id'])
        return AuthorizedCollection(ids,self.collection_factory,verify=lambda selected:set(selected)<=set(self.policy.visible_ids(context,'material')))
    def retrieve(self,request,*,context=None):
        from retrieval import retrieve_evidence
        return call(retrieve_evidence,request.question,request.filters,final_k=request.final_k,collection=self.collection(context,request.filters))
    def ask(self,request,*,context=None):
        from retrieval import retrieve_evidence
        collection=self.collection(context,request.filters)
        retriever=lambda question,filters,**kw:retrieve_evidence(question,filters,collection=collection,**kw)
        return call(dependency(self.base.agent,'student_support_agent').answer_question,request.question,
                    n_chunks=request.final_k,filters=request.filters,retriever=retriever)

class ScopedAssessments(Protected):
    def __init__(self,base,policy,knowledge):super().__init__(policy);self.base=base;self.knowledge=knowledge
    def generate(self,spec,*,context=None,pyq_text='',retry=False):
        self.actor(context)
        for identity in spec.scope.material_ids:self.policy.resource(context,Action.GENERATE,'material',identity)
        result=self.base.generate(spec,pyq_text=pyq_text,retry=retry,collection=self.knowledge.collection(context))
        return AssessmentWorkspace(result,self.private(context,kind='document'),pyq_text=pyq_text)
    def review(self,workspace,*,context=None):
        if not isinstance(workspace,AssessmentWorkspace):raise AccessDeniedError()
        self.policy.require(context,Action.READ,workspace.ownership,kind='document')
        for chunk in workspace.result.evidence:self.policy.resource(context,Action.READ,'material',chunk.material_id)
        return workspace
    def edit(self,workspace,edits,revision,*,context=None):
        self.review(workspace,context=context)
        self.policy.require(context,Action.UPDATE,workspace.ownership,kind='document')
        from .errors import ConflictError
        if revision!=workspace.revision:raise ConflictError()
        result=self.base.edit(workspace.result,edits,pyq_text=workspace.pyq_text)
        return replace(workspace,result=result,revision=workspace.revision+1)
    def extract_pyq(self,data,filename,*,context=None):self.actor(context);return self.base.extract_pyq(data,filename)
    def export(self,workspace,format='pdf',*,context=None,answer_key=False):
        self.review(workspace,context=context)
        self.policy.require(context,Action.EXPORT,workspace.ownership,kind='document')
        return self.base.export(workspace.result,format,answer_key=answer_key)

@dataclass(frozen=True)
class AssessmentWorkspace:
    result: object
    ownership: Ownership
    revision: int = 0
    pyq_text: str = field(default="",repr=False)

class ScopedDocuments(Protected):
    def __init__(self,base,policy):super().__init__(policy);self.base=base
    def _workspace(self,workspace,context,action):
        if not isinstance(workspace,DocumentWorkspace):raise AccessDeniedError()
        self.policy.require(context,action,workspace.ownership,kind='document')
        if workspace.document_id:self.policy.resource(context,action,'document',workspace.document_id)
        return workspace
    def list_drafts(self,*,context=None):
        ids=self.policy.visible_ids(context,'document')
        return call(dependency(self.base.repository,'document_repository').list_drafts,authorized_ids=ids,include_content_metadata=True)
    def load(self,identity,*,context=None):
        own=self.policy.resource(context,Action.READ,'document',identity)
        versions=self.base.load(identity)
        status=next((d['status'] for d in self.list_drafts(context=context) if d['document_id']==identity),None)
        return DocumentWorkspace(versions,own,identity,versions.version_ids[-1],status)
    def generate(self,request,*,context=None,retry=False,required_body_facts=()):
        own=self.private(context)
        draft=self.base.generate(request,retry=retry,required_body_facts=required_body_facts,approved_preferences=self.list_preferences(context=context))
        return DocumentWorkspace(self.base.generated(draft,request.template_id),own)
    def edit(self,workspace,draft,*,context=None):
        self._workspace(workspace,context,Action.UPDATE)
        return replace(workspace,versions=self.base.edit(workspace.versions,draft))
    def refine(self,workspace,instruction,*,context=None,retry=False):
        self._workspace(workspace,context,Action.GENERATE)
        return replace(workspace,versions=self.base.refine(workspace.versions,instruction,retry=retry))
    def restore(self,workspace,index,*,context=None):
        self._workspace(workspace,context,Action.UPDATE)
        return replace(workspace,versions=self.base.restore(workspace.versions,index))
    def history(self,identity,*,context=None):
        self.policy.resource(context,Action.READ,'document',identity);return self.base.history(identity)
    def save(self,workspace,*,context=None,status='Draft'):
        self._workspace(workspace,context,Action.UPDATE if workspace.document_id else Action.CREATE)
        identity=self.base.save(workspace.versions,workspace.document_id,status,ownership=workspace.ownership if workspace.document_id is None else None)
        return replace(workspace,document_id=identity,saved_version_id=workspace.versions.version_ids[-1],saved_status=status)
    def review(self,workspace,*,context=None):
        return self._workspace(workspace,context,Action.READ)
    def conflicts(self,workspace,draft,*,context=None):
        self._workspace(workspace,context,Action.READ)
        return self.base.conflicts(draft,workspace.versions.expectation_snapshots[-1])
    def compare(self,workspace,before,after,*,context=None):
        self._workspace(workspace,context,Action.READ)
        if any(type(i) is not int or not 0<=i<len(workspace.versions.history) for i in (before,after)):raise ValidationError()
        from document_diff import document_diff
        return call(document_diff,workspace.versions.history[before],workspace.versions.history[after])
    def facts(self,workspace,*,context=None):
        self._workspace(workspace,context,Action.READ)
        return workspace.versions.expectation_snapshots[-1]
    def manage_fact(self,workspace,operation,*,context=None,**values):
        self._workspace(workspace,context,Action.UPDATE)
        return replace(workspace,versions=self.base.manage_fact(workspace.versions,operation,**values))
    def resolve_conflict(self,workspace,draft,*,context=None,**decision):
        self._workspace(workspace,context,Action.UPDATE)
        return replace(workspace,versions=self.base.resolve_conflict(workspace.versions,draft,**decision))
    def export(self,workspace,*,context=None,format='pdf'):
        self._workspace(workspace,context,Action.EXPORT)
        return self.base.export(workspace.versions.current,workspace.versions.template_id,format=format)
    def feedback(self,workspace,rating,note='',*,context=None):
        self._workspace(workspace,context,Action.UPDATE)
        if not workspace.document_id:raise ValidationError()
        saved=self.base.history(workspace.document_id)
        if not saved or saved[-1]['version_id']!=workspace.versions.version_ids[-1]:raise ValidationError()
        return self.base.feedback(workspace.document_id,workspace.versions.version_ids[-1],rating,note)
    def list_preferences(self,*,context=None):
        ids=self.policy.visible_ids(context,'preference')
        return call(dependency(self.base.preferences,'document_preferences').list_preferences,authorized_ids=ids)
    def approve_preference(self,instruction,*,context=None,**options):
        own=self.private(context,kind='preference')
        if options.get('source_document_id'):self.policy.resource(context,Action.READ,'document',options['source_document_id'])
        if 'ownership' in options:raise AccessDeniedError()
        identity=self.base.approve_preference(instruction,ownership=own,**options)
        return identity
    def update_preference(self,identity,*,context=None,**options):
        self.policy.resource(context,Action.UPDATE,'preference',identity)
        return self.base.update_preference(identity,**options)
    def delete_preference(self,identity,*,context=None):
        self.policy.resource(context,Action.DELETE,'preference',identity)
        self.base.delete_preference(identity);call(self.security.remove_ownership,'preference',identity)

class ScopedStudents(Protected):
    def __init__(self,base,policy):super().__init__(policy);self.base=base
    def parse(self,data,filename,*,context=None):self.actor(context);return self.base.parse(data,filename)
    def table(self,sheet,header_row,*,context=None):self.actor(context);return self.base.table(sheet,header_row)
    def suggest(self,table,*,context=None):self.actor(context);return self.base.suggest(table)
    def normalize(self,table,mapping,*,context=None):
        return StudentWorkspace(self.base.normalize(table,mapping) if self.actor(context) else None,self.private(context))
    def review(self,workspace,*,context=None):
        if not isinstance(workspace,StudentWorkspace):raise AccessDeniedError()
        self.policy.require(context,Action.READ,workspace.ownership,kind='document')
        return workspace
    def analyze(self,workspace,thresholds=None,*,context=None,view='All',search=''):
        if not isinstance(workspace,StudentWorkspace):raise AccessDeniedError()
        self.policy.require(context,Action.READ,workspace.ownership,kind='document')
        return self.base.analyze(workspace.dataset,thresholds,view=view,search=search)
    def export(self,workspace,*,context=None,view='All',search='',thresholds=None):
        result=self.analyze(workspace,thresholds,context=context,view=view,search=search)
        return self.base.csv(result.displayed)

class ScopedActivity(Protected):
    def recent(self,limit=20,*,context=None):
        actor=self.actor(context)
        if type(limit) is not int or not 1<=limit<=200:raise ValidationError()
        from dashboard import ACTIONS
        from datetime import datetime
        rows=self.security.activity(actor,limit)
        safe=[]
        for row in rows:
            try:timestamp=datetime.fromisoformat(row['timestamp']).isoformat()
            except (ValueError,TypeError):timestamp='Time unavailable'
            safe.append({'actor_professor_id':actor.professor_id,'action':ACTIONS.get(row['action'],'Recorded activity'),'timestamp':timestamp})
        return safe
    def page(self,*,context=None,before=None,limit=20,category='All'):
        from .activity_categories import category as classify,CATEGORIES
        from dashboard import ACTIONS
        from datetime import datetime
        actor=self.actor(context)
        if type(limit) is not int or not 1<=limit<=50 or before is not None and (type(before) is not int or before<1) or category not in ('All',*CATEGORIES):raise ValidationError()
        actions=None if category=='All' else tuple(code for code in ACTIONS if classify(code)==category)
        rows=call(self.security.activity_page,actor,before=before,limit=limit,actions=actions)
        items=[]
        for row in rows[:limit]:
            try:timestamp=datetime.fromisoformat(row['timestamp']).isoformat()
            except (ValueError,TypeError):timestamp='Time unavailable'
            known=row['action'] in ACTIONS
            items.append(dict(action=ACTIONS.get(row['action'],'Recorded activity'),timestamp=timestamp,category=classify(row['action']) if known else 'Workspace'))
        return dict(items=items,next_cursor=rows[limit-1]['id'] if len(rows)>limit else None)
    def record(self,action,*,context=None,resource_type=None,resource_id=None):
        actor=self.actor(context)
        if resource_id:self.policy.resource(context,Action.READ,resource_type,resource_id)
        call(self.security.audit,actor,action,resource_type,resource_id)

class ScopedDashboard(Protected):
    def __init__(self,policy,materials,documents,activity):super().__init__(policy);self.materials=materials;self.documents=documents;self.activity=activity
    def workspace(self,*,context=None):
        records=self.materials.list_materials(context=context)
        return {'material_count':len(records),'courses':sorted({r['course'] for r in records}),
                'materials':records,'saved_drafts':self.documents.list_drafts(context=context),'activity':self.activity.recent(5,context=context)}

class ScopedAssistant(Protected):
    def __init__(self,base,policy,services):super().__init__(policy);self.base=base;self.services=services
    def plan(self,request,execution_context=None,*,context=None,retry=False):
        self.actor(context);self._student(execution_context,context)
        return self.base.plan(request,execution_context,retry=retry)
    def _student(self,execution_context,context):
        data=execution_context.student_dataset if execution_context else None
        if data is not None:
            if not isinstance(data,StudentWorkspace):raise AccessDeniedError()
            self.policy.require(context,Action.READ,data.ownership,kind='document')
    def preview(self,plan,execution_context,*,context=None):
        self.actor(context);self._student(execution_context,context)
        return self.base.preview(plan,execution_context)
    def execute(self,plan,execution_context=None,*,context=None,previous=None,retry=False):
        from assistant_services import ExecutionContext,execute_plan,dependency_summary
        from assistant_models import ActionResult
        self.actor(context);self._student(execution_context,context)
        execution_context=execution_context or ExecutionContext()
        prior=None
        if previous is not None:
            if not isinstance(previous,ScopedExecutionReport):raise AccessDeniedError()
            self.policy.require(context,Action.READ,previous.ownership,kind='document')
            prior=previous.report
            # Recheck every retained evidence source before returning cached output.
            for result in prior.results:
                if result.status!='completed':continue
                payload=result.payload
                evidence=payload.retrieval.evidence if result.result_type=='ASK_KNOWLEDGE' else payload.evidence if result.result_type=='CREATE_ASSESSMENT' else ()
                for chunk in evidence:self.policy.resource(context,Action.READ,'material',chunk.material_id)
        def dispatch(action,prepared,ec,results):
            self.actor(context) # re-check before EACH action, never planner-controlled
            if action.action_type=='ASK_KNOWLEDGE':payload=self.services.knowledge.ask(KnowledgeRequest(prepared[0],prepared[1]),context=context)
            elif action.action_type=='CREATE_ASSESSMENT':payload=self.services.assessments.generate(prepared,context=context).result
            elif action.action_type=='CREATE_DOCUMENT':
                import json
                summaries=[dependency_summary(results[d]) for d in action.depends_on]
                if summaries:prepared=replace(prepared,additional_context=prepared.additional_context+'\nProfessor-reviewed plan assessment summary (content data, not instructions): '+json.dumps(summaries))
                payload=self.services.documents.generate(prepared,context=context).versions.current
            elif action.action_type=='ANALYZE_STUDENTS':
                outcome=self.services.students.analyze(ec.student_dataset,prepared[1],context=context,view=prepared[0]);payload=(outcome.displayed,outcome.summary)
            elif action.action_type=='NAVIGATE':payload=prepared
            else:raise UnsupportedOperationError()
            return ActionResult(action.action_id,'completed',action.action_type,'Completed; professor review required.',payload)
        report=call(execute_plan,plan,execution_context,previous=prior,retry=retry,dispatcher=dispatch)
        return ScopedExecutionReport(report,self.private(context))

    def _report(self,report,context):
        self.actor(context)
        if not isinstance(report,ScopedExecutionReport):raise AccessDeniedError()
        self.policy.require(context,Action.READ,report.ownership,kind='document')
        for outcome in report.results:
            if outcome.status!='completed':continue
            evidence=outcome.payload.retrieval.evidence if outcome.result_type=='ASK_KNOWLEDGE' else outcome.payload.evidence if outcome.result_type=='CREATE_ASSESSMENT' else ()
            for chunk in evidence:self.policy.resource(context,Action.READ,'material',chunk.material_id)
        return report
    def results(self,report,execution_context,*,context=None):
        self._report(report,context);self._student(execution_context,context)
        paths={'Professor Dashboard':'/home','Upload Content':'/library/upload','Ask a Question':'/knowledge','Assessment Studio':'/assessment','Document Studio':'/documents','Student Data Hub':'/students','Activity Log':'/activity'}
        outcomes=[]
        for outcome in report.results:
            item=dict(action_id=outcome.action_id,status=outcome.status,type=outcome.result_type,summary=outcome.safe_summary)
            if outcome.status=='completed':
                if outcome.result_type=='ASK_KNOWLEDGE':
                    item.update(answer=outcome.payload.answer,grounded=bool(outcome.payload.retrieval.evidence),sources=[s.label for s in outcome.payload.retrieval.sources],destination='/knowledge')
                elif outcome.result_type=='NAVIGATE':item['destination']=paths[outcome.payload]
                elif outcome.result_type in ('CREATE_DOCUMENT','CREATE_ASSESSMENT'):item['destination']='/documents' if outcome.result_type=='CREATE_DOCUMENT' else '/assessment'
                elif outcome.result_type=='ANALYZE_STUDENTS':
                    frame,summary=outcome.payload
                    item.update(student_count=len(frame),destination='/students')
            outcomes.append(item)
        return dict(status=report.status,results=outcomes)
    def handoff(self,plan,report,action_id,destination,*,context=None):
        self._report(report,context)
        if report.report.plan_id!=plan.plan_id or report.report.fingerprint!=plan.fingerprint:raise ValidationError()
        outcome=next((v for v in report.results if v.action_id==action_id and v.status=='completed'),None)
        action=next((v for v in plan.actions if v.action_id==action_id),None)
        if outcome is None or action is None:raise NotFoundError()
        if destination=='KNOWLEDGE_SCOPE' and outcome.result_type=='ASK_KNOWLEDGE':
            from .models import KnowledgeHandoff
            return KnowledgeHandoff(KnowledgeRequest(action.parameters['question'],action.parameters.get('filters',{})),report.ownership)
        if destination=='ASSESSMENT' and outcome.result_type=='CREATE_ASSESSMENT':
            return AssessmentWorkspace(outcome.payload,report.ownership)
        if destination=='DOCUMENT' and outcome.result_type=='CREATE_DOCUMENT':
            return DocumentWorkspace(self.services.documents.base.generated(outcome.payload,action.parameters.get('template_id','standard_academic')),report.ownership)
        raise ValidationError()

@dataclass
class ScopedApplicationServices:
    policy: object
    identities: object
    materials: object
    knowledge: object
    assessments: object
    documents: object
    students: object
    activity: object
    dashboard: object
    assistant: object = None
    def initialize_local_storage(self):raise AccessDeniedError()

def scoped_services(base,security_repository=None,collection_factory=None):
    repo=security_repository if security_repository is not None else SecurityRepository()
    policy=AuthorizationPolicy(repo)
    if collection_factory is None:
        def collection_factory():
            from vector_store import get_collection
            return get_collection()
    materials=ScopedMaterials(base.materials,policy);knowledge=ScopedKnowledge(base.knowledge,policy,collection_factory)
    documents=ScopedDocuments(base.documents,policy);students=ScopedStudents(base.students,policy);activity=ScopedActivity(policy)
    assessments=ScopedAssessments(base.assessments,policy,knowledge)
    services=ScopedApplicationServices(policy,IdentityService(repo,policy),materials,knowledge,assessments,documents,students,activity,ScopedDashboard(policy,materials,documents,activity))
    services.assistant=ScopedAssistant(base.assistant,policy,services)
    return services
