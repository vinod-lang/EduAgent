"""Document Studio: explicit session edits, versions, save actions and current exports."""
import streamlit as st
import db
from ai_provider import AIProviderError
from document_models import CATALOG,TONES,FIELDS,DocumentRequest,DocumentDraft,DocumentVersions,DocumentError
from document_studio import generate_draft,refine_draft
from document_templates import TEMPLATES,get_template
from document_export import document_docx_bytes,document_pdf_bytes
from document_repository import save_draft,list_drafts,load_draft
from document_feedback_ui import render_history,render_preferences,render_feedback


def _activity(action):
    try:db.log_activity(action,'')
    except Exception:st.warning('Document is available, but the activity event could not be recorded.')


def _set_editor(versions):
    st.session_state['studio_versions']=versions
    for field in FIELDS:st.session_state['studio_edit_'+field]=getattr(versions.current,field)
    st.session_state['studio_edit_body']='\n\n'.join(versions.current.body)


def render_document_studio():
    pending=st.session_state.pop('studio_pending_versions',None)
    if pending is not None:_set_editor(pending)
    st.header('Document Studio')
    st.caption('Describe the purpose and known facts. Only explicitly approved local preferences guide future drafts; the underlying model is not trained.')
    kind=st.selectbox('Document type',list(CATALOG),format_func=lambda k:CATALOG[k][0],key='studio_type')
    description=st.text_area('Describe what you need drafted',key='studio_description',height=140)
    tone=st.selectbox('Tone',TONES,key='studio_tone')
    template=st.selectbox('Template',list(TEMPLATES),format_func=lambda k:TEMPLATES[k].label)
    st.caption('Generic academic layout. Institutional logos and arbitrary uploaded template import are not included.')
    values={}
    with st.expander('Optional context'):
        for field in ('recipient','sender','title','subject','date','reference_number','signature'):
            values[field]=st.text_input(field.replace('_',' ').capitalize(),key='studio_request_'+field)
        values['additional_context']=st.text_area('Additional context',key='studio_context')
    render_preferences(kind,template)
    if st.button('Generate document',disabled=not description.strip()):
        try:
            request=DocumentRequest(kind,description,tone,template,**values)
            with st.spinner('Drafting a structured document...'):draft=generate_draft(request)
            _set_editor(DocumentVersions.generated(draft,template))
            st.session_state.pop('studio_saved_id',None)
            _activity('document_generated')
        except (DocumentError,AIProviderError) as exc:st.error(str(exc))
    try:
        saved=list_drafts()
        if saved:
            with st.expander('Saved drafts'):
                identities={row['document_id']:f"{row['updated_at']} - {row['status']}" for row in saved}
                selected=st.selectbox('Saved draft',list(identities),format_func=identities.__getitem__)
                if st.button('Load saved draft'):
                    _set_editor(load_draft(selected));st.session_state['studio_saved_id']=selected
    except DocumentError as exc:st.error(str(exc))
    # Preserve a pre-existing plain-text session draft without inventing facts.
    if 'studio_versions' not in st.session_state and isinstance(st.session_state.get('document'),str) and st.session_state['document'].strip():
        _set_editor(DocumentVersions.generated(DocumentDraft('custom',body=(st.session_state['document'],))))
    versions=st.session_state.get('studio_versions')
    if versions is None:
        st.info('Generate a document to review, edit, save and export it.');return
    st.subheader('Professor editing')
    st.caption(f'Current version {len(versions.history)}. Editing takes effect on Apply edits; downloads use that applied version.')
    fields={}
    with st.form('studio_edit_form'):
        for field in FIELDS:
            # Keep irrelevant letter controls out of announcements and memos.
            if field in ('salutation','closing') and CATALOG[versions.current.document_type][1] not in ('letter','email'):
                fields[field]='';continue
            fields[field]=st.text_input('Edit '+field.replace('_',' '),key='studio_edit_'+field)
        body=st.text_area('Edit body (blank lines separate paragraphs)',key='studio_edit_body',height=240)
        if st.form_submit_button('Apply edits'):
            try:
                draft=DocumentDraft(versions.current.document_type,body=tuple(p.strip() for p in body.split('\n\n') if p.strip()),**fields)
                versions=versions.update(draft);st.session_state['studio_versions']=versions
                st.session_state['document']='\n\n'.join(draft.body)
                st.success('Edits applied to the current export version.')
            except DocumentError as exc:st.error(str(exc))
    if st.button('Undo last version',disabled=len(versions.history)<2):
        st.session_state['studio_pending_versions']=versions.undo();st.rerun()
    with st.expander('Original generated draft'):
        for _,text in get_template(versions.template_id).blocks(versions.original):st.text(text)
    refinement=st.text_input('Refinement instruction',key='studio_refinement')
    if st.button('Refine current document',disabled=not refinement.strip()):
        try:
            with st.spinner('Refining the applied current version...'):draft=refine_draft(versions.current,refinement)
            st.session_state['studio_pending_versions']=versions.update(draft,'ai_refinement');st.rerun()
        except (DocumentError,AIProviderError) as exc:st.error(str(exc))
    status=st.selectbox('Save status',['Draft','Final'])
    if st.button('Update Draft' if st.session_state.get('studio_saved_id') else 'Save Draft'):
        try:
            st.session_state['studio_saved_id']=save_draft(versions,st.session_state.get('studio_saved_id'),status)
            st.session_state['studio_save_message']='Current draft saved locally. Document content is excluded from Activity Log.'
            st.rerun()
        except DocumentError as exc:st.error(str(exc))
    if st.session_state.get('studio_save_message'):st.success(st.session_state.pop('studio_save_message'))
    restored=render_history(versions,st.session_state.get('studio_saved_id'))
    if restored is not None:
        st.session_state['studio_pending_versions']=restored;st.rerun()
    render_feedback(versions,st.session_state.get('studio_saved_id'))
    st.subheader('Current document preview')
    for field,text in get_template(versions.template_id).blocks(versions.current):
        if field=='title':st.subheader(text)
        else:st.text(text)
    try:
        st.download_button('Download current DOCX',document_docx_bytes(versions.current,versions.template_id),'document.docx','application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        st.download_button('Download current PDF',document_pdf_bytes(versions.current,versions.template_id),'document.pdf','application/pdf')
    except DocumentError as exc:st.error(str(exc))
