"""Isolated professor workspace regressions; no production stores or live AI."""
import copy
import json
from pathlib import Path
from unittest.mock import Mock
import pytest
from streamlit.testing.v1 import AppTest
import db
import material_service as service
from dashboard import build_material_tree, PAGES, get_activity_view
from test_material_identity import storage, hierarchy, upload

@pytest.fixture
def workspace(storage, agents, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(service, 'vectors_api', lambda _: storage[1])
    def start(navigation=None):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'), default_timeout=20)
        if navigation is not None:
            app.session_state['navigation'] = navigation
        return app.run()
    return start

def button(app,label):
    return next(b for b in app.button if b.label == label)

def test_tree_natural_unicode_and_empty_courses():
    records=[dict(course='講義',semester=s,subject='ML',unit=u,original_filename=f,
                  material_id=f'{s}-{u}-{f}',created_at='2026-10-04')
             for s in ['Semester 10','Semester 2'] for u in ['Unit 10','Unit 2']
             for f in ['notes10.pdf','notes2.pdf']]
    tree=build_material_tree(records,['Empty'])
    assert tree['Empty']=={}
    assert list(tree['講義'])==['Semester 2','Semester 10']
    assert list(tree['講義']['Semester 2']['ML'])==['Unit 2','Unit 10']
    assert [m['original_filename'] for m in tree['講義']['Semester 2']['ML']['Unit 2']]==['notes2.pdf','notes10.pdf']
    assert tree==build_material_tree(list(reversed(records)),['Empty'])

def test_duplicate_names_remain_independent(storage,hierarchy):
    a=upload(storage,hierarchy)['material'];b=upload(storage,hierarchy,data=b'other')['material']
    leaves=build_material_tree([b,a])[hierarchy['course']][hierarchy['semester']][hierarchy['subject']][hierarchy['unit']]
    assert {m['material_id'] for m in leaves}=={a['material_id'],b['material_id']}

def test_dashboard_sections_and_private_identity(workspace,storage,hierarchy):
    material=upload(storage,hierarchy)['material']; app=workspace()
    assert not app.exception
    assert [t.label for t in app.tabs]==['Overview','Smart Assistant / Quick Actions','Academic Knowledge','Recent Activity']
    rendered=' '.join(str(e.value) for kind in ['markdown','caption','header','subheader'] for e in getattr(app,kind))
    assert material['material_id'] not in rendered and material['managed_filename'] not in rendered
    assert material['original_filename'] in rendered
    assert list(app.sidebar.radio[0].options)==list(PAGES)
    assert button(app,'Delete material').disabled
    assert any(e.label=='Unit: Unit Test' for e in app.expander)

@pytest.mark.parametrize('old,new',[('Smart Assistant','Professor Dashboard'),('Courses & Activity','Activity Log')])
def test_old_navigation_migrates(workspace,old,new):
    app=workspace(old)
    assert not app.exception and app.sidebar.radio[0].value==new

def test_edit_moves_tree_and_preserves_identity(workspace,storage,hierarchy):
    original=upload(storage,hierarchy)['material'];before=copy.deepcopy(storage[1].rows)
    path=storage[0]/original['managed_filename'];content=path.read_bytes()
    app=workspace()
    updates=dict(course=' New Course ',semester=' Semester 2 ',subject=' New Subject ',unit=' Unit 10 ')
    for field,value in updates.items():
        next(w for w in app.text_input if w.label==field.capitalize()).set_value(value)
    button(app,'Save hierarchy').click().run()
    assert not app.exception
    saved=db.get_material(original['material_id'])
    for key,value in updates.items():
        assert saved[key]==value.strip()
        assert all(row['metadata'][key]==value.strip() for row in storage[1].rows.values())
        assert any(e.label==f'{key.capitalize()}: {value.strip()}' for e in app.expander)
    for key in ['material_id','file_hash','chunk_ids','managed_filename','original_filename']:
        assert saved[key]==original[key]
    assert path.read_bytes()==content and set(before)==set(storage[1].rows)
    assert all(before[k]['document']==storage[1].rows[k]['document'] for k in before)

@pytest.mark.parametrize('field',['course','semester','subject','unit'])
def test_blank_edit_controlled(workspace,storage,hierarchy,field):
    material=upload(storage,hierarchy)['material'];before=copy.deepcopy(storage[1].rows)
    app=workspace();next(w for w in app.text_input if w.label==field.capitalize()).set_value('  ')
    button(app,'Save hierarchy').click().run()
    assert not app.exception and app.error
    assert db.get_material(material['material_id'])==material and storage[1].rows==before

@pytest.mark.parametrize('failure',['vector','sqlite'])
def test_edit_failure_surfaces_and_preserves_registry(workspace,storage,hierarchy,monkeypatch,failure):
    material=upload(storage,hierarchy)['material']; before=copy.deepcopy(storage[1].rows)
    if failure=='vector': storage[1].fail_update=True
    else: monkeypatch.setattr(db,'update_material_hierarchy',Mock(side_effect=RuntimeError('synthetic SQLite failure')))
    app=workspace();next(w for w in app.text_input if w.label=='Unit').set_value('Changed')
    button(app,'Save hierarchy').click().run()
    assert not app.exception and app.error
    assert db.get_material(material['material_id'])==material and storage[1].rows==before

def test_confirmation_and_exact_delete(workspace,storage,hierarchy,monkeypatch):
    a=upload(storage,hierarchy)['material'];b=upload(storage,hierarchy,data=b'other')['material']
    app=workspace();assert all(w.disabled for w in app.button if w.label=='Delete material')
    app.checkbox(key=f"confirm_{a['material_id']}").check().run()
    app.button(key=f"delete_{a['material_id']}").click().run()
    assert not app.exception and db.get_material(a['material_id']) is None
    assert db.get_material(b['material_id'])==b
    assert set(storage[1].rows)==set(json.loads(b['chunk_ids']))
    assert not (storage[0]/a['managed_filename']).exists()
    assert (storage[0]/b['managed_filename']).exists()

def test_delete_failure_clear(workspace,storage,hierarchy):
    material=upload(storage,hierarchy)['material'];before=copy.deepcopy(storage[1].rows)
    storage[1].fail_delete=True
    app=workspace();app.checkbox[0].check().run();button(app,'Delete material').click().run()
    assert not app.exception and app.error
    assert db.get_material(material['material_id'])==material and storage[1].rows==before
    assert (storage[0]/material['managed_filename']).exists()

def test_legacy_informational_only(workspace):
    db.add_document_record('Synthetic legacy','Known course',None,'legacy.pdf')
    app=workspace()
    assert not app.exception and not app.checkbox and not app.text_input
    assert any('Synthetic legacy' in e.value for e in app.markdown)
    assert any('Editing/deletion is disabled' in e.value for e in app.caption)
    assert not any(e.label.startswith('Semester:') for e in app.expander)

def test_activity_privacy_and_no_management(workspace):
    db.log_activity('PRIVATE QUESTION','PRIVATE STUDENT MARKS')
    db.log_activity('material_uploaded','PRIVATE DOCUMENT CONTENT')
    app=workspace().sidebar.radio[0].set_value('Activity Log').run()
    assert not app.exception and not app.text_input and not app.checkbox
    rendered=' '.join(e.value for e in app.markdown)
    assert 'PRIVATE' not in rendered and 'Material uploaded' in rendered and 'Recorded activity' in rendered
    assert not any(b.label in ['Delete material','Save hierarchy'] for b in app.button)

def test_activity_malformed_sanitized(storage,monkeypatch):
    monkeypatch.setattr(db,'get_recent_activity',lambda limit:[None,{'timestamp':'PRIVATE','action':[],'details':'PRIVATE'}])
    assert get_activity_view()==[dict(timestamp='Time unavailable',action='Recorded activity')]*2

def test_blank_assistant_does_not_dispatch(workspace,agents,monkeypatch):
    classifier=Mock();monkeypatch.setattr(agents['coordinator'],'classify_intent',classifier)
    app=workspace();button(app,'Submit').click().run()
    assert not app.exception and app.warning;classifier.assert_not_called()


def test_multiple_courses_subjects_and_units():
    records=[dict(course=c,semester=s,subject=t,unit=u,original_filename='Synthetic.pdf',
                  material_id=f'{c}-{s}-{t}-{u}')
             for c in ['Course 10','Course 2'] for s in ['10','2']
             for t in ['Zoology','Algorithms'] for u in ['10','2']]
    tree=build_material_tree(records)
    assert list(tree)==['Course 2','Course 10']
    assert list(tree['Course 2'])==['2','10']
    assert list(tree['Course 2']['2'])==['Algorithms','Zoology']
    assert list(tree['Course 2']['2']['Algorithms'])==['2','10']
    assert len(records)==16

def test_empty_registered_course(workspace):
    with db.material_connection() as conn:
        conn.execute("INSERT INTO courses (course_name,created_at) VALUES (?,?)",('Empty Course','2026-10-04'))
    app=workspace()
    assert not app.exception and any(e.label=='Course: Empty Course' for e in app.expander)
    assert any('No managed materials in this course' in e.value for e in app.caption)

def test_unicode_material_renders(workspace,storage,hierarchy):
    values=dict(hierarchy,course='講義',subject='機械学習',unit='単元 2')
    upload(storage,values,name='講義 — PCA.pdf')
    app=workspace()
    assert not app.exception
    assert {'Course: 講義','Subject: 機械学習','Unit: 単元 2','講義 — PCA.pdf'}.issubset({e.label for e in app.expander})

def test_unchecked_delete_never_calls_service(workspace,storage,hierarchy,monkeypatch):
    material=upload(storage,hierarchy)['material']
    deletion=Mock();monkeypatch.setattr(service,'delete_material',deletion)
    app=workspace();app.checkbox[0].check().run();app.checkbox[0].uncheck().run()
    assert button(app,'Delete material').disabled
    # AppTest can synthesize a disabled-button click: explicit guard must still hold.
    button(app,'Delete material').click().run()
    assert not app.exception
    deletion.assert_not_called()
    assert db.get_material(material['material_id'])==material

def test_unknown_assistant_intent_keeps_existing_fallback(workspace,agents,monkeypatch):
    classifier=Mock(return_value='unknown')
    monkeypatch.setattr(agents['coordinator'],'classify_intent',classifier)
    app=workspace();app.text_area[0].set_value('Synthetic request');button(app,'Submit').click().run()
    assert not app.exception and any("couldn't confidently classify" in e.value for e in app.info)
    classifier.assert_called_once_with('Synthetic request')
