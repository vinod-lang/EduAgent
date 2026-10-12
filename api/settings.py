"""Explicit development-only authentication and restrictive browser configuration."""
import os,json
from dataclasses import dataclass,field
from pathlib import Path

@dataclass(frozen=True)
class APISettings:
    mode:str='production'
    dev_auth_enabled:bool=False
    dev_identities:dict=field(default_factory=dict,repr=False)
    dev_access_key:str=field(default='',repr=False)
    database_path:str='.runtime/api-development.sqlite3'
    uploads_path:str='.runtime/api-uploads'
    chroma_path:str='.runtime/api-chroma'
    cors_origins:tuple=()
    session_seconds:int=3600
    cookie_name:str='eduagent_session'
    @property
    def development_auth(self):return self.mode=='development' and self.dev_auth_enabled
    @property
    def secure_cookie(self):return self.mode!='development'
    def __post_init__(self):
        from security.models import opaque
        if self.mode not in ('development','production','institutional'):raise ValueError('Invalid API mode.')
        if not 60<=self.session_seconds<=86400:raise ValueError('Invalid session lifetime.')
        if self.dev_auth_enabled and self.mode!='development':raise ValueError('Development authentication is forbidden outside development.')
        if self.development_auth and len(self.dev_access_key)<32:raise ValueError('Development access key must have at least 32 characters.')
        for alias,identity in self.dev_identities.items():
            if not isinstance(alias,str) or not alias or len(alias)>100:raise ValueError('Invalid development identity alias.')
            opaque(identity)
        for origin in self.cors_origins:
            from urllib.parse import urlsplit
            parsed=urlsplit(origin)
            if parsed.scheme not in ('http','https') or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username:raise ValueError('CORS origins must be explicit scheme/host origins.')
    @classmethod
    def from_environment(cls):
        return cls(mode=os.getenv('EDUAGENT_API_MODE','production'),dev_auth_enabled=os.getenv('EDUAGENT_DEV_AUTH','false').lower()=='true',
            dev_identities=json.loads(os.getenv('EDUAGENT_DEV_IDENTITIES','{}')),dev_access_key=os.getenv('EDUAGENT_DEV_ACCESS_KEY',''),
            database_path=os.getenv('EDUAGENT_API_DB','.runtime/api-development.sqlite3'),uploads_path=os.getenv('EDUAGENT_API_UPLOADS','.runtime/api-uploads'),chroma_path=os.getenv('EDUAGENT_API_CHROMA','.runtime/api-chroma'),
            cors_origins=tuple(filter(None,os.getenv('EDUAGENT_API_ORIGINS','').split(','))))
