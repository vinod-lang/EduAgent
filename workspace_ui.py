"""Professor workspace presentation. Mutations and intelligence remain in services."""
import streamlit as st
from dashboard import QUICK_ACTIONS, material_type, build_material_tree
from application import create_application_services
from security.models import development_legacy_context
from application.errors import ApplicationError
legacy_content_view = create_application_services(context=development_legacy_context()).dashboard.legacy
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
            except (ApplicationError,MaterialError) as exc:
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
    st.write("Type what you want in plain English. Review the proposed plan before any service executes.")

    columns = st.columns(3)
    for position, (label, target) in enumerate(QUICK_ACTIONS.items()):
        columns[position % 3].button(label, on_click=navigate_to, args=(target,), key=f"quick_{target}")
    st.caption("Create Assessment opens Assessment Studio for Quiz or Question Paper generation.")

    from assistant_ui import render_assistant
    render_assistant(navigate_to)


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
