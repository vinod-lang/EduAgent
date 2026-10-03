from pathlib import Path
from unittest.mock import Mock
import pytest
import pytesseract
import streamlit as st
from streamlit.testing.v1 import AppTest
import db
import material_service as service
from dashboard import get_dashboard_summary, QUICK_ACTIONS
from test_material_identity import storage, hierarchy, upload
from test_content_ingestion import image_bytes


def test_empty_dashboard(storage):
    summary = get_dashboard_summary()
    assert summary['course_count'] == summary['managed_count'] == summary['legacy_count'] == 0
    assert not summary['recent_activity'] and not summary['recent_materials']


def test_registered_course_without_material(storage):
    db.add_course_if_new('Synthetic Course')
    summary = get_dashboard_summary()
    assert summary['course_count'] == 1 and summary['managed_count'] == 0
    assert summary['materials_by_course'] == {'Synthetic Course': 0}


def test_dashboard_legacy_only(storage):
    db.add_course_if_new('Synthetic Course')
    db.add_document_record('Legacy', 'Synthetic Course', None, 'legacy.pdf')
    summary = get_dashboard_summary()
    assert summary['legacy_count'] == 1 and summary['managed_count'] == 0


def test_dashboard_managed_hierarchy_and_activity(storage, hierarchy):
    upload(storage, hierarchy)
    upload(storage, dict(hierarchy, unit='Unit 2'), data=b'synthetic B')
    upload(storage, dict(hierarchy, course='Synthetic Course 2'), data=b'synthetic C')
    summary = get_dashboard_summary()
    assert summary['course_count'] == 2 and summary['managed_count'] == 3
    assert summary['materials_by_course'] == {hierarchy['course']: 2, 'Synthetic Course 2': 1}
    assert {m['unit'] for m in summary['recent_materials']} == {'Unit Test', 'Unit 2'}
    assert summary['recent_activity'][0]['action'] == 'Material uploaded'
    assert all(set(item) == {'action', 'timestamp'} for item in summary['recent_activity'])


def test_activity_optional_metadata_and_privacy(storage, monkeypatch):
    monkeypatch.setattr(db, 'get_recent_activity', Mock(return_value=[None, {}, {'action': [], 'timestamp': None}, {'action': 'PRIVATE CONTENT', 'details': 'PRIVATE MARKS', 'timestamp': 'PRIVATE DATA'}]))
    summary = get_dashboard_summary()
    assert len(summary['recent_activity']) == 4
    assert 'PRIVATE' not in str(summary)
    assert all(item['timestamp'] == 'Time unavailable' for item in summary['recent_activity'])


def test_recent_activity_bounded(storage):
    for i in range(10): db.log_activity('material_uploaded', 'synthetic private details')
    assert len(get_dashboard_summary()['recent_activity']) == 5


@pytest.fixture
def dashboard_app(storage, agents, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    return AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'), default_timeout=20).run()


def test_default_dashboard_and_empty_states(dashboard_app):
    app = dashboard_app
    assert not app.exception and app.sidebar.radio[0].value == 'Professor Dashboard'
    assert [item.value for item in app.metric] == ['0', '0', '0']
    assert len(app.info) == 3
    assert len(app.sidebar.radio[0].options) == 8


@pytest.mark.parametrize('target', QUICK_ACTIONS)
def test_dashboard_quick_navigation(dashboard_app, target):
    next(button for button in dashboard_app.button if button.label == target).click().run()
    assert not dashboard_app.exception and dashboard_app.sidebar.radio[0].value == QUICK_ACTIONS[target]


def test_upload_types_and_hierarchy(dashboard_app):
    app = dashboard_app.sidebar.radio[0].set_value('Upload Content').run()
    uploader = app.get('file_uploader')[0]
    assert list(uploader.proto.type) == ['.pdf', '.png', '.jpg', '.jpeg']
    assert {'Course name:', 'Semester:', 'Subject:', 'Unit:'}.issubset({item.label for item in app.text_input})
    assert any('20 MB' in item.value for item in app.caption)


@pytest.mark.parametrize('unavailable', [False, True])
def test_image_upload_ui(storage, agents, monkeypatch, tmp_path, unavailable):
    monkeypatch.chdir(tmp_path)
    data = image_bytes()
    class Uploaded:
        name = 'synthetic.png'
        size = len(data)
        def getvalue(self): return data
    monkeypatch.setattr(st, 'file_uploader', lambda *args, **kwargs: Uploaded())
    monkeypatch.setattr(service, 'vectors_api', lambda _: storage[1])
    ocr = Mock(side_effect=pytesseract.TesseractNotFoundError()) if unavailable else Mock(return_value='Synthetic PCA OCR text')
    monkeypatch.setattr(pytesseract, 'image_to_string', ocr)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'), default_timeout=20).run()
    app.sidebar.radio[0].set_value('Upload Content').run()
    next(b for b in app.button if b.label == 'Add to Database').click().run()
    assert not app.exception
    if unavailable:
        assert any('not installed or configured' in item.value for item in app.warning)
        assert not db.list_materials() and not storage[1].rows
    else:
        assert app.success and any('Synthetic PCA OCR text' in item.value for item in app.text)
        app.sidebar.radio[0].set_value('Professor Dashboard').run()
        assert any(item.value == 'Image/OCR' for item in app.caption)
        assert not app.exception


def test_ui_size_check_before_reading(storage, agents, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    class Uploaded:
        name = 'too-big.png'
        size = 21 * 1024 * 1024
        getvalue = Mock(side_effect=AssertionError('Must not read oversized upload'))
    monkeypatch.setattr(st, 'file_uploader', lambda *args, **kwargs: Uploaded())
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'), default_timeout=20).run()
    app.sidebar.radio[0].set_value('Upload Content').run()
    next(b for b in app.button if b.label == 'Add to Database').click().run()
    assert not app.exception and any('size limit' in item.value for item in app.error)
    Uploaded.getvalue.assert_not_called()


def test_invalid_upload_configuration_is_controlled(dashboard_app, monkeypatch):
    monkeypatch.setenv('EDUAGENT_MAX_UPLOAD_MB', 'invalid')
    app = dashboard_app.sidebar.radio[0].set_value('Upload Content').run()
    assert not app.exception and any('must be numeric' in item.value for item in app.error)
