"""Assessment Studio controls; backend owns validation, grounding and arithmetic."""
import hashlib
import streamlit as st
from generation_ui import render_diagnostic
from generation_diagnostics import from_error,validated
from dashboard import natural_key
from assessment_spec import AssessmentScope,AssessmentSpec,AssessmentError,TYPES,DIFFICULTIES,BLOOMS
from assessment_export import AssessmentExportError
from application import create_application_services
from application.errors import ApplicationError
services = create_application_services()
generate_assessment = services.assessments.generate
extract_pyq = services.assessments.extract_pyq
assessment_pdf_bytes = services.assessments.pdf
assessment_docx_bytes = services.assessments.docx
from ai_provider import AIProviderError
from retrieval import RetrievalError


def scope_records():
    return services.materials.scope_records()


def _choice(label,rows,scope,field):
    values=sorted({r[field] for r in rows if all(r.get(k)==v for k,v in scope.items()) and isinstance(r.get(field),str) and r[field].strip()},key=natural_key)
    key='assessment_'+field
    if key in st.session_state and st.session_state[key] not in values:
        st.session_state[key]=values[0] if values else None
    return st.selectbox(label,values,key=key,index=0 if values else None)


def render_assessment_studio():
    st.header('Assessment Studio')
    mode=st.radio('Assessment mode',['Quiz','Question Paper'],horizontal=True,key='assessment_mode')
    rows=scope_records(); scope={}
    for key in ('course','semester','subject'):
        value=_choice(key.capitalize(),rows,scope,key)
        if value:scope[key]=value
    eligible=[r for r in rows if len(scope)==3 and all(r.get(k)==v for k,v in scope.items())]
    unit_options=sorted({r['unit'] for r in eligible if isinstance(r.get('unit'),str) and r['unit'].strip()},key=natural_key)
    if 'assessment_units' in st.session_state:
        st.session_state['assessment_units']=[value for value in st.session_state['assessment_units'] if value in unit_options]
    units=st.multiselect('Units',unit_options,key='assessment_units')
    managed=[r for r in eligible if r.get('material_id') and r.get('unit') in units]
    labels={r['material_id']:f"{r['original_filename']} - {r['unit']} - Uploaded {r.get('created_at') or 'Time unavailable'}" for r in managed}
    if 'assessment_materials' in st.session_state:
        st.session_state['assessment_materials']=[value for value in st.session_state['assessment_materials'] if value in labels]
    identities=st.multiselect('Materials (optional)',list(labels),format_func=labels.__getitem__,key='assessment_materials')
    st.caption('No Material selection uses eligible evidence in the selected Units. Legacy content participates only when its stored metadata matches the full scope; missing hierarchy is not inferred.')
    title=st.text_input('Assessment title',value=mode,key='assessment_title_'+mode)
    institution=st.text_input('Institution (optional)',key='assessment_institution')
    topic=st.text_input('Focus / topic',value='Key concepts and applications',key='assessment_topic')
    instructions=st.text_area('Student instructions',value='Answer all questions.',key='assessment_instructions')
    st.subheader('Question types')
    types={k:st.number_input(k+' count',min_value=0,max_value=100,value=3 if k=='MCQ' else 2,key='assessment_type_'+k) for k in TYPES}
    total=sum(types.values());st.caption(f'Total questions: {total}')
    st.subheader('Difficulty distribution')
    difficulty={k:st.number_input(k+' count',min_value=0,max_value=100,value={'Easy':1,'Medium':3,'Hard':1}[k],key='assessment_difficulty_'+k) for k in DIFFICULTIES}
    st.subheader('Bloom distribution')
    blooms={k:st.number_input(k+' count',min_value=0,max_value=100,value={'Remember':1,'Understand':2,'Apply':2}.get(k,0),key='assessment_bloom_'+k) for k in BLOOMS}
    marks=st.number_input('Total marks',min_value=1,max_value=10000,value=10,key='assessment_marks')
    st.caption(f'Question types total = {total}; Difficulty total = {sum(difficulty.values())}; Bloom total = {sum(blooms.values())}.')
    spec=None
    try:
        spec=AssessmentSpec(mode,AssessmentScope(scope.get('course'),scope.get('semester'),scope.get('subject'),tuple(units),tuple(identities)),types,difficulty,blooms,total,marks,title,institution,instructions,topic)
        st.subheader('Deterministic question plan')
        st.dataframe([s.to_dict() for s in spec.plan],hide_index=True)
    except (ApplicationError,AssessmentError) as exc:
        st.warning(str(exc))
    pyq=st.file_uploader('Optional PYQ style guidance',type=['pdf','png','jpg','jpeg'],key='assessment_pyq')
    st.caption('PYQs guide style only; they are temporarily extracted locally and never registered as teaching materials. Verbatim reuse is rejected where detectable.')
    fingerprint=hashlib.sha256(pyq.getvalue()).hexdigest() if pyq is not None else None
    if st.button('Generate assessment',disabled=spec is None):
        st.session_state.pop('assessment_result',None)
        if spec is None:
            st.warning('Correct the specification before generation.')
        else:
            try:
                with st.spinner('Retrieving scoped evidence and generating a validated assessment...'):
                    guidance=extract_pyq(pyq.getvalue(),pyq.name) if pyq is not None else ''
                    result=generate_assessment(spec,pyq_text=guidance)
                st.session_state['assessment_result']=(result,fingerprint)
                try:
                    services.activity.record('assessment_generated')
                except Exception:
                    st.warning('Assessment validated, but the activity event could not be recorded.')
            except (ApplicationError,AssessmentError,AIProviderError,RetrievalError) as exc:
                render_diagnostic(from_error(exc))
    stored=st.session_state.get('assessment_result')
    if not stored:return
    result,generated_fingerprint=stored
    if spec!=result.spec or fingerprint!=generated_fingerprint:
        st.info('Configuration/PYQ changed. Regenerate to review and export the current specification.');return
    render_assessment_result(result)


def render_assessment_result(result, key_prefix="assessment_studio"):
    spec=result.spec
    render_diagnostic(validated(result.provenance))
    st.success('Assessment structure validated. Review academic accuracy, difficulty and Bloom alignment before use.')
    st.subheader('Validation summary')
    summary=result.validation_summary
    checks=[dict(Check='Questions',Actual=summary['questions'],Requested=spec.total_questions),dict(Check='Marks',Actual=summary['total_marks'],Requested=spec.total_marks)]
    for key,expected in [('question_types',spec.question_types),('difficulties',spec.difficulties),('blooms',spec.blooms)]:
        checks.extend(dict(Check=label,Actual=summary[key].get(label,0),Requested=count) for label,count in expected.items())
    st.dataframe(checks,hide_index=True)
    st.caption('Requested distributions and marks satisfied; evidence references and MCQ structure validated. Academic review is still required.')
    st.subheader('Professor review')
    for q in result.questions:
        st.markdown(f'**Q{q.question_number}. [{q.marks} marks] {q.question_text}**')
        st.caption(f'{q.question_type} | {q.difficulty} | {q.bloom_level}')
        for letter,text in q.options:st.write(f'{letter}) {text}')
        for source in q.sources:st.caption('Retrieved source: '+source)
        with st.expander(f'Professor answer key Q{q.question_number}'):
            if q.correct_answer:st.write('Correct answer: '+q.correct_answer)
            st.write('Suggested model answer: '+q.model_answer)
    st.subheader('Separate exports')
    st.caption('Student paper excludes answer keys and internal retrieval metadata. Professor keys are separate and require grading review.')
    try:
        paper=assessment_pdf_bytes(result);key=assessment_pdf_bytes(result,answer_key=True)
        st.download_button('Student paper PDF',paper,'assessment.pdf','application/pdf',key=key_prefix+'_paper_pdf')
        st.download_button('Professor answer key PDF',key,'assessment_answer_key.pdf','application/pdf',key=key_prefix+'_key_pdf')
        st.download_button('Student paper DOCX',assessment_docx_bytes(result),'assessment.docx','application/vnd.openxmlformats-officedocument.wordprocessingml.document',key=key_prefix+'_paper_docx')
        st.download_button('Professor answer key DOCX',assessment_docx_bytes(result,answer_key=True),'assessment_answer_key.docx','application/vnd.openxmlformats-officedocument.wordprocessingml.document',key=key_prefix+'_key_docx')
    except (ApplicationError,AssessmentExportError) as exc:st.error(str(exc))
