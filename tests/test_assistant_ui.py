"""Assistant session UI tests; no production data or model execution."""
from unittest.mock import Mock
import pytest
import assistant_ui as ui
import assistant_services as services
from assistant_models import ActionResult,ExecutionReport
from test_app import app
from test_assistant import plan,action,combined,student_context,assessment_params


def click(app,label):return next(b for b in app.button if b.label==label).click().run()


def submit(app,p,monkeypatch):
    monkeypatch.setattr(ui,'plan_request',Mock(return_value=p))
    app.text_area(key='dashboard_assistant_request').set_value(p.original_request)
    return click(app,'Submit')


def test_preview_does_not_execute(app,monkeypatch):
    dispatch=Mock();monkeypatch.setattr(services,'dispatch',dispatch)
    app=submit(app,plan(action()),monkeypatch)
    assert not app.exception and any(s.value=='Plan preview' for s in app.subheader)
    dispatch.assert_not_called()
    click(app,'Execute reviewed plan')
    assert dispatch.call_count==1


def test_navigation_results_explicit_open(app,monkeypatch):
    app=submit(app,plan(action()),monkeypatch);app=click(app,'Execute reviewed plan')
    assert not app.exception
    assert any('a: completed' in e.value for e in app.markdown)
    assert any(b.label=='Open Professor Dashboard' for b in app.button)


def test_missing_scope_disabled(app,monkeypatch):
    p=plan(action('CREATE_ASSESSMENT',{'assessment_type':'Quiz'}))
    app=submit(app,p,monkeypatch)
    assert not app.exception and any('scope.course' in e.value for e in app.warning)
    assert next(b for b in app.button if b.label=='Execute reviewed plan').disabled


def test_changed_request_cannot_execute(app,monkeypatch):
    app=submit(app,plan(action()),monkeypatch)
    app.text_area(key='dashboard_assistant_request').set_value('Changed request').run()
    assert next(b for b in app.button if b.label=='Execute reviewed plan').disabled


def test_partial_failure_and_retry_ui(app,monkeypatch):
    p=plan(action(),action(identity='b'))
    good=ActionResult('a','completed','NAVIGATE','Completed locally.','Professor Dashboard')
    failed=ActionResult('b','failed','NAVIGATE','Failed.',error='Service failed.')
    run=Mock(side_effect=[ExecutionReport(p.plan_id,(good,failed)),ExecutionReport(p.plan_id,(good,ActionResult('b','completed','NAVIGATE','Completed locally.','Professor Dashboard')))])
    monkeypatch.setattr(ui,'execute_plan',run)
    app=submit(app,p,monkeypatch);app=click(app,'Execute reviewed plan')
    assert not app.exception and any('partial failure' in e.value for e in app.subheader)
    app=click(app,'Retry failed safe actions')
    assert not app.exception and run.call_count==2
    assert any(e.value=='Results: completed' for e in app.subheader)


def test_student_result_local_ui(app,monkeypatch):
    context=student_context();app.session_state['student_validation']=context.student_dataset
    p=plan(action('ANALYZE_STUDENTS',{'view':'Attendance concern'}))
    app=submit(app,p,monkeypatch);app=click(app,'Execute reviewed plan')
    assert not app.exception
    assert app.dataframe[0].value.student_id.tolist()==['SYN02']
    assert any('No AI receives' in e.value for e in app.caption)


def test_document_handoff_existing_studio(app,monkeypatch):
    import document_studio
    from document_models import DocumentDraft
    monkeypatch.setattr(document_studio,'generate_draft',Mock(return_value=DocumentDraft('notice',body=('Synthetic notice',))))
    p=plan(action('CREATE_DOCUMENT',{'document_type':'notice','description':'Draft notice'}))
    app=submit(app,p,monkeypatch);app=click(app,'Execute reviewed plan')
    assert not app.exception
    app=click(app,'Open in Document Studio')
    assert not app.exception and app.sidebar.radio[0].value=='Document Studio'
    assert app.session_state['studio_versions'].current.body==('Synthetic notice',)


def test_assessment_full_review_exports(app,monkeypatch):
    import assessment_studio
    from assessment_fixtures import raw,spec,evidence
    monkeypatch.setattr(assessment_studio,'generate_assessment',Mock(return_value=assessment_studio.validate_output(raw(),spec(),evidence())))
    app=submit(app,plan(action('CREATE_ASSESSMENT',assessment_params())),monkeypatch)
    app=click(app,'Execute reviewed plan')
    assert not app.exception and any(e.value=='Professor review' for e in app.subheader)
    assert any(e.label=='Professor answer key Q1' for e in app.expander)


def test_student_change_releases_old_result(app,monkeypatch):
    app.session_state['student_validation']=student_context().student_dataset
    p=plan(action('ANALYZE_STUDENTS',{'view':'All'}))
    app=submit(app,p,monkeypatch);app=click(app,'Execute reviewed plan')
    app.session_state['student_validation']=None;app.run()
    assert not app.exception and 'assistant_report' not in app.session_state


def test_multiple_assessments_unique_export_widgets(app,monkeypatch):
    import assessment_studio
    from assessment_fixtures import raw,spec,evidence
    monkeypatch.setattr(assessment_studio,'generate_assessment',Mock(return_value=assessment_studio.validate_output(raw(),spec(),evidence())))
    p=plan(action('CREATE_ASSESSMENT',assessment_params()),action('CREATE_ASSESSMENT',assessment_params(),identity='b'))
    app=submit(app,p,monkeypatch);app=click(app,'Execute reviewed plan')
    assert not app.exception
    assert len([e for e in app.subheader if e.value=='Professor review'])==2
