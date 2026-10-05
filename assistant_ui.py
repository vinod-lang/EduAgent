"""Session-only plan review and deterministic results. No final LLM summary."""
import streamlit as st
from generation_ui import render_diagnostic
from generation_diagnostics import from_error,validated,clarification,failed
from structured_generation import Failure
from assistant_models import PlanError
from assistant_services import ExecutionContext
from application import create_application_services
from application.errors import ApplicationError
services = create_application_services()
plan_request = services.assistant.plan
validate_plan = services.assistant.validate
execute_plan = services.assistant.execute
from analytics_agent import Thresholds
from ai_provider import AIProviderError


def session_context():
    return ExecutionContext(st.session_state.get('student_validation'),Thresholds(
        st.session_state.get('student_marks_limit',50),st.session_state.get('student_attendance_limit',70),
        st.session_state.get('student_marks_decline',10),st.session_state.get('student_attendance_decline',10)))


def render_results(report,plan,navigate_to):
    st.subheader('Results: '+report.status.replace('_',' '))
    for result in report.results:
        st.write(f'{result.action_id}: {result.status}')
        if result.status!='completed':
            st.warning(result.error or result.safe_summary);continue
        with st.expander(result.action_id+' result',expanded=True):
            if result.result_type=='ASK_KNOWLEDGE':
                st.write(result.payload.answer)
                for source in result.payload.sources:st.caption('Retrieved source: '+source)
            elif result.result_type=='CREATE_ASSESSMENT':
                from assessment_ui import render_assessment_result
                render_assessment_result(result.payload,key_prefix="assistant_"+result.action_id)
            elif result.result_type=='CREATE_DOCUMENT':
                from document_models import DocumentVersions
                st.write(result.payload.to_dict())
                st.caption('Open in Document Studio to edit, refine, review versions/preferences and export. Existing Studio draft is replaced only when you choose this action; saved drafts are unchanged.')
                def open_document(draft=result.payload,action_id=result.action_id):
                    action=next(a for a in plan.actions if a.action_id==action_id)
                    st.session_state['studio_pending_versions']=DocumentVersions.generated(draft,action.parameters.get('template_id','standard_academic'))
                    st.session_state.pop('studio_saved_id',None)
                    navigate_to('Document Studio')
                st.button('Open in Document Studio',key='assistant_open_'+result.action_id,on_click=open_document)
            elif result.result_type=='ANALYZE_STUDENTS':
                public_results = services.students.public
                result_csv_bytes = services.students.csv
                frame,summary=result.payload
                st.caption('Local filtered students; class summary covers the full eligible dataset. No AI receives these results.')
                st.write(summary);st.dataframe(public_results(frame),hide_index=True)
                st.download_button('Export displayed students CSV',result_csv_bytes(frame),'assistant_students.csv','text/csv',key='assistant_csv_'+result.action_id)
            else:
                st.button('Open '+result.payload,key='assistant_nav_'+result.action_id,on_click=navigate_to,args=(result.payload,))


def render_assistant(navigate_to):
    request=st.text_area('What do you need?',key='dashboard_assistant_request',placeholder='Create a scoped quiz and draft an announcement, or show students with attendance concern.')
    details=st.text_area('Additional details / corrections (optional)',key='assistant_details')
    context=session_context()
    # Replacing/clearing/revalidating student data invalidates old local results.
    dataset=context.student_dataset
    import hashlib
    signature=(hashlib.sha256(dataset.frame.to_csv(index=False).encode()).hexdigest() if dataset is not None else None,context.thresholds)
    if st.session_state.get('assistant_context_key',signature)!=signature:
        st.session_state.pop('assistant_plan',None);st.session_state.pop('assistant_report',None)
    st.session_state['assistant_context_key']=signature
    if st.button('Submit'):
        st.session_state.pop('assistant_plan',None);st.session_state.pop('assistant_report',None)
        if not request.strip():st.warning('Please type a request.')
        else:
            try:
                with st.spinner('Planning only — no services execute yet...'):
                    plan=plan_request(request+('\n'+details if details.strip() else ''),context)
                st.session_state['assistant_plan']=plan
            except (ApplicationError,PlanError,AIProviderError) as exc:render_diagnostic(from_error(exc))
    plan=st.session_state.get('assistant_plan')
    if plan is None:return
    if plan.unsupported:
        render_diagnostic(failed(Failure.UNSUPPORTED_OPERATION));return
    st.subheader('Plan preview')
    for index,action in enumerate(plan.execution_order,1):
        st.write(f'{index}. {action.action_type}')
        st.write(action.parameters)
        if action.depends_on:st.caption('Depends on: '+', '.join(action.depends_on)+' (assessment title/type/count only)')
    try:missing=validate_plan(plan,context)
    except (ApplicationError,PlanError) as exc:
        render_diagnostic(from_error(exc));return
    if missing:render_diagnostic(clarification())
    else:render_diagnostic(validated(plan.provenance))
    for item in missing:st.warning(item.action_id+' needs: '+', '.join(item.missing_fields)+'. Add details above and Submit again.')
    report=st.session_state.get('assistant_report')
    current=request+('\n'+details if details.strip() else '')
    stale=current!=plan.original_request
    if stale:st.warning('Request changed. Submit again to review a new plan before execution.')
    if st.button('Execute reviewed plan',disabled=bool(missing) or stale or report is not None):
        if not missing and not stale and report is None:
            try:
                with st.spinner('Executing validated services...'):st.session_state['assistant_report']=execute_plan(plan,context)
            except (ApplicationError,PlanError):st.error('Execution rejected. Review the plan and available data.')
    report=st.session_state.get('assistant_report')
    if report is not None:
        render_results(report,plan,navigate_to)
        if report.status!='completed' and st.button('Retry failed safe actions',disabled=bool(missing) or stale):
            if not missing and not stale:
                try:
                    with st.spinner('Retrying failed/blocked steps; completed steps are preserved...'):
                        st.session_state['assistant_report']=execute_plan(plan,context,previous=report,retry=True)
                    st.rerun()
                except (ApplicationError,PlanError):st.error('Retry rejected; create a new plan.')
