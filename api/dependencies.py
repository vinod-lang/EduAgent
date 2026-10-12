"""Only authentication boundary constructs trusted request ProfessorContext."""
from fastapi import Request
from application.runtime import storage_context
from application.errors import call

def principal(request:Request):
    from security.sessions import AuthenticationError
    if not request.app.state.settings.development_auth:raise AuthenticationError()
    return call(request.app.state.sessions.authenticate,request.cookies.get(request.app.state.settings.cookie_name),
        csrf=request.headers.get('X-CSRF-Token'),mutation=request.method not in ('GET','HEAD','OPTIONS'))

def services(request:Request):
    # Both enter/exit occur within this sync generator dependency's worker context.
    return request.app.state.services

# Domain operations enter this context on the same thread as the operation itself.
def invoke(request,operation,*args,**kwargs):
    with storage_context(request.app.state.settings.database_path):return call(operation,*args,**kwargs)
