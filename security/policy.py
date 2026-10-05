"""Deterministic default deny. Roles never override private ownership."""
from application.errors import ApplicationError,NotFoundError
from .models import ProfessorContext,ProfessorIdentity,Ownership,Scope,Action,Role,Status

class AccessDeniedError(ApplicationError):
    code='ACCESS_DENIED'
    message='Access is not permitted for this operation.'

class AuthorizationPolicy:
    def __init__(self,repository):self.repository=repository
    def actor(self,context):
        if not isinstance(context,ProfessorContext):raise AccessDeniedError()
        try: actor=self.repository.get_professor(context.professor_id)
        except Exception as exc:raise AccessDeniedError() from exc
        if actor is None or actor.status!=Status.ACTIVE or (actor.institution_id,actor.department_id)!=(context.institution_id,context.department_id):raise AccessDeniedError()
        return actor
    def allows(self,context,action,ownership,*,kind='material'):
        try:
            actor=self.actor(context)
            if not isinstance(action,Action) or not isinstance(ownership,Ownership) or kind not in ('material','document','preference'):return False
            if kind!='material' and ownership.visibility_scope!=Scope.PRIVATE:return False
            owner=self.repository.get_professor(ownership.owner_professor_id)
            if owner is None or owner.institution_id!=ownership.institution_id or actor.institution_id!=ownership.institution_id:return False
            if ownership.department_id is not None and owner.department_id!=ownership.department_id:return False
            scope=ownership.visibility_scope
            if scope==Scope.PRIVATE: readable=actor.professor_id==ownership.owner_professor_id
            elif scope==Scope.COURSE:
                course=self.repository.course(ownership.course_id)
                readable=bool(course and (course['institution_id'],course['department_id'])==(ownership.institution_id,ownership.department_id) and actor.department_id==ownership.department_id and self.repository.is_member(actor.professor_id,ownership.course_id))
            elif scope==Scope.DEPARTMENT:readable=actor.department_id==ownership.department_id
            else:readable=True
            if not readable:return False
            if action in (Action.READ,Action.EXPORT,Action.GENERATE):return True
            own=actor.professor_id==ownership.owner_professor_id
            if action==Action.CREATE:
                return own and (scope in (Scope.PRIVATE,Scope.COURSE) or (scope==Scope.DEPARTMENT and Role.DEPARTMENT_ADMIN in actor.roles) or (scope==Scope.INSTITUTE and Role.INSTITUTE_ADMIN in actor.roles))
            if action==Action.SHARE:return own
            return own or (scope==Scope.DEPARTMENT and Role.DEPARTMENT_ADMIN in actor.roles) or (scope==Scope.INSTITUTE and Role.INSTITUTE_ADMIN in actor.roles)
        except Exception:return False
    def require(self,context,action,ownership,*,kind='material'):
        if not self.allows(context,action,ownership,kind=kind):raise AccessDeniedError()
    def resource(self,context,action,kind,identity):
        self.actor(context)
        ownership=self.repository.ownership(kind,identity)
        if not self.allows(context,action,ownership,kind=kind):raise NotFoundError()
        return ownership
    def visible_ids(self,context,kind):
        actor=self.actor(context)
        return tuple(i for i in self.repository.candidates(kind,actor) if self.allows(context,Action.READ,self.repository.ownership(kind,i),kind=kind))
    def private(self,context):
        actor=self.actor(context)
        return Ownership(actor.professor_id,actor.institution_id,Scope.PRIVATE,actor.department_id)

class IdentityService:
    """Administrative metadata operations. First admin is explicitly offline-provisioned."""
    def __init__(self,repository,policy):self.repository=repository;self.policy=policy
    def _admin(self,context,institution_id,department_id=None):
        actor=self.policy.actor(context)
        if actor.institution_id!=institution_id or not (Role.INSTITUTE_ADMIN in actor.roles or department_id==actor.department_id and Role.DEPARTMENT_ADMIN in actor.roles):raise AccessDeniedError()
        return actor
    def create(self,identity,*,context):
        actor=self._admin(context,identity.institution_id,identity.department_id)
        if Role.INSTITUTE_ADMIN in identity.roles and Role.INSTITUTE_ADMIN not in actor.roles:raise AccessDeniedError()
        self.repository.bootstrap_professor(identity)
    def get(self,identity,*,context):
        actor=self.policy.actor(context);professor=self.repository.get_professor(identity)
        if professor is None:raise NotFoundError()
        if actor.professor_id!=identity:self._admin(context,professor.institution_id,professor.department_id)
        return professor
    def list(self,*,context):
        actor=self.policy.actor(context);self._admin(context,actor.institution_id,actor.department_id)
        return tuple(p for p in self.repository.list_professors(actor.institution_id) if Role.INSTITUTE_ADMIN in actor.roles or p.department_id==actor.department_id)
    def update(self,identity,*,context):
        old=self.get(identity.professor_id,context=context);actor=self.policy.actor(context)
        if Role.INSTITUTE_ADMIN in old.roles and Role.INSTITUTE_ADMIN not in actor.roles:raise AccessDeniedError()
        if old.roles!=identity.roles or old.status!=identity.status:
            self._admin(context,identity.institution_id,identity.department_id)
            if Role.INSTITUTE_ADMIN in identity.roles and Role.INSTITUTE_ADMIN not in actor.roles:raise AccessDeniedError()
        self.repository.update_professor(identity)
    def membership(self,professor_id,course_id,*,context,member=True):
        course=self.repository.course(course_id)
        if course is None:raise NotFoundError()
        self._admin(context,course['institution_id'],course['department_id'])
        self.repository.set_membership(professor_id,course_id,member=member)
