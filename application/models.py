"""Transport-neutral contracts; no invented identity or authorization guarantees."""
from __future__ import annotations
from typing import TYPE_CHECKING
from dataclasses import dataclass, field
from typing import Mapping
if TYPE_CHECKING:
    from assistant_models import ActionPlan, Clarification
    from generation_diagnostics import GenerationDiagnostic

from security.models import ProfessorContext

@dataclass(frozen=True)
class KnowledgeRequest:
    question: str
    filters: Mapping[str, str] = field(default_factory=dict)
    final_k: int | None = None

@dataclass(frozen=True)
class MaterialUpload:
    content: bytes = field(repr=False)
    filename: str
    hierarchy: Mapping[str, str]

@dataclass(frozen=True)
class AssistantPreview:
    plan: ActionPlan
    clarifications: tuple[Clarification, ...]
    unsupported: bool
    diagnostic: GenerationDiagnostic

@dataclass(frozen=True)
class StudentAnalysis:
    """Local DataFrame domain result; explicit records conversion for future transports."""
    displayed: object = field(repr=False)
    summary: dict
    def to_dict(self):
        import math
        def safe(value):
            if isinstance(value, float) and not math.isfinite(value): return None
            if isinstance(value, dict): return {k: safe(v) for k, v in value.items()}
            if isinstance(value, (list, tuple)): return [safe(v) for v in value]
            return value
        return safe({'students': self.displayed.to_dict(orient='records'), 'summary': self.summary})
