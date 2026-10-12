"""Deterministic dashboard and privacy-filtered activity, no AI generations."""
from ._dependencies import dependency
from .errors import call,ValidationError

class ActivityService:
    def __init__(self, *, queries=None, repository=None): self.queries=queries; self.repository=repository
    def recent(self,limit=20):
        if type(limit) is not int or not 1<=limit<=200: raise ValidationError()
        return call(dependency(self.queries,'dashboard').get_activity_view,limit=limit)
    def record(self,action):
        from dashboard import ACTIONS
        if action not in ACTIONS: raise ValidationError()
        # Deliberately no details argument: private payloads cannot be supplied.
        return call(dependency(self.repository,'db').log_activity,action,'')

class DashboardService:
    def __init__(self,materials,activity,*,queries=None,documents=None):
        self.materials=materials; self.activity=activity; self.queries=queries; self.documents=documents
    def summary(self): return call(dependency(self.queries,'dashboard').get_dashboard_summary)
    def legacy(self): return call(dependency(self.queries,'dashboard').legacy_content_view)
    def workspace(self):
        return {'summary':self.summary(),'materials':self.materials.list_materials(),'courses':self.materials.courses(),
                'saved_drafts':self.documents.list_drafts() if self.documents is not None else []}
