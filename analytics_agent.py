"""Validated deterministic snapshot and history analytics; no model calls."""
import csv
import io
from dataclasses import dataclass
import math
import pandas as pd


class AnalyticsValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Thresholds:
    marks: float = 50
    attendance: float = 70
    marks_decline: float = 10
    attendance_decline: float = 10

    def __post_init__(self):
        for key, value in vars(self).items():
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
                raise AnalyticsValidationError(f'Invalid threshold: {key}')
        if self.attendance > 100 or self.marks_decline == 0 or self.attendance_decline == 0:
            raise AnalyticsValidationError('Attendance threshold must be 0–100; decline thresholds must be positive.')


DEFAULT_THRESHOLDS = Thresholds()


def read_input(source):
    if isinstance(source, pd.DataFrame):
        return source.copy()
    try:
        if hasattr(source, 'read'):
            raw = source.read()
        else:
            with open(source, 'rb') as stream:
                raw = stream.read()
        text = raw.decode('utf-8-sig') if isinstance(raw, bytes) else raw
        rows = list(csv.reader(io.StringIO(text), strict=True))
        if not rows or not rows[0]:
            raise AnalyticsValidationError('CSV is empty.')
        headers = rows[0]
        if len(set(headers)) != len(headers):
            raise AnalyticsValidationError('Duplicate column headers are not allowed.')
        for number, row in enumerate(rows[1:], start=2):
            if row and len(row) != len(headers):
                raise AnalyticsValidationError(f'Malformed CSV row {number}: expected {len(headers)} fields.')
        return pd.read_csv(io.StringIO(text), dtype={'student_id': 'string', 'student_name': 'string'})
    except AnalyticsValidationError:
        raise
    except Exception as exc:
        raise AnalyticsValidationError(f'Unable to read CSV: {exc}') from exc


def validate_input(source):
    frame = read_input(source).reset_index(drop=True)
    if frame.empty:
        raise AnalyticsValidationError('Input must contain student rows.')
    if not frame.columns.is_unique or any(not isinstance(c, str) or not c.strip() for c in frame.columns):
        raise AnalyticsValidationError('Column names must be unique, nonblank strings.')
    if 'student_name' not in frame:
        raise AnalyticsValidationError('Missing required column: student_name.')
    names = frame['student_name'].astype('string').str.strip()
    if names.isna().any() or names.eq('').any():
        raise AnalyticsValidationError('Student names must not be blank.')
    frame['student_name'] = names
    attendance_columns = [c for c in ('attendance', 'attendance_percent') if c in frame]
    if len(attendance_columns) != 1:
        raise AnalyticsValidationError('Provide exactly one attendance column: attendance or attendance_percent.')
    attendance = attendance_columns[0]
    if 'assessment_number' in frame:
        if 'marks' not in frame or attendance != 'attendance_percent':
            raise AnalyticsValidationError('Trend columns require assessment_number, marks, attendance_percent.')
        extras = set(frame.columns) - {'student_name','student_id','assessment_number','marks','attendance_percent'}
        if extras:
            raise AnalyticsValidationError('Ambiguous trend schema: unexpected columns ' + ', '.join(sorted(extras)))
        mode = 'trend'; marks = ['marks']
    else:
        mode = 'snapshot'
        marks = [c for c in frame if c not in {'student_name','student_id',attendance}]
        if not marks:
            raise AnalyticsValidationError('No usable marks columns; provide at least one numeric marks column.')
    for column in marks + [attendance] + (['assessment_number'] if mode == 'trend' else []):
        raw = frame[column]
        blank = raw.isna() | raw.astype('string').str.strip().eq('').fillna(False)
        converted = pd.to_numeric(raw.where(~blank), errors='coerce')
        invalid = ~blank & (converted.isna() | converted.map(lambda value: not math.isfinite(value) if pd.notna(value) else False))
        if invalid.any():
            raise AnalyticsValidationError(f'Invalid numeric values in column {column}; source rows {list(frame.index[invalid] + 1)}.')
        if converted.dropna().lt(0).any():
            raise AnalyticsValidationError(f'Column {column} must be nonnegative.')
        if column == attendance and converted.dropna().gt(100).any():
            raise AnalyticsValidationError('Attendance percentage must be within 0–100.')
        if column == 'assessment_number' and (converted.isna().any() or converted.le(0).any() or converted.dropna().mod(1).ne(0).any()):
            raise AnalyticsValidationError('assessment_number must be a present positive integer.')
        frame[column] = converted.astype(float)
    if 'student_id' in frame:
        ids = frame['student_id'].astype('string').str.strip()
        if ids.isna().any() or ids.eq('').any():
            raise AnalyticsValidationError('student_id must not be blank.')
        frame['student_id'] = ids
    if mode == 'trend':
        identity = 'student_id' if 'student_id' in frame else 'student_name'
        if frame.duplicated([identity, 'assessment_number']).any():
            raise AnalyticsValidationError('Ambiguous student identity: duplicate assessment numbers; provide distinct student_id values.')
        if 'student_id' in frame and frame.groupby('student_id')['student_name'].nunique().gt(1).any():
            raise AnalyticsValidationError('A student_id has inconsistent student names.')
    return frame, mode, marks, attendance


def calculate_trend(values, decline_threshold=DEFAULT_THRESHOLDS.marks_decline):
    if len(values) < 2:
        return 'Not enough data'  # retained public label, displayed as insufficient evidence
    if any(pd.isna(v) for v in values):
        return 'Insufficient data'
    change = values[-1] - sum(values[:-1]) / len(values[:-1])
    return 'Declining' if change <= -decline_threshold else 'Improving' if change >= decline_threshold else 'Stable'


def analyze_performance(source, attendance_threshold=DEFAULT_THRESHOLDS.attendance, marks_threshold=DEFAULT_THRESHOLDS.marks, *, thresholds=None):
    config = thresholds or Thresholds(marks=marks_threshold, attendance=attendance_threshold)
    frame, mode, marks, attendance = validate_input(source)
    records = []
    groups = ((f'row_{pos}', row['student_name'], pd.DataFrame([row])) for pos, (_, row) in enumerate(frame.iterrows())) if mode == 'snapshot' else ((str(identity), group['student_name'].iloc[0], group.sort_values('assessment_number')) for identity, group in frame.groupby('student_id' if 'student_id' in frame else 'student_name', sort=False))
    for identity, name, group in groups:
        missing = []; reasons = []; practice = False; attendance_concern = False
        if mode == 'snapshot':
            row = group.iloc[0]
            available = row[marks].dropna()
            score = float(available.mean()) if len(available) else float('nan')
            att = row[attendance]
            missing = [c for c in marks+[attendance] if pd.isna(row[c])]
            marks_trend = attendance_trend = 'Not applicable'
            if pd.notna(score) and score < config.marks:
                reasons.append(f'Average marks {score:g} < threshold {config.marks:g}');practice=True
        else:
            mh = group['marks'].tolist(); ah = group[attendance].tolist()
            score, att = mh[-1], ah[-1]
            marks_trend = calculate_trend(mh, config.marks_decline)
            attendance_trend = calculate_trend(ah, config.attendance_decline)
            for _, row in group.iterrows():
                missing.extend(f"{c} at assessment {int(row['assessment_number'])}" for c in ('marks',attendance) if pd.isna(row[c]))
            if len(group) < 2:
                missing.append('Insufficient history for trend evaluation')
            if pd.notna(score) and score < config.marks:
                reasons.append(f'Latest marks {score:g} < threshold {config.marks:g}');practice=True
            if marks_trend == 'Declining':
                decline = sum(mh[:-1])/len(mh[:-1])-mh[-1]
                reasons.append(f'Marks trend is declining by {decline:g} points');practice=True
            if attendance_trend == 'Declining':
                decline = sum(ah[:-1])/len(ah[:-1])-ah[-1]
                reasons.append(f'Attendance trend is declining by {decline:g} points')
        if pd.notna(att) and att < config.attendance:
            reasons.append(f"{'Latest attendance' if mode == 'trend' else 'Attendance'} {att:g}% < threshold {config.attendance:g}%")
            attendance_concern = True
        concern = bool(reasons); incomplete = bool(missing)
        records.append(dict(analysis_id=identity, student_name=name, average_marks=score if mode=='snapshot' else float('nan'), latest_marks=score, attendance=att, latest_attendance=att, marks_trend=marks_trend, attendance_trend=attendance_trend, academic_concern=concern, incomplete_data=incomplete, concern_reasons=reasons, missing_fields=missing, attendance_concern=attendance_concern, practice_eligible=practice, needs_support=concern, reasons='; '.join(reasons+(['Incomplete data: '+', '.join(missing)] if missing else [])) or 'No concerns'))
    result = pd.DataFrame(records)
    summary = dict(mode=mode, total_students=len(result), complete_data=int((~result.incomplete_data).sum()), incomplete_data=int(result.incomplete_data.sum()), academic_concerns=int(result.academic_concern.sum()), concern_and_incomplete=int((result.academic_concern & result.incomplete_data).sum()), class_average_marks=result.latest_marks.mean(), average_attendance=result.latest_attendance.mean(), marks_available_count=int(result.latest_marks.notna().sum()), attendance_available_count=int(result.latest_attendance.notna().sum()), averages_basis='Available student averages' if mode=='snapshot' else 'Available latest student values', students_needing_support=result.loc[result.academic_concern,'student_name'].tolist(), marks_trends=result.marks_trend.value_counts().to_dict(), attendance_trends=result.attendance_trend.value_counts().to_dict())
    return result, summary


def filter_results(frame, view='All students'):
    masks = {'All students': pd.Series(True,index=frame.index), 'Academic concern': frame.academic_concern, 'Incomplete data': frame.incomplete_data, 'Both': frame.academic_concern & frame.incomplete_data}
    if view not in masks:
        raise AnalyticsValidationError('Unknown analysis filter.')
    return frame.loc[masks[view]].copy()


def attendance_warning_candidates(frame):
    return frame.loc[frame.attendance_concern].copy()


def practice_candidates(frame):
    return frame.loc[frame.practice_eligible].copy()


def display_results(frame):
    display = frame.copy()
    for column in ('concern_reasons','missing_fields'):
        display[column] = display[column].map(lambda values: '; '.join(values))
    return display.astype(object).where(pd.notna(display), 'Missing')


def analytics_csv_bytes(frame):
    return display_results(frame).to_csv(index=False).encode('utf-8-sig')


if __name__ == '__main__':
    results, summary = analyze_performance('sample_trend_data.csv')
    print('Academic support report:', summary)
    for _, row in display_results(results).iterrows():
        print(row['student_name'], row['reasons'])
