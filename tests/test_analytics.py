import pandas as pd
import pytest
from analytics_agent import analyze_performance,calculate_trend

@pytest.mark.parametrize("values,expected", [([40,50,70],"Improving"),([80,70,50],"Declining"),([70,72,75],"Stable"),([70],"Not enough data")])
def test_trend(values,expected): assert calculate_trend(values)==expected

def analyze(monkeypatch,marks,attendance):
    frame=pd.DataFrame({"student_name":["Synthetic"]*len(marks),"assessment_number":range(1,len(marks)+1),"marks":marks,"attendance_percent":attendance})
    monkeypatch.setattr(pd,"read_csv",lambda path:frame)
    return analyze_performance("unused.csv")

@pytest.mark.parametrize("marks,att,reason", [([30],[90],"Latest marks"),([80],[60],"Latest attendance"),([80,75,60],[90,90,90],"declining")])
def test_support(monkeypatch,marks,att,reason):
    frame,summary=analyze(monkeypatch,marks,att)
    assert frame.iloc[0]["needs_support"] and reason in frame.iloc[0]["reasons"]
    assert summary["total_students"]==1

def test_valid(monkeypatch):
    frame,_=analyze(monkeypatch,[70,72,75],[90,91,92])
    assert not frame.iloc[0]["needs_support"]

@pytest.mark.xfail(strict=True,reason="Later analytics build: NaN must not imply no concerns")
def test_missing_data_known_gap(monkeypatch):
    frame,_=analyze(monkeypatch,[float('nan')],[float('nan')])
    assert frame.iloc[0]["reasons"]!="No concerns"

@pytest.mark.xfail(strict=True,reason="Later analytics build: controlled numeric validation")
def test_nonnumeric_known_gap(monkeypatch):
    with pytest.raises(ValueError,match="numeric"):
        analyze(monkeypatch,["bad",70],[90,90])

@pytest.mark.xfail(strict=True,reason="Later analytics build: controlled required-column validation")
def test_missing_column_known_gap(monkeypatch):
    monkeypatch.setattr(pd,"read_csv",lambda path:pd.DataFrame({"student_name":["Synthetic"]}))
    with pytest.raises(ValueError,match="column"):analyze_performance("unused.csv")

@pytest.mark.xfail(strict=True,reason="Later analytics build: distinct student IDs instead of name grouping")
def test_duplicate_names_known_gap(monkeypatch):
    frame=pd.DataFrame({"student_name":["Same","Same"],"assessment_number":[1,1],"marks":[80,30],"attendance_percent":[90,60]})
    monkeypatch.setattr(pd,"read_csv",lambda path:frame)
    assert analyze_performance("unused.csv")[1]["total_students"]==2
