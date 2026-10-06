from pathlib import Path
from unittest.mock import Mock
import pytest
from streamlit.testing.v1 import AppTest
import db
from rag_ui import scope_options
from rag_fixtures import Collection, row
from test_material_identity import storage, hierarchy, upload


@pytest.fixture
def ui(storage,hierarchy,agents,monkeypatch,tmp_path):
    monkeypatch.chdir(tmp_path)
    a=upload(storage,hierarchy)['material']
    b=upload(storage,dict(hierarchy,course='Other Course',semester='Semester 7',subject='Other Subject',unit='Other Unit'),data=b'other')['material']
    db.add_course_if_new('Legacy Course')
    db.add_document_record('PCA','Legacy Course','Legacy Unit','PCA.pdf')
    provider=Mock(return_value='Synthetic answer')
    monkeypatch.setattr(agents['student_support_agent'].ai_provider,'generate_chat',provider)
    collection=Collection([row('a',metadata=dict(a,source=a['original_filename'])),row('b','Other material content',metadata=dict(b,source=b['original_filename'])),row('legacy','Legacy PCA context',metadata={'source':'PCA','course':'Legacy Course','unit':'Legacy Unit'})])
    monkeypatch.setattr(agents['vectors'],'collection',collection)
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=20).run()
    app.sidebar.radio[0].set_value('Ask a Question').run()
    return app,provider,collection,a,b


def select(app,label,value):
    return next(control for control in app.selectbox if control.label==label).set_value(value).run()


def ask(app):
    next(control for control in app.text_input if control.label=='Your question:').set_value('Synthetic question')
    return next(button for button in app.button if button.label=='Ask').click().run()


def test_cascading_controls_and_material_identity(ui):
    app,provider,collection,a,b=ui
    select(app,'Course scope:',a['course'])
    assert next(c for c in app.selectbox if c.label=='Semester scope:').options==['All / no filter',a['semester']]
    select(app,'Semester scope:',a['semester'])
    select(app,'Subject scope:',a['subject'])
    select(app,'Unit scope:',a['unit'])
    select(app,'Material scope:',a['material_id'])
    ask(app)
    assert not app.exception and provider.call_count==1
    where=collection.calls[-1]['where']
    assert where=={'$and':[{key:a[key]} for key in ('course','semester','subject','unit','material_id')]}
    assert any(a['original_filename'] in item.value for item in app.caption)
    assert all(a['managed_filename'] not in item.value for item in app.caption)
    assert app.json


def test_legacy_course_no_deeper_metadata_required(ui):
    app,provider,collection,a,b=ui
    select(app,'Course scope:','Legacy Course')
    assert next(c for c in app.selectbox if c.label=='Semester scope:').options==['All / no filter']
    ask(app)
    assert not app.exception and provider.call_count==1
    assert any('PCA' in item.value for item in app.caption)
    assert collection.calls[-1]['where']=={'course':'Legacy Course'}


def test_no_evidence_message_and_no_generation(ui):
    app,provider,collection,a,b=ui
    collection.rows=[]
    ask(app)
    assert not app.exception
    assert any('No sufficiently relevant' in item.value for item in app.info)
    provider.assert_not_called()
    assert app.json


def test_bad_configuration_rendered_safely(ui,monkeypatch):
    app,provider,collection,a,b=ui
    monkeypatch.setenv('EDUAGENT_RAG_MAX_DISTANCE','nan')
    ask(app)
    assert not app.exception and app.error
    provider.assert_not_called()


def test_scope_helper_filters_exactly():
    materials=[dict(material_id='A',original_filename='same.pdf',course='C',semester='S',subject='ML',unit='U'),dict(material_id='B',original_filename='same.pdf',course='Other',semester='S',subject='ML',unit='U')]
    assert scope_options(materials,{'course':'C'},'unit')==['U']
    assert list(scope_options(materials,{'course':'C'},'material_id'))==['A']
    assert scope_options(materials,{'subject':'No Match'},'unit')==[]


def test_same_filename_material_choices_are_distinct(storage,hierarchy):
    a=upload(storage,hierarchy)['material']
    b=upload(storage,hierarchy,data=b'different bytes')['material']
    choices=scope_options(db.list_materials(),{},'material_id')
    assert set(choices)=={a['material_id'],b['material_id']}
    assert len(set(choices.values()))==2
    assert all('Uploaded' in label and a['managed_filename'] not in label for label in choices.values())
