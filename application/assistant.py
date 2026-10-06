"""Explicit plan/preview/execute; retain registry, privacy, confirmation and retry gates."""
from __future__ import annotations
from typing import TYPE_CHECKING
from ._dependencies import dependency
from .errors import call
from .models import AssistantPreview
if TYPE_CHECKING:
    from assistant_models import ActionPlan, ExecutionReport
    from assistant_services import ExecutionContext

class AssistantService:
    def __init__(self, *, planner=None, executor=None): self.planner=planner; self.executor=executor
    def plan(self,request: str,context: ExecutionContext | None=None,**options) -> ActionPlan:
        return call(dependency(self.planner,'assistant_planner').plan_request,request,context,**options)
    def validate(self,plan,context): return call(dependency(self.executor,'assistant_services').validate_plan,plan,context)
    def preview(self,plan: ActionPlan,context: ExecutionContext) -> AssistantPreview:
        from generation_diagnostics import clarification,validated,failed
        from structured_generation import Failure
        missing=self.validate(plan,context) if not plan.unsupported else ()
        diagnostic=failed(Failure.UNSUPPORTED_OPERATION) if plan.unsupported else clarification() if missing else validated(plan.provenance)
        return AssistantPreview(plan,missing,plan.unsupported,diagnostic)
    def execute(self,plan: ActionPlan,context: ExecutionContext | None=None,previous: ExecutionReport | None=None,retry: bool=False) -> ExecutionReport:
        return call(dependency(self.executor,'assistant_services').execute_plan,plan,context,previous,retry)
