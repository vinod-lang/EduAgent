from retrieval import RetrievalError
from rag_ui import available_courses, scope_options
from dashboard import get_dashboard_summary, material_type, QUICK_ACTIONS
from config import get_max_upload_bytes, ConfigurationError
import streamlit as st
import os
from content_agent import extract_text_from_pdf
from material_service import upload_material, delete_material, edit_hierarchy, MaterialError
from student_support_agent import answer_question
from assessment_agent import generate_questions
from document_agent import generate_document
from analytics_agent import (analyze_performance, AnalyticsValidationError, Thresholds, DEFAULT_THRESHOLDS,
    filter_results, display_results, analytics_csv_bytes, attendance_warning_candidates, practice_candidates)
from coordinator import classify_intent
from export_utils import generate_docx_bytes, generate_quiz_pdf_bytes, generate_question_paper_pdf_bytes
from document_agent import generate_batch_attendance_warnings
from db import list_materials, legacy_materials, init_db, add_course_if_new, get_all_courses, add_document_record, get_documents_for_course, log_activity, get_recent_activity
from assessment_agent import generate_questions, generate_personalized_practice
from assessment_agent import generate_questions, generate_personalized_practice, generate_question_paper

from ai_provider import AIProviderError


def call_ai(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except (AIProviderError, RetrievalError) as exc:
        st.error(str(exc))
        st.stop()


init_db()  # creates tables if they don't exist yet — safe to call every run


# Page setup
st.set_page_config(page_title="EduAgent", page_icon="🎓", layout="centered")
st.title("🎓 EduAgent — AI Assistant for Course Material")

# --- COORDINATOR LOGIC ---
# This sidebar selection IS the coordinator: it decides which
# "agent" gets control based on what the user wants to do.
page = st.sidebar.radio(
    "Choose an action:",
    ["Professor Dashboard","Smart Assistant","Upload Content", "Ask a Question", "Generate Quiz", "Draft Document", "Analytics", "Courses & Activity", "Question Paper"], key="navigation"
)

# Make sure a folder exists to temporarily store uploaded files
os.makedirs("uploads", exist_ok=True)

def navigate_to(page_name):
    st.session_state['navigation'] = page_name


if page == "Professor Dashboard":
    st.header("Professor Dashboard")
    overview = get_dashboard_summary()
    cards = st.columns(3)
    cards[0].metric("Registered courses", overview['course_count'])
    cards[1].metric("Managed materials", overview['managed_count'])
    cards[2].metric("Legacy registered documents", overview['legacy_count'])
    st.caption("Counts use SQLite records. Legacy records do not verify indexed vectors; unregistered Chroma content is not counted.")
    st.subheader("Quick actions")
    for target in QUICK_ACTIONS:
        st.button(target, on_click=navigate_to, args=(target,))
    st.subheader("Managed materials by course")
    if overview['materials_by_course']:
        for course_name, count in overview['materials_by_course'].items():
            st.write(f"{course_name}: {count}")
    else:
        st.info("No registered courses yet. Upload academic content to get started.")
    st.subheader("Recently uploaded managed materials")
    for material in overview['recent_materials']:
        st.write(material['original_filename'])
        st.caption(material_type(material) + " · " + " → ".join(material[k] for k in ('course', 'semester', 'subject', 'unit')))
    if not overview['recent_materials']:
        st.info("No managed materials yet. Existing legacy records remain available in Courses & Activity.")
    st.subheader("Recent activity")
    for activity in overview['recent_activity']:
        st.write(f"{activity['timestamp']} — {activity['action']}")
    if not overview['recent_activity']:
        st.info("No recent activity.")


# --- COORDINATOR AGENT (smart routing) ---
if page == "Smart Assistant":
    st.header("🧭 Coordinator Agent")
    st.write("Type what you want in plain English. The coordinator will decide which agent(s) should handle it.")

    user_input = st.text_area(
        "What do you need?",
        placeholder="e.g. 'Make a 10-question quiz from Unit 3 and a notice announcing it for tomorrow'"
    )

    if st.button("Submit"):
        if user_input.strip() == "":
            st.warning("Please type a request.")
        else:
            with st.spinner("Deciding which agent(s) should handle this..."):
                intent = call_ai(classify_intent, user_input)

            st.caption(f"🔀 Routed to: **{intent}**")

            if intent == "question":
                with st.spinner("Thinking..."):
                    answer, sources = call_ai(answer_question, user_input)
                st.write(answer)
                if sources:
                    st.caption(f"📚 Source: {', '.join(sources)}")

            elif intent == "quiz":
                with st.spinner("Generating quiz..."):
                    questions = call_ai(generate_questions, source_name="PCA", num_questions=5)
                if questions:
                    for i, q in enumerate(questions, start=1):
                        st.markdown(f"**Q{i}. {q['question']}**")
                        if "options" in q:
                            for letter, opt in q["options"].items():
                                st.write(f"{letter}) {opt}")
                else:
                    st.error("Could not generate a valid quiz.")

            elif intent == "document":
                with st.spinner("Drafting document..."):
                    doc = call_ai(generate_document, "Notice", {
                        "course": "General", "subject": user_input,
                        "details": user_input, "date": "TBD"
                    })
                st.text_area("Result:", value=doc, height=250)

            elif intent == "quiz_and_notice":
                # STEP 1: Assessment Agent runs first
                with st.spinner("Step 1/2 — Generating quiz..."):
                    questions = call_ai(generate_questions, source_name="PCA", num_questions=5)

                # STEP 2: Document Agent runs next, referencing the quiz
                with st.spinner("Step 2/2 — Drafting announcement notice..."):
                    doc = call_ai(generate_document, "Notice", {
                        "course": "General",
                        "subject": "Upcoming Test",
                        "details": user_input,
                        "date": "Tomorrow"
                    })

                st.success("✅ Two agents completed this request — please review both before use.")

                st.subheader("1️⃣ Generated Quiz (Assessment Agent)")
                if questions:
                    for i, q in enumerate(questions, start=1):
                        st.markdown(f"**Q{i}. {q['question']}**")
                        if "options" in q:
                            for letter, opt in q["options"].items():
                                st.write(f"{letter}) {opt}")
                else:
                    st.error("Quiz generation failed.")

                st.subheader("2️⃣ Generated Notice (Document Agent)")
                st.text_area("Notice:", value=doc, height=200)

            else:
                st.info("I couldn't confidently classify this request. Try rephrasing, or use the sidebar tabs directly.")


# --- PAGE 1: CONTENT AGENT ---
if page == "Upload Content":
    st.header("📄 Content Agent")
    st.write("Upload PDF, PNG, JPG or JPEG academic content. Images use local Tesseract OCR.")

    course = st.text_input("Course name:", value="B.Tech CSE")
    semester = st.text_input("Semester:", value="Semester 5")
    subject = st.text_input("Subject:", value="Machine Learning")
    unit = st.text_input("Unit:", value="Unit 1")
    uploaded_file = st.file_uploader("Choose a PDF or image", type=["pdf", "png", "jpg", "jpeg"])
    try:
        upload_limit = get_max_upload_bytes()
        st.caption(f"Maximum upload size: {upload_limit / 1024 / 1024:g} MB")
    except ConfigurationError as exc:
        st.error(str(exc))
        st.stop()

    if st.button("Add to Database"):
        if uploaded_file is None:
            st.warning("Choose a PDF or image first.")
        else:
            try:
                if uploaded_file.size > upload_limit:
                    raise MaterialError("Upload exceeds the configured size limit.")
                with st.spinner("Extracting content and storing chunks..."):
                    outcome = upload_material(uploaded_file.getvalue(), uploaded_file.name,
                        dict(course=course, semester=semester, subject=subject, unit=unit))
                if outcome["success"]:
                    material = outcome["material"]
                    st.success(f"Indexed {material['original_filename']} — " + " → ".join(material[k] for k in ('course','semester','subject','unit')))
                    if outcome.get("text_preview"):
                        st.caption("Extracted OCR text preview (up to 1,000 characters)")
                        st.text(outcome["text_preview"])
                else:
                    st.warning(outcome["error"])
                for warning in outcome.get("warnings", []):
                    st.warning(warning)
            except MaterialError as exc:
                st.error(str(exc))


# --- PAGE 2: STUDENT SUPPORT AGENT ---
elif page == "Ask a Question":
    st.header("💬 Student Support Agent")
    st.write("Ask a question based on the uploaded course material.")

    materials = list_materials()
    scope = {}
    selected_course = st.selectbox("Course scope:", [None] + available_courses(materials),
                                   format_func=lambda value: "All courses" if value is None else value)
    if selected_course is not None:
        scope['course'] = selected_course
    for level in ('semester', 'subject', 'unit'):
        choices = scope_options(materials, scope, level)
        selected = st.selectbox(level.capitalize() + " scope:", [None] + choices,
                                format_func=lambda value: "All / no filter" if value is None else value)
        if selected is not None:
            scope[level] = selected
    material_choices = scope_options(materials, scope, 'material_id')
    selected_material = st.selectbox("Material scope:", [None] + list(material_choices),
        format_func=lambda value: "All matching materials" if value is None else material_choices[value])
    if selected_material is not None:
        scope['material_id'] = selected_material
    st.caption("Legacy content remains searchable broadly or by course. Deeper filters require stored metadata and exclude incompatible legacy chunks.")
    question = st.text_input("Your question:")

    if st.button("Ask"):
        if question.strip() == "":
            st.warning("Please type a question first.")
        else:
            with st.spinner("Retrieving evidence and answering..."):
                result = call_ai(answer_question, question, filters=scope)
            if result.retrieval_status == 'no_evidence':
                st.info(result.answer)
            else:
                st.markdown("**Answer:**")
                st.write(result.answer)
            if result.sources:
                st.markdown("**Retrieved evidence sources:**")
                for source in result.sources:
                    st.caption(source)
            with st.expander("Development: retrieval diagnostics"):
                st.json(result.retrieval.diagnostics.to_dict())


# --- PAGE 3: ASSESSMENT AGENT ---
elif page == "Generate Quiz":
    st.header("📝 Assessment Agent")
    st.write("Generate questions from the course material.")

    source_name = st.text_input("Source name:", value="PCA")
    course_filter = st.text_input("Course (optional):", value="")
    question_type = st.selectbox("Question type:", ["MCQ", "Descriptive"])
    difficulty = st.selectbox("Difficulty:", ["Easy", "Medium", "Hard"])
    num_questions = st.slider("Number of questions:", 1, 10, 5)

    if st.button("Generate Questions"):
        with st.spinner("Generating questions... this can take a minute on a local model"):
            course_arg = course_filter if course_filter.strip() else None
            questions = call_ai(generate_questions,
                source_name=source_name,
                course=course_arg,
                num_questions=num_questions,
                question_type=question_type,
                difficulty=difficulty
            )

        if questions is None:
            st.error("Could not generate valid questions. Try again.")
        else:
            st.session_state["questions"] = questions
            log_activity("generate_quiz", f"{num_questions} {question_type} questions from {source_name}")

    if "questions" in st.session_state:
        questions = st.session_state["questions"]

        st.subheader("Generated Questions (review before use)")
        pdf_buffer = generate_quiz_pdf_bytes(questions, title=f"{source_name} — Quiz")
        st.download_button(
        label="📥 Download Quiz + Answer Key (PDF)",
        data=pdf_buffer,
        file_name=f"{source_name.replace(' ', '_')}_quiz.pdf",
        mime="application/pdf"
    )
        for i, q in enumerate(questions, start=1):
            st.markdown(f"**Q{i}. {q['question']}**")

            if "options" in q:
                for letter, opt in q["options"].items():
                    st.write(f"{letter}) {opt}")
                with st.expander(f"Show answer — Q{i}"):
                    st.write(f"**Answer:** {q['correct_answer']}")
                    st.write(q.get("explanation", ""))
            else:
                with st.expander(f"Show model answer — Q{i}"):
                    st.write(q["model_answer"])

            st.caption(f"📚 Source: {q['source_label']}")
            st.write("---")

# --- PAGE 4: DOCUMENT AGENT ---
elif page == "Draft Document":
    st.header("📋 Document Agent")
    st.write("Pick a template and fill in the details — no need to write full sentences.")

    from document_agent import TEMPLATES  # import the template definitions

    template_name = st.selectbox("Document type:", list(TEMPLATES.keys()))
    fields_needed = TEMPLATES[template_name]["fields"]

    # Dynamically create one input box per field this template needs
    field_values = {}
    for field in fields_needed:
        label = field.replace("_", " ").capitalize()
        field_values[field] = st.text_input(label, key=f"doc_{field}")

    if st.button("Generate Document"):
        missing = [f for f in fields_needed if not field_values[f].strip()]
        if missing:
            st.warning(f"Please fill in: {', '.join(missing)}")
        else:
            with st.spinner("Drafting document..."):
                document = call_ai(generate_document, template_name, field_values)
            st.session_state["document"] = document
            st.session_state["document_template"] = template_name
            st.session_state.pop("document_editor", None)
            log_activity("generate_document", f"{template_name} document generated")

    if "document" in st.session_state:
        st.subheader("Generated Document (review before sending)")
        st.session_state["document"] = st.text_area("Result:", value=st.session_state["document"], height=300, key="document_editor")

        docx_buffer = generate_docx_bytes(st.session_state["document"])
        st.download_button(
            label="📥 Download as Word Document (.docx)",
            data=docx_buffer,
            file_name=f"{st.session_state.get('document_template', 'Document').replace(' ', '_')}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

# --- PAGE 5: ANALYTICS AGENT ---
elif page == "Analytics":
    
    st.header("📊 Analytics Agent")
    st.write("Upload snapshot marks or multi-assessment history. Analysis stays in memory.")
    csv_file = st.file_uploader("Choose a CSV file", type="csv")
    marks_limit = st.number_input("Marks concern threshold", min_value=0.0, value=float(DEFAULT_THRESHOLDS.marks))
    attendance_limit = st.number_input("Attendance concern threshold (%)", min_value=0.0, max_value=100.0, value=float(DEFAULT_THRESHOLDS.attendance))
    marks_decline = st.number_input("Marks decline threshold", min_value=0.1, value=float(DEFAULT_THRESHOLDS.marks_decline))
    attendance_decline = st.number_input("Attendance decline threshold", min_value=0.1, value=float(DEFAULT_THRESHOLDS.attendance_decline))
    if csv_file is not None:
        try:
            import io
            df, summary = analyze_performance(io.BytesIO(csv_file.getvalue()), thresholds=Thresholds(marks_limit, attendance_limit, marks_decline, attendance_decline))
        except AnalyticsValidationError as exc:
            st.error(str(exc))
        else:
            st.caption(f"Detected mode: {summary['mode']}")
            st.metric("Total Students", summary['total_students'])
            st.metric("Academic concerns", summary['academic_concerns'])
            st.metric("Incomplete data", summary['incomplete_data'])
            st.caption(f"Complete: {summary['complete_data']}; concern + incomplete: {summary['concern_and_incomplete']}")
            def available(value):
                return "Unavailable" if value != value else f"{value:.2f}"
            st.write(f"Class marks average: {available(summary['class_average_marks'])}; attendance average: {available(summary['average_attendance'])}%. Based on {summary['averages_basis'].lower()}.")
            st.caption(f"Marks available for {summary['marks_available_count']} students; attendance available for {summary['attendance_available_count']}.")
            if summary['mode'] == 'trend':
                st.write({'Marks trends': summary['marks_trends'], 'Attendance trends': summary['attendance_trends']})
            view = st.selectbox("Investigation view", ['All students','Academic concern','Incomplete data','Both'])
            shown = filter_results(df, view)
            st.dataframe(display_results(shown), hide_index=True)
            st.download_button("Download current view (CSV)", analytics_csv_bytes(shown), file_name='analytics_view.csv', mime='text/csv')
            for _, row in shown.iterrows():
                icon = '⚠️' if row['academic_concern'] or row['incomplete_data'] else '✅'
                with st.expander(f"{icon} {row['student_name']} ({row['analysis_id']})"):
                    st.write(row['reasons'])
            warning_students = attendance_warning_candidates(shown)
            practice_students = practice_candidates(shown)
            course_name_input = st.text_input("Course name for these letters:", value="Machine Learning", key="batch_course")
            # Bind generated session output to this exact data/config/filter; never show stale letters.
            signature = (csv_file.getvalue(), marks_limit, attendance_limit, marks_decline, attendance_decline, view)
            if st.session_state.get('analytics_signature') != signature:
                st.session_state.pop('batch_letters', None)
                st.session_state.pop('practice_sets', None)
                st.session_state['analytics_signature'] = signature
            if not warning_students.empty:
                if st.button("Generate Warning Letters for Attendance Concerns"):
                    letters = call_ai(generate_batch_attendance_warnings, warning_students, course_name=course_name_input, required_percent=str(attendance_limit))
                    st.session_state['batch_letters'] = letters
                    log_activity('batch_warnings', 'Attendance warning batch generated')
            else:
                st.caption("No confirmed low-attendance students in this view. Missing attendance requires verification.")
            for pos, item in enumerate(st.session_state.get('batch_letters', [])):
                with st.expander(f"Letter for {item['student_name']} ({pos+1})"):
                    st.text_area("Content:", value=item['document'], key=f"letter_{pos}")
                    st.download_button("Download letter (DOCX)", generate_docx_bytes(item['document']), file_name=f'Warning_{pos+1}.docx', key=f'download_letter_{pos}')
            if not practice_students.empty:
                practice_source = st.text_input("Source material to draw from:", value="PCA", key="practice_source")
                if st.button("Generate Personalized Practice Quizzes"):
                    st.session_state['practice_sets'] = call_ai(generate_personalized_practice, practice_students, source_name=practice_source)
                    log_activity('personalized_practice', 'Practice batch generated')
            for pos, item in enumerate(st.session_state.get('practice_sets', [])):
                with st.expander(f"Practice quiz for {item['student_name']} ({pos+1})"):
                    if item['questions']:
                        for i, q in enumerate(item['questions'], start=1):
                            st.markdown(f"**Q{i}. {q['question']}**")
                            if 'options' in q:
                                for letter, opt in q['options'].items():
                                    st.write(f"{letter}) {opt}")
                            st.caption(f"Bloom's level: {q.get('bloom_level', 'N/A')} | Source: {q['source_label']}")
                    else:
                        st.error("Could not generate questions for this student.")

elif page == "Courses & Activity":
    st.header("📚 Courses & Activity Log")
    notice = st.session_state.pop("material_notice", None)
    if notice:
        st.success(notice)

    st.subheader("Courses")
    courses = get_all_courses()
    if courses:
        selected_course = st.selectbox("Select a course to see its material:", courses)
        docs = legacy_materials(selected_course)
        managed = list_materials(selected_course)
        for d in docs:
            st.write(f"📄 **{d['filename']}** — {selected_course} → {d['semester']} → {d['subject']} → {d['unit']}")
            st.caption(f"Uploaded: {(d.get('uploaded_at') or 'Unknown')[:16]}. Legacy material — ownership migration is required before editing or deletion.")
        for material in managed:
            identity = material['material_id']
            st.caption(f"Uploaded: {material['created_at'][:16]}")
            st.write(f"📄 **{material['original_filename']}** — " + " → ".join(material[k] for k in ('course','semester','subject','unit')))
            st.caption(material_type(material))
            with st.expander(f"Manage {material['original_filename']} ({identity[:8]})"):
                values = {k: st.text_input(k.capitalize(), value=material[k], key=f"hierarchy_{identity}_{k}") for k in ('course','semester','subject','unit')}
                if st.button("Save hierarchy", key=f"edit_{identity}"):
                    try:
                        outcome = edit_hierarchy(identity, values)
                        if outcome['success']:
                            st.session_state['material_notice'] = "Hierarchy updated in registry and exact vector metadata."
                            st.rerun()
                        else:
                            st.error(outcome['error'])
                        for warning in outcome.get('warnings', []):
                            st.warning(warning)
                    except MaterialError as exc:
                        st.error(str(exc))
                confirm = st.checkbox("Confirm permanent deletion", key=f"confirm_{identity}")
                if st.button("Delete material", key=f"delete_{identity}", disabled=not confirm):
                    outcome = delete_material(identity)
                    if outcome['success']:
                        st.session_state['material_notice'] = f"Material deleted: {outcome['vectors_deleted']} vectors removed; upload removed: {outcome['file_deleted']}. " + " ".join(outcome['warnings'])
                        st.rerun()
                    else:
                        st.error(outcome['error'])
                    for warning in outcome.get('warnings', []):
                        st.warning(warning)
        if not docs and not managed:
            st.write("No material uploaded yet for this course.")
    else:
        st.write("No courses yet — upload material under 'Upload Content' first.")

    st.subheader("Recent Activity")
    activity = get_recent_activity()
    if activity:
        for a in activity:
            st.caption(f"🕒 {a['timestamp'][:16]} — **{a['action']}**: {a['details']}")
    else:
        st.write("No activity recorded yet.")



elif page == "Question Paper":
    st.header("📃 Question Paper Generator")
    st.write("Configure a full test with marks distribution — mirrors how a real exam is assembled.")

    source_name = st.text_input("Source material:", value="PCA", key="qp_source")
    course_filter = st.text_input("Course (optional):", value="", key="qp_course")
    difficulty = st.selectbox("Overall difficulty:", ["Easy", "Medium", "Hard"], key="qp_difficulty")

    col1, col2 = st.columns(2)
    with col1:
        num_mcq = st.number_input("Number of MCQs:", min_value=0, max_value=20, value=5)
        marks_per_mcq = st.number_input("Marks per MCQ:", min_value=1, max_value=10, value=2)
    with col2:
        num_descriptive = st.number_input("Number of descriptive questions:", min_value=0, max_value=10, value=2)
        marks_per_descriptive = st.number_input("Marks per descriptive:", min_value=1, max_value=20, value=5)

    if st.button("Generate Question Paper"):
        with st.spinner("Assembling question paper..."):
            course_arg = course_filter if course_filter.strip() else None
            paper = call_ai(generate_question_paper,
                source_name=source_name,
                course=course_arg,
                num_mcq=num_mcq,
                num_descriptive=num_descriptive,
                marks_per_mcq=marks_per_mcq,
                marks_per_descriptive=marks_per_descriptive,
                difficulty=difficulty
            )
        st.session_state["question_paper"] = paper
        log_activity("generate_question_paper", f"{num_mcq} MCQ + {num_descriptive} descriptive, {paper['total_marks']} total marks")

    if "question_paper" in st.session_state:
        paper = st.session_state["question_paper"]

        st.success(f"✅ Total Marks: {paper['total_marks']}")

        pdf_buffer = generate_question_paper_pdf_bytes(paper, title=f"{source_name} — Question Paper")
        st.download_button(
            label="📥 Download Question Paper (PDF)",
            data=pdf_buffer,
            file_name=f"{source_name.replace(' ', '_')}_paper.pdf",
            mime="application/pdf"
        )

        if paper["mcq_section"]:
            st.subheader("Section A: MCQs")
            for i, q in enumerate(paper["mcq_section"], start=1):
                st.markdown(f"**Q{i}. [{q['marks']} marks] {q['question']}**")
                for letter, opt in q["options"].items():
                    st.write(f"{letter}) {opt}")
                st.caption(f"📚 Source: {q['source_label']}")

        if paper["descriptive_section"]:
            st.subheader("Section B: Descriptive")
            for i, q in enumerate(paper["descriptive_section"], start=1):
                st.markdown(f"**Q{i}. [{q['marks']} marks] {q['question']}**")
                st.caption(f"📚 Source: {q['source_label']}")