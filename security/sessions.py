"""Opaque local-development sessions; hashed credentials, explicit schema lifecycle."""
import hashlib
import secrets
import time
from dataclasses import dataclass,field
from application.errors import ApplicationError
from security.models import Status,ProfessorContext

class AuthenticationError(ApplicationError):
    code='UNAUTHENTICATED';message='Sign in with a valid development session.'
class CSRFError(ApplicationError):
    code='CSRF_REJECTED';message='Refresh the session and retry with its mutation token.'

def digest(token):return hashlib.sha256(token.encode()).hexdigest()

@dataclass(frozen=True)
class Principal:
    context:ProfessorContext
    session_key:str=field(repr=False)
    expires_at:float

class SessionService:
    def __init__(self,repository,*,ttl=3600,clock=time.time):
        self.repository=repository;self.ttl=ttl;self.clock=clock
    def initialize(self):
        with self.repository.connection() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS auth_sessions (token_hash TEXT PRIMARY KEY,professor_id TEXT NOT NULL REFERENCES professors(professor_id),csrf_hash TEXT NOT NULL,created_at REAL NOT NULL,expires_at REAL NOT NULL,revoked_at REAL)')
    def issue(self,professor_id):
        professor=self.repository.get_professor(professor_id)
        if professor is None or professor.status!=Status.ACTIVE:raise AuthenticationError()
        token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32);now=self.clock()
        with self.repository.connection() as conn:
            conn.execute('DELETE FROM auth_sessions WHERE expires_at<=? OR revoked_at IS NOT NULL',(now,))
            conn.execute('INSERT INTO auth_sessions VALUES (?,?,?,?,?,NULL)',(digest(token),professor_id,digest(csrf),now,now+self.ttl))
        return token,csrf
    def authenticate(self,token,*,csrf=None,mutation=False):
        if not isinstance(token,str) or not 32<=len(token)<=128:raise AuthenticationError()
        with self.repository.connection() as conn:
            row=conn.execute('SELECT * FROM auth_sessions WHERE token_hash=?',(digest(token),)).fetchone()
        if row is None or row['revoked_at'] is not None or row['expires_at']<=self.clock():raise AuthenticationError()
        professor=self.repository.get_professor(row['professor_id'])
        if professor is None or professor.status!=Status.ACTIVE:raise AuthenticationError()
        if mutation and (not isinstance(csrf,str) or not 32<=len(csrf)<=128 or not secrets.compare_digest(row['csrf_hash'],digest(csrf))):raise CSRFError()
        return Principal(ProfessorContext.from_identity(professor),row['token_hash'],row['expires_at'])
    def csrf(self,token):
        # Rotation is explicit: old browser mutation token stops working.
        principal=self.authenticate(token);csrf=secrets.token_urlsafe(32)
        with self.repository.connection() as conn:conn.execute('UPDATE auth_sessions SET csrf_hash=? WHERE token_hash=?',(digest(csrf),principal.session_key))
        return csrf
    def revoke(self,principal):
        with self.repository.connection() as conn:conn.execute('UPDATE auth_sessions SET revoked_at=? WHERE token_hash=?',(self.clock(),principal.session_key))
