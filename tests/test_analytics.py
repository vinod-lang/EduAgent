import pandas as pd
import pytest
from analytics_agent import analyze_performance,calculate_trend

@pytest.mark.parametrize("values,expected", [([40,50,70],"Improving"),([80,70,50],"Declining"),([70,72,75],"Stable"),([70],"Not enough data")])
def test_trend(values,expected): assert calculate_trend(values)==expected

def analyze(monkeypatch,marks,attendance):
    frame=pd.DataFrame({"student_name":["Synthetic"]*len(marks),"assessment_number":range(1,len(marks)+1),"marks":marks,"attendance_percent":attendance})
    return analyze_performance(frame)

@pytest.mark.parametrize("marks,att,reason", [([30],[90],"Latest marks"),([80],[60],"Latest attendance"),([80,75,60],[90,90,90],"declining")])
def test_support(monkeypatch,marks,att,reason):
    frame,summary=analyze(monkeypatch,marks,att)
    assert frame.iloc[0]["needs_support"] and reason in frame.iloc[0]["reasons"]
    assert summary["total_students"]==1

def test_valid(monkeypatch):
    frame,_=analyze(monkeypatch,[70,72,75],[90,91,92])
    assert not frame.iloc[0]["needs_support"]

def test_missing_data_known_gap(monkeypatch):
    frame,_=analyze(monkeypatch,[float('nan')],[float('nan')])
    assert frame.iloc[0]["reasons"]!="No concerns"

def test_nonnumeric_known_gap(monkeypatch):
    with pytest.raises(ValueError,match="numeric"):
        analyze(monkeypatch,["bad",70],[90,90])

def test_missing_column_known_gap(monkeypatch):
    with pytest.raises(ValueError,match="column"):
        analyze_performance(pd.DataFrame({"student_name":["Synthetic"]}))

def test_duplicate_names_known_gap(monkeypatch):
    frame=pd.DataFrame({"student_name":["Same","Same"],"assessment_number":[1,1],"marks":[80,30],"attendance_percent":[90,60]})
    with pytest.raises(ValueError, match="identity"):
        analyze_performance(frame)
