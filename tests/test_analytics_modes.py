import io
import math
import pandas as pd
import pytest
from analytics_agent import *


def snapshot(**changes):
    row=dict(student_name='Synthetic',attendance_percent=90,assignment=60,final=80);row.update(changes)
    return pd.DataFrame([row])


def trend(marks=(60,70,90),attendance=None,**changes):
    attendance = [90]*len(marks) if attendance is None else attendance
    data=dict(student_name=['Synthetic']*len(marks),assessment_number=list(range(1,len(marks)+1)),marks=list(marks),attendance_percent=list(attendance));data.update(changes)
    return pd.DataFrame(data)


def test_snapshot_arithmetic():
    frame=pd.DataFrame([dict(student_name='A',attendance=90,assignment=60,final=80),dict(student_name='B',attendance=60,assignment=20,final=40)])
    out,summary=analyze_performance(frame)
    assert out.average_marks.tolist()==[70,30]
    assert summary['class_average_marks']==(70+30)/2 and summary['average_attendance']==75
    assert summary['academic_concerns']==1 and summary['complete_data']==2

@pytest.mark.parametrize('changes,score,incomplete,concern',[({},70,False,False),({'assignment':None},80,True,False),({'assignment':None,'final':None},None,True,False),({'attendance_percent':None},70,True,False),({'assignment':20,'final':None,'attendance_percent':None},20,True,True)])
def test_missing_states(changes,score,incomplete,concern):
    out,_=analyze_performance(snapshot(**changes));row=out.iloc[0]
    assert row.incomplete_data==incomplete and row.academic_concern==concern
    assert pd.isna(row.average_marks) if score is None else row.average_marks==score
    if incomplete:assert row.missing_fields and row.reasons!='No concerns'

@pytest.mark.parametrize('column,value',[('assignment','bad'),('attendance_percent','bad'),('attendance_percent',-1),('attendance_percent',101),('assignment',-1),('assignment',float('inf')),('attendance_percent',float('-inf')),('student_name',' ')])
def test_validation(column,value):
    with pytest.raises(AnalyticsValidationError):analyze_performance(snapshot(**{column:value}))

@pytest.mark.parametrize('source',[pd.DataFrame(),pd.DataFrame({'student_name':['A'],'attendance':[90]}),pd.DataFrame({'student_name':['A'],'marks':[90]}),pd.DataFrame([['A',90,2]],columns=['student_name','attendance','attendance']),io.BytesIO(b'student_name,attendance,marks,marks\nA,90,2,3'),io.BytesIO(b'student_name,attendance,marks\nA,90,2,extra')])
def test_bad_schema(source):
    with pytest.raises(AnalyticsValidationError):analyze_performance(source)


def test_duplicate_snapshot_names():
    frame=pd.concat([snapshot(),snapshot(assignment=20)],ignore_index=True)
    out,summary=analyze_performance(frame)
    assert summary['total_students']==2 and out.analysis_id.nunique()==2


def test_one_marks_column():
    out,_=analyze_performance(snapshot().drop(columns='final'))
    assert out.average_marks.iloc[0]==60


def test_thresholds_and_counts():
    frame=pd.concat([snapshot(),snapshot(assignment=30,final=40,attendance_percent=None)],ignore_index=True)
    out,summary=analyze_performance(frame,thresholds=Thresholds(marks=80,attendance=95))
    assert out.academic_concern.tolist()==[True,True]
    assert summary['concern_and_incomplete']==1 and summary['incomplete_data']==1

@pytest.mark.parametrize('marks,attendance,mt,at',[([50,60,80],[70,80,95],'Improving','Improving'),([90,80,50],[90,85,60],'Declining','Declining'),([70,72,75],[90,91,92],'Stable','Stable'),([80],[90],'Not enough data','Not enough data'),([80,None],[90,90],'Insufficient data','Stable'),([None,80],[90,None],'Insufficient data','Insufficient data')])
def test_trends(marks,attendance,mt,at):
    out,_=analyze_performance(trend(marks,attendance));row=out.iloc[0]
    assert row.marks_trend==mt and row.attendance_trend==at
    if None in marks or None in attendance or len(marks)<2:assert row.incomplete_data


def test_trend_thresholds():
    out,_=analyze_performance(trend([90,85]),thresholds=Thresholds(marks_decline=4))
    assert out.practice_eligible.iloc[0]
    out,_=analyze_performance(trend([90,85]),thresholds=Thresholds(marks_decline=10))
    assert not out.practice_eligible.iloc[0]

@pytest.mark.parametrize('assessment',['bad',None,0,-1,1.5,float('inf')])
def test_invalid_assessment(assessment):
    with pytest.raises(AnalyticsValidationError):analyze_performance(trend([80],[90],assessment_number=[assessment]))


def test_explicit_identity():
    frame=pd.DataFrame({'student_name':['Same','Same'],'student_id':['idA','idB'],'assessment_number':[1,1],'marks':[80,30],'attendance_percent':[90,60]})
    out,summary=analyze_performance(frame)
    assert summary['total_students']==2 and out.analysis_id.nunique()==2


def test_batch_eligibility():
    frame=pd.DataFrame([dict(student_name='A',attendance=90,marks=20),dict(student_name='B',attendance=60,marks=80),dict(student_name='C',attendance=60,marks=20),dict(student_name='D',attendance=None,marks=80)])
    out,_=analyze_performance(frame)
    assert attendance_warning_candidates(out).student_name.tolist()==['B','C']
    assert practice_candidates(out).student_name.tolist()==['A','C']
    assert out.loc[3,'incomplete_data'] and not out.loc[3,'attendance_concern']


def test_filtered_unicode_export():
    frame=pd.concat([snapshot(student_name='Synthetic α',attendance_percent=None),snapshot(student_name='Other')],ignore_index=True)
    out,_=analyze_performance(frame);filtered=filter_results(out,'Incomplete data')
    exported=pd.read_csv(io.BytesIO(analytics_csv_bytes(filtered)),keep_default_na=False)
    assert exported.student_name.tolist()==['Synthetic α']
    assert exported.attendance.tolist()==['Missing'] and exported.incomplete_data.tolist()==[True]
    assert len(filter_results(out,'All students'))==2 and filter_results(out,'Both').empty


def test_no_llm_used(monkeypatch):
    import ollama
    monkeypatch.setattr(ollama,'chat',lambda **kwargs:(_ for _ in ()).throw(AssertionError('No LLM')))
    analyze_performance(snapshot());analyze_performance(trend())


def test_batch_and_practice_agent_boundary(agents,monkeypatch):
    frame=pd.DataFrame([dict(student_name='Marks',attendance=90,marks=20),dict(student_name='Attendance',attendance=60,marks=80),dict(student_name='Missing',attendance=None,marks=80)])
    out,_=analyze_performance(frame)
    from unittest.mock import Mock
    doc=agents['document_agent'];spy=Mock(return_value='Synthetic letter');monkeypatch.setattr(doc,'generate_document',spy)
    assert [r['student_name'] for r in doc.generate_batch_attendance_warnings(out,required_percent='70')]==['Attendance']
    assert spy.call_args.args[1]['required_percent']=='70'
    assessment=agents['assessment_agent'];mock=Mock(return_value=[]);monkeypatch.setattr(assessment,'generate_questions',mock)
    assert [r['student_name'] for r in assessment.generate_personalized_practice(out,'PCA')]==['Marks']
    mock.assert_called_once()
