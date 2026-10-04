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

@pytest.mark.parametrize("page", ["Professor Dashboard","Upload Content","Ask a Question","Assessment Studio","Document Studio","Analytics","Activity Log"])
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
    monkeypatch.setattr(agents["coordinator"],"classify_intent",Mock(return_value=intent))
    qa=Mock(return_value=("Synthetic answer",["Synthetic source"]))
    quiz=Mock(return_value=[dict(mcq,source_label="Synthetic source")])
    doc=Mock(return_value="Synthetic notice")
    monkeypatch.setattr(agents["student_support_agent"],"answer_question",qa)
    monkeypatch.setattr(agents["assessment_agent"],"generate_questions",quiz)
    monkeypatch.setattr(agents["document_agent"],"generate_document",doc)
    app.text_area[0].set_value("Synthetic request")
    next(button for button in app.button if button.label=="Submit").click().run()
    assert not app.exception
    assert qa.called==(intent=="question")
    assert quiz.called==(intent in ["quiz","quiz_and_notice"])
    assert doc.called==(intent in ["document","quiz_and_notice"])
    if quiz.called:quiz.assert_called_once_with(source_name="PCA",num_questions=5)


def test_controlled_provider_failure(app,agents,monkeypatch):
    from ai_provider import AIConnectionError
    monkeypatch.setattr(agents['coordinator'],'classify_intent',Mock(side_effect=AIConnectionError('Local AI service is unavailable. Make sure Ollama is running.')))
    app.text_area[0].set_value('Synthetic request')
    next(b for b in app.button if b.label=='Submit').click().run()
    assert not app.exception
    assert any('Make sure Ollama is running' in item.value for item in app.error)
