"""Hierarchy-aware evidence and answers; existing gate/prompt/provider are unchanged."""
from __future__ import annotations
from typing import TYPE_CHECKING
from ._dependencies import dependency
from .errors import call
from .models import KnowledgeRequest
if TYPE_CHECKING:
    from student_support_agent import QAResult
    from retrieval import RetrievalResult

class KnowledgeService:
    def __init__(self, *, agent=None, retriever=None): self.agent=agent; self.retriever=retriever
    def retrieve(self, request: KnowledgeRequest) -> RetrievalResult:
        operation=self.retriever or dependency(None,'retrieval').retrieve_evidence
        return call(operation,request.question,request.filters,final_k=request.final_k)
    def ask(self, request: KnowledgeRequest) -> QAResult:
        return self.answer_question(request.question,n_chunks=request.final_k,filters=request.filters)
    def answer_question(self, question, n_chunks=None, course=None, **scope):
        return call(dependency(self.agent,'student_support_agent').answer_question,
                    question,n_chunks=n_chunks,course=course,**scope)
