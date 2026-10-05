"""One explicit upload → mapping → validation → analytics workflow; no AI/storage."""
import hashlib
import streamlit as st
from analytics_agent import Thresholds, DEFAULT_THRESHOLDS
from student_ingestion import (MAX_BYTES, MAX_ROWS, MAX_COLUMNS, MAX_SHEETS, StudentDataError,
    suggested_maximum,
    Mapping, Assessment)
from student_hub import clear_student_data
from application import create_application_services
from application.errors import ApplicationError
service = create_application_services().students
parse_student_file = service.parse
header_candidates = service.headers
make_raw_table = service.table
suggest_columns = service.suggest
normalize_dataset = service.normalize
analyze_dataset = service.analyze_dataset
filter_students = service.filter
public_results = service.public
result_csv_bytes = service.csv
validation_csv_bytes = service.validation_csv


def _reset_derived(keep=()):
    for key in list(st.session_state):
        if key.startswith('student_') and key not in keep and not key.startswith('student_upload_') and key!='student_epoch':
            del st.session_state[key]


def render_student_hub():
    st.header('Student Data Hub')
    st.caption('CSV/XLSX stays in this session. No student data is saved or sent to AI. Clear Student Data releases it.')
    st.caption(f'Limits: 10 MB, {MAX_ROWS:,} rows, {MAX_COLUMNS} columns, {MAX_SHEETS} sheets. UTF-8 CSV only; XLS/XLSM unsupported.')
    st.button('Clear Student Data',key='hub_clear',on_click=clear_student_data,args=(st.session_state,))
    epoch = st.session_state.get('student_epoch',0)
    uploaded = st.file_uploader('Choose a student CSV or XLSX file',type=['csv','xlsx'],max_upload_size=10,key=f'student_upload_{epoch}')
    if uploaded is not None:
        try:
            if getattr(uploaded,'size',0)>MAX_BYTES:
                raise StudentDataError('Student file exceeds the 10 MB limit.')
            data = uploaded.getvalue()
            filename = getattr(uploaded,'name','students.csv')
            fingerprint = hashlib.sha256(data).hexdigest()+filename
            if st.session_state.get('student_fingerprint') != fingerprint:
                _reset_derived()
                book = parse_student_file(data,filename)
                st.session_state['student_book'] = book
                st.session_state['student_fingerprint'] = fingerprint
        except (ApplicationError,StudentDataError) as exc:
            _reset_derived()
            st.error(str(exc)); return
    book = st.session_state.get('student_book')
    if book is None:
        st.info('Choose a student spreadsheet to inspect and map its columns.'); return
    options = [s.name for s in book.sheets]
    selected = st.selectbox('Sheet to analyze',options,index=0 if len(options)==1 else None,
                            placeholder='Choose a sheet; sheets are never combined',key='student_sheet')
    if selected is None:
        st.info('Select a sheet before mapping.'); return
    sheet = book.sheet(selected)
    if sheet.hidden:
        st.warning('This sheet is hidden in the source workbook. It is analyzed only because you explicitly selected it.')
    if not sheet.rows:
        st.error('Selected sheet is empty.'); return
    candidates,confidence = header_candidates(sheet)
    st.caption(f'Header suggestion: {confidence}; candidate rows: {", ".join(map(str,candidates)) or "none"}. Confirm or correct the row below.')
    with st.expander('Raw sheet preview before header selection'):
        st.dataframe([list(r) for r in sheet.rows[:20]],hide_index=False)
    # Sheet-specific header keys avoid carrying a choice between unrelated sheets.
    header = int(st.number_input('Header row (1-based)',min_value=1,max_value=len(sheet.rows),
                value=candidates[0] if candidates else 1,step=1,key=f'student_header_{options.index(selected)}'))
    try:
        table = make_raw_table(sheet,header)
    except (ApplicationError,StudentDataError) as exc:
        st.error(str(exc)); return
    table_key = (st.session_state['student_fingerprint'],selected,header)
    if st.session_state.get('student_table_key') != table_key:
        # Only mapping/results are reset; preserve the currently rendered widgets.
        for key in list(st.session_state):
            if key.startswith(('student_map_','student_assessment_','student_confirm','student_validation','student_results','student_analysis','student_search','student_view')):
                del st.session_state[key]
        st.session_state['student_table_key'] = table_key
    st.session_state['student_raw'] = table
    st.subheader('Raw data preview')
    st.caption(f'{len(table.frame):,} rows · {len(table.frame.columns)} columns. Preview limited to 20 rows; original labels remain visible.')
    st.dataframe(table.frame.head(20),hide_index=True)
    suggestions = suggest_columns(table)
    st.subheader('Confirm column mapping')
    columns = list(table.frame)
    def selector(role,label,optional=True):
        suggestion = suggestions[role]
        st.caption(f'{label}: {suggestion.confidence}' + (f' — {", ".join(suggestion.candidates)}' if suggestion.candidates else ''))
        choices = [None]+columns
        return st.selectbox(label,choices,index=choices.index(suggestion.selected) if suggestion.selected else 0,
                            format_func=lambda v:'Not mapped' if v is None else v,key='student_map_'+role)
    identity = selector('student_id','Student ID / Roll Number')
    name = selector('student_name','Student Name')
    attendance = selector('attendance','Attendance')
    assessment_number = selector('assessment_number','Assessment number (history mode; optional)')
    scale = st.selectbox('Attendance representation',['auto','percentage','fraction'],key='student_map_attendance_scale')
    st.caption('Auto: 75/75% → 75%, 0.75 → 75%, 0 → 0%; values 1–<2 require an explicit scale. Fraction mode: 1.0 → 100%. Percentage mode: 1.0 → 1%.')
    assessment_columns = st.multiselect('Assessment / marks columns',columns,
                                        default=list(suggestions['assessments'].candidates),key='student_map_assessments')
    assessments = []
    for column in assessment_columns:
        pos = columns.index(column)
        with st.expander(f'Configure assessment: {column}',expanded=True):
            label = st.text_input('Assessment display name',value='marks' if assessment_number else column,key=f'student_assessment_name_{pos}')
            maximum = suggested_maximum(column)
            representation = st.selectbox('Marks representation',['percentage','raw'],index=1 if maximum else 0,key=f'student_assessment_scale_{pos}')
            max_value = None
            if representation == 'raw':
                max_value = st.number_input('Maximum marks (required)',min_value=0.0,value=maximum or 0.0,key=f'student_assessment_max_{pos}')
            st.caption('Percentage mode must be explicitly confirmed; raw marks need a positive maximum. Raw scores are converted to percentages, then averaged equally by Build 3.')
            assessments.append(Assessment(column,label,representation,max_value))
    mapping = Mapping(identity,name,attendance,tuple(assessments),scale,assessment_number)
    confirmed = st.checkbox('I confirm the header, identity, attendance scale and assessment mappings',key='student_confirm')
    signature = (table_key,mapping,confirmed)
    if st.session_state.get('student_validation_key') != signature:
        st.session_state.pop('student_validation',None)
        st.session_state.pop('student_results',None)
    if st.button('Validate student data',disabled=not confirmed,key='student_validate'):
        if not confirmed:
            st.warning('Confirm the mappings first.'); return
        try:
            st.session_state['student_validation'] = normalize_dataset(table,mapping)
            st.session_state['student_validation_key'] = signature
            st.session_state.pop('student_results',None)
        except (ApplicationError,StudentDataError) as exc:
            st.error(str(exc))
    dataset = st.session_state.get('student_validation')
    if dataset is None:
        st.info('Confirm mappings and validate before running analytics.'); return
    st.subheader('Validation report')
    st.write(dataset.summary)
    if dataset.issues:
        st.dataframe(dataset.validation_frame(),hide_index=True)
    st.caption('ERROR rows are excluded; WARNING rows with missing values remain incomplete. Duplicate identities are never merged. Invalid history blocks the whole affected identity to avoid a misleading trend.')
    st.download_button('Download validation report (CSV)',validation_csv_bytes(dataset),'student_validation.csv','text/csv')
    if dataset.frame.empty:
        st.error('No eligible students. Correct the source or mapping and validate again.'); return
    st.subheader('Deterministic analytics')
    marks_limit = st.number_input('Marks concern threshold (%)',min_value=0.0,max_value=100.0,value=float(DEFAULT_THRESHOLDS.marks),key='student_marks_limit')
    attendance_limit = st.number_input('Attendance concern threshold (%)',min_value=0.0,max_value=100.0,value=float(DEFAULT_THRESHOLDS.attendance),key='student_attendance_limit')
    marks_decline = st.number_input('Marks decline threshold (percentage points)',min_value=0.1,value=float(DEFAULT_THRESHOLDS.marks_decline),key='student_marks_decline')
    attendance_decline = st.number_input('Attendance decline threshold (percentage points)',min_value=0.1,value=float(DEFAULT_THRESHOLDS.attendance_decline),key='student_attendance_decline')
    thresholds = Thresholds(marks_limit,attendance_limit,marks_decline,attendance_decline)
    analysis_key = (signature,thresholds)
    if st.session_state.get('student_analysis_key') != analysis_key:
        st.session_state.pop('student_results',None)
    if st.button('Analyze eligible students',key='student_analyze'):
        try:
            st.session_state['student_results'] = analyze_dataset(dataset,thresholds)
            st.session_state['student_analysis_key'] = analysis_key
        except (StudentDataError,ValueError) as exc:
            st.error(str(exc))
    outcome = st.session_state.get('student_results')
    if outcome is None:
        return
    result, summary = outcome
    st.caption(f"Detected mode: {summary['mode']}")
    st.metric('Total Students',summary['total_students'])
    st.metric('Academic/support concerns',summary['academic_concerns'])
    st.metric('Incomplete data',summary['incomplete_data'])
    st.caption(f"Complete: {summary['complete_data']}; concern + incomplete: {summary['concern_and_incomplete']}")
    def available(v):
        return 'Unavailable' if v!=v else f'{v:.2f}'
    st.write(f"Class marks average: {available(summary['class_average_marks'])}%; attendance average: {available(summary['average_attendance'])}%. Based on {summary['averages_basis'].lower()}.")
    st.caption(f"Marks available for {summary['marks_available_count']} students; attendance available for {summary['attendance_available_count']}.")
    if summary['mode']=='trend':
        st.write({'Marks trends':summary['marks_trends'],'Attendance trends':summary['attendance_trends']})
    view = st.selectbox('Student view',['All','Concern','Attendance concern','Academic concern','Incomplete'],key='student_view')
    search = st.text_input('Search student name or ID',key='student_search')
    shown = filter_students(result,view,search)
    st.dataframe(public_results(shown),hide_index=True)
    st.download_button('Download current view (CSV)',result_csv_bytes(shown),'student_results.csv','text/csv')
    for _,row in shown.iterrows():
        with st.expander(f"{row['student_name']} — {row['status']}"):
            st.write(row['reasons'])
    st.caption('No student records are sent to AI. Personalized generation and student-data persistence require a separate privacy design.')
