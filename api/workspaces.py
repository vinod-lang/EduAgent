"""Bounded ephemeral session-owned handles, never client-supplied domain ownership."""
import threading,time,uuid
from contextlib import contextmanager
from application.errors import NotFoundError,ConflictError

class Workspaces:
    def __init__(self,*,maximum=100,clock=time.time):self.rows={};self.item_locks={};self.lock=threading.RLock();self.maximum=maximum;self.clock=clock
    def _purge(self):
        for key in list(self.rows):
            if self.rows[key][2]<=self.clock():
                del self.rows[key];self.item_locks.pop(key,None)
    def put(self,principal,kind,value):
        with self.lock:
            self._purge()
            if len(self.rows)>=self.maximum:raise ConflictError()
            key=str(uuid.uuid4());self.item_locks[key]=threading.RLock();self.rows[key]=(principal.session_key,kind,principal.expires_at,value);return key
    @contextmanager
    def item(self,principal,key,kind):
        # Independent workspaces do not hold a process-wide lock during AI work.
        with self.lock:
            self._purge();row=self.rows.get(key)
            if row is None or row[0]!=principal.session_key or row[1]!=kind:raise NotFoundError()
            lock=self.item_locks[key]
        with lock:
            with self.lock:
                self._purge();row=self.rows.get(key)
                if row is None or row[0]!=principal.session_key or row[1]!=kind:raise NotFoundError()
            yield row[3]
    def update(self,principal,key,kind,value):
        with self.item(principal,key,kind):
            with self.lock:
                if key not in self.rows:raise NotFoundError()
                self.rows[key]=(principal.session_key,kind,principal.expires_at,value)
    def handles(self,principal,kind):
        with self.lock:
            self._purge()
            return [key for key,row in self.rows.items() if row[0]==principal.session_key and row[1]==kind]
    def clear(self,principal):
        with self.lock:
            for key in list(self.rows):
                if self.rows[key][0]==principal.session_key:
                    del self.rows[key];self.item_locks.pop(key,None)

    def remove(self,principal,key,kind):
        with self.item(principal,key,kind):
            with self.lock:self.rows.pop(key,None);self.item_locks.pop(key,None)

    def clear_student(self,principal,key):
        with self.item(principal,key,'student-data') as dataset:
            with self.lock:
                related=[k for k,row in self.rows.items() if row[0]==principal.session_key and (k==key or row[1]=='plan' and row[3][1].student_dataset is dataset)]
                for k in related:self.rows.pop(k,None);self.item_locks.pop(k,None)
