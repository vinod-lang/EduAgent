"""Validated quiz/paper/PYQ generation and clean exports, without UI objects."""
from __future__ import annotations
from typing import TYPE_CHECKING
from ._dependencies import dependency
from .errors import call, UnsupportedOperationError
if TYPE_CHECKING:
    from assessment_spec import AssessmentSpec
    from assessment_studio import AssessmentResult

class AssessmentService:
    def __init__(self, *, studio=None, pyq=None, exporter=None):
        self.studio=studio; self.pyq=pyq; self.exporter=exporter
    def generate(self, spec: AssessmentSpec, **options) -> AssessmentResult:
        return call(dependency(self.studio,'assessment_studio').generate_assessment,spec,**options)
    def edit(self,result,edits,*,pyq_text=""):
        from assessment_editing import edit_assessment
        return call(edit_assessment,result,edits,pyq_text=pyq_text)
    def extract_pyq(self, data, filename):
        return call(dependency(self.pyq,'assessment_pyq').extract_pyq,data,filename)
    def export(self, result, format='pdf', *, answer_key=False):
        if format not in ('pdf','docx'): raise UnsupportedOperationError()
        exporter=dependency(self.exporter,'assessment_export')
        operation=exporter.assessment_pdf_bytes if format=='pdf' else exporter.assessment_docx_bytes
        return call(operation,result,answer_key=answer_key)
    def pdf(self,result,**kwargs): return self.export(result,'pdf',**kwargs)
    def docx(self,result,**kwargs): return self.export(result,'docx',**kwargs)
