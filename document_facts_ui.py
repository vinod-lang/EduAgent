"""Explicit professor-only fact management; no inference during rendering."""
import streamlit as st
from document_facts import FIELDS
from application import create_application_services
from security.models import development_legacy_context
from application.errors import ApplicationError
service = create_application_services(context=development_legacy_context()).documents
fact = service.fact
conflicts = service.conflicts
confirm_edit = service.confirm_edit
update_fact = service.update_fact
remove_fact = service.remove_fact
from document_models import DocumentError


def render_fact_conflict(versions):
    candidate=st.session_state.get('studio_fact_conflict')
    if candidate is None:return
    st.warning('Your edit changed a previously confirmed fact. The previous version remains current until you resolve this.')
    replacements={}
    changed=conflicts(candidate,versions.expectation_snapshots[-1])
    for number,f in enumerate(changed):
        if f.field=='body':replacements[f.fact_id]=st.text_input('Replacement confirmed body fact '+str(number+1),key='conflict_replacement_'+str(number))
    if st.button('Update confirmed facts and apply edit'):
        try:
            expectations=confirm_edit(candidate,versions.expectation_snapshots[-1],replacements)
            st.session_state['studio_pending_versions']=service.edit(versions,candidate,expectations=expectations)
            st.session_state.pop('studio_fact_conflict',None);st.rerun()
        except (ApplicationError,DocumentError):st.error('Enter replacement facts that match your edit, or remove the constraint explicitly in fact management.')
    if st.button('Keep original confirmed facts and revise edit'):
        st.session_state.pop('studio_fact_conflict',None)
        st.info('Confirmed facts retained. Revise the proposed edit before applying it.')


def render_confirmed_facts(versions):
    with st.expander('Confirmed facts'):
        st.caption('Confirmed facts are protected during AI refinement. Other free-text content still requires professor review.')
        expectations=versions.expectation_snapshots[-1]
        if not expectations:st.info('No confirmed fact constraints recorded.')
        for index,f in enumerate(expectations):
            st.text(f.field.replace('_',' ').capitalize()+': '+f.value)
            value=st.text_input('Updated confirmed value '+str(index+1),value=f.value,key='fact_value_'+versions.version_ids[-1]+'_'+str(index))
            if st.button('Update confirmed fact '+str(index+1)):
                try:
                    updated=update_fact(expectations,f.fact_id,value)
                    st.session_state['studio_pending_versions']=service.edit(versions,versions.current,expectations=updated);st.rerun()
                except (ApplicationError,DocumentError):st.error('The proposed fact does not match the current document. Apply an edit and resolve its conflict, or use a matching value.')
            if st.button('Remove confirmed fact '+str(index+1)):
                st.session_state['studio_pending_versions']=service.edit(versions,versions.current,expectations=remove_fact(expectations,f.fact_id));st.rerun()
        field=st.selectbox('Fact field',FIELDS,key='new_fact_field')
        value=st.text_input('New confirmed fact value',key='new_fact_value')
        if st.button('Add confirmed fact',disabled=not value.strip()):
            try:
                updated=expectations+(fact(field,value),)
                st.session_state['studio_pending_versions']=service.edit(versions,versions.current,expectations=updated);st.rerun()
            except (ApplicationError,DocumentError):st.error('The fact must match the current document and not duplicate a required structured field.')
