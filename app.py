import streamlit as st
import os
from content_agent import extract_text_from_pdf
from vector_store import add_pdf_to_database
from student_support_agent import answer_question
from assessment_agent import generate_questions
from document_agent import generate_document
from analytics_agent import analyze_performance
from coordinator import classify_intent


# Page setup
st.set_page_config(page_title="EduAgent", page_icon="🎓", layout="centered")
st.title("🎓 EduAgent — AI Assistant for Course Material")

# --- COORDINATOR LOGIC ---
# This sidebar selection IS the coordinator: it decides which
# "agent" gets control based on what the user wants to do.
page = st.sidebar.radio(
    "Choose an action:",
    ["Smart Assistant","Upload Content", "Ask a Question", "Generate Quiz", "Draft Document", "Analytics"]
)

# Make sure a folder exists to temporarily store uploaded files
os.makedirs("uploads", exist_ok=True)

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
                intent = classify_intent(user_input)

            st.caption(f"🔀 Routed to: **{intent}**")

            if intent == "question":
                with st.spinner("Thinking..."):
                    answer, sources = answer_question(user_input)
                st.write(answer)
                if sources:
                    st.caption(f"📚 Source: {', '.join(sources)}")

            elif intent == "quiz":
                with st.spinner("Generating quiz..."):
                    questions = generate_questions(source_name="PCA", num_questions=5)
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
                    doc = generate_document("Notice", {
                        "course": "General", "subject": user_input,
                        "details": user_input, "date": "TBD"
                    })
                st.text_area("Result:", value=doc, height=250)

            elif intent == "quiz_and_notice":
                # STEP 1: Assessment Agent runs first
                with st.spinner("Step 1/2 — Generating quiz..."):
                    questions = generate_questions(source_name="PCA", num_questions=5)

                # STEP 2: Document Agent runs next, referencing the quiz
                with st.spinner("Step 2/2 — Drafting announcement notice..."):
                    doc = generate_document("Notice", {
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
    st.write("Upload a PDF to add it to the searchable course material.")

    course = st.text_input("Course name:", value="Machine Learning")
    unit = st.text_input("Unit/Topic:", value="Unit 1")

    uploaded_file = st.file_uploader("Choose a PDF", type="pdf")

    if uploaded_file is not None:
        save_path = os.path.join("uploads", uploaded_file.name)
        with open(save_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

        st.success(f"Uploaded: {uploaded_file.name}")

        if st.button("Add to Database"):
            with st.spinner("Processing PDF and storing chunks..."):
                source_name = uploaded_file.name.replace(".pdf", "")
                add_pdf_to_database(save_path, source_name, course=course, unit=unit)
            st.success(f"✅ Added to '{course} / {unit}'!")


# --- PAGE 2: STUDENT SUPPORT AGENT ---
elif page == "Ask a Question":
    st.header("💬 Student Support Agent")
    st.write("Ask a question based on the uploaded course material.")

    course_filter = st.text_input("Limit search to course (optional):", value="")
    question = st.text_input("Your question:")

    if st.button("Ask"):
        if question.strip() == "":
            st.warning("Please type a question first.")
        else:
            with st.spinner("Thinking..."):
                course_arg = course_filter if course_filter.strip() else None
                answer, sources = answer_question(question, course=course_arg)
            st.markdown("**Answer:**")
            st.write(answer)
            if sources:
                st.caption(f"📚 Source: {', '.join(sources)}")


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
            questions = generate_questions(
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

    if "questions" in st.session_state:
        questions = st.session_state["questions"]

        st.subheader("Generated Questions (review before use)")
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
                document = generate_document(template_name, field_values)
            st.session_state["document"] = document

    if "document" in st.session_state:
        st.subheader("Generated Document (review before sending)")
        st.text_area("Result:", value=st.session_state["document"], height=300)

# --- PAGE 5: ANALYTICS AGENT ---
elif page == "Analytics":
    st.header("📊 Analytics Agent")
    st.write("Upload assessment history (multiple rows per student) to identify trend-based academic support needs.")

    csv_file = st.file_uploader("Choose a CSV file", type="csv")

    if csv_file is not None:
        save_path = os.path.join("uploads", csv_file.name)
        with open(save_path, "wb") as f:
            f.write(csv_file.getbuffer())

        df, summary = analyze_performance(save_path)

        st.metric("Total Students", summary["total_students"])

        st.subheader("⚠️ Students who may benefit from faculty intervention")
        if summary["students_needing_support"]:
            for name in summary["students_needing_support"]:
                st.write(f"- {name}")
        else:
            st.write("No students currently flagged. 🎉")

        st.subheader("Full Report (with evidence)")
        for _, row in df.iterrows():
            icon = "⚠️" if row["needs_support"] else "✅"
            with st.expander(f"{icon} {row['student_name']}"):
                st.write(f"**Latest marks:** {row['latest_marks']} ({row['marks_trend']})")
                st.write(f"**Latest attendance:** {row['latest_attendance']}% ({row['attendance_trend']})")
                st.write(f"**Reason:** {row['reasons']}")