"""Professor workspace presentation. Mutations and intelligence remain in services."""
import streamlit as st
from dashboard import QUICK_ACTIONS, material_type, build_material_tree, legacy_content_view
from material_service import MaterialError


def render_activity(activity):
    if not activity:
        st.info("No recent activity.")
    for entry in activity:
        st.write(f"{entry['timestamp']} — {entry['action']}")


def render_material_controls(material, *, edit_hierarchy, delete_material):
    identity = material['material_id']
    st.caption(material_type(material))
    st.caption(f"Uploaded: {material.get('created_at') or 'Time unavailable'}")
    with st.form(key=f"edit_form_{identity}"):
        values = {key: st.text_input(key.capitalize(), value=material[key], key=f"hierarchy_{identity}_{key}")
                  for key in ('course', 'semester', 'subject', 'unit')}
        if st.form_submit_button("Save hierarchy"):
            try:
                outcome = edit_hierarchy(identity, values)
                if outcome['success']:
                    st.session_state['material_notice'] = "Hierarchy updated in registry and exact vector metadata."
                    st.rerun()
                st.error(outcome['error'])
                for warning in outcome.get('warnings', []):
                    st.warning(warning)
            except MaterialError as exc:
                st.error(str(exc))
    confirm = st.checkbox("Confirm permanent deletion", key=f"confirm_{identity}")
    if st.button("Delete material", key=f"delete_{identity}", disabled=not confirm):
        # Check confirmation as well as disabling the control for UI safety.
        if not confirm:
            st.warning("Confirm permanent deletion before deleting this material.")
        else:
            outcome = delete_material(identity)
            if outcome['success']:
                st.session_state['material_notice'] = f"Material deleted: {outcome['vectors_deleted']} vectors removed; upload removed: {outcome['file_deleted']}. " + " ".join(outcome['warnings'])
                st.rerun()
            st.error(outcome['error'])
            for warning in outcome.get('warnings', []):
                st.warning(warning)


def render_material_browser(materials, courses, *, edit_hierarchy, delete_material):
    tree = build_material_tree(materials, courses)
    st.subheader("Academic Knowledge / Materials")
    if not materials:
        st.info("No managed materials yet. Use Upload Content to add academic knowledge.")
    for course, semesters in tree.items():
        with st.expander(f"Course: {course}"):
            if not semesters:
                st.caption("No managed materials in this course.")
            for semester, subjects in semesters.items():
                with st.expander(f"Semester: {semester}"):
                    for subject, units in subjects.items():
                        with st.expander(f"Subject: {subject}"):
                            for unit, records in units.items():
                                with st.expander(f"Unit: {unit}"):
                                    for material in records:
                                        with st.expander(material['original_filename']):
                                            st.write(material['original_filename'])
                                            render_material_controls(material, edit_hierarchy=edit_hierarchy, delete_material=delete_material)
    st.subheader("Legacy registered content")
    st.caption("Legacy material — managed ownership is unavailable. Editing/deletion is disabled. Unregistered Chroma-only content is not counted or assigned to this tree.")
    for entry in legacy_content_view():
        st.write(f"{entry['source_name']} — {entry.get('course') or 'Course unavailable'}")
        st.caption(f"Recorded unit: {entry.get('unit') or 'Unavailable'}; uploaded: {entry.get('uploaded_at') or 'Time unavailable'}")


def render_assistant(*, call_ai, classify_intent, answer_question, generate_questions, generate_document, navigate_to):
    st.subheader("Smart Assistant")
    st.write("Type what you want in plain English. The coordinator will decide which agent(s) should handle it.")

    columns = st.columns(3)
    for position, (label, target) in enumerate(QUICK_ACTIONS.items()):
        columns[position % 3].button(label, on_click=navigate_to, args=(target,), key=f"quick_{target}")
    st.caption("Create Assessment opens the current Generate Quiz workflow. Question Paper remains available in the sidebar until Assessment Studio is introduced.")

    user_input = st.text_area(
        "What do you need?", key="dashboard_assistant_request",
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




def render_dashboard(overview, materials, courses, *, call_ai, classify_intent, answer_question,
                     generate_questions, generate_document, navigate_to, edit_hierarchy, delete_material):
    st.header("Professor Dashboard")
    notice = st.session_state.pop('material_notice', None)
    if notice:
        st.success(notice)
    overview_tab, assistant_tab, knowledge_tab, activity_tab = st.tabs([
        'Overview', 'Smart Assistant / Quick Actions', 'Academic Knowledge', 'Recent Activity'])
    with overview_tab:
        cards = st.columns(3)
        cards[0].metric("Registered courses", overview['course_count'])
        cards[1].metric("Managed materials", overview['managed_count'])
        cards[2].metric("Legacy registered documents", overview['legacy_count'])
        st.caption("Counts use SQLite records. Legacy records do not verify indexed vectors; unregistered Chroma content is not counted.")
        if overview['recent_materials']:
            recent = overview['recent_materials'][0]
            st.write(f"Latest upload: {recent['original_filename']}")
            st.caption(f"{material_type(recent)} · Uploaded {recent.get('created_at') or 'Time unavailable'}")
        st.subheader("Managed materials by course")
        if overview['materials_by_course']:
            for course, count in overview['materials_by_course'].items():
                st.write(f"{course}: {count}")
        else:
            st.info("No registered courses yet. Upload academic content to get started.")
    with assistant_tab:
        render_assistant(call_ai=call_ai, classify_intent=classify_intent, answer_question=answer_question,
                         generate_questions=generate_questions, generate_document=generate_document, navigate_to=navigate_to)
    with knowledge_tab:
        render_material_browser(materials, courses, edit_hierarchy=edit_hierarchy, delete_material=delete_material)
    with activity_tab:
        render_activity(overview['recent_activity'])
