"""All OCR tests mock the engine; originals and live Chroma are never opened."""
import io
import sys
from unittest.mock import Mock
import pytest
from PIL import Image
import pytesseract
from content_agent import extract_content, ContentExtractionError
from config import get_max_upload_bytes, ConfigurationError


def image_bytes(format='PNG', color='white'):
    buffer = io.BytesIO()
    with Image.new('RGB', (64, 32), color) as image:
        image.save(buffer, format=format)
    return buffer.getvalue()


@pytest.mark.parametrize('suffix', ['.png', '.jpg', '.jpeg', '.PNG', '.JPG', '.JPEG'])
def test_supported_image(tmp_path, monkeypatch, suffix):
    path = tmp_path / ('notes' + suffix)
    path.write_bytes(image_bytes('PNG' if suffix.lower() == '.png' else 'JPEG'))
    ocr = Mock(return_value='  PCA  preserves\t variance. \r\n\n\n 講義  résumé  ')
    monkeypatch.setattr(pytesseract, 'image_to_string', ocr)
    assert extract_content(path) == 'PCA preserves variance.\n\n講義 résumé'
    assert ocr.call_args.kwargs == {'timeout': 30}


@pytest.mark.parametrize('data,suffix', [(b'broken', '.png'), (b'%PDF-fake', '.jpg'), (image_bytes('GIF'), '.jpg'), (image_bytes('PNG'), '.jpeg')])
def test_reject_invalid_image(tmp_path, monkeypatch, data, suffix):
    path = tmp_path / ('notes' + suffix); path.write_bytes(data)
    ocr = Mock(); monkeypatch.setattr(pytesseract, 'image_to_string', ocr)
    with pytest.raises(ContentExtractionError): extract_content(path)
    ocr.assert_not_called()


@pytest.mark.parametrize('failure,message', [(pytesseract.TesseractNotFoundError(), 'not installed or configured'), (RuntimeError('synthetic timeout'), 'failed or timed out')])
def test_controlled_ocr_error(tmp_path, monkeypatch, failure, message):
    path = tmp_path / 'notes.png'; path.write_bytes(image_bytes())
    monkeypatch.setattr(pytesseract, 'image_to_string', Mock(side_effect=failure))
    with pytest.raises(ContentExtractionError, match=message): extract_content(path)


def test_missing_ocr_python_dependency(tmp_path, monkeypatch):
    path = tmp_path / 'notes.png'; path.write_bytes(image_bytes())
    monkeypatch.setitem(sys.modules, 'pytesseract', None)
    with pytest.raises(ContentExtractionError, match='pytesseract is not installed'): extract_content(path)


def test_pdf_page_provenance_without_ocr(tmp_path, monkeypatch):
    from fpdf import FPDF
    pdf = FPDF(); pdf.add_page(); pdf.set_font('Helvetica', size=12)
    pdf.cell(text='Synthetic PCA lecture'); pdf.add_page(); pdf.cell(text='Covariance matrix')
    path = tmp_path / 'lecture.PDF'; pdf.output(path)
    monkeypatch.setitem(sys.modules, 'pytesseract', None)
    text = extract_content(path)
    assert '--- Page 1 ---' in text and '--- Page 2 ---' in text
    assert 'Synthetic PCA lecture' in text and 'Covariance matrix' in text


def test_corrupt_pdf_is_controlled(tmp_path):
    path = tmp_path / 'lecture.pdf'; path.write_bytes(b'fake PDF')
    with pytest.raises(ContentExtractionError, match='PDF could not be read'): extract_content(path)


@pytest.mark.parametrize('value', ['0', '-1', 'nan', 'inf', 'invalid', '1e308'])
def test_invalid_size_configuration(monkeypatch, value):
    monkeypatch.setenv('EDUAGENT_MAX_UPLOAD_MB', value)
    with pytest.raises(ConfigurationError): get_max_upload_bytes()


def test_upload_limit_override_and_default(monkeypatch):
    monkeypatch.delenv('EDUAGENT_MAX_UPLOAD_MB', raising=False)
    assert get_max_upload_bytes() == 20 * 1024 * 1024
    monkeypatch.setenv('EDUAGENT_MAX_UPLOAD_MB', '1.5')
    assert get_max_upload_bytes() == 1572864


def test_decompression_bomb_rejected(tmp_path, monkeypatch):
    path = tmp_path / 'notes.png'; path.write_bytes(image_bytes())
    monkeypatch.setattr(Image, 'MAX_IMAGE_PIXELS', 1000)
    ocr = Mock(); monkeypatch.setattr(pytesseract, 'image_to_string', ocr)
    with pytest.raises(ContentExtractionError, match='too large'): extract_content(path)
    ocr.assert_not_called()


def test_unsupported_extension(tmp_path):
    path = tmp_path / 'notes.gif'; path.write_bytes(image_bytes('GIF'))
    with pytest.raises(ContentExtractionError, match='Supported formats'): extract_content(path)
