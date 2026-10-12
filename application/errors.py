"""Stable public failures; domain validators remain authoritative."""
import sqlite3

class ApplicationError(ValueError):
    code = 'APPLICATION_ERROR'
    message = 'The operation could not be completed. Review the request and try again.'
    def __init__(self, *, diagnostic=None, message=None):
        super().__init__(message or self.message)
        self.generation_diagnostic = diagnostic
    def to_dict(self):
        return {'code': self.code, 'message': str(self)}

class ValidationError(ApplicationError):
    code = 'VALIDATION_ERROR'
    message = 'The request is invalid. Check required fields and input values.'
class NotFoundError(ApplicationError):
    code = 'NOT_FOUND'
    message = 'The requested item was not found.'
class ConflictError(ApplicationError):
    code = 'CONFLICT'
    message = 'The change conflicts with existing confirmed facts or saved state. Resolve it before proceeding.'
class ProviderUnavailableError(ApplicationError):
    code = 'PROVIDER_UNAVAILABLE'
    message = 'The local AI service could not complete the request. Check its availability.'
class ProviderGenerationError(ApplicationError):
    code = 'PROVIDER_ERROR'
    message = 'The local AI service could not complete generation. Review the request or try a smaller request.'
class ModelUnavailableError(ProviderUnavailableError):
    code = 'MODEL_UNAVAILABLE'
    message = 'The configured local AI models are unavailable. Ask the administrator to check installed models.'
class ProviderTimeoutError(ProviderUnavailableError):
    code = 'PROVIDER_TIMEOUT'
    message = 'The local AI service took too long to respond. Try a smaller request or retry later.'
class StudentMappingError(ValidationError):
    code = 'INVALID_MAPPING'

class InsufficientEvidenceError(ApplicationError):
    code = 'INSUFFICIENT_EVIDENCE'
    message = 'Not enough matching academic material was found.'
class UnsupportedOperationError(ApplicationError):
    code = 'UNSUPPORTED_OPERATION'
    message = 'This operation is not available. Use a supported workflow.'
class StorageError(ApplicationError):
    code = 'STORAGE_ERROR'
    message = 'Local storage could not complete the operation.'


def call(operation, *args, **kwargs):
    """Map expected failures only. Unexpected developer errors still propagate."""
    from ai_provider import AIProviderError, AIModelUnavailableError, AIConnectionError, AIStructuredRequestError, AIResponseError
    from assessment_spec import AssessmentError, NoAssessmentEvidence
    from assistant_models import PlanError, UnsupportedPlanError
    from document_models import DocumentError
    from document_facts import DocumentFactConflict
    from document_repository import DocumentStorageError
    from material_service import MaterialError
    from student_ingestion import StudentDataError
    from retrieval import RetrievalError
    from config import ConfigurationError
    from generation_diagnostics import from_error
    try:
        return operation(*args, **kwargs)
    except ApplicationError:
        raise
    except (AIProviderError, NoAssessmentEvidence, UnsupportedPlanError, DocumentFactConflict,
            DocumentStorageError, AssessmentError, PlanError, DocumentError, MaterialError,
            StudentDataError, RetrievalError, ConfigurationError, sqlite3.Error, OSError) as exc:
        kind = (ProviderUnavailableError if isinstance(exc, AIProviderError) else
                InsufficientEvidenceError if isinstance(exc, NoAssessmentEvidence) else
                UnsupportedOperationError if isinstance(exc, UnsupportedPlanError) else
                ConflictError if isinstance(exc, DocumentFactConflict) else
                StorageError if isinstance(exc, (DocumentStorageError, sqlite3.Error, OSError)) else ValidationError)
        if isinstance(exc, AIModelUnavailableError):kind=ModelUnavailableError
        elif isinstance(exc, AIProviderError) and from_error(exc).category=='TIMEOUT':kind=ProviderTimeoutError
        elif isinstance(exc,(AIStructuredRequestError,AIResponseError)):kind=ValidationError
        elif isinstance(exc,AIProviderError) and not isinstance(exc,AIConnectionError):kind=ProviderGenerationError
        # Preserve reviewed constant ingestion guidance, never interpolate cells or paths.
        public_student_messages = {
            'Supported student files are CSV and XLSX; XLS/XLSM are not supported.',
            'Student file is empty.',
            'Student file exceeds the 10 MB limit.',
            'Cannot read XLSX. Choose a valid, unencrypted workbook.',
            'Cannot read CSV. Use valid UTF-8 text with consistent quoting.',
            'CSV contains invalid null characters.',
            'CSV contains no data.',
            'Cannot determine CSV delimiter; use UTF-8 comma-separated CSV.',
        }
        mapping_messages={
            'Identity, name, attendance and assessment-number columns cannot be marks.':'Identity, name, attendance and assessment-number columns cannot be marks.',
            'A marks column cannot be the assessment-number column.':'A marks column cannot be the assessment-number column.',
            'Map at least Student ID or Student Name.':'Student identifier or name is not mapped.',
            'Map attendance and at least one assessment column.':'Map attendance and at least one marks column.',
            'Raw marks require a finite positive maximum.':'Maximum marks is required for raw marks. Enter a positive maximum.',
            'Choose raw or percentage marks.':'Choose raw marks with a maximum, or explicitly confirm percentage marks.',
            'Mapped fields must be distinct, existing source columns.':'Map distinct columns from the selected sheet.',
            'Selected sheet/header contains no student rows.':'The selected sheet and header contain no student rows.',
        }
        if isinstance(exc,StudentDataError) and str(exc) in mapping_messages:
            failure=StudentMappingError(message=mapping_messages[str(exc)])
            failure.message=mapping_messages[str(exc)]
            failure.code={
                'Map at least Student ID or Student Name.':'STUDENT_ID_NOT_MAPPED',
                'Map attendance and at least one assessment column.':'STUDENT_COLUMNS_NOT_MAPPED',
                'Raw marks require a finite positive maximum.':'MARKS_MAXIMUM_REQUIRED',
                'Choose raw or percentage marks.':'MARKS_SCALE_REQUIRED',
                'Selected sheet/header contains no student rows.':'NO_STUDENT_ROWS',
            }.get(str(exc),'INVALID_MAPPING')
            raise failure from exc
        message = str(exc) if isinstance(exc, StudentDataError) and str(exc) in public_student_messages else None
        raise kind(diagnostic=from_error(exc), message=message) from exc
