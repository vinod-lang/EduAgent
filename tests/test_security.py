"""Build 19 deterministic permissions and synthetic isolated professor metadata."""
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import uuid
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import db
from security.models import *
from security.repository import SecurityRepository
from security.policy import AuthorizationPolicy,IdentityService,AccessDeniedError
from application import create_application_services
from application.materials import MaterialService
from application.errors import ApplicationError,NotFoundError,ConflictError,ValidationError
from application.models import MaterialUpload,KnowledgeRequest
from material_fixtures import Vectors

def identity():return str(uuid.uuid4())

@pytest.fixture
def secured(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DB_PATH',str(tmp_path/'isolated.db'));db.init_db()
    repo=SecurityRepository();repo.initialize()
    institute,other_institute,dept,other_dept,foreign_dept=(identity() for _ in range(5))
    a=ProfessorIdentity(identity(),'Synthetic A',institute,dept)
    b=ProfessorIdentity(identity(),'Synthetic B',institute,dept)
    c=ProfessorIdentity(identity(),'Synthetic C',institute,other_dept)
    d=ProfessorIdentity(identity(),'Synthetic D',other_institute,foreign_dept)
    admin=ProfessorIdentity(identity(),'Synthetic admin',institute,dept,roles=(Role.INSTITUTE_ADMIN,Role.DEPARTMENT_ADMIN))
    for professor in (a,b,c,d,admin):repo.bootstrap_professor(professor)
    course,other_course=identity(),identity()
    repo.register_course(course,institute,dept);repo.register_course(other_course,institute,other_dept)
    repo.set_membership(a.professor_id,course)
    policy=AuthorizationPolicy(repo)
    return SimpleNamespace(repo=repo,policy=policy,a=a,b=b,c=c,d=d,admin=admin,course=course,other_course=other_course,tmp=tmp_path)


def ctx(professor):return ProfessorContext.from_identity(professor)
def own(professor,scope=Scope.PRIVATE,course=None):
    return Ownership(professor.professor_id,professor.institution_id,scope,None if scope==Scope.INSTITUTE else professor.department_id,course)

@pytest.mark.parametrize('action',[Action.READ,Action.UPDATE,Action.DELETE,Action.EXPORT,Action.GENERATE,Action.SHARE])
def test_private_matrix(secured,action):
    s=secured
    assert s.policy.allows(ctx(s.a),action,own(s.a))
    for other in (s.b,s.c,s.d,s.admin):assert not s.policy.allows(ctx(other),action,own(s.a))

@pytest.mark.parametrize('action',[Action.READ,Action.EXPORT,Action.GENERATE])
@pytest.mark.parametrize('scope',[Scope.COURSE,Scope.DEPARTMENT,Scope.INSTITUTE])
def test_shared_read_matrix(secured,action,scope):
    s=secured;o=own(s.a,scope,s.course if scope==Scope.COURSE else None)
    expected=[True,scope!=Scope.COURSE,scope==Scope.INSTITUTE,False,scope!=Scope.COURSE]
    for professor,allowed in zip((s.a,s.b,s.c,s.d,s.admin),expected):assert s.policy.allows(ctx(professor),action,o)==allowed


def test_membership_revocation_and_roles_not_bypass(secured):
    s=secured;o=own(s.a,Scope.COURSE,s.course)
    assert not s.policy.allows(ctx(s.admin),Action.READ,o)
    s.repo.set_membership(s.b.professor_id,s.course);assert s.policy.allows(ctx(s.b),Action.READ,o)
    assert not s.policy.allows(ctx(s.b),Action.UPDATE,o)
    s.repo.set_membership(s.b.professor_id,s.course,member=False);assert not s.policy.allows(ctx(s.b),Action.READ,o)

@pytest.mark.parametrize('scope',[Scope.PRIVATE,Scope.COURSE,Scope.DEPARTMENT,Scope.INSTITUTE])
def test_create_scope_expansion(secured,scope):
    s=secured;o=own(s.a,scope,s.course if scope==Scope.COURSE else None)
    assert s.policy.allows(ctx(s.a),Action.CREATE,o)==(scope in (Scope.PRIVATE,Scope.COURSE))
    assert not s.policy.allows(ctx(s.admin),Action.CREATE,o) # cannot impersonate owner

@pytest.mark.parametrize('context',[None,ProfessorContext(),LegacyDevelopmentContext()])
def test_missing_context_default_deny(secured,context):
    assert not secured.policy.allows(context,Action.READ,own(secured.a))


def test_unknown_inactive_and_forged_context(secured):
    s=secured
    assert not s.policy.allows(ProfessorContext(identity(),s.a.institution_id,s.a.department_id),Action.READ,own(s.a))
    assert not s.policy.allows(ProfessorContext(s.a.professor_id,s.d.institution_id,s.d.department_id),Action.READ,own(s.a))
    s.repo.update_professor(replace(s.a,status=Status.INACTIVE))
    assert not s.policy.allows(ctx(s.a),Action.READ,own(s.a))

@pytest.mark.parametrize('change',[{'visibility_scope':'PRIVATE'},{'visibility_scope':Scope.COURSE},{'visibility_scope':Scope.DEPARTMENT,'department_id':None},{'visibility_scope':Scope.INSTITUTE,'department_id':str(uuid.uuid4())},{'course_id':str(uuid.uuid4())},{'owner_professor_id':'Professor Name'}])
def test_ownership_invariants(secured,change):
    with pytest.raises(ValueError):replace(own(secured.a),**change)


def test_contradictory_repository_ownership_denies(secured):
    s=secured
    contradictory=Ownership(s.a.professor_id,s.a.institution_id,Scope.DEPARTMENT,s.c.department_id)
    assert not s.policy.allows(ctx(s.c),Action.READ,contradictory)
    wrong_course=Ownership(s.a.professor_id,s.a.institution_id,Scope.COURSE,s.a.department_id,s.other_course)
    assert not s.policy.allows(ctx(s.a),Action.READ,wrong_course)
    assert not s.policy.allows(ctx(s.a),'READ',own(s.a))


def test_legacy_missing_ownership_never_shared(secured):
    s=secured
    record=identity()
    assert s.repo.ownership('material',record) is None
    with pytest.raises(NotFoundError):s.policy.resource(ctx(s.a),Action.READ,'material',record)
    assert s.policy.visible_ids(ctx(s.a),'material')==()


def test_identity_administration_no_escalation(secured):
    s=secured;service=IdentityService(s.repo,s.policy)
    with pytest.raises(AccessDeniedError):service.update(replace(s.a,roles=(Role.INSTITUTE_ADMIN,)),context=ctx(s.a))
    with pytest.raises(AccessDeniedError):service.membership(s.b.professor_id,s.course,context=ctx(s.a))
    service.membership(s.b.professor_id,s.course,context=ctx(s.admin));assert s.repo.is_member(s.b.professor_id,s.course)
    service.update(replace(s.a,display_name='Synthetic renamed'),context=ctx(s.a))
    assert service.get(s.a.professor_id,context=ctx(s.a)).display_name=='Synthetic renamed'
    assert len(service.list(context=ctx(s.admin)))==4
    with pytest.raises(AccessDeniedError):service.get(s.d.professor_id,context=ctx(s.admin))
    with pytest.raises(ValueError):s.repo.set_membership(s.d.professor_id,s.course)


def test_schema_additive_idempotent_and_transactional(secured):
    s=secured
    db.add_document_record('Synthetic legacy','C','Unit 1','legacy.pdf')
    before=db.get_documents_for_course('C')
    s.repo.initialize();s.repo.initialize()
    assert db.get_documents_for_course('C')==before
    assert s.repo.get_professor(s.a.professor_id)==s.a
    assert s.repo.ownership('document',identity()) is None
    with db.material_connection() as conn:
        assert 'password' not in str([r['name'] for r in conn.execute('PRAGMA table_info(professors)')]).lower()
    # An interrupted migration must leave no partial companion tables.
    import security.repository as module
    file=s.tmp/'migration.db';factory=lambda:sqlite3.connect(file)
    bad=SecurityRepository(factory)
    original=module.SCHEMA
    try:
        module.SCHEMA=original+';THIS IS INVALID SQL;'
        with pytest.raises(sqlite3.Error):bad.initialize()
    finally:module.SCHEMA=original
    with factory() as conn:assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='professors'").fetchone()


class SecureVectors(Vectors):
    configuration={'hnsw':{'space':'cosine'}}
    def __init__(self):super().__init__();self.queries=[]
    def matches(self,metadata,where):
        if not where:return True
        if '$and' in where:return all(self.matches(metadata,w) for w in where['$and'])
        return all(metadata.get(k) in v['$in'] if isinstance(v,dict) else metadata.get(k)==v for k,v in where.items())
    def get(self,where=None,include=None):return {'ids':[i for i,r in self.rows.items() if self.matches(r['metadata'],where)]}
    def query(self,where=None,**kwargs):
        self.queries.append(where)
        rows=[(i,r) for i,r in self.rows.items() if self.matches(r['metadata'],where)][:kwargs['n_results']]
        return {'ids':[[i for i,r in rows]],'documents':[[r['document'] for i,r in rows]],'metadatas':[[r['metadata'] for i,r in rows]],'distances':[[.1 for _ in rows]]}

@pytest.fixture
def services(secured):
    vectors=SecureVectors()
    materials=MaterialService(uploads=secured.tmp/'uploads',vectors=vectors,extractor=lambda path:path.read_bytes().decode())
    factory=Mock(return_value=vectors)
    api=create_application_services(materials=materials,security_repository=secured.repo,collection_factory=factory)
    return api,vectors,factory


def upload(api,s,professor,label,ownership=None):
    return api.materials.upload(MaterialUpload(('Synthetic PCA overlapping '+label+' text. '*20).encode(),'synthetic.pdf',dict(course='ML',semester='S1',subject='ML',unit='Unit 1')),context=ctx(professor),ownership=ownership)['material']


def test_material_permission_crud_and_query_isolation(secured,services):
    s=secured;api,vectors,_=services
    a=upload(api,s,s.a,'A');b=upload(api,s,s.b,'B')
    assert [r['material_id'] for r in api.materials.list_materials(context=ctx(s.a))]==[a['material_id']]
    with pytest.raises(NotFoundError):api.materials.get(b['material_id'],context=ctx(s.a))
    for operation in (lambda:api.materials.delete(b['material_id'],context=ctx(s.a)),lambda:api.materials.edit_hierarchy(b['material_id'],{},context=ctx(s.a))):
        with pytest.raises(NotFoundError):operation()
    api.materials.delete(a['material_id'],context=ctx(s.a))
    assert api.materials.get(b['material_id'],context=ctx(s.b))
    assert all(r['metadata']['owner_professor_id']==s.b.professor_id for r in vectors.rows.values())


def test_scope_expansion_requires_permission(secured,services):
    s=secured;api,_,_=services;a=upload(api,s,s.a,'A')
    api.materials.share(a['material_id'],own(s.a,Scope.COURSE,s.course),context=ctx(s.a))
    assert not api.materials.list_materials(context=ctx(s.b))
    s.repo.set_membership(s.b.professor_id,s.course)
    assert api.materials.get(a['material_id'],context=ctx(s.b))
    with pytest.raises(NotFoundError):api.materials.share(a['material_id'],own(s.b),context=ctx(s.b))
    with pytest.raises(AccessDeniedError):api.materials.share(a['material_id'],own(s.a,Scope.INSTITUTE),context=ctx(s.a))


def test_cross_scope_rag_never_sends_unauthorized_evidence(secured,services,monkeypatch):
    import ai_provider
    s=secured;api,vectors,_=services
    a=upload(api,s,s.a,'A_PRIVATE');b=upload(api,s,s.b,'B_PRIVATE_SECRET')
    shared=upload(api,s,s.a,'COURSE_SHARED',own(s.a,Scope.COURSE,s.course))
    # Trusted offline fixture provisioning: authorization policy still validates every read.
    dept=upload(api,s,s.c,'OTHER_DEPARTMENT')
    s.repo.remove_ownership('material',dept['material_id']);s.repo.put_ownership('material',dept['material_id'],own(s.c,Scope.DEPARTMENT))
    institute=upload(api,s,s.admin,'INSTITUTE_APPROVED',own(s.admin,Scope.INSTITUTE))
    provider=Mock(return_value='Synthetic grounded answer');monkeypatch.setattr(ai_provider,'generate_chat',provider)
    result=api.knowledge.ask(KnowledgeRequest('Explain PCA'),context=ctx(s.a))
    assert result.retrieval_status=='evidence_found'
    ids={e.material_id for e in result.retrieval.evidence}
    assert ids=={a['material_id'],shared['material_id'],institute['material_id']}
    assert b['material_id'] not in ids and dept['material_id'] not in ids
    prompt=str(provider.call_args)
    assert 'B_PRIVATE_SECRET' not in prompt and 'OTHER_DEPARTMENT' not in prompt
    assert all('$in' in str(where) for where in vectors.queries)
    with pytest.raises(NotFoundError):api.knowledge.ask(KnowledgeRequest('PCA',{'material_id':b['material_id']}),context=ctx(s.a))
    assert provider.call_count==1


def test_no_allowed_materials_no_vector_or_provider(secured,services,monkeypatch):
    import ai_provider
    s=secured;api,_,factory=services
    provider=Mock();monkeypatch.setattr(ai_provider,'generate_chat',provider)
    result=api.knowledge.ask(KnowledgeRequest('PCA'),context=ctx(s.a))
    assert result.retrieval_status=='no_evidence'
    factory.assert_not_called();provider.assert_not_called()


def test_faulty_vector_adapter_cannot_leak(secured,services,monkeypatch):
    import ai_provider
    s=secured;api,vectors,_=services;a=upload(api,s,s.a,'A');b=upload(api,s,s.b,'B')
    def bad(**kwargs):
        row=next(r for r in vectors.rows.values() if r['metadata']['material_id']==b['material_id'])
        return {'ids':[['bad']],'documents':[[row['document']]],'metadatas':[[row['metadata']]],'distances':[[.1]]}
    monkeypatch.setattr(vectors,'query',bad)
    provider=Mock();monkeypatch.setattr(ai_provider,'generate_chat',provider)
    with pytest.raises(ApplicationError):api.knowledge.ask(KnowledgeRequest('PCA'),context=ctx(s.a))
    provider.assert_not_called()


def test_missing_scoped_context_denies_before_resources(services):
    api,_,factory=services
    for operation in (lambda:api.materials.list_materials(),lambda:api.knowledge.ask(KnowledgeRequest('PCA')),lambda:api.documents.list_drafts(),lambda:api.activity.recent(),lambda:api.dashboard.workspace()):
        with pytest.raises(AccessDeniedError):operation()
    factory.assert_not_called()


def document_draft(date='10 October 2026'):
    from document_models import DocumentDraft
    from document_facts import fact
    draft=DocumentDraft('notice',date=date,body=('Synthetic INR 2500 allocation.',))
    return replace(draft,fact_expectations=(fact('date',date,'structured_request'),fact('body','INR 2500')))


def workspace(s,professor):
    from document_models import DocumentVersions
    return DocumentWorkspace(DocumentVersions.generated(document_draft()),own(professor))


def test_document_guessed_ids_versions_facts_and_private_exports(secured,services):
    s=secured;api,_,_=services
    saved=api.documents.save(workspace(s,s.a),context=ctx(s.a))
    assert api.documents.load(saved.document_id,context=ctx(s.a)).versions.expectation_snapshots==saved.versions.expectation_snapshots
    for operation in (lambda:api.documents.load(saved.document_id,context=ctx(s.b)),lambda:api.documents.history(saved.document_id,context=ctx(s.b)),lambda:api.documents.export(saved,context=ctx(s.b)),lambda:api.documents.feedback(saved,'Good',context=ctx(s.b))):
        with pytest.raises(ApplicationError):operation()
    assert api.documents.list_drafts(context=ctx(s.b))==[]
    assert len(api.documents.list_drafts(context=ctx(s.a)))==1
    changed=replace(saved.versions.current,date='12 October 2026')
    with pytest.raises(ConflictError):api.documents.edit(saved,changed,context=ctx(s.a))
    confirmed=api.documents.resolve_conflict(saved,changed,context=ctx(s.a),update_confirmed=True)
    restored=api.documents.restore(confirmed,0,context=ctx(s.a))
    assert restored.versions.current.date=='10 October 2026'
    api.documents.save(restored,context=ctx(s.a))
    assert len(api.documents.history(saved.document_id,context=ctx(s.a)))==3
    assert api.documents.export(restored,context=ctx(s.a),format='docx')[:2]==b'PK'
    api.documents.feedback(restored,'Good','Synthetic private feedback',context=ctx(s.a))


def test_private_preferences_cannot_influence_other_professor(secured,services,monkeypatch):
    import document_studio
    from document_models import DocumentRequest
    s=secured;api,_,_=services
    a=api.documents.approve_preference('SYNTHETIC_A_PRIVATE_STYLE',context=ctx(s.a),scope='general')
    b=api.documents.approve_preference('SYNTHETIC_B_PRIVATE_STYLE',context=ctx(s.b),scope='general')
    assert [p.preference_id for p in api.documents.list_preferences(context=ctx(s.a))]==[a]
    assert [p.preference_id for p in api.documents.list_preferences(context=ctx(s.b))]==[b]
    for op in (lambda:api.documents.update_preference(a,context=ctx(s.b),instruction='Changed'),lambda:api.documents.delete_preference(a,context=ctx(s.b))):
        with pytest.raises(NotFoundError):op()
    draft=document_draft()
    request=DocumentRequest('notice','Synthetic notice',date=draft.date)
    provider=Mock(return_value=draft.to_json());monkeypatch.setattr(document_studio.ai_provider,'generate_chat',provider)
    generated=api.documents.generate(request,context=ctx(s.b))
    prompt=str(provider.call_args)
    assert 'SYNTHETIC_B_PRIVATE_STYLE' in prompt and 'SYNTHETIC_A_PRIVATE_STYLE' not in prompt
    assert generated.ownership.owner_professor_id==s.b.professor_id
    api.documents.delete_preference(b,context=ctx(s.b))
    assert api.documents.list_preferences(context=ctx(s.b))==()


def test_legacy_preferences_and_documents_excluded_scoped(secured,services):
    from document_preferences import approve_preference
    from document_repository import save_draft
    from document_models import DocumentVersions
    s=secured;api,_,_=services
    legacy=save_draft(DocumentVersions.generated(document_draft()))
    approve_preference('SYNTHETIC_LEGACY_ONLY',scope='general')
    assert api.documents.list_drafts(context=ctx(s.a))==[]
    assert api.documents.list_preferences(context=ctx(s.a))==()
    with pytest.raises(NotFoundError):api.documents.load(legacy,context=ctx(s.a))
    legacy_services=create_application_services(context=development_legacy_context())
    assert legacy_services.documents.load(legacy)
    assert legacy_services.documents.list_preferences()


def test_document_owner_registration_failure_rolls_back(secured,services,monkeypatch):
    from document_repository import list_drafts
    s=secured;api,_,_=services
    monkeypatch.setattr(SecurityRepository,'attach_ownership',Mock(side_effect=sqlite3.OperationalError('Synthetic failure')))
    with pytest.raises(ApplicationError):api.documents.save(workspace(s,s.a),context=ctx(s.a))
    assert not list_drafts()


def test_material_registration_failure_rolls_back_every_layer(secured,services,monkeypatch):
    s=secured;api,vectors,_=services
    monkeypatch.setattr(SecurityRepository,'attach_ownership',Mock(side_effect=sqlite3.OperationalError('Synthetic failure')))
    result=api.materials.upload(MaterialUpload(b'Synthetic PCA text','test.pdf',dict(course='ML',semester='S1',subject='ML',unit='Unit 1')),context=ctx(s.a))
    assert not result['success'] and not db.list_materials() and not vectors.rows
    assert not list((s.tmp/'uploads').iterdir())


def test_inaccessible_duplicate_does_not_reveal_existing_material(secured,services):
    s=secured;api,_,_=services
    content=b'Synthetic identical shared content'
    request=MaterialUpload(content,'private_A_filename.pdf',dict(course='ML',semester='S1',subject='ML',unit='Unit 1'))
    a=api.materials.upload(request,context=ctx(s.a))
    duplicate=api.materials.upload(replace(request,filename='B_filename.pdf'),context=ctx(s.b))
    assert not duplicate['success']
    assert a['material']['material_id'] not in str(duplicate) and 'private_A_filename' not in str(duplicate)
    assert 'existing_material' not in duplicate


def test_assessment_scope_and_export_authorization(secured,services,monkeypatch):
    import ai_provider
    from assessment_fixtures import spec
    s=secured;api,_,_=services;b=upload(api,s,s.b,'PRIVATE_B')
    specification=replace(spec(),scope=replace(spec().scope,material_ids=(b['material_id'],)))
    provider=Mock();monkeypatch.setattr(ai_provider,'generate_chat',provider)
    with pytest.raises(NotFoundError):api.assessments.generate(specification,context=ctx(s.a))
    with pytest.raises(ApplicationError):api.assessments.generate(spec(),context=ctx(s.a))
    provider.assert_not_called()
    from application.scoped import AssessmentWorkspace
    artifact=AssessmentWorkspace('synthetic result',own(s.a))
    with pytest.raises(AccessDeniedError):api.assessments.export(artifact,context=ctx(s.b))


def assistant_plan(*actions):
    from assistant_models import parse_plan
    return parse_plan(json.dumps({'unsupported':False,'actions':list(actions)}),'Synthetic plan')
def action(kind='NAVIGATE',params=None,identity='a',depends=()):
    return dict(action_id=identity,action_type=kind,parameters=params or {'page':'Professor Dashboard'},depends_on=list(depends))


def test_assistant_authorizes_each_action_partial_failure(secured,services,monkeypatch):
    import ai_provider
    s=secured;api,_,_=services;b=upload(api,s,s.b,'PRIVATE_B')
    plan=assistant_plan(action(),action('ASK_KNOWLEDGE',{'question':'PCA','filters':{'material_id':b['material_id']}},'b'))
    provider=Mock();monkeypatch.setattr(ai_provider,'generate_chat',provider)
    report=api.assistant.execute(plan,context=ctx(s.a))
    assert report.status=='partial_failure' and [r.status for r in report.results]==['completed','failed']
    assert 'PRIVATE_B' not in str(report.results[1])
    provider.assert_not_called()
    with pytest.raises(AccessDeniedError):api.assistant.execute(plan,context=ctx(s.b),previous=report,retry=True)
    retry=api.assistant.execute(plan,context=ctx(s.a),previous=report,retry=True)
    assert retry.results[0]==report.results[0] and retry.results[1].status=='failed'


def test_assistant_refusal_confirmation_and_private_student_gate(secured,services,monkeypatch):
    import ai_provider
    from assistant_models import parse_plan
    from assistant_services import ExecutionContext
    from student_ingestion import Mapping,Assessment
    s=secured;api,_,_=services
    provider=Mock();monkeypatch.setattr(ai_provider,'generate_chat',provider)
    book=api.students.parse(b'ID,Name,Attendance,Quiz\n001,Synthetic Private A,90,80\n', 'synthetic.csv',context=ctx(s.a))
    table=api.students.table(book.sheets[0],1,context=ctx(s.a))
    data=api.students.normalize(table,Mapping('ID','Name','Attendance',(Assessment('Quiz','Quiz'),)),context=ctx(s.a))
    with pytest.raises(AccessDeniedError):api.students.analyze(data,context=ctx(s.b))
    with pytest.raises(ApplicationError):api.assistant.plan('Write about Synthetic Private A',ExecutionContext(data),context=ctx(s.a))
    with pytest.raises(AccessDeniedError):api.assistant.plan('Show all students',ExecutionContext(data),context=ctx(s.b))
    local=api.assistant.plan('show all students',ExecutionContext(data),context=ctx(s.a))
    outcome=api.assistant.execute(local,ExecutionContext(data),context=ctx(s.a))
    assert outcome.status=='completed' and outcome.results[0].payload[1]['total_students']==1
    refused=parse_plan('{"unsupported":true,"actions":[]}','Synthetic refusal')
    assert api.assistant.preview(refused,ExecutionContext(),context=ctx(s.a)).unsupported
    with pytest.raises(ApplicationError):api.assistant.execute(refused,context=ctx(s.a))
    provider.assert_not_called()


def test_actor_audit_is_private_and_contains_no_details(secured,services):
    s=secured;api,_,_=services
    a=upload(api,s,s.a,'A')
    api.activity.record('material_uploaded',context=ctx(s.a),resource_type='material',resource_id=a['material_id'])
    assert api.activity.recent(context=ctx(s.b))==[]
    event=api.activity.recent(context=ctx(s.a))[0]
    assert event['actor_professor_id']==s.a.professor_id and 'details' not in event
    with pytest.raises(ValueError):api.activity.record('RAW_PRIVATE_PROMPT',context=ctx(s.a))
    with s.repo.connection() as conn:
        conn.execute('INSERT INTO security_activity(actor_professor_id,action,timestamp) VALUES (?,?,?)',(s.a.professor_id,'PRIVATE FACT VALUE','PRIVATE PATH'))
    assert 'PRIVATE' not in str(api.activity.recent(context=ctx(s.a)))
    assert api.dashboard.workspace(context=ctx(s.a))['material_count']==1
    assert api.dashboard.workspace(context=ctx(s.b))['material_count']==0


def test_new_vector_metadata_retains_hierarchy(secured,services):
    s=secured;api,vectors,_=services;a=upload(api,s,s.a,'A')
    for row in vectors.rows.values():
        meta=row['metadata'];assert meta['owner_professor_id']==s.a.professor_id
        assert meta['institution_id']==s.a.institution_id and meta['visibility_scope']=='PRIVATE'
        assert meta['material_id']==a['material_id'] and meta['unit']=='Unit 1'
        assert (meta['course'],meta['semester'],meta['subject'])==('ML','S1','ML')


def test_policy_and_scoped_services_have_no_ui_or_llm_authorization():
    import ast
    root=Path(__file__).resolve().parents[1]
    for name in ('security/models.py','security/policy.py','security/repository.py'):
        source=(root/name).read_text();tree=ast.parse(source)
        imports=[]
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):imports.extend(n.name for n in node.names)
            if isinstance(node,ast.ImportFrom):imports.append(node.module or '')
        assert not any(n.split('.')[0] in ('streamlit','ollama','ai_provider','structured_generation') for n in imports)
    assert 'session_state' not in (root/'application/scoped.py').read_text()


def test_revoked_membership_during_retrieval_blocks_provider(secured,services,monkeypatch):
    import ai_provider
    s=secured;api,vectors,_=services
    shared=upload(api,s,s.a,'SHARED',own(s.a,Scope.COURSE,s.course))
    original=vectors.query
    def revoke(**kwargs):
        raw=original(**kwargs);s.repo.set_membership(s.a.professor_id,s.course,member=False);return raw
    monkeypatch.setattr(vectors,'query',revoke)
    provider=Mock();monkeypatch.setattr(ai_provider,'generate_chat',provider)
    with pytest.raises(ApplicationError):api.knowledge.ask(KnowledgeRequest('PCA'),context=ctx(s.a))
    provider.assert_not_called()


def test_real_isolated_chroma_where_filter_without_embeddings_or_models(tmp_path):
    import chromadb
    from security.retrieval import AuthorizedCollection
    collection=chromadb.PersistentClient(path=str(tmp_path/'isolated-chroma')).create_collection('synthetic_authorization',embedding_function=None,metadata={'hnsw:space':'cosine'})
    collection.add(ids=['A','B','shared'],documents=['Synthetic A PCA','Synthetic B PRIVATE PCA','Synthetic shared PCA'],embeddings=[[1.,0.],[1.,0.],[1.,0.]],metadatas=[{'material_id':'A'},{'material_id':'B'},{'material_id':'shared'}])
    secured=AuthorizedCollection(('A','shared'),lambda:collection)
    assert secured.count()==2
    raw=secured.query(query_embeddings=[[1.,0.]],n_results=2,include=['documents','metadatas','distances'])
    assert set(raw['ids'][0])=={'A','shared'} and 'PRIVATE' not in str(raw)


def test_private_preferences_never_become_shared(secured):
    s=secured
    assert not s.policy.allows(ctx(s.a),Action.READ,own(s.a,Scope.INSTITUTE),kind='preference')
    assert not s.policy.allows(ctx(s.a),Action.READ,own(s.a,Scope.DEPARTMENT),kind='document')
