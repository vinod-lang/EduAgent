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
    from ai_provider import AIProviderError
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
        message = str(exc) if isinstance(exc, StudentDataError) and str(exc) in public_student_messages else None
        raise kind(diagnostic=from_error(exc), message=message) from exc
