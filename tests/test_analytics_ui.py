import pytest
from test_student_hub_ui import hub, analyze

@pytest.mark.parametrize('payload,mode',[(b'student_name,attendance,marks\nSynthetic,90,80\n','snapshot'),(b'student_name,assessment_number,marks,attendance_percent\nSynthetic,1,70,90\nSynthetic,2,80,90\n','trend')])
def test_analytics_upload(hub,payload,mode):
    start,_,tmp=hub
    app=analyze(start(payload))
    assert not app.exception and any(f'Detected mode: {mode}' in c.value for c in app.caption)
    assert len(app.metric)>=3 and app.get('download_button')
    assert not list((tmp/'uploads').glob('*.csv'))


def test_validation_and_filters(hub,monkeypatch):
    from unittest.mock import Mock
    import student_hub_ui
    start,uploads,_=hub
    spy=Mock(wraps=student_hub_ui.result_csv_bytes)
    monkeypatch.setattr(student_hub_ui,'result_csv_bytes',spy)
    app=analyze(start(b'student_name,attendance,marks\nMarks,90,20\nAttendance,60,80\nMissing,,80\n'))
    app.selectbox(key='student_view').set_value('Incomplete').run()
    assert not app.exception and app.dataframe[-1].value.student_name.tolist()==['Missing']
    assert spy.call_args.args[0].student_name.tolist()==['Missing']
    assert not any(b.label.startswith('Generate ') for b in app.button)
