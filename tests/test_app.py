import io
from pathlib import Path
from unittest.mock import Mock
import pytest
from streamlit.testing.v1 import AppTest
import db
import export_utils

@pytest.fixture
def app(agents,monkeypatch,tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(db,"DB_PATH",str(tmp_path/"app.db"))
    for module in agents.values():
        if hasattr(module,"ai_provider"):
            monkeypatch.setattr(module.ai_provider,"generate_chat",Mock(side_effect=AssertionError("No live generation in tests")))
    return AppTest.from_file(str(Path(__file__).resolve().parents[1]/"app.py"),default_timeout=20).run()

@pytest.mark.parametrize("page", ["Professor Dashboard","Upload Content","Ask a Question","Assessment Studio","Document Studio","Student Data Hub","Activity Log"])
def test_pages_with_document(app,page):
    app.session_state["document"]="Synthetic draft"
    app.sidebar.radio[0].set_value(page).run()
    assert not app.exception

def test_manual_edit_export(app,monkeypatch):
    import document_export
    from docx import Document
    app.session_state["document"]="Synthetic old draft"
    app.sidebar.radio[0].set_value("Document Studio").run()
    app.text_area(key='studio_edit_body').set_value("Synthetic edited draft")
    next(b for b in app.button if b.label=='Apply edits').click().run()
    assert not app.exception
    versions=app.session_state['studio_versions']
    assert versions.original.body==('Synthetic old draft',)
    assert versions.current.body==('Synthetic edited draft',)
    text='\n'.join(p.text for p in Document(io.BytesIO(document_export.document_docx_bytes(versions.current))).paragraphs)
    assert 'Synthetic edited draft' in text and 'Synthetic old draft' not in text

@pytest.mark.parametrize("intent", ["question","quiz","document","quiz_and_notice"])
def test_dispatch(app,agents,monkeypatch,mcq,intent):
    import assistant_ui
    from assistant_models import parse_plan,ActionResult,ExecutionReport
    kinds={'question':['ASK_KNOWLEDGE'],'quiz':['CREATE_ASSESSMENT'],'document':['CREATE_DOCUMENT'],'quiz_and_notice':['CREATE_ASSESSMENT','CREATE_DOCUMENT']}[intent]
    import json
    plan=parse_plan(json.dumps({'unsupported':False,'actions':[dict(action_id='a'+str(i),action_type=k,parameters={},depends_on=[]) for i,k in enumerate(kinds)]}),'Synthetic request')
    monkeypatch.setattr(assistant_ui,'plan_request',Mock(return_value=plan))
    monkeypatch.setattr(assistant_ui,'validate_plan',Mock(return_value=()))
    run=Mock(return_value=ExecutionReport(plan.plan_id,tuple(ActionResult(a.action_id,'failed',a.action_type,'Failed.') for a in plan.actions)))
    monkeypatch.setattr(assistant_ui,'execute_plan',run)
    app.text_area[0].set_value('Synthetic request')
    next(b for b in app.button if b.label=='Submit').click().run()
    assert not app.exception and not run.called
    next(b for b in app.button if b.label=='Execute reviewed plan').click().run()
    assert not app.exception
    run.assert_called_once()


def test_controlled_provider_failure(app,agents,monkeypatch):
    from ai_provider import AIConnectionError
    import assistant_ui
    monkeypatch.setattr(assistant_ui,'plan_request',Mock(side_effect=AIConnectionError('Local AI service is unavailable. Make sure Ollama is running.')))
    app.text_area[0].set_value('Synthetic request')
    next(b for b in app.button if b.label=='Submit').click().run()
    assert not app.exception
    assert any('local AI service' in item.value for item in app.error)
