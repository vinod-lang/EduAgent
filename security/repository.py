"""Additive companion metadata, explicit initialization, no ownership backfill."""
from contextlib import contextmanager
from datetime import datetime,timezone
import json
import sqlite3
from .models import ProfessorIdentity,Ownership,Scope,Role,Status,opaque

KINDS=('material','document','preference')
SCHEMA='''
CREATE TABLE IF NOT EXISTS professors (
 professor_id TEXT PRIMARY KEY, display_name TEXT NOT NULL,
 institution_id TEXT NOT NULL, department_id TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('ACTIVE','INACTIVE')), roles_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS security_courses (
 course_id TEXT PRIMARY KEY,institution_id TEXT NOT NULL,department_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS professor_course_memberships (
 professor_id TEXT NOT NULL REFERENCES professors(professor_id),
 course_id TEXT NOT NULL REFERENCES security_courses(course_id),
 PRIMARY KEY(professor_id,course_id));
CREATE TABLE IF NOT EXISTS resource_ownership (
 resource_type TEXT NOT NULL CHECK(resource_type IN ('material','document','preference')),
 resource_id TEXT NOT NULL,owner_professor_id TEXT NOT NULL REFERENCES professors(professor_id),
 institution_id TEXT NOT NULL,department_id TEXT,course_id TEXT,
 visibility_scope TEXT NOT NULL CHECK(visibility_scope IN ('PRIVATE','COURSE','DEPARTMENT','INSTITUTE')),
 PRIMARY KEY(resource_type,resource_id));
CREATE TABLE IF NOT EXISTS security_activity (
 id INTEGER PRIMARY KEY,actor_professor_id TEXT NOT NULL REFERENCES professors(professor_id),
 action TEXT NOT NULL,resource_type TEXT,resource_id TEXT,timestamp TEXT NOT NULL);
'''

class SecurityRepository:
    def __init__(self,connection_factory=None): self.connection_factory=connection_factory
    @contextmanager
    def connection(self):
        if self.connection_factory is None:
            import db
            conn=db.get_connection()
        else: conn=self.connection_factory()
        conn.row_factory=sqlite3.Row
        try:
            with conn: yield conn
        finally: conn.close()
    @staticmethod
    def has(conn,table):return bool(conn.execute('SELECT 1 FROM sqlite_master WHERE type=\'table\' AND name=?',(table,)).fetchone())
    def initialize(self):
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            # Separate statements inside one transaction, unlike executescript's implicit commit.
            for statement in SCHEMA.split(';'):
                if statement.strip():conn.execute(statement)
    def get_professor(self,identity):
        with self.connection() as conn:
            if not self.has(conn,'professors'):return None
            row=conn.execute('SELECT * FROM professors WHERE professor_id=?',(identity,)).fetchone()
        if row is None:return None
        try:return ProfessorIdentity(row['professor_id'],row['display_name'],row['institution_id'],row['department_id'],Status(row['status']),tuple(Role(r) for r in json.loads(row['roles_json'])))
        except (ValueError,TypeError):return None
    def _write_professor(self,identity, *, create=False):
        if not isinstance(identity,ProfessorIdentity):raise ValueError('Invalid professor metadata.')
        with self.connection() as conn:
            if create:conn.execute('INSERT INTO professors VALUES (?,?,?,?,?,?)',(identity.professor_id,identity.display_name,identity.institution_id,identity.department_id,identity.status.value,json.dumps([r.value for r in identity.roles])))
            else:
                old=conn.execute('SELECT institution_id,department_id FROM professors WHERE professor_id=?',(identity.professor_id,)).fetchone()
                if old is None or (old['institution_id'],old['department_id'])!=(identity.institution_id,identity.department_id):raise ValueError('Institution/department reassignment requires a separate migration.')
                conn.execute('UPDATE professors SET display_name=?,status=?,roles_json=? WHERE professor_id=?',(identity.display_name,identity.status.value,json.dumps([r.value for r in identity.roles]),identity.professor_id))
    def bootstrap_professor(self,identity):
        """Trusted offline provisioning only, not an application/UI permission bypass."""
        self._write_professor(identity,create=True)
    def update_professor(self,identity):self._write_professor(identity)
    def list_professors(self,institution_id):
        with self.connection() as conn:
            ids=[r[0] for r in conn.execute('SELECT professor_id FROM professors WHERE institution_id=? ORDER BY professor_id',(institution_id,))]
        return tuple(self.get_professor(i) for i in ids)
    def register_course(self,course_id,institution_id,department_id):
        for value in (course_id,institution_id,department_id):opaque(value)
        with self.connection() as conn:conn.execute('INSERT INTO security_courses VALUES (?,?,?)',(course_id,institution_id,department_id))
    def course(self,identity):
        with self.connection() as conn:
            if not self.has(conn,'security_courses'):return None
            row=conn.execute('SELECT * FROM security_courses WHERE course_id=?',(identity,)).fetchone()
        return dict(row) if row else None
    def set_membership(self,professor_id,course_id,*,member=True):
        professor=self.get_professor(professor_id);course=self.course(course_id)
        if professor is None or course is None or (professor.institution_id,professor.department_id)!=(course['institution_id'],course['department_id']):raise ValueError('Invalid course membership.')
        with self.connection() as conn:
            if member:conn.execute('INSERT OR IGNORE INTO professor_course_memberships VALUES (?,?)',(professor_id,course_id))
            else:conn.execute('DELETE FROM professor_course_memberships WHERE professor_id=? AND course_id=?',(professor_id,course_id))
    def is_member(self,professor_id,course_id):
        with self.connection() as conn:
            return self.has(conn,'professor_course_memberships') and bool(conn.execute('SELECT 1 FROM professor_course_memberships WHERE professor_id=? AND course_id=?',(professor_id,course_id)).fetchone())
    def ownership(self,kind,identity):
        if kind not in KINDS:return None
        with self.connection() as conn:
            if not self.has(conn,'resource_ownership'):return None
            row=conn.execute('SELECT * FROM resource_ownership WHERE resource_type=? AND resource_id=?',(kind,identity)).fetchone()
        if row is None:return None
        try:return Ownership(row['owner_professor_id'],row['institution_id'],Scope(row['visibility_scope']),row['department_id'],row['course_id'])
        except (TypeError,ValueError):return None
    @staticmethod
    def attach_ownership(conn,kind,identity,ownership):
        if kind not in KINDS or not isinstance(ownership,Ownership):raise ValueError('Invalid ownership metadata.')
        opaque(identity)
        conn.execute('INSERT INTO resource_ownership VALUES (?,?,?,?,?,?,?)',(kind,identity,ownership.owner_professor_id,ownership.institution_id,ownership.department_id,ownership.course_id,ownership.visibility_scope.value))

    def put_ownership(self,kind,identity,ownership):
        if kind not in KINDS or not isinstance(ownership,Ownership):raise ValueError('Invalid ownership metadata.')
        opaque(identity)
        with self.connection() as conn:
            self.attach_ownership(conn,kind,identity,ownership)
    def change_ownership(self,kind,identity,old,new):
        if kind not in KINDS or not isinstance(old,Ownership) or not isinstance(new,Ownership):raise ValueError('Invalid ownership transition.')
        with self.connection() as conn:
            changed=conn.execute("""UPDATE resource_ownership SET institution_id=?,department_id=?,course_id=?,visibility_scope=? WHERE resource_type=? AND resource_id=? AND owner_professor_id=? AND institution_id=? AND department_id IS ? AND course_id IS ? AND visibility_scope=?""",
                (new.institution_id,new.department_id,new.course_id,new.visibility_scope.value,kind,identity,old.owner_professor_id,old.institution_id,old.department_id,old.course_id,old.visibility_scope.value)).rowcount
            if changed!=1:raise ValueError('Ownership changed; reload before sharing.')
    def remove_ownership(self,kind,identity):
        with self.connection() as conn:conn.execute('DELETE FROM resource_ownership WHERE resource_type=? AND resource_id=?',(kind,identity))
    def candidates(self,kind,actor):
        with self.connection() as conn:
            if not self.has(conn,'resource_ownership'):return ()
            # Narrow in SQL before any resource payload is read; policy remains final authority.
            rows=conn.execute('''SELECT resource_id FROM resource_ownership WHERE resource_type=? AND institution_id=?
             AND ((visibility_scope='PRIVATE' AND owner_professor_id=?) OR
                  (visibility_scope='COURSE' AND course_id IN (SELECT course_id FROM professor_course_memberships WHERE professor_id=?)) OR
                  (visibility_scope='DEPARTMENT' AND department_id=?) OR visibility_scope='INSTITUTE')''',
                 (kind,actor.institution_id,actor.professor_id,actor.professor_id,actor.department_id)).fetchall()
        return tuple(r[0] for r in rows)
    def audit(self,actor,action,kind=None,identity=None):
        from dashboard import ACTIONS
        if action not in ACTIONS or (kind is not None and kind not in KINDS):raise ValueError('Invalid audit metadata.')
        if identity is not None:opaque(identity)
        with self.connection() as conn:conn.execute('INSERT INTO security_activity(actor_professor_id,action,resource_type,resource_id,timestamp) VALUES (?,?,?,?,?)',(actor.professor_id,action,kind,identity,datetime.now(timezone.utc).isoformat()))
    def activity(self,actor,limit=20):
        with self.connection() as conn:
            if not self.has(conn,'security_activity'):return []
            return [dict(r) for r in conn.execute('SELECT actor_professor_id,action,resource_type,resource_id,timestamp FROM security_activity WHERE actor_professor_id=? ORDER BY id DESC LIMIT ?',(actor.professor_id,limit))]
