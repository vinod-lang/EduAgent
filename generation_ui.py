"""One presentation boundary for trusted safe diagnostics."""
import streamlit as st
from generation_diagnostics import GenerationDiagnostic

def render_diagnostic(diagnostic):
    if not isinstance(diagnostic,GenerationDiagnostic):raise TypeError('A safe diagnostic is required.')
    message=diagnostic.title+': '+diagnostic.professor_message
    if diagnostic.category=='UNSUPPORTED_OPERATION':st.info(message)
    elif diagnostic.status=='rejected':st.error(message)
    elif diagnostic.status=='clarification':st.warning(message)
    else:st.success(message)
    st.caption(diagnostic.suggested_action)
    if diagnostic.attempts_used:st.caption(f'Generation attempts: {diagnostic.attempts_used}')
    st.caption('Saved locally.' if diagnostic.saved else 'No new result was saved by this operation.')
