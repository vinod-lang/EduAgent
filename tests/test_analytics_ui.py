import io
from pathlib import Path
from unittest.mock import Mock
import pytest
import db
from streamlit.testing.v1 import AppTest

class Upload:
    def __init__(self, data): self.data=data
    def getvalue(self): return self.data

@pytest.mark.parametrize('payload,mode',[(b'student_name,attendance,marks\nSynthetic,90,80\n','snapshot'),(b'student_name,assessment_number,marks,attendance_percent\nSynthetic,1,70,90\nSynthetic,2,80,90\n','trend')])
def test_analytics_upload(agents,monkeypatch,tmp_path,payload,mode):
    import streamlit as st
    monkeypatch.chdir(tmp_path);monkeypatch.setattr(db,'DB_PATH',str(tmp_path/'test.db'))
    monkeypatch.setattr(st,'file_uploader',lambda *a,**k:Upload(payload))
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=20).run()
    app.sidebar.radio[0].set_value('Analytics').run()
    assert not app.exception and any(f'Detected mode: {mode}' in c.value for c in app.caption)
    assert len(app.dataframe)==1 and len(app.metric)>=3
    assert any(e.type=='download_button' for e in app.get('download_button'))
    assert not list((tmp_path/'uploads').glob('*.csv'))


def test_validation_and_filters(agents,monkeypatch,tmp_path):
    import streamlit as st
    monkeypatch.chdir(tmp_path);monkeypatch.setattr(db,'DB_PATH',str(tmp_path/'test.db'))
    import analytics_agent
    export_spy = Mock(wraps=analytics_agent.analytics_csv_bytes)
    monkeypatch.setattr(analytics_agent, 'analytics_csv_bytes', export_spy)
    payload=[b'student_name,attendance,marks\nSynthetic,90,bad\n']
    monkeypatch.setattr(st,'file_uploader',lambda *a,**k:Upload(payload[0]))
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=20).run()
    app.sidebar.radio[0].set_value('Analytics').run()
    assert not app.exception and app.error and not app.dataframe
    payload[0]=b'student_name,attendance,marks\nMarks,90,20\nAttendance,60,80\nMissing,,80\n'
    app.run();assert not app.exception
    labels={b.label for b in app.button}
    assert 'Generate Warning Letters for Attendance Concerns' in labels and 'Generate Personalized Practice Quizzes' in labels
    doc=Mock(return_value=[]);quiz=Mock(return_value=[])
    monkeypatch.setattr(agents['document_agent'],'generate_batch_attendance_warnings',doc)
    monkeypatch.setattr(agents['assessment_agent'],'generate_personalized_practice',quiz)
    next(b for b in app.button if b.label=='Generate Warning Letters for Attendance Concerns').click().run()
    assert doc.call_args.args[0].student_name.tolist()==['Attendance']
    next(b for b in app.button if b.label=='Generate Personalized Practice Quizzes').click().run()
    assert quiz.call_args.args[0].student_name.tolist()==['Marks']
    next(s for s in app.selectbox if s.label=='Investigation view').set_value('Incomplete data').run()
    assert not app.exception and app.dataframe[0].value.student_name.tolist()==['Missing']
    assert not any(b.label.startswith('Generate ') for b in app.button)
    assert export_spy.call_args.args[0].student_name.tolist()==['Missing']
