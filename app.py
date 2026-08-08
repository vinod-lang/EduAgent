import streamlit as st
import os
from content_agent import extract_text_from_pdf
from vector_store import add_pdf_to_database
from student_support_agent import answer_question
from assessment_agent import generate_mcqs, print_quiz
from document_agent import generate_document
from analytics_agent import analyze_performance


# Page setup
st.set_page_config(page_title="EduAgent", page_icon="🎓", layout="centered")
st.title("🎓 EduAgent — AI Assistant for Course Material")

# --- COORDINATOR LOGIC ---
# This sidebar selection IS the coordinator: it decides which
# "agent" gets control based on what the user wants to do.
page = st.sidebar.radio(
    "Choose an action:",
    ["Upload Content", "Ask a Question", "Generate Quiz", "Draft Document", "Analytics"]
)

# Make sure a folder exists to temporarily store uploaded files
os.makedirs("uploads", exist_ok=True)


# --- PAGE 1: CONTENT AGENT ---
if page == "Upload Content":
    st.header("📄 Content Agent")
    st.write("Upload a PDF to add it to the searchable course material.")

    uploaded_file = st.file_uploader("Choose a PDF", type="pdf")

    if uploaded_file is not None:
        # Save the uploaded file to disk so our existing functions can read it
        save_path = os.path.join("uploads", uploaded_file.name)
        with open(save_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

        st.success(f"Uploaded: {uploaded_file.name}")

        if st.button("Add to Database"):
            with st.spinner("Processing PDF and storing chunks..."):
                # source_name uses the filename without ".pdf" as a label
                source_name = uploaded_file.name.replace(".pdf", "")
                add_pdf_to_database(save_path, source_name)
            st.success("✅ Added to the knowledge base!")


# --- PAGE 2: STUDENT SUPPORT AGENT ---
elif page == "Ask a Question":
    st.header("💬 Student Support Agent")
    st.write("Ask a question based on the uploaded course material.")

    question = st.text_input("Your question:")

    if st.button("Ask"):
        if question.strip() == "":
            st.warning("Please type a question first.")
        else:
            with st.spinner("Thinking..."):
                answer = answer_question(question)
            st.markdown("**Answer:**")
            st.write(answer)


# --- PAGE 3: ASSESSMENT AGENT ---
elif page == "Generate Quiz":
    st.header("📝 Assessment Agent")
    st.write("Generate multiple-choice questions from the course material.")

    source_name = st.text_input(
        "Source name (the filename you uploaded, without .pdf):",
        value="sample_lecture"
    )
    num_questions = st.slider("Number of questions:", 1, 10, 5)

    if st.button("Generate Quiz"):
        with st.spinner("Generating questions... this can take a minute on a local model"):
            quiz = generate_mcqs(source_name=source_name, num_questions=num_questions)

        if quiz is None:
            st.error("Could not generate a valid quiz. Try again.")
        else:
            st.session_state["quiz"] = quiz  # save so it doesn't disappear on rerun

    # Display quiz if we have one generated
    if "quiz" in st.session_state:
        quiz = st.session_state["quiz"]

        st.subheader("Quiz")
        for i, q in enumerate(quiz, start=1):
            st.markdown(f"**Q{i}. {q['question']}**")
            for letter, option_text in q["options"].items():
                st.write(f"{letter}) {option_text}")
            st.write("")

        with st.expander("📋 Show Answer Key"):
            for i, q in enumerate(quiz, start=1):
                st.write(f"Q{i}: {q['correct_answer']} — {q['explanation']}")

# --- PAGE 4: DOCUMENT AGENT ---
elif page == "Draft Document":
    st.header("📋 Document Agent")
    st.write("Draft a notice, circular, or email in an institutional format.")

    doc_type = st.selectbox("Document type:", ["Notice", "Circular", "Email"])
    instruction = st.text_area(
        "What should this document say?",
        placeholder="e.g. Inform students that the mid-semester exam is postponed to next Monday."
    )

    if st.button("Generate Document"):
        if instruction.strip() == "":
            st.warning("Please describe what the document should say.")
        else:
            with st.spinner("Drafting document..."):
                document = generate_document(instruction, doc_type)
            st.session_state["document"] = document

    if "document" in st.session_state:
        st.subheader("Generated Document")
        st.text_area("Result:", value=st.session_state["document"], height=300)

# --- PAGE 5: ANALYTICS AGENT ---
elif page == "Analytics":
    st.header("📊 Analytics Agent")
    st.write("Upload a CSV of marks and attendance to identify students who may need support.")

    csv_file = st.file_uploader("Choose a CSV file", type="csv")

    if csv_file is not None:
        save_path = os.path.join("uploads", csv_file.name)
        with open(save_path, "wb") as f:
            f.write(csv_file.getbuffer())

        df, summary = analyze_performance(save_path)

        col1, col2, col3 = st.columns(3)
        col1.metric("Total Students", summary["total_students"])
        col2.metric("Avg Marks", summary["class_average_marks"])
        col3.metric("Avg Attendance", f"{summary['class_average_attendance']}%")

        st.subheader("⚠️ Students who may need support")
        if summary["students_needing_support"]:
            for name in summary["students_needing_support"]:
                st.write(f"- {name}")
        else:
            st.write("No students currently flagged. 🎉")

        st.subheader("Full Data")
        st.dataframe(df[["student_name", "average_marks", "attendance_percent", "needs_support"]])