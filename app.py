from retrieval import RetrievalError
from rag_ui import available_courses, scope_options
from dashboard import get_dashboard_summary, get_activity_view, PAGES
from workspace_ui import render_dashboard, render_activity
from assessment_ui import render_assessment_studio
from config import get_max_upload_bytes, ConfigurationError
import streamlit as st
import os
from content_agent import extract_text_from_pdf
from material_service import upload_material, delete_material, edit_hierarchy, MaterialError
from student_support_agent import answer_question
from assessment_agent import generate_questions
from document_agent import generate_document
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

# Dashboard hosts the coordinator UI; sidebar navigation opens dedicated workflows.
legacy_navigation = {"Smart Assistant": "Professor Dashboard", "Courses & Activity": "Activity Log",
                     "Generate Quiz": "Assessment Studio", "Question Paper": "Assessment Studio",
                     "Draft Document": "Document Studio", "Analytics": "Student Data Hub"}
if st.session_state.get("navigation") in legacy_navigation:
    st.session_state["navigation"] = legacy_navigation[st.session_state["navigation"]]
page = st.sidebar.radio(
    "Choose an action:",
    PAGES, key="navigation"
)

# Make sure a folder exists to temporarily store uploaded files
os.makedirs("uploads", exist_ok=True)

def navigate_to(page_name):
    st.session_state['navigation'] = page_name


if page == "Professor Dashboard":
    render_dashboard(get_dashboard_summary(), list_materials(), get_all_courses(),
                     call_ai=call_ai, classify_intent=classify_intent, answer_question=answer_question,
                     generate_questions=generate_questions, generate_document=generate_document,
                     navigate_to=navigate_to, edit_hierarchy=edit_hierarchy, delete_material=delete_material)


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
                from generation_ui import render_diagnostic
                from generation_diagnostics import failed
                from structured_generation import Failure
                render_diagnostic(failed(Failure.INSUFFICIENT_EVIDENCE))
                st.info(result.answer)
            else:
                st.success("Grounded answer available. Review the answer against its sources.")
                st.markdown("**Answer:**")
                st.write(result.answer)
            if result.sources:
                st.markdown("**Retrieved evidence sources:**")
                for source in result.sources:
                    st.caption(source)
            with st.expander("Development: retrieval diagnostics"):
                st.json(result.retrieval.diagnostics.to_dict())


# Unified professor-facing assessment workflow.
elif page == "Assessment Studio":
    render_assessment_studio()


elif page == "Document Studio":
    from document_ui import render_document_studio
    render_document_studio()

elif page == "Student Data Hub":
    from student_hub_ui import render_student_hub
    render_student_hub()

elif page == "Activity Log":
    st.header("Activity Log")
    st.caption("Recorded actions and timestamps only. Raw details, questions, student records and document contents are not displayed.")
    render_activity(get_activity_view(limit=20))
