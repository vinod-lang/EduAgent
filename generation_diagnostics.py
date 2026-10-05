"""Safe generation metadata: no prompts, responses, facts, IDs or traces."""
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from structured_generation import Failure

_MESSAGES = {
    Failure.INVALID_JSON: ('Unusable response', 'EduAgent could not produce a usable structured response.', 'Try generating again.'),
    Failure.SCHEMA_INVALID: ('Format validation failed', 'The generated response did not match the required format.', 'Try generating again.'),
    Failure.PRODUCT_VALIDATION_FAILED: ('Requirements not satisfied', 'The generated content did not satisfy all requested requirements.', 'Review the request and try again.'),
    Failure.FACT_PRESERVATION_FAILED: ('Required facts not preserved', 'One or more required facts were missing or changed in the generated document.', 'Keep the previous version and review confirmed facts.'),
    Failure.INSUFFICIENT_EVIDENCE: ('More material needed', 'Not enough matching academic material was found to answer or generate this reliably.', 'Adjust the scope or provide matching material.'),
    Failure.PROVIDER_ERROR: ('AI service unavailable', 'The local AI service could not complete the request.', 'Check that Ollama and the configured model are available.'),
    Failure.TIMEOUT: ('AI service timed out', 'The local AI service took too long to respond.', 'Try again later or use a smaller request.'),
    Failure.UNSUPPORTED_OPERATION: ('Unsupported request', 'This operation is not available in EduAgent.', 'Use a supported workflow; external and destructive actions are unavailable.'),
}

@dataclass(frozen=True)
class GenerationDiagnostic:
    status: str
    category: str
    title: str
    professor_message: str
    suggested_action: str
    attempts_used: int = 0
    saved: bool = False

@dataclass(frozen=True)
class GenerationProvenance:
    generation_type: str
    generated_at: str
    validation_status: str
    attempts_used: int
    model: str
    provider: str
    grounded: bool = False
    professor_edited: bool = False
    preferences_applied: bool = False
    fallback_active: bool = False
    normalization_applied: bool = False
    normalization_type: str | None = None

    def __post_init__(self):
        if self.generation_type not in ('document','document refinement','assessment','assistant plan') or self.validation_status != 'Validated' or type(self.attempts_used) is not int or not 1 <= self.attempts_used <= 2:
            raise ValueError('Invalid generation provenance.')
        datetime.fromisoformat(self.generated_at)
        if not all(isinstance(v,str) and v.strip() for v in (self.model,self.provider)) or any(type(v) is not bool for v in (self.grounded,self.professor_edited,self.preferences_applied,self.fallback_active,self.normalization_applied)):
            raise ValueError('Invalid generation provenance.')
        if self.normalization_type not in (None,'known_mcq_option_shape') or self.normalization_applied!=(self.normalization_type is not None):raise ValueError('Invalid normalization provenance.')


def failed(category, attempts=0):
    category=Failure(category)
    title,message,action=_MESSAGES[category]
    return GenerationDiagnostic('rejected',category.value,title,message,action,attempts,False)


def validated(provenance=None, *, saved=False):
    grounded=bool(provenance and provenance.grounded)
    return GenerationDiagnostic('validated','VALIDATED','Validated',
        'Grounded in course material. Ready for professor review.' if grounded else 'Ready for professor review. Structural validation does not verify factual accuracy.',
        'Review before use.',provenance.attempts_used if provenance else 0,saved)


def clarification():
    return GenerationDiagnostic('clarification','MISSING_INFORMATION','More information needed','Required information is missing. No action has executed.','Complete the requested fields and submit again.')


def from_error(error):
    diagnostic=getattr(error,'generation_diagnostic',None)
    if isinstance(diagnostic,GenerationDiagnostic):return diagnostic
    from assessment_spec import NoAssessmentEvidence
    from assistant_models import UnsupportedPlanError
    from document_facts import DocumentFactConflict
    if isinstance(error,UnsupportedPlanError):return failed(Failure.UNSUPPORTED_OPERATION)
    if isinstance(error,DocumentFactConflict):return failed(Failure.FACT_PRESERVATION_FAILED)
    from ai_provider import AIProviderError
    import httpx
    if isinstance(error,NoAssessmentEvidence):return failed(Failure.INSUFFICIENT_EVIDENCE)
    if isinstance(error,AIProviderError):
        category=Failure.TIMEOUT if isinstance(error.__cause__,(TimeoutError,httpx.TimeoutException)) else Failure.PROVIDER_ERROR
        return failed(category)
    return failed(Failure.PRODUCT_VALIDATION_FAILED)


def annotate(value, kind, attempts, *, grounded=False, preferences_applied=False, normalization_applied=False, normalization_type=None):
    from ai_provider import configured,get_last_generation_selection
    config=configured()
    selection=get_last_generation_selection()
    provenance=GenerationProvenance(kind,datetime.now(timezone.utc).isoformat(),'Validated',attempts,selection.effective_model if selection else config.model,config.provider,grounded,False,preferences_applied,selection.fallback_active if selection else False,normalization_applied,normalization_type)
    return replace(value,provenance=provenance)
