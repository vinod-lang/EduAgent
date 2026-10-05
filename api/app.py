"""Versioned web adapter. Factory/import have no runtime initialization side effects."""
import secrets,uuid
from fastapi import FastAPI,Request
from fastapi.middleware.cors import CORSMiddleware
from .settings import APISettings
from .workspaces import Workspaces
from .errors import install,error

def create_api_app(*,settings=None,services=None,sessions=None,workspaces=None):
    settings=settings or APISettings.from_environment()
    if services is None:
        from application import create_application_services
        from application.materials import MaterialService
        from security.repository import SecurityRepository
        from application.runtime import ConfiguredVectors
        vectors=ConfiguredVectors(settings.chroma_path)
        services=create_application_services(materials=MaterialService(uploads=settings.uploads_path,vectors=vectors),security_repository=SecurityRepository(database_path=settings.database_path),collection_factory=vectors.collection)
    if sessions is None:
        from security.sessions import SessionService
        sessions=SessionService(services.policy.repository,ttl=settings.session_seconds)
    app=FastAPI(title='EduAgent API',version='1.0.0',docs_url='/api/v1/docs' if settings.mode=='development' else None,openapi_url='/api/v1/openapi.json' if settings.mode=='development' else None,redoc_url=None)
    app.state.settings=settings;app.state.services=services;app.state.sessions=sessions;app.state.workspaces=workspaces or Workspaces()
    if settings.cors_origins:app.add_middleware(CORSMiddleware,allow_origins=list(settings.cors_origins),allow_credentials=True,allow_methods=['GET','POST','PUT','PATCH','DELETE'],allow_headers=['Content-Type','X-CSRF-Token','X-Development-Key'])
    from .limits import BodyLimit
    app.add_middleware(BodyLimit)
    @app.middleware('http')
    async def safety(request:Request,next):
        request.state.request_id=str(uuid.uuid4()) # never echo arbitrary client correlation input
        try:response=await next(request)
        except Exception:response=error(request,'INTERNAL_ERROR','The operation could not be completed.',500)
        response.headers.update({'X-Request-ID':request.state.request_id,'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY','Cache-Control':'no-store'})
        return response
    install(app)
    from .routes import router
    app.include_router(router,prefix='/api/v1')
    return app
