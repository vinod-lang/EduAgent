"""Temporary local PYQ extraction; never registers files, vectors or records."""
from pathlib import Path
from tempfile import TemporaryDirectory
from assessment_spec import AssessmentError
from material_service import validate_filename, MaterialError
from content_agent import extract_content, ContentExtractionError
from config import get_max_upload_bytes, ConfigurationError


def extract_pyq(data,name):
    try:
        validate_filename(name)
        limit=get_max_upload_bytes()
    except (MaterialError,ConfigurationError) as exc:
        raise AssessmentError(str(exc)) from exc
    if not isinstance(data,bytes) or not data or len(data)>limit:
        raise AssessmentError('PYQ requires nonempty file bytes within the upload size limit.')
    try:
        with TemporaryDirectory(prefix='eduagent-pyq-') as directory:
            path=Path(directory)/('guidance'+Path(name).suffix.lower())
            path.write_bytes(data)
            text=extract_content(path)
    except (ContentExtractionError,OSError) as exc:
        raise AssessmentError(f'PYQ extraction failed: {exc}') from exc
    if not isinstance(text,str) or not text.strip():raise AssessmentError('PYQ contains no usable extracted text.')
    if len(text)>20000:raise AssessmentError('PYQ guidance exceeds 20,000 characters; use a smaller excerpt/file.')
    return text.strip()
