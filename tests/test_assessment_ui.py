import json
from pathlib import Path
from unittest.mock import Mock
import pytest
from streamlit.testing.v1 import AppTest
import db
import assessment_ui as ui
from assessment_studio import validate_output
from assessment_spec import AssessmentError
from assessment_fixtures import output,evidence
from test_material_identity import storage,hierarchy,upload

@pytest.fixture
def studio_app(storage,hierarchy,agents,monkeypatch,tmp_path):
    monkeypatch.chdir(tmp_path)
    a=upload(storage,dict(hierarchy,unit='Unit 1'))['material']
    b=upload(storage,dict(hierarchy,unit='Unit 2'),data=b'synthetic B',name='Synthetic.png')['material']
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=30).run()
    app.sidebar.radio[0].set_value('Assessment Studio').run()
    return app,[a,b]

def button(app,label):return next(w for w in app.button if w.label==label)

def ready(app):
    app.multiselect[0].set_value(['Unit 1']).run()
    return app

@pytest.mark.parametrize('mode',['Quiz','Question Paper'])
def test_modes_and_navigation(studio_app,mode):
    app,_=studio_app
    app.radio(key='assessment_mode').set_value(mode).run()
    assert not app.exception and any(h.value=='Assessment Studio' for h in app.header)
    assert len(app.sidebar.radio[0].options)==7
    assert 'Generate Quiz' not in app.sidebar.radio[0].options and 'Question Paper' not in app.sidebar.radio[0].options
    assert button(app,'Generate assessment').disabled
    assert list(app.get('file_uploader')[0].proto.type)==['.pdf','.png','.jpg','.jpeg']

def test_quick_action_opens_studio(studio_app):
    app,_=studio_app;app.sidebar.radio[0].set_value('Professor Dashboard').run()
    button(app,'Create Assessment').click().run()
    assert not app.exception and app.sidebar.radio[0].value=='Assessment Studio'

@pytest.mark.parametrize('old',['Generate Quiz','Question Paper'])
def test_old_navigation_maps(storage,agents,monkeypatch,tmp_path,old):
    monkeypatch.chdir(tmp_path)
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=30)
    app.session_state['navigation']=old;app.run()
    assert not app.exception and app.sidebar.radio[0].value=='Assessment Studio'

def test_multi_units_and_materials(studio_app):
    app,records=studio_app
    app.multiselect[0].set_value(['Unit 1','Unit 2']).run()
    app.multiselect[1].set_value([r['material_id'] for r in records]).run()
    assert not app.exception and not button(app,'Generate assessment').disabled
    assert app.multiselect[1].value==[r['material_id'] for r in records]
    assert all(r['material_id'] not in label for r in records for label in app.multiselect[1].options)
    assert len(app.dataframe)==1

@pytest.mark.parametrize('field,value',[('MCQ count',0),('Easy count',0),('Understand count',0),('Total marks',1)])
def test_distribution_validation_disables_generation(studio_app,field,value):
    app,_=studio_app;ready(app)
    next(w for w in app.number_input if w.label==field).set_value(value).run()
    assert not app.exception and app.warning and button(app,'Generate assessment').disabled

def test_success_review_downloads_and_private_activity(studio_app,monkeypatch):
    app,_=studio_app;ready(app)
    def generation(spec,**kwargs):return validate_output(json.dumps(output(spec.plan)),spec,evidence())
    generate=Mock(side_effect=generation);monkeypatch.setattr(ui,'generate_assessment',generate)
    button(app,'Generate assessment').click().run()
    assert not app.exception and app.success
    assert len(app.dataframe)==2 and len(app.get('download_button'))==4
    assert any(h.value=='Validation summary' for h in app.subheader)
    assert len([c for c in app.caption if c.value.startswith('Retrieved source:')])==5
    activity=db.get_recent_activity();assert activity[0]['action']=='assessment_generated' and activity[0]['details']==''
    generate.assert_called_once()
    # A changed plan must not offer downloads of the previous specification.
    app.text_input(key='assessment_topic').set_value('Changed focus').run()
    assert not app.exception and not app.get('download_button')
    assert any('Regenerate' in i.value for i in app.info)

@pytest.mark.parametrize('failure',[AssessmentError('Invalid structured output'),ui.RetrievalError('No evidence'),ui.AIProviderError('Local AI unavailable')])
def test_controlled_generation_errors(studio_app,monkeypatch,failure):
    app,_=studio_app;ready(app)
    monkeypatch.setattr(ui,'generate_assessment',Mock(side_effect=failure))
    button(app,'Generate assessment').click().run()
    assert not app.exception and app.error and not app.get('download_button')
    assert not any(a['action']=='assessment_generated' for a in db.get_recent_activity())

def test_pyq_guidance_upload_no_registry_pollution(studio_app,monkeypatch):
    import streamlit as st
    app,_=studio_app;before=db.list_materials()
    class Uploaded:
        name='Synthetic PYQ.png'
        def getvalue(self):return b'synthetic PYQ bytes'
    monkeypatch.setattr(st,'file_uploader',lambda *args,**kwargs:Uploaded())
    extraction=Mock(return_value='Synthetic style only');monkeypatch.setattr(ui,'extract_pyq',extraction)
    generate=Mock(side_effect=lambda spec,**kwargs:validate_output(json.dumps(output(spec.plan)),spec,evidence()))
    monkeypatch.setattr(ui,'generate_assessment',generate)
    ready(app);button(app,'Generate assessment').click().run()
    assert not app.exception and app.success and db.list_materials()==before
    extraction.assert_called_once_with(b'synthetic PYQ bytes','Synthetic PYQ.png')
    assert generate.call_args.kwargs['pyq_text']=='Synthetic style only'
    assert len(list(Path('uploads').iterdir()))==2

def test_cascade_restricts_units_materials(studio_app,hierarchy,storage):
    app,_=studio_app
    upload(storage,dict(hierarchy,course='Other',semester='S2',subject='Other topic',unit='Other Unit'),data=b'other')
    app.run()
    app.selectbox(key='assessment_course').set_value('Other').run()
    assert not app.exception
    assert app.selectbox(key='assessment_semester').value=='S2'
    assert app.selectbox(key='assessment_subject').value=='Other topic'
    assert app.multiselect[0].options==['Other Unit']
    assert not app.multiselect[1].options

def test_legacy_with_missing_hierarchy_not_invented(storage,agents,monkeypatch,tmp_path):
    monkeypatch.chdir(tmp_path);db.add_document_record('Synthetic legacy','C','U1','old.pdf')
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=30).run()
    app.sidebar.radio[0].set_value('Assessment Studio').run()
    assert not app.exception and not app.selectbox(key='assessment_semester').options
    assert button(app,'Generate assessment').disabled


def test_optional_activity_failure_does_not_crash_review(studio_app,monkeypatch):
    app,_=studio_app;ready(app)
    monkeypatch.setattr(ui,'generate_assessment',lambda spec,**kwargs:validate_output(json.dumps(output(spec.plan)),spec,evidence()))
    monkeypatch.setattr(db,'log_activity',Mock(side_effect=RuntimeError('synthetic log failure')))
    button(app,'Generate assessment').click().run()
    assert not app.exception and app.success and len(app.get('download_button'))==4
    assert any('activity event could not' in w.value for w in app.warning)


def test_unit_change_clears_out_of_scope_material_selection(studio_app):
    app,records=studio_app
    app.multiselect[0].set_value(['Unit 1','Unit 2']).run()
    app.multiselect[1].set_value([r['material_id'] for r in records]).run()
    app.multiselect[0].set_value(['Unit 1']).run()
    assert not app.exception
    assert app.multiselect[1].value==[records[0]['material_id']]


def test_course_change_clears_selected_units_and_materials(studio_app,hierarchy,storage):
    app,records=studio_app
    upload(storage,dict(hierarchy,course='Other',semester='S2',subject='Other topic',unit='Other Unit'),data=b'other')
    app.run();app.multiselect[0].set_value(['Unit 1']).run()
    app.multiselect[1].set_value([records[0]['material_id']]).run()
    app.selectbox(key='assessment_course').set_value('Other').run()
    assert not app.exception and app.multiselect[0].value==[] and app.multiselect[1].value==[]
    assert button(app,'Generate assessment').disabled
