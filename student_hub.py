"""Ephemeral deterministic Student Data Hub services above the Build 3 engine."""
import io
import pandas as pd
from analytics_agent import analyze_performance, Thresholds, display_results
from student_ingestion import StudentDataError

RESULT_COLUMNS = ('student_id','student_name','status','average_marks','latest_marks','attendance',
                  'marks_trend','attendance_trend','academic_concern','attendance_concern',
                  'incomplete_data','practice_eligible','reasons')


def analyze_dataset(dataset, thresholds=None):
    if dataset.frame.empty:
        raise StudentDataError('No eligible student rows. Correct the validation errors first.')
    result, summary = analyze_performance(dataset.frame, thresholds=thresholds or Thresholds())
    if 'student_id' in dataset.frame:
        if dataset.mode == 'snapshot':
            result['student_id'] = dataset.frame.student_id.tolist()
        else:
            result['student_id'] = result.analysis_id
    result['status'] = ['Concern + incomplete' if r.academic_concern and r.incomplete_data else
                        'Incomplete' if r.incomplete_data else 'Concern' if r.academic_concern else 'Normal'
                        for _,r in result.iterrows()]
    return result, summary


def filter_students(frame, view='All', search=''):
    masks = {'All': pd.Series(True,index=frame.index), 'Concern': frame.needs_support,
             'Attendance concern': frame.attendance_concern, 'Academic concern': frame.practice_eligible,
             'Incomplete': frame.incomplete_data}
    if view not in masks:
        raise StudentDataError('Unknown student filter.')
    shown = frame.loc[masks[view]].copy()
    term = search.strip().casefold()
    if term:
        match = shown.student_name.astype(str).str.casefold().str.contains(term,regex=False)
        if 'student_id' in shown:
            match |= shown.student_id.astype(str).str.casefold().str.contains(term,regex=False)
        shown = shown.loc[match].copy()
    return shown


def public_results(frame):
    return display_results(frame).loc[:,[c for c in RESULT_COLUMNS if c in frame]].rename(
        columns={'academic_concern':'support_concern','practice_eligible':'academic_concern'})


def safe_csv_bytes(frame):
    """Escape spreadsheet-active strings, preserving numeric zeros and missingness."""
    clean = frame.astype(object).where(pd.notna(frame),'Missing').copy()
    def safe(value):
        return "'"+value if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@','\t','\r','\n')) else value
    clean = clean.map(safe)
    clean.columns = [safe(str(c)) for c in clean.columns]
    return clean.to_csv(index=False).encode('utf-8-sig')


def result_csv_bytes(frame):
    return safe_csv_bytes(public_results(frame))


def validation_csv_bytes(dataset):
    return safe_csv_bytes(dataset.validation_frame())


def clear_student_data(state):
    """Remove only this workflow's state; rotate uploader to release widget bytes."""
    epoch = state.get('student_epoch',0)+1
    for key in list(state):
        if key.startswith('student_') or key in {'analytics_signature','batch_letters','practice_sets'}:
            del state[key]
    state['student_epoch'] = epoch
