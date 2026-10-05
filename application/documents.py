"""Document lifecycle and explicit fact/preference decisions; domain owns validation."""
from __future__ import annotations
from typing import TYPE_CHECKING
from dataclasses import replace
if TYPE_CHECKING:
    from document_models import DocumentRequest, DocumentDraft, DocumentVersions
from ._dependencies import dependency
from .errors import call, UnsupportedOperationError

class DocumentService:
    def __init__(self, *, studio=None, repository=None, preferences=None, exporter=None):
        self.studio=studio; self.repository=repository; self.preferences=preferences; self.exporter=exporter
    def generate(self,request: DocumentRequest,**options) -> DocumentDraft:
        return call(dependency(self.studio,'document_studio').generate_draft,request,**options)
    def refine_draft(self,current,instruction,**options):
        return call(dependency(self.studio,'document_studio').refine_draft,current,instruction,**options)
    def refine(self,versions: DocumentVersions,instruction: str,**options) -> DocumentVersions:
        current=replace(versions.current,fact_expectations=versions.expectation_snapshots[-1])
        return self.edit(versions,self.refine_draft(current,instruction,**options),'ai_refinement')
    def generated(self,draft,template_id='standard_academic'):
        from document_models import DocumentVersions
        return call(DocumentVersions.generated,draft,template_id)
    def edit(self,versions,draft,source='professor_edit',**options): return call(versions.update,draft,source,**options)
    def restore(self,versions,index): return call(versions.restore,index)
    def undo(self,versions): return call(versions.undo)
    def save(self,versions,document_id=None,status='Draft',**options):
        return call(dependency(self.repository,'document_repository').save_draft,versions,document_id,status,**options)
    def list_drafts(self): return call(dependency(self.repository,'document_repository').list_drafts)
    def load(self,document_id: str) -> DocumentVersions: return call(dependency(self.repository,'document_repository').load_draft,document_id)
    def history(self,document_id): return call(dependency(self.repository,'document_repository').list_versions,document_id)
    def conflicts(self,draft,expectations): return call(dependency(None,'document_facts').conflicts,draft,expectations)
    def confirm_edit(self,draft,expectations,replacements=None):
        return call(dependency(None,'document_facts').confirm_edit,draft,expectations,replacements)
    def resolve_conflict(self,versions,draft,*,update_confirmed=False,replacements=None):
        if not update_confirmed: return versions
        facts=self.confirm_edit(draft,versions.expectation_snapshots[-1],replacements)
        return self.edit(versions,draft,expectations=facts)
    def fact(self,*args,**kwargs): return call(dependency(None,'document_facts').fact,*args,**kwargs)
    def update_fact(self,*args,**kwargs): return call(dependency(None,'document_facts').update_fact,*args,**kwargs)
    def remove_fact(self,*args,**kwargs): return call(dependency(None,'document_facts').remove_fact,*args,**kwargs)
    def manage_fact(self,versions,operation,*,field=None,value=None,fact_id=None):
        facts=versions.expectation_snapshots[-1]
        if operation=='add': facts=facts+(self.fact(field,value),)
        elif operation=='update': facts=self.update_fact(facts,fact_id,value)
        elif operation=='remove': facts=self.remove_fact(facts,fact_id)
        else: raise UnsupportedOperationError()
        return self.edit(versions,versions.current,expectations=facts)
    def export(self,draft,template_id='standard_academic',*,format='pdf'):
        if format not in ('pdf','docx'): raise UnsupportedOperationError()
        exporter=dependency(self.exporter,'document_export')
        operation=exporter.document_pdf_bytes if format=='pdf' else exporter.document_docx_bytes
        return call(operation,draft,template_id)
    def pdf(self,draft,template_id='standard_academic'): return self.export(draft,template_id,format='pdf')
    def docx(self,draft,template_id='standard_academic'): return self.export(draft,template_id,format='docx')
    def approve_preference(self,*args,**kwargs): return call(dependency(self.preferences,'document_preferences').approve_preference,*args,**kwargs)
    def list_preferences(self): return call(dependency(self.preferences,'document_preferences').list_preferences)
    def update_preference(self,*args,**kwargs): return call(dependency(self.preferences,'document_preferences').update_preference,*args,**kwargs)
    def delete_preference(self,identity): return call(dependency(self.preferences,'document_preferences').delete_preference,identity)
    def feedback(self,*args,**kwargs): return call(dependency(self.preferences,'document_preferences').save_feedback,*args,**kwargs)
