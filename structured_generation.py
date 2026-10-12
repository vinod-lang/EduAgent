"""Bounded, private structured generation. Product validators are final authority."""
from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar
import hashlib
import json
import httpx
from jsonschema import Draft202012Validator
import ai_provider
from generation_trace import stage,event,schema_failure,provider_completed

T = TypeVar('T')

class Failure(str, Enum):
    PROVIDER_ERROR = 'PROVIDER_ERROR'
    TIMEOUT = 'TIMEOUT'
    INVALID_JSON = 'INVALID_JSON'
    SCHEMA_INVALID = 'SCHEMA_INVALID'
    PRODUCT_VALIDATION_FAILED = 'PRODUCT_VALIDATION_FAILED'
    FACT_PRESERVATION_FAILED = 'FACT_PRESERVATION_FAILED'
    INSUFFICIENT_EVIDENCE = 'INSUFFICIENT_EVIDENCE'
    UNSUPPORTED_OPERATION = 'UNSUPPORTED_OPERATION'
    DOCUMENT_QUALITY_FAILED = 'DOCUMENT_QUALITY_FAILED'

class DocumentQualityFailure(ValueError):
    def __init__(self, message, *, rule=None):
        super().__init__(message)
        self.rule = rule

class FactPreservationFailure(ValueError):
    pass

class UnsupportedGeneratedFactFailure(FactPreservationFailure):
    """New unsupported assertion, never a supplied/confirmed fact mutation."""
    rule = "unsupported_factual_value"

@dataclass(frozen=True)
class ResponseMetadata:
    sha256: str
    characters: int

@dataclass(frozen=True)
class StructuredGenerationResult(Generic[T]):
    value: T | None
    failure: Failure | None
    attempt_count: int
    first_failure: Failure | None
    responses: tuple[ResponseMetadata, ...] = ()
    connection_failure: bool = False
    normalization_applied: bool = False
    normalization_type: str | None = None
    model_unavailable: bool = False

    @property
    def accepted(self):
        return self.failure is None

    def require(self, error_type, feature):
        if self.accepted:
            return self.value
        message = f'EduAgent could not produce a valid {feature} ({self.failure.value}). Review the request and try again. No result was saved.'
        from generation_diagnostics import failed
        if self.model_unavailable:
            error=ai_provider.AIModelUnavailableError(message)
        elif self.connection_failure:
            error=ai_provider.AIConnectionError(message)
        elif self.failure in (Failure.PROVIDER_ERROR, Failure.TIMEOUT):
            error=ai_provider.AIProviderError(message)
        else:
            error=error_type(message)
        error.generation_diagnostic=failed(self.failure,self.attempt_count)
        raise error


def extract_object(raw, *, maximum=1000000):
    if not isinstance(raw, str) or len(raw) > maximum:
        raise ValueError('Missing or oversized response.')
    text = raw.strip()
    if text.startswith('```json\n') and text.endswith('\n```'):
        text = text[8:-4].strip()
    elif text.startswith('Here is the result:\n'):
        text = text[len('Here is the result:\n'):].strip()
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate key.')
            result[key] = value
        return result
    def constant(_):
        raise ValueError('Nonfinite constant.')
    data = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    if not isinstance(data, dict):
        raise ValueError('Exactly one object required.')
    return data


def generate_structured(messages, schema, validator, *, retry=False, maximum=1000000,
                        semantic_schema=False, fact_fields=(), normalizer=None, trace_observer=None, document_quality_retry=False):
    """One attempt by default; optional second attempt for syntax/shape only.

    No raw responses, prompts, facts, validation traces or exception details are
    retained in results/logs. Native schema support does not replace validation.
    semantic_schema disables shape retries for policy-sensitive planner contracts.
    """
    if type(retry) is not bool or type(document_quality_retry) is not bool:
        raise ValueError('Retry must be a boolean (maximum one retry).')
    Draft202012Validator.check_schema(schema)
    checker = Draft202012Validator(schema)
    history = []
    normalization_applied=False
    normalization_type=None
    ai_provider.clear_generation_selection()
    first = None
    current = [dict(message) for message in messages]
    for attempt in range(1, 3 if retry or document_quality_retry else 2):
        repairable_quality = False
        if document_quality_retry:event(generation_attempt=attempt)
        connection = False
        try:
            kwargs = {'messages':current}
            if ai_provider.get_provider_capabilities().supports_structured_output:
                kwargs['response_format'] = schema
            raw = ai_provider.generate_chat(**kwargs)
            provider_completed()
        except (ai_provider.AIStructuredRequestError,ai_provider.AIResponseError) as exc:
            stage('provider_completed',False,failure_rule='provider_failure')
            failure=Failure.SCHEMA_INVALID if isinstance(exc,ai_provider.AIStructuredRequestError) else Failure.INVALID_JSON
            event(failure_code=failure.value)
            if document_quality_retry and attempt == 2:event(corrective_retry='fail',final_failure_code=failure.value)
            return StructuredGenerationResult(None,failure,attempt,first or failure,tuple(history))
        except ai_provider.AIProviderError as exc:
            stage('provider_completed',False,failure_rule='provider_failure')
            cause = exc.__cause__
            failure = Failure.TIMEOUT if isinstance(cause, (TimeoutError, httpx.TimeoutException)) else Failure.PROVIDER_ERROR
            event(failure_code=failure.value)
            if document_quality_retry and attempt == 2:event(corrective_retry='fail',final_failure_code=failure.value)
            return StructuredGenerationResult(None, failure, attempt, first or failure, tuple(history), isinstance(exc, ai_provider.AIConnectionError), model_unavailable=isinstance(exc, ai_provider.AIModelUnavailableError))
        if isinstance(raw, str):
            history.append(ResponseMetadata(hashlib.sha256(raw.encode('utf-8',errors='replace')).hexdigest(), len(raw)))
        try:
            data = extract_object(raw, maximum=maximum)
        except (ValueError, TypeError, RecursionError):
            stage('parse',False,failure_rule='structured_output_invalid')
            failure = Failure.INVALID_JSON
        else:
            stage('parse')
            if normalizer is not None:
                try:
                    normalized=normalizer(data)
                except ValueError:
                    stage('normalization',False,failure_code='PRODUCT_VALIDATION_FAILED',failure_rule='normalization_invalid')
                    return StructuredGenerationResult(None,Failure.PRODUCT_VALIDATION_FAILED,attempt,first or Failure.PRODUCT_VALIDATION_FAILED,tuple(history))
                stage('normalization')
                data=normalized.data
                normalization_applied=normalization_applied or normalized.applied
                normalization_type=normalized.normalization_type or normalization_type
            if trace_observer is not None:trace_observer(data)
            errors = list(checker.iter_errors(data))
            if errors:
                schema_failure(errors,fact_fields)
                # Changed values/counts/enums are semantic, not repairable shape.
                semantic = semantic_schema or any(e.validator in ('const','enum','minItems','maxItems','uniqueItems','oneOf','minimum','maximum','minLength','maxLength') for e in errors)
                fact_error = any((e.path and e.path[0] in fact_fields) or (e.validator == 'required' and any(k in fact_fields and k not in data for k in e.validator_value)) for e in errors)
                failure = Failure.FACT_PRESERVATION_FAILED if fact_error else (Failure.PRODUCT_VALIDATION_FAILED if semantic else Failure.SCHEMA_INVALID)
            else:
                stage('schema')
                try:
                    value = validator(json.dumps(data, ensure_ascii=False, allow_nan=False))
                except DocumentQualityFailure as exc:
                    repairable_quality = document_quality_retry and exc.rule == 'placeholder'
                    stage('quality',False)
                    failure = Failure.DOCUMENT_QUALITY_FAILED
                except FactPreservationFailure as exc:
                    repairable_quality = document_quality_retry and isinstance(exc, UnsupportedGeneratedFactFailure)
                    stage('fact_validation',False)
                    failure = Failure.FACT_PRESERVATION_FAILED
                except ValueError:
                    stage('product_validation',False,failure_rule='product_validation')
                    failure = Failure.PRODUCT_VALIDATION_FAILED
                else:
                    stage('product_validation')
                    event(failure_code='NONE')
                    if document_quality_retry and attempt == 2:event(corrective_retry='pass')
                    return StructuredGenerationResult(value, None, attempt, first, tuple(history),False,normalization_applied,normalization_type)
        event(failure_code=failure.value)
        first = first or failure
        if document_quality_retry and attempt == 2:event(corrective_retry='fail',final_failure_code=failure.value)
        if attempt == 2 or not (repairable_quality or (retry and failure in (Failure.INVALID_JSON, Failure.SCHEMA_INVALID))):
            return StructuredGenerationResult(None, failure, attempt, first, tuple(history), connection,normalization_applied,normalization_type)
        if repairable_quality:
            event(corrective_retry='started',reason='unsupported_factual_value' if failure == Failure.FACT_PRESERVATION_FAILED else 'placeholder')
            correction = 'The previous draft contained unresolved placeholder text. Regenerate the complete document from the authoritative original request and confirmed facts. Do not use placeholders or invent missing facts. Omit unavailable assertions or use natural conditional language. Preserve all explicitly supplied and confirmed facts. Return one JSON object matching the contract.'
            if failure == Failure.FACT_PRESERVATION_FAILED:
                correction = 'The previous draft introduced unsupported factual assertions. Regenerate the complete document using only the authoritative professor request, supplied fields, confirmed facts and authorized context. Do not invent dates, venues, amounts, funding sources, attachments, completed preparations, approvals, deadlines, reference numbers, participant counts or institutional arrangements. Do not use placeholders. Omit unavailable assertions or use natural conditional language. Professional connective prose, rationale, respectful requests and general benefits are allowed. Preserve every supplied and confirmed fact. Return one JSON object matching the contract.'
        else:
            correction = 'Previous output did not match the required schema. Return one JSON object matching this contract.'
        current = [dict(message) for message in messages] + [{'role':'user','content':correction}]
