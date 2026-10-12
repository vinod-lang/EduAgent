import json
from unittest.mock import Mock
import pytest
import document_ui as ui
import document_studio as studio
import document_preferences as preferences
from document_models import DocumentDraft
from document_repository import list_versions
from test_document_ui import app,button


def generate(app,monkeypatch):
    monkeypatch.setattr(ui,'generate_draft',lambda req:DocumentDraft(req.document_type,title='Synthetic request',body=('Synthetic original body',)))
    app.selectbox(key='studio_type').set_value('permission_request').run()
    app.text_area(key='studio_description').set_value('Request permission for a synthetic workshop').run()
    button(app,'Generate document').click().run();assert not app.exception


def test_end_to_end_approve_generate_disable(app,monkeypatch):
    generate(app,monkeypatch)
    app.text_input(key='studio_edit_closing').set_value('Respectfully,')
    button(app,'Apply edits').click().run()
    assert not app.exception and preferences.list_preferences()==()
    button(app,'Save Draft').click().run()
    app.selectbox(key='feedback_compare_from').set_value(0)
    app.selectbox(key='feedback_compare_to').set_value(1).run()
    candidate=next(w for w in app.text_input if w.label=='Reusable instruction')
    candidate.set_value('Use a concise opening.').run()
    button(app,'Approve Preference').click().run()
    assert not app.exception and len(preferences.list_preferences())==1
    assert preferences.list_preferences()[0].source_document_id==app.session_state['studio_saved_id']
    response=DocumentDraft('permission_request',title='Second request',body=('Synthetic second body',))
    spy=Mock(return_value=response.to_json());monkeypatch.setattr(studio.ai_provider,'generate_chat',spy)
    monkeypatch.setattr(ui,'generate_draft',studio.generate_draft)
    button(app,'Generate document').click().run()
    assert not app.exception and 'Use a concise opening.' in spy.call_args.kwargs['messages'][1]['content']
    assert len(app.session_state['studio_versions'].history)==1
    button(app,'Deactivate').click().run()
    button(app,'Generate document').click().run()
    assert not app.exception and json.loads(spy.call_args.kwargs['messages'][1]['content'])['approved_style_guidance']==[]


def test_ignore_candidate_and_restore_preserves_history(app,monkeypatch):
    generate(app,monkeypatch)
    app.text_input(key='studio_edit_closing').set_value('Regards,')
    button(app,'Apply edits').click().run()
    app.selectbox(key='feedback_compare_from').set_value(0)
    app.selectbox(key='feedback_compare_to').set_value(1).run()
    button(app,'Ignore candidate').click().run()
    assert not app.exception and not any(b.label=='Approve Preference' for b in app.button)
    app.run();assert not any(b.label=='Approve Preference' for b in app.button)
    app.selectbox(key='feedback_history_version').set_value(0).run()
    button(app,'Restore selected version').click().run()
    assert not app.exception
    versions=app.session_state['studio_versions']
    assert len(versions.history)==3 and versions.sources[-1]=='restored'
    assert versions.current==versions.original and versions.history[1].closing=='Regards,'
    button(app,'Save Draft').click().run()
    assert len(list_versions(app.session_state['studio_saved_id']))==3
    assert preferences.list_preferences()==()


def test_manual_management_and_feedback(app,monkeypatch):
    app.text_input[0] # Optional context is still available.
    entry=next(w for w in app.text_input if w.label=='New preference instruction')
    entry.set_value('Prefer short paragraphs.')
    button(app,'Approve manual preference').click().run()
    assert not app.exception and len(preferences.list_preferences())==1
    edit=next(w for w in app.text_input if w.label=='Edit approved instruction')
    edit.set_value('Avoid ceremonial wording.').run()
    button(app,'Update preference').click().run()
    assert preferences.list_preferences()[0].instruction=='Avoid ceremonial wording.'
    button(app,'Deactivate').click().run();assert not preferences.list_preferences()[0].active
    button(app,'Activate').click().run();assert preferences.list_preferences()[0].active
    assert button(app,'Delete preference').disabled
    next(w for w in app.checkbox if w.label=='Confirm preference deletion').check().run()
    button(app,'Delete preference').click().run();assert preferences.list_preferences()==()
    generate(app,monkeypatch);button(app,'Save Draft').click().run()
    next(w for w in app.text_area if w.label=='Private feedback note (optional)').set_value('Private synthetic feedback')
    button(app,'Save feedback').click().run()
    assert not app.exception and any('Feedback saved' in s.value for s in app.success)


def test_manual_blank_and_unsaved_feedback_errors(app,monkeypatch):
    button(app,'Approve manual preference').click().run()
    assert not app.exception and app.error and preferences.list_preferences()==()
    generate(app,monkeypatch)
    button(app,'Save feedback').click().run()
    assert not app.exception and any('Save the current version' in error.value for error in app.error)
