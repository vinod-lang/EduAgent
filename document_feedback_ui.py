"""Transparent feedback controls. No approval or writes during rendering."""
import streamlit as st
from document_models import DocumentError,CATALOG,TONES
from document_templates import get_template
from document_diff import document_diff,comparison_key,CATEGORIES,REUSABLE_CATEGORIES
from document_preferences import SCOPES
from application import create_application_services
from application.errors import ApplicationError
service = create_application_services().documents
approve_preference = service.approve_preference
list_preferences = service.list_preferences
update_preference = service.update_preference
delete_preference = service.delete_preference
save_feedback = service.feedback

LABELS={'generated':'AI Generated','professor_edit':'Professor Edit','ai_refinement':'AI Refinement','restored':'Restored','legacy_current':'Legacy Current — action unknown'}


def render_history(versions,document_id):
    for key in ('feedback_history_version','feedback_compare_from','feedback_compare_to'):
        if key in st.session_state and st.session_state[key] not in range(len(versions.history)):
            st.session_state[key]=0
    with st.expander('Version history and what changed'):
        st.caption('History is persisted on Save/Update. Restoring adds a new version and retains later history.')
        index=st.selectbox('Historical version',list(range(len(versions.history))),format_func=lambda i:f'Version {i+1} — {LABELS[versions.sources[i]]}',key='feedback_history_version')
        historical=versions.history[index]
        st.caption('Created: '+versions.timestamps[index])
        for _,text in get_template(versions.template_id).blocks(historical):st.text(text)
        if st.button('Restore selected version'):
            return service.restore(versions,index)
        before_index=st.selectbox('Compare from version',list(range(len(versions.history))),format_func=lambda i:f'Version {i+1}',index=max(0,len(versions.history)-2),key='feedback_compare_from')
        after_index=st.selectbox('Compare to version',list(range(len(versions.history))),format_func=lambda i:f'Version {i+1}',index=len(versions.history)-1,key='feedback_compare_to')
        key=comparison_key(document_id,versions.version_ids[before_index],versions.version_ids[after_index])
        changes=document_diff(versions.history[before_index],versions.history[after_index])
        if not changes:st.info('No content changes in this comparison.')
        decisions=st.session_state.setdefault('feedback_candidate_decisions',{})
        for number,change in enumerate(changes):
            st.write(f'{change.action.capitalize()}: {change.field}')
            if change.before:st.text('Before: '+'\n'.join(change.before))
            if change.after:st.text('After: '+'\n'.join(change.after))
            candidate_key=key+':'+str(number)
            if candidate_key in decisions:
                st.caption('Candidate '+decisions[candidate_key]);continue
            st.caption('Suggested category: '+change.category+'. This is advisory; no preference has been stored.')
            if change.category in ('factual','unknown'):st.info('Do not generalize document facts. Choose a reusable category and write generic guidance only if appropriate.')
            category=st.selectbox('Candidate category',CATEGORIES,index=CATEGORIES.index(change.category),key='candidate_category_'+candidate_key)
            instruction=st.text_input('Reusable instruction',value=change.candidate_instruction,key='candidate_instruction_'+candidate_key)
            scope=st.selectbox('Apply preference to',SCOPES,key='candidate_scope_'+candidate_key)
            if st.button('Ignore candidate',key='ignore_'+candidate_key):
                decisions[candidate_key]='ignored';st.rerun()
            if st.button('Approve Preference',key='approve_'+candidate_key,disabled=category not in REUSABLE_CATEGORIES or not instruction.strip()):
                try:
                    if not document_id:raise DocumentError('Save the document history before approving an edit-derived preference.')
                    approve_preference(instruction,category,scope,document_type=versions.current.document_type if scope!='general' else None,template_id=versions.template_id if scope=='template' else None,source_document_id=document_id,source_before_id=versions.version_ids[before_index],source_after_id=versions.version_ids[after_index])
                    decisions[candidate_key]='approved';st.rerun()
                except (ApplicationError,DocumentError) as exc:st.error(str(exc))
    return None


def render_preferences(document_type,template_id):
    with st.expander('Approved preference management'):
        st.caption('Local professor-approved drafting guidance; model weights are never trained. Specific scope wins for known rule conflicts. No source document text is shown here.')
        with st.form('manual_preference'):
            instruction=st.text_input('New preference instruction')
            category=st.selectbox('Preference category',REUSABLE_CATEGORIES)
            scope=st.selectbox('Preference scope',SCOPES)
            selected_type=st.selectbox('Preference document type',list(CATALOG),index=list(CATALOG).index(document_type),format_func=lambda k:CATALOG[k][0])
            tone=st.selectbox('Preference tone (optional)',('Any',*TONES))
            if st.form_submit_button('Approve manual preference'):
                try:
                    approve_preference(instruction,category,scope,document_type=selected_type if scope!='general' else None,template_id=template_id if scope=='template' else None,tone=None if tone=='Any' else tone)
                    st.success('Preference explicitly approved.')
                except (ApplicationError,DocumentError) as exc:st.error(str(exc))
        try:
            preferences=list_preferences()
            if not preferences:st.info('No approved preferences yet.')
            for preference in preferences:
                identity=preference.preference_id
                st.caption(f'{preference.category} | {preference.scope} | {CATALOG[preference.document_type][0] if preference.document_type else "All document types"} | {"Active" if preference.active else "Inactive"}')
                text=st.text_input('Edit approved instruction',value=preference.instruction,key='preference_text_'+identity)
                if st.button('Update preference',key='update_preference_'+identity):
                    update_preference(identity,text);st.rerun()
                if st.button('Deactivate' if preference.active else 'Activate',key='toggle_preference_'+identity):
                    update_preference(identity,active=not preference.active);st.rerun()
                confirm=st.checkbox('Confirm preference deletion',key='confirm_preference_'+identity)
                if st.button('Delete preference',key='delete_preference_'+identity,disabled=not confirm):
                    delete_preference(identity);st.rerun()
        except (ApplicationError,DocumentError) as exc:st.error(str(exc))


def render_feedback(versions,document_id):
    with st.expander('Optional draft feedback'):
        with st.form('draft_feedback'):
            rating=st.selectbox('Draft quality',['Good','Needs Changes'])
            note=st.text_area('Private feedback note (optional)')
            if st.form_submit_button('Save feedback'):
                try:
                    if not document_id:raise DocumentError('Save the current version before recording feedback.')
                    save_feedback(document_id,versions.version_ids[-1],rating,note)
                    st.success('Feedback saved locally. It is not automatically reusable guidance.')
                except (ApplicationError,DocumentError) as exc:st.error(str(exc))
