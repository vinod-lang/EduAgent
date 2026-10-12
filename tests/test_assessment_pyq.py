import io
from pathlib import Path
from unittest.mock import Mock
import pytest
from PIL import Image
from fpdf import FPDF
import assessment_pyq as pyq
from assessment_spec import AssessmentError
from content_agent import ContentExtractionError
from test_material_identity import storage

def pdf_bytes():
    pdf=FPDF();pdf.add_page();pdf.set_font('Helvetica',size=12);pdf.cell(0,10,'Synthetic PYQ: Explain principal components.')
    return bytes(pdf.output())

def test_pdf_extract_without_persistence(storage):
    import db
    before=db.list_materials();found=pyq.extract_pyq(pdf_bytes(),'Synthetic.pdf')
    assert 'Synthetic PYQ' in found and db.list_materials()==before and not storage[1].rows and not storage[0].exists()

@pytest.mark.parametrize('name,format',[('Old.png','PNG'),('Old.jpg','JPEG'),('Old.jpeg','JPEG')])
def test_image_ocr(name,format,monkeypatch):
    import pytesseract
    chat=Mock(return_value='Synthetic PYQ style');monkeypatch.setattr(pytesseract,'image_to_string',chat)
    buffer=io.BytesIO();Image.new('RGB',(20,20),'white').save(buffer,format=format)
    assert pyq.extract_pyq(buffer.getvalue(),name)=='Synthetic PYQ style'
    chat.assert_called_once()

@pytest.mark.parametrize('data,name',[(b'','Old.pdf'),(b'broken','Old.pdf'),(b'bad','Old.png'),(b'bad','Old.csv'),(b'bad','../Old.pdf')])
def test_invalid_upload(data,name):
    with pytest.raises(AssessmentError):pyq.extract_pyq(data,name)

@pytest.mark.parametrize('text',['','  ','a'*20001])
def test_empty_or_large_extraction(monkeypatch,text):
    monkeypatch.setattr(pyq,'extract_content',lambda _:text)
    with pytest.raises(AssessmentError):pyq.extract_pyq(b'synthetic','Old.pdf')

def test_size_limit(monkeypatch):
    monkeypatch.setattr(pyq,'get_max_upload_bytes',lambda:3)
    with pytest.raises(AssessmentError):pyq.extract_pyq(b'oversized','Old.pdf')

@pytest.mark.parametrize('failure',[False,True])
def test_temp_path_removed_on_success_and_failure(monkeypatch,failure):
    seen=[]
    def extractor(path):
        seen.append(Path(path));assert path.exists()
        if failure:raise ContentExtractionError('Synthetic failure')
        return 'Synthetic style'
    monkeypatch.setattr(pyq,'extract_content',extractor)
    if failure:
        with pytest.raises(AssessmentError):pyq.extract_pyq(b'fake','Old.pdf')
    else:pyq.extract_pyq(b'fake','Old.pdf')
    assert seen and not seen[0].exists() and not seen[0].parent.exists()

def test_ocr_unavailable(monkeypatch):
    import pytesseract
    monkeypatch.setattr(pytesseract,'image_to_string',Mock(side_effect=pytesseract.TesseractNotFoundError()))
    buffer=io.BytesIO();Image.new('RGB',(20,20)).save(buffer,format='PNG')
    with pytest.raises(AssessmentError,match='Tesseract'):pyq.extract_pyq(buffer.getvalue(),'Old.png')
