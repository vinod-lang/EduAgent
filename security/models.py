"""Identity/ownership only, never authentication credentials or inferred membership."""
from dataclasses import dataclass
from enum import Enum
from uuid import UUID

class Scope(str,Enum):
    PRIVATE='PRIVATE'; COURSE='COURSE'; DEPARTMENT='DEPARTMENT'; INSTITUTE='INSTITUTE'
class Role(str,Enum):
    PROFESSOR='PROFESSOR'; DEPARTMENT_ADMIN='DEPARTMENT_ADMIN'; INSTITUTE_ADMIN='INSTITUTE_ADMIN'
class Action(str,Enum):
    READ='READ'; CREATE='CREATE'; UPDATE='UPDATE'; DELETE='DELETE'; SHARE='SHARE'; EXPORT='EXPORT'; GENERATE='GENERATE'
class Status(str,Enum): ACTIVE='ACTIVE'; INACTIVE='INACTIVE'
class OwnershipState(str,Enum): LEGACY='LEGACY'; OWNED='OWNED'


def opaque(value):
    if not isinstance(value,str) or str(UUID(value))!=value: raise ValueError('Expected a canonical opaque UUID.')
    return value

@dataclass(frozen=True)
class ProfessorIdentity:
    professor_id: str
    display_name: str
    institution_id: str
    department_id: str
    status: Status = Status.ACTIVE
    roles: tuple[Role,...] = (Role.PROFESSOR,)
    def __post_init__(self):
        for value in (self.professor_id,self.institution_id,self.department_id): opaque(value)
        if not isinstance(self.display_name,str) or not self.display_name.strip() or len(self.display_name)>200:raise ValueError('Invalid display name.')
        if not isinstance(self.status,Status) or not isinstance(self.roles,tuple) or not self.roles or any(not isinstance(r,Role) for r in self.roles) or len(set(self.roles))!=len(self.roles):raise ValueError('Invalid identity state.')

@dataclass(frozen=True)
class ProfessorContext:
    """Trusted backend caller claim; policy revalidates against repository metadata."""
    professor_id: str | None = None
    institution_id: str | None = None
    department_id: str | None = None
    @classmethod
    def from_identity(cls,identity): return cls(identity.professor_id,identity.institution_id,identity.department_id)

@dataclass(frozen=True)
class LegacyDevelopmentContext:
    """Explicit single-user bypass; NEVER issue from an untrusted API request."""
    mode: str = 'development_single_user_legacy'
    def __post_init__(self):
        if self.mode!='development_single_user_legacy':raise ValueError('Invalid legacy context.')

def development_legacy_context(): return LegacyDevelopmentContext()

@dataclass(frozen=True)
class Ownership:
    owner_professor_id: str
    institution_id: str
    visibility_scope: Scope = Scope.PRIVATE
    department_id: str | None = None
    course_id: str | None = None
    def __post_init__(self):
        opaque(self.owner_professor_id);opaque(self.institution_id)
        if not isinstance(self.visibility_scope,Scope):raise ValueError('Invalid visibility scope.')
        for value in (self.department_id,self.course_id):
            if value is not None: opaque(value)
        if self.visibility_scope==Scope.COURSE and (not self.course_id or not self.department_id):raise ValueError('Course ownership requires course and department.')
        if self.visibility_scope==Scope.DEPARTMENT and (not self.department_id or self.course_id):raise ValueError('Invalid department ownership.')
        if self.visibility_scope==Scope.INSTITUTE and (self.department_id or self.course_id):raise ValueError('Institute scope cannot carry narrower scope identifiers.')
        if self.visibility_scope==Scope.PRIVATE and self.course_id:raise ValueError('Private scope must not imply course sharing.')
    def vector_metadata(self):
        return {k:v.value if isinstance(v,Enum) else v for k,v in vars(self).items() if v is not None}

@dataclass(frozen=True)
class DocumentWorkspace:
    versions: object
    ownership: Ownership
    document_id: str | None = None
    saved_version_id: str | None = None
    saved_status: str | None = None
@dataclass(frozen=True)
class StudentWorkspace:
    dataset: object
    ownership: Ownership
    @property
    def frame(self):return self.dataset.frame

@dataclass(frozen=True)
class ScopedExecutionReport:
    report: object
    ownership: Ownership
    @property
    def results(self):return self.report.results
    @property
    def status(self):return self.report.status
