"""Stable error envelopes intentionally omit exception input and internal context."""
from fastapi.responses import JSONResponse
from application.errors import ApplicationError
from security.sessions import AuthenticationError,CSRFError
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError as PydanticValidationError
from starlette.exceptions import HTTPException

STATUS={'ACCESS_DENIED':403,'UNAUTHENTICATED':401,'CSRF_REJECTED':403,'NOT_FOUND':404,'CONFLICT':409,'PROVIDER_UNAVAILABLE':503,'STORAGE_ERROR':503,'INSUFFICIENT_EVIDENCE':422,'UNSUPPORTED_OPERATION':400,'VALIDATION_ERROR':422,'VALIDATION':422}
def error(request,code,message,status):
    return JSONResponse(status_code=status,content={'error':{'code':code,'message':message,'request_id':getattr(request.state,'request_id','unavailable')}})
def install(app):
    @app.exception_handler(ApplicationError)
    async def controlled(request,exc):
        if request.url.path.startswith('/api/v1/document-workspaces') and request.url.path.endswith('/export'):
            from font_resolver import FontResolutionError
            cause=exc.__cause__
            while cause is not None:
                if isinstance(cause,FontResolutionError):
                    return error(request,'PDF_FONT_UNAVAILABLE','PDF export needs a suitable local font for this document. Ask the administrator to configure the PDF font, or export DOCX.',422)
                cause=cause.__cause__
        response=error(request,exc.code,exc.message,STATUS.get(exc.code,400))
        if request.url.path.startswith(('/api/v1/assessments','/api/v1/documents','/api/v1/document-workspaces','/api/v1/assistant')) and exc.generation_diagnostic is not None:
            from generation_diagnostics import failed
            from structured_generation import Failure
            try:diagnostic=failed(exc.generation_diagnostic.category,exc.generation_diagnostic.attempts_used)
            except (ValueError,AttributeError):diagnostic=failed(Failure.PRODUCT_VALIDATION_FAILED)
            import json
            payload=json.loads(response.body)
            payload['error']['diagnostic']={k:getattr(diagnostic,k) for k in ('category','title','professor_message','suggested_action')}
            return JSONResponse(status_code=response.status_code,content=payload)
        return response
    @app.exception_handler(PydanticValidationError)
    @app.exception_handler(RequestValidationError)
    async def validation(request,exc):return error(request,'INVALID_REQUEST','Check the required request fields and formats.',422)
    @app.exception_handler(Exception)
    async def unexpected(request,exc):return error(request,'INTERNAL_ERROR','The operation could not be completed.',500)

    @app.exception_handler(HTTPException)
    async def http_error(request,exc):
        return error(request,'NOT_FOUND' if exc.status_code==404 else 'HTTP_ERROR','Resource not found.' if exc.status_code==404 else 'The request could not be completed.',exc.status_code)
