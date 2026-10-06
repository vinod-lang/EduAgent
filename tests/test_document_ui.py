import json
from pathlib import Path
from unittest.mock import Mock
import pytest
from streamlit.testing.v1 import AppTest
import db
import document_ui as ui
from document_models import DocumentDraft,DocumentError
from ai_provider import AIConnectionError

@pytest.fixture
def app(tmp_path,monkeypatch,agents):
    monkeypatch.chdir(tmp_path);monkeypatch.setattr(db,'DB_PATH',str(tmp_path/'studio.db'))
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=30).run()
    app.sidebar.radio[0].set_value('Document Studio').run();return app

def button(app,label):return next(b for b in app.button if b.label==label)

def generate(app,monkeypatch):
    monkeypatch.setattr(ui,'generate_draft',lambda request:DocumentDraft(request.document_type,title='Synthetic notice',body=('Synthetic original body',)))
    app.text_area(key='studio_description').set_value('Notify fictional students of a tutorial').run()
    button(app,'Generate document').click().run();assert not app.exception


def test_empty_controls_and_navigation(app):
    assert not app.exception and len(app.sidebar.radio[0].options)==7
    assert 'Draft Document' not in app.sidebar.radio[0].options
    assert button(app,'Generate document').disabled
    assert len(app.selectbox(key='studio_type').options)==17
    assert app.selectbox(key='studio_tone').value=='Formal & Natural'
    assert not any('Course' in w.label for w in app.text_input)
    app.sidebar.radio[0].set_value('Professor Dashboard').run()
    button(app,'Create Document').click().run()
    assert app.sidebar.radio[0].value=='Document Studio' and not app.exception


def test_old_navigation_alias(app):
    old=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=30)
    old.session_state['navigation']='Draft Document';app=old.run()
    assert not app.exception and app.sidebar.radio[0].value=='Document Studio'


def test_generation_edit_save_load_refine_undo(app,monkeypatch):
    generate(app,monkeypatch)
    assert len(app.get('download_button'))==2
    assert db.get_recent_activity()[0]['action']=='document_generated' and db.get_recent_activity()[0]['details']==''
    assert ui.list_drafts()==[]
    app.text_input(key='studio_edit_title').set_value('Professor edited heading')
    app.text_area(key='studio_edit_body').set_value('Professor edited body')
    button(app,'Apply edits').click().run()
    assert app.session_state['studio_versions'].current.body==('Professor edited body',)
    button(app,'Save Draft').click().run();assert not app.exception and len(ui.list_drafts())==1
    button(app,'Update Draft').click().run();assert len(ui.list_drafts())==1
    monkeypatch.setattr(ui,'refine_draft',lambda current,instruction:DocumentDraft('notice',title=current.title,body=('Refined synthetic body',)))
    app.text_input(key='studio_refinement').set_value('Make it concise').run()
    button(app,'Refine current document').click().run()
    assert not app.exception and app.session_state['studio_versions'].current.body==('Refined synthetic body',)
    button(app,'Undo last version').click().run()
    assert app.session_state['studio_versions'].current.body==('Professor edited body',)
    button(app,'Load saved draft').click().run()
    assert not app.exception and app.session_state['studio_versions'].current.body==('Professor edited body',)

@pytest.mark.parametrize('error',[DocumentError('Invalid structured output'),AIConnectionError('Local AI unavailable')])
def test_generation_error_no_exception(app,monkeypatch,error):
    monkeypatch.setattr(ui,'generate_draft',Mock(side_effect=error))
    app.text_area(key='studio_description').set_value('Synthetic request').run()
    button(app,'Generate document').click().run()
    assert not app.exception and app.error and not app.get('download_button')


def test_invalid_edit_retains_current(app,monkeypatch):
    generate(app,monkeypatch)
    app.text_area(key='studio_edit_body').set_value(' ')
    button(app,'Apply edits').click().run()
    assert not app.exception and app.error
    assert app.session_state['studio_versions'].current.body==('Synthetic original body',)
