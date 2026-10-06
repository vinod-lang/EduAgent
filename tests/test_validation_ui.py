import json
from dataclasses import replace
from unittest.mock import Mock
import pytest
import ai_provider
import document_ui
import assistant_ui
import assessment_ui
from test_document_ui import app as document_app,button
from test_app import app as assistant_app
from test_assessment_ui import studio_app,ready
from test_material_identity import storage,hierarchy
from test_assistant import plan,action
from document_models import DocumentRequest,DocumentDraft,DocumentVersions,DocumentError
from document_facts import fact
from generation_diagnostics import annotate,failed
from structured_generation import Failure


def install_document(app):
    d=annotate(DocumentDraft('notice',date='10 October 2026',body=('Synthetic event costs INR 2500.',)),'document',1)
    d=replace(d,fact_expectations=(fact('date',d.date,'structured_request'),))
    app.session_state['studio_pending_versions']=DocumentVersions.generated(d)
    app.run();assert not app.exception
    return app


def test_document_fact_display_and_safe_status(document_app):
    app=install_document(document_app)
    assert any('date' in e.value.casefold() and '10 October 2026' in e.value for e in app.text)
    assert any('Validated' in e.value for e in app.success)
    identity=app.session_state['studio_versions'].expectation_snapshots[0][0].fact_id
    assert not any(identity in e.value for group in (app.text,app.caption,app.error,app.warning,app.success) for e in group)
    assert any('Other free-text' in e.value for e in app.caption)


def test_conflict_keep_original(document_app):
    app=install_document(document_app)
    app.text_input(key='studio_edit_date').set_value('12 October 2026')
    button(app,'Apply edits').click().run()
    assert not app.exception and app.warning
    assert app.session_state['studio_versions'].current.date=='10 October 2026'
    button(app,'Keep original confirmed facts and revise edit').click().run()
    assert app.session_state['studio_versions'].current.date=='10 October 2026'
    assert 'studio_fact_conflict' not in app.session_state


def test_conflict_update_save_reload(document_app):
    app=install_document(document_app)
    app.text_input(key='studio_edit_date').set_value('12 October 2026')
    button(app,'Apply edits').click().run()
    button(app,'Update confirmed facts and apply edit').click().run()
    assert not app.exception
    v=app.session_state['studio_versions']
    assert v.current.date=='12 October 2026' and v.expectation_snapshots[-1][0].value=='12 October 2026'
    button(app,'Save Draft').click().run()
    button(app,'Load saved draft').click().run()
    assert app.session_state['studio_versions'].expectation_snapshots[-1][0].value=='12 October 2026'
    assert any('Saved locally' in e.value for e in app.caption)


def test_manual_add_update_remove(document_app):
    app=install_document(document_app)
    app.selectbox(key='new_fact_field').set_value('body').run()
    app.text_input(key='new_fact_value').set_value('INR 2500').run()
    button(app,'Add confirmed fact').click().run()
    assert not app.exception and len(app.session_state['studio_versions'].expectation_snapshots[-1])==2
    button(app,'Update confirmed fact 2').click().run()
    assert not app.exception
    button(app,'Remove confirmed fact 2').click().run()
    assert not app.exception and len(app.session_state['studio_versions'].expectation_snapshots[-1])==1


def test_failed_refinement_keeps_current(document_app,monkeypatch):
    app=install_document(document_app);before=app.session_state['studio_versions']
    error=DocumentError('PRIVATE raw rejected content /private/path');error.generation_diagnostic=failed(Failure.FACT_PRESERVATION_FAILED,1)
    monkeypatch.setattr(document_ui,'refine_draft',Mock(side_effect=error))
    app.text_input(key='studio_refinement').set_value('Shorten').run()
    button(app,'Refine current document').click().run()
    assert not app.exception and app.error
    assert app.session_state['studio_versions']==before
    assert all('PRIVATE' not in e.value and '/private/path' not in e.value for e in app.error)

@pytest.mark.parametrize('category',[Failure.INVALID_JSON,Failure.SCHEMA_INVALID,Failure.PRODUCT_VALIDATION_FAILED,Failure.INSUFFICIENT_EVIDENCE,Failure.PROVIDER_ERROR,Failure.TIMEOUT])
def test_assessment_failure_safe_no_export(studio_app,monkeypatch,category):
    app,_=studio_app;ready(app)
    error=assessment_ui.AssessmentError('PRIVATE prompt /private/path');error.generation_diagnostic=failed(category,1)
    monkeypatch.setattr(assessment_ui,'generate_assessment',Mock(side_effect=error))
    button(app,'Generate assessment').click().run()
    assert not app.exception and app.error and not app.get('download_button')
    assert 'assessment_result' not in app.session_state
    assert all('PRIVATE' not in e.value and '/private/path' not in e.value for e in app.error)


def test_assessment_success_diagnostic(studio_app,monkeypatch):
    from assessment_fixtures import output,evidence
    from assessment_studio import validate_output
    app,_=studio_app;ready(app)
    def generate(spec,**kw):return annotate(validate_output(json.dumps(output(spec.plan)),spec,evidence()),'assessment',1,grounded=True)
    monkeypatch.setattr(assessment_ui,'generate_assessment',generate)
    button(app,'Generate assessment').click().run()
    assert any('Grounded in course material' in e.value for e in app.success)
    assert any('evidence references and MCQ' in e.value for e in app.caption)

@pytest.mark.parametrize('category',[Failure.INVALID_JSON,Failure.UNSUPPORTED_OPERATION,Failure.PROVIDER_ERROR,Failure.TIMEOUT])
def test_assistant_failure_safe(assistant_app,monkeypatch,category):
    error=assistant_ui.PlanError('PRIVATE generated plan');error.generation_diagnostic=failed(category,1)
    monkeypatch.setattr(assistant_ui,'plan_request',Mock(side_effect=error))
    assistant_app.text_area(key='dashboard_assistant_request').set_value('Synthetic request').run()
    button(assistant_app,'Submit').click().run()
    messages=assistant_app.info if category==Failure.UNSUPPORTED_OPERATION else assistant_app.error
    assert not assistant_app.exception and messages
    assert all('PRIVATE' not in e.value for e in messages)
    assert 'assistant_plan' not in assistant_app.session_state


def test_assistant_clarification(assistant_app,monkeypatch):
    p=plan(action('CREATE_ASSESSMENT',{'assessment_type':'Quiz'}))
    monkeypatch.setattr(assistant_ui,'plan_request',Mock(return_value=p))
    assistant_app.text_area(key='dashboard_assistant_request').set_value(p.original_request)
    button(assistant_app,'Submit').click().run()
    assert any('More information needed' in e.value for e in assistant_app.warning)
    assert button(assistant_app,'Execute reviewed plan').disabled


def test_assistant_valid_plan_status(assistant_app,monkeypatch):
    p=plan(action());monkeypatch.setattr(assistant_ui,'plan_request',Mock(return_value=p))
    assistant_app.text_area(key='dashboard_assistant_request').set_value(p.original_request)
    button(assistant_app,'Submit').click().run()
    assert any('Validated' in e.value for e in assistant_app.success)


def test_document_assistant_metadata_handoff():
    from assistant_services import dispatch,ExecutionContext
    from assistant_models import PlannedAction
    import document_studio
    from unittest.mock import patch
    generated=replace(annotate(DocumentDraft('notice',date='10 October 2026',body=('Synthetic',)),'document',1),fact_expectations=(fact('date','10 October 2026'),))
    action=PlannedAction('a','CREATE_DOCUMENT',json.dumps({'document_type':'notice','description':'Synthetic','date':'10 October 2026'}))
    with patch.object(document_studio,'generate_draft',return_value=generated):
        result=dispatch(action,DocumentRequest('notice','Synthetic',date='10 October 2026'),ExecutionContext(),{})
    assert result.payload.provenance==generated.provenance
    assert result.payload.fact_expectations==generated.fact_expectations
