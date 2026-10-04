"""Synthetic Student Data Hub UI integration, including explicit review/privacy."""
from pathlib import Path
from unittest.mock import Mock
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest
import db
from test_student_ingestion import workbook_bytes

ROOT=Path(__file__).resolve().parents[1]
class Upload:
    def __init__(self,data,name='synthetic.csv'):
        self.data=data;self.name=name;self.size=len(data)
    def getvalue(self):return self.data

@pytest.fixture
def hub(agents,monkeypatch,tmp_path):
    monkeypatch.chdir(tmp_path);monkeypatch.setattr(db,'DB_PATH',str(tmp_path/'hub.db'))
    uploads=[None]
    monkeypatch.setattr(st,'file_uploader',lambda *a,**kw: uploads[0])
    def start(data=None,name='synthetic.csv',navigation='Student Data Hub'):
        uploads[0]=Upload(data,name) if data is not None else None
        app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=20)
        app.session_state['navigation']=navigation
        return app.run()
    return start,uploads,tmp_path


def button(app,label):return next(b for b in app.button if b.label==label)

def confirm_validate(app):
    app.checkbox(key='student_confirm').check().run()
    button(app,'Validate student data').click().run()
    assert not app.exception
    return app


def analyze(app):
    confirm_validate(app);button(app,'Analyze eligible students').click().run()
    assert not app.exception;return app


def test_empty_hub_and_old_navigation(hub):
    start,_,_=hub
    app=start(navigation='Analytics')
    assert not app.exception and app.sidebar.radio[0].value=='Student Data Hub'
    assert len(app.sidebar.radio[0].options)==7 and 'Analytics' not in app.sidebar.radio[0].options
    assert app.info and not app.dataframe


def test_upload_preview_confirm_analysis_export_clear(hub):
    start,uploads,tmp=hub
    app=start(b'Roll No,Name,Attendance,Quiz\n001,Student A,90,80\n002,Student B,60,30\n003,Student C,N/A,\n')
    assert not app.exception and len(app.dataframe)==2
    assert button(app,'Validate student data').disabled
    analyze(app)
    result,summary=app.session_state['student_results']
    assert summary['total_students']==3 and result.status.tolist()==['Normal','Concern','Incomplete']
    assert len(app.metric)==3
    assert len(app.get('download_button'))==2
    app.selectbox(key='student_view').set_value('Concern').run()
    assert app.dataframe[-1].value.student_id.tolist()==['002']
    app.selectbox(key='student_view').set_value('All').run()
    app.text_input(key='student_search').set_value('001').run()
    assert app.dataframe[-1].value.student_id.tolist()==['001']
    assert not any(b.label.startswith('Generate ') for b in app.button)
    app.session_state['studio_example']='preserved'
    uploads[0]=None;button(app,'Clear Student Data').click().run()
    assert not app.exception and not app.dataframe
    assert app.session_state['studio_example']=='preserved'
    assert 'student_raw' not in app.session_state and 'student_results' not in app.session_state
    assert not list((tmp/'uploads').glob('*.csv'))


def test_multisheet_explicit_selection_and_header(hub):
    start,_,_=hub
    app=start(workbook_bytes([('Section A',[['Synthetic title'],[],['Roll No','Name','Attendance','Quiz'],['001','A',90,80]],False),('Section B',[['Roll No','Name','Attendance','Quiz'],['002','B',90,80]],False)]),'x.xlsx')
    assert not app.exception and app.selectbox(key='student_sheet').value is None
    assert not app.dataframe
    app.selectbox(key='student_sheet').set_value('Section A').run()
    assert app.number_input(key='student_header_0').value==3
    analyze(app);assert app.session_state['student_results'][0].student_id.tolist()==['001']
    app.selectbox(key='student_sheet').set_value('Section B').run()
    assert not app.exception and 'student_results' not in app.session_state
    assert not app.checkbox(key='student_confirm').value
    analyze(app);assert app.session_state['student_results'][0].student_id.tolist()==['002']


def test_raw_marks_configuration(hub):
    start,_,_=hub
    app=start(b'Roll No,Name,Attendance,Quiz (20),Mid Sem\n001,A,82%,16,32\n002,B,61%,8,20\n003,C,N/A,15,\n')
    assert app.selectbox(key='student_assessment_scale_3').value=='raw'
    app.selectbox(key='student_assessment_scale_4').set_value('raw').run()
    assert app.number_input(key='student_assessment_max_4').value==0
    confirm_validate(app);assert app.error and 'student_validation' not in app.session_state
    app.number_input(key='student_assessment_max_4').set_value(40.).run()
    analyze(app)
    result,_=app.session_state['student_results']
    assert result.average_marks.tolist()==[80,45,75]
    assert result.status.tolist()==['Normal','Concern','Incomplete']


def test_ambiguous_mapping_requires_professor_override(hub):
    start,_,_=hub
    app=start(b'Name,Student Name,Attendance,Attendance %,Quiz\nA,A,90,90,80\n')
    assert app.selectbox(key='student_map_student_name').value is None
    assert app.selectbox(key='student_map_attendance').value is None
    confirm_validate(app);assert app.error
    app.selectbox(key='student_map_student_name').set_value('Name')
    app.selectbox(key='student_map_attendance').set_value('Attendance').run()
    analyze(app);assert app.session_state['student_results'][1]['total_students']==1

@pytest.mark.parametrize('data,name,match',[(b'bad','x.xlsx','XLSX'),(b'','x.csv','empty'),(b'A,B\n','x.xls','Supported')])
def test_controlled_upload_error(hub,data,name,match):
    start,_,_=hub;app=start(data,name)
    assert not app.exception and any(match in e.value for e in app.error)


def test_ui_size_guard_before_getvalue(hub):
    start,uploads,_=hub;app=start()
    file=Upload(b'data');file.size=11*1024*1024;file.getvalue=Mock(side_effect=AssertionError('No read'))
    uploads[0]=file;app.run()
    assert not app.exception and app.error;file.getvalue.assert_not_called()


def test_invalid_row_excluded_missing_preserved(hub):
    start,_,_=hub
    app=analyze(start(b'Roll No,Name,Attendance,Quiz\n001,A,90,80\n002,B,145,eighty\n003,C,,80\n'))
    assert not app.exception
    validation=app.session_state['student_validation']
    assert validation.summary['invalid_rows']==1 and validation.summary['incomplete_rows']==1
    assert app.session_state['student_results'][0].student_id.tolist()==['001','003']


def test_threshold_mapping_changes_hide_stale_results(hub):
    start,_,_=hub
    app=analyze(start(b'Roll No,Name,Attendance,Quiz\n001,A,90,80\n'))
    app.number_input(key='student_marks_limit').set_value(85.).run()
    assert 'student_results' not in app.session_state
    button(app,'Analyze eligible students').click().run()
    assert app.session_state['student_results'][0].needs_support.iloc[0]
    app.selectbox(key='student_map_attendance_scale').set_value('fraction').run()
    assert 'student_validation' not in app.session_state and 'student_results' not in app.session_state


def test_ui_privacy_no_llm_logs_or_student_persistence(hub,monkeypatch):
    import ai_provider
    start,_,tmp=hub
    forbidden=Mock(side_effect=AssertionError('No AI or private activity'))
    monkeypatch.setattr(ai_provider,'generate_chat',forbidden);monkeypatch.setattr(db,'log_activity',forbidden)
    app=analyze(start(b'Roll No,Name,Attendance,Quiz\nprivate-001,Synthetic private name,90,80\n'))
    forbidden.assert_not_called()
    assert not app.exception and not db.get_recent_activity()
    with db.material_connection() as conn:
        assert not conn.execute('SELECT * FROM materials').fetchall()
    assert not list((tmp/'uploads').iterdir()) and not (tmp/'chroma_db').exists()
    assert not any(p.suffix in {'.csv','.xlsx'} for p in tmp.rglob('*'))


def test_hidden_empty_sheets(hub):
    start,_,_=hub
    app=start(workbook_bytes([('Visible',[],False),('Hidden',[['Name','Attendance','Quiz'],['Synthetic',90,80]],True)]),'x.xlsx')
    app.selectbox(key='student_sheet').set_value('Visible').run()
    assert not app.exception and app.error
    app.selectbox(key='student_sheet').set_value('Hidden').run()
    assert not app.exception and app.warning
    analyze(app);assert app.session_state['student_results'][1]['total_students']==1


def test_new_upload_invalidates_prior_mapping_and_results(hub):
    start,uploads,_=hub
    app=analyze(start(b'Roll No,Name,Attendance,Quiz\n001,A,90,80\n'))
    uploads[0]=Upload(b'Student ID,Student Name,Attendance %,Assignment\n002,B,80,70\n')
    app.run()
    assert not app.exception and 'student_results' not in app.session_state
    assert not app.checkbox(key='student_confirm').value
    assert app.selectbox(key='student_map_student_id').value=='Student ID'
    analyze(app);assert app.session_state['student_results'][0].student_id.tolist()==['002']


def test_mapping_confirmation_revocation_hides_outputs(hub):
    start,_,_=hub
    app=analyze(start(b'Roll No,Name,Attendance,Quiz\n001,A,90,80\n'))
    app.checkbox(key='student_confirm').uncheck().run()
    assert 'student_results' not in app.session_state and 'student_validation' not in app.session_state
    assert button(app,'Validate student data').disabled


def test_empty_filtered_export(hub,monkeypatch):
    import student_hub_ui
    start,_,_=hub
    spy=Mock(wraps=student_hub_ui.result_csv_bytes);monkeypatch.setattr(student_hub_ui,'result_csv_bytes',spy)
    app=analyze(start(b'Roll No,Name,Attendance,Quiz\n001,A,90,80\n'))
    app.text_input(key='student_search').set_value('missing ID').run()
    assert not app.exception and app.dataframe[-1].value.empty
    assert spy.call_args.args[0].empty
