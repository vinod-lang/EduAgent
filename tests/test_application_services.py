"""Build 18 use-case contracts: synthetic inputs, fake boundaries, isolated SQLite."""
import ast
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import db
from application import create_application_services
from security.models import development_legacy_context
from application.materials import MaterialService
from application.knowledge import KnowledgeService
from application.assessments import AssessmentService
from application.documents import DocumentService
from application.students import StudentService
from application.assistant import AssistantService
from application.overview import ActivityService, DashboardService
from application.models import KnowledgeRequest, MaterialUpload, ProfessorContext
from application.errors import (call, ApplicationError, ValidationError, NotFoundError,
    ConflictError, ProviderUnavailableError, InsufficientEvidenceError,
    UnsupportedOperationError, StorageError)
from test_material_identity import storage, hierarchy
from assessment_fixtures import output, spec, evidence
from document_models import DocumentDraft, DocumentRequest, DocumentVersions, DocumentError
from document_facts import fact
from assistant_models import parse_plan, PlanError, UnsupportedPlanError
from assistant_services import ExecutionContext
from student_ingestion import Mapping, Assessment

ROOT=Path(__file__).resolve().parents[1]


def test_import_and_construction_without_streamlit_or_storage(tmp_path):
    code='''
import sys
sys.path.insert(0, sys.argv[1])
class Guard:
    def find_spec(self, name, *args):
        if name.split('.')[0] in ('streamlit','chromadb','sentence_transformers','torch'):
            raise AssertionError('Forbidden resource/dependency import: '+name)
sys.meta_path.insert(0,Guard())
import application
services=application.create_application_services()
assert services.documents and services.knowledge
'''
    result=subprocess.run([sys.executable,'-c',code,str(ROOT)],cwd=tmp_path,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert not list(tmp_path.iterdir())


def test_architecture_no_streamlit_ollama_sqlite_or_chroma_clients():
    for path in (ROOT/'application').glob('*.py'):
        tree=ast.parse(path.read_text())
        for node in ast.walk(tree):
            names=[a.name for a in node.names] if isinstance(node,ast.Import) else [node.module or ''] if isinstance(node,ast.ImportFrom) else []
            assert not any(n.split('.')[0] in ('streamlit','ollama','chromadb') for n in names),path.name
        assert 'PersistentClient(' not in path.read_text() and 'sqlite3.connect(' not in path.read_text()


def test_factory_injection_no_actions():
    material=Mock();activity=Mock();knowledge=Mock()
    services=create_application_services(materials=material,activity=activity,knowledge=knowledge,context=development_legacy_context())
    assert services.materials is material and services.activity is activity and services.knowledge is knowledge
    assert services.dashboard.materials is material and services.dashboard.activity is activity
    assert not material.mock_calls and not activity.mock_calls and not knowledge.mock_calls
    assert ProfessorContext().professor_id is None


def test_material_lifecycle_scope_duplicate_and_exact_deletion(storage,hierarchy):
    root,vectors=storage
    service=MaterialService(uploads=root,vectors=vectors,extractor=lambda _: 'Synthetic PCA content. '*40)
    a=service.upload(MaterialUpload(b'synthetic A','notes.pdf',hierarchy))['material']
    b=service.upload(MaterialUpload(b'synthetic B','notes.pdf',hierarchy))['material']
    assert a['material_id']!=b['material_id']
    duplicate=service.upload(MaterialUpload(b'synthetic A','renamed.pdf',hierarchy))
    assert duplicate['duplicate'] and len(service.list_materials())==2
    assert service.get(a['material_id'])['unit']==hierarchy['unit']
    assert service.hierarchy()[hierarchy['course']][hierarchy['semester']][hierarchy['subject']][hierarchy['unit']]
    assert len(service.scope_records())==2
    assert service.edit_hierarchy(a['material_id'],dict(hierarchy,unit='Unit Updated'))['success']
    assert service.delete(a['material_id'])['success']
    assert service.get(b['material_id'])['unit']==hierarchy['unit']
    assert (root/b['managed_filename']).exists()
    assert all(row['metadata']['material_id']==b['material_id'] for row in vectors.rows.values())
    with pytest.raises(NotFoundError):service.get(a['material_id'])


def test_material_delegation_and_safe_partial_failure():
    backend=SimpleNamespace(delete_material=Mock(return_value={'success':False,'error':'SQL /private/path PRIVATE','warnings':['PRIVATE secret'],'vectors_deleted':2,'sqlite_deleted':False}))
    service=MaterialService(lifecycle=backend,uploads='injected-root',vectors='fake-boundary')
    outcome=service.delete('synthetic-id')
    assert not outcome['success'] and outcome['vectors_deleted']==2
    assert 'PRIVATE' not in str(outcome) and '/private' not in str(outcome)
    backend.delete_material.assert_called_once_with('synthetic-id',uploads='injected-root',vectors='fake-boundary')


def test_knowledge_request_delegation_and_retrieval():
    agent=SimpleNamespace(answer_question=Mock(return_value='domain result'))
    retrieve=Mock(return_value='typed evidence')
    service=KnowledgeService(agent=agent,retriever=retrieve)
    request=KnowledgeRequest('Synthetic academic question',{'unit':'Unit 2'},4)
    assert service.ask(request)=='domain result'
    agent.answer_question.assert_called_once_with(request.question,n_chunks=4,course=None,filters=request.filters)
    assert service.retrieve(request)=='typed evidence'
    retrieve.assert_called_once_with(request.question,request.filters,final_k=4)

@pytest.mark.parametrize('distance,allowed',[(.49,True),(.50,True),(.5001,False),(.9,False)])
def test_knowledge_actual_no_evidence_gate(agents,monkeypatch,distance,allowed):
    vectors=sys.modules['vector_store']
    vectors.search_database.return_value={'documents':[['Synthetic PCA academic evidence']], 'metadatas':[[{'source':'synthetic','unit':'Unit 1'}]],'distances':[[distance]]}
    provider=Mock(return_value='Synthetic supported answer')
    monkeypatch.setattr(agents['student_support_agent'].ai_provider,'generate_chat',provider)
    result=KnowledgeService().ask(KnowledgeRequest('Explain PCA'))
    assert (result.retrieval_status=='evidence_found') is allowed
    if allowed:provider.assert_called_once();assert result.sources
    else:provider.assert_not_called();assert not result.sources
    json.dumps(asdict(result))


def test_assessment_normalization_survives_service(monkeypatch):
    import assessment_studio
    monkeypatch.setattr(assessment_studio,'assessment_evidence',lambda *a,**k:evidence())
    data=output();options=data['questions'][0]['options'];data['questions'][0]['options']=[{k:v} for k,v in options.items()]
    chat=Mock(return_value=json.dumps(data));monkeypatch.setattr(assessment_studio.ai_provider,'generate_chat',chat)
    result=AssessmentService().generate(spec())
    assert result.provenance.normalization_applied and dict(result.questions[0].options)==options
    chat.assert_called_once()

@pytest.mark.parametrize('format',['pdf','docx'])
def test_assessment_exports_and_pyq_delegation(format):
    exporter=SimpleNamespace(assessment_pdf_bytes=Mock(return_value=b'pdf'),assessment_docx_bytes=Mock(return_value=b'docx'))
    pyq=SimpleNamespace(extract_pyq=Mock(return_value='synthetic guidance'))
    studio=SimpleNamespace(generate_assessment=Mock(return_value='validated result'))
    service=AssessmentService(studio=studio,pyq=pyq,exporter=exporter)
    assert service.extract_pyq(b'synthetic','synthetic.png')=='synthetic guidance'
    assert service.generate('spec',pyq_text='synthetic guidance',retry=True)=='validated result'
    assert service.export('result',format,answer_key=True)==format.encode()
    getattr(exporter,'assessment_'+format+'_bytes').assert_called_once_with('result',answer_key=True)


def document_versions():
    draft=DocumentDraft('notice',date='10 October 2026',body=('Synthetic INR 2500 allocation.',))
    draft=replace(draft,fact_expectations=(fact('date',draft.date,'structured_request'),fact('body','INR 2500')))
    return DocumentVersions.generated(draft)


def test_document_edit_conflict_resolution_restore_persistence(storage):
    service=DocumentService();versions=document_versions()
    edited=replace(versions.current,date='12 October 2026')
    with pytest.raises(ConflictError):service.edit(versions,edited)
    assert service.resolve_conflict(versions,edited) is versions
    updated=service.resolve_conflict(versions,edited,update_confirmed=True)
    assert updated.current.date=='12 October 2026'
    assert updated.expectation_snapshots[-1][0].source=='professor_confirmed'
    identity=service.save(updated)
    loaded=service.load(identity)
    assert loaded.expectation_snapshots==updated.expectation_snapshots
    restored=service.restore(loaded,0)
    assert restored.current.date=='10 October 2026' and restored.expectation_snapshots[-1]==versions.expectation_snapshots[0]
    service.save(restored,identity)
    assert len(service.history(identity))==3 and len(service.list_drafts())==1
    assert all(row['details']=='' for row in db.get_recent_activity())

@pytest.mark.parametrize('bad',[False,True])
def test_document_refinement_protected_facts_and_previous_preserved(storage,monkeypatch,bad):
    import document_studio
    service=DocumentService();versions=service.load(service.save(document_versions()))
    raw=versions.current.to_dict()
    if bad:raw['body']=['Synthetic INR 25000 allocation.']
    provider=Mock(return_value=json.dumps(raw));monkeypatch.setattr(document_studio.ai_provider,'generate_chat',provider)
    if bad:
        with pytest.raises(ValidationError):service.refine(versions,'Make it concise')
        assert len(versions.history)==1 and '2500' in versions.current.body[0]
    else:
        refined=service.refine(versions,'Make it concise')
        assert refined.sources[-1]=='ai_refinement' and refined.expectation_snapshots[-1]==versions.expectation_snapshots[-1]
    payload=json.loads(provider.call_args.kwargs['messages'][1]['content'])
    assert len(payload['protected_facts'])==2


def test_document_generation_delegation_and_fact_management():
    draft=DocumentDraft('notice',body=('Synthetic Unicode 講義.',))
    studio=SimpleNamespace(generate_draft=Mock(return_value=draft))
    service=DocumentService(studio=studio)
    request=DocumentRequest('notice','Synthetic notice')
    assert service.generate(request) is draft
    versions=service.generated(draft)
    added=service.manage_fact(versions,'add',field='body',value='講義')
    identity=added.expectation_snapshots[-1][0].fact_id
    changed=service.manage_fact(added,'update',fact_id=identity,value='Unicode 講義')
    removed=service.manage_fact(changed,'remove',fact_id=identity)
    assert not removed.expectation_snapshots[-1]
    assert service.restore(removed,1).expectation_snapshots[-1]==added.expectation_snapshots[-1]

@pytest.mark.parametrize('operation',['approve_preference','list_preferences','update_preference','delete_preference','feedback'])
def test_document_preference_feedback_delegation(operation):
    target='save_feedback' if operation=='feedback' else operation
    fake=SimpleNamespace(**{target:Mock(return_value='domain result')})
    service=DocumentService(preferences=fake)
    args=() if operation=='list_preferences' else ('synthetic',)
    assert getattr(service,operation)(*args)=='domain result'
    getattr(fake,target).assert_called_once_with(*args)

@pytest.mark.parametrize('format',['pdf','docx'])
def test_document_export_clean_and_in_memory(format):
    exporter=SimpleNamespace(document_pdf_bytes=Mock(return_value=b'pdf'),document_docx_bytes=Mock(return_value=b'docx'))
    draft=document_versions().current
    assert DocumentService(exporter=exporter).export(draft,format=format)==format.encode()
    getattr(exporter,'document_'+format+'_bytes').assert_called_once_with(draft,'standard_academic')


def test_student_pipeline_deterministic_local_no_provider(monkeypatch):
    import ai_provider
    provider=Mock(side_effect=AssertionError('Student data cannot enter AI'))
    monkeypatch.setattr(ai_provider,'generate_chat',provider)
    service=StudentService()
    workbook=service.parse(b'ID,Name,Attendance,Quiz\n001,Synthetic A,90,80\n002,Synthetic B,60,30\n003,Synthetic C,,\n','synthetic.csv')
    table=service.table(workbook.sheets[0],1)
    assert service.headers(workbook.sheets[0]) and service.suggest(table)
    mapping=Mapping('ID','Name','Attendance',(Assessment('Quiz','Quiz'),),'percentage')
    dataset=service.normalize(table,mapping)
    result=service.analyze(dataset,view='Concern')
    assert result.summary['total_students']==3
    assert result.displayed.student_id.tolist()==['002']
    assert result.summary['incomplete_data']==1
    assert b'002' in service.csv(result.displayed) and b'001' not in service.csv(result.displayed)
    assert service.validation_csv(dataset)
    json.dumps(result.to_dict(),allow_nan=False)
    provider.assert_not_called()


def plan(kind='NAVIGATE',parameters=None):
    return parse_plan(json.dumps({'unsupported':False,'actions':[{'action_id':'one','action_type':kind,'parameters':parameters or {'page':'Professor Dashboard'},'depends_on':[]}]}),'Synthetic request')


def test_assistant_preview_execute_and_refusal(monkeypatch):
    import ai_provider
    provider=Mock(side_effect=AssertionError('No live AI'));monkeypatch.setattr(ai_provider,'generate_chat',provider)
    service=AssistantService();context=ExecutionContext()
    p=plan()
    preview=service.preview(p,context)
    assert preview.diagnostic.status=='validated' and not preview.clarifications
    report=service.execute(p,context)
    assert report.status=='completed' and report.results[0].payload=='Professor Dashboard'
    unsupported=parse_plan('{"unsupported":true,"actions":[]}','Synthetic unsupported request')
    assert service.preview(unsupported,context).unsupported
    with pytest.raises(ValidationError):service.execute(unsupported,context)
    assert service.preview(plan('CREATE_DOCUMENT',{'document_type':'notice'}),context).clarifications
    with pytest.raises(ValidationError):service.execute(plan('NAVIGATE',{'page':'Professor Dashboard','function':'shell'}),context)
    provider.assert_not_called()


def test_assistant_student_privacy_gate(monkeypatch):
    import ai_provider
    from types import SimpleNamespace
    import pandas as pd
    provider=Mock(side_effect=AssertionError('Private request blocked'));monkeypatch.setattr(ai_provider,'generate_chat',provider)
    context=ExecutionContext(SimpleNamespace(frame=pd.DataFrame({'student_name':['Synthetic Private'],'student_id':['00001']})))
    with pytest.raises(UnsupportedOperationError):AssistantService().plan('Write about Synthetic Private',context)
    provider.assert_not_called()


def test_assistant_injection_preserves_retry_arguments():
    executor=SimpleNamespace(execute_plan=Mock(return_value='partial outcome'))
    service=AssistantService(executor=executor)
    assert service.execute('plan','context',previous='prior',retry=True)=='partial outcome'
    executor.execute_plan.assert_called_once_with('plan','context','prior',True)


def test_activity_and_dashboard_private_log_sanitized(storage):
    db.log_activity('document_saved','PRIVATE fact: 2500 /secret/path')
    db.log_activity('PRIVATE raw request','PRIVATE student name')
    activity=ActivityService();rows=activity.recent()
    assert 'PRIVATE' not in str(rows) and '2500' not in str(rows) and '/secret' not in str(rows)
    activity.record('document_generated')
    assert db.get_recent_activity()[0]['details']==''
    with pytest.raises(ValidationError):activity.record('PRIVATE raw request')
    with pytest.raises(TypeError):activity.record('document_saved',details='PRIVATE')
    services=create_application_services(context=development_legacy_context())
    view=services.dashboard.workspace()
    assert view['summary']['managed_count']==0 and view['materials']==[]
    json.dumps(view)

@pytest.mark.parametrize('limit',[0,-1,201,'20',True])
def test_activity_limit_validation(limit):
    with pytest.raises(ValidationError):ActivityService().recent(limit)

@pytest.mark.parametrize('factory,expected',[
    (lambda:__import__('ai_provider').AIConnectionError('PRIVATE prompt /path'),ProviderUnavailableError),
    (lambda:__import__('assessment_spec').NoAssessmentEvidence('PRIVATE evidence'),InsufficientEvidenceError),
    (lambda:UnsupportedPlanError('PRIVATE request'),UnsupportedOperationError),
    (lambda:DocumentError('PRIVATE fact /path'),ValidationError),
    (lambda:__import__('document_facts').DocumentFactConflict(2),ConflictError),
    (lambda:__import__('sqlite3').OperationalError('PRIVATE SQL'),StorageError),
    (lambda:__import__('student_ingestion').StudentDataError('PRIVATE student 001'),ValidationError),
])
def test_error_taxonomy_safe(factory,expected):
    with pytest.raises(expected) as caught:call(Mock(side_effect=factory()))
    public=json.dumps(caught.value.to_dict())+str(caught.value.generation_diagnostic)
    assert 'PRIVATE' not in public and '/path' not in public and '001' not in public
    assert caught.value.__cause__ is not None


def test_unexpected_developer_error_not_silenced():
    with pytest.raises(RuntimeError):call(Mock(side_effect=RuntimeError('developer bug')))

@pytest.mark.parametrize('service',[AssessmentService(),DocumentService()])
def test_unsupported_exports(service):
    with pytest.raises(UnsupportedOperationError):service.export(None,format='html')
