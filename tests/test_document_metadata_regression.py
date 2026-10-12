"""Step 1B authoritative date assembly and fact conflicts; synthetic mocks only."""
import io,json
from unittest.mock import Mock
import pytest
import ai_provider
from document_models import DocumentError,DocumentVersions
from document_studio import generate_draft,refine_draft
from document_export import visible_blocks,document_docx_bytes,document_pdf_bytes
from tests.test_document_safety import draft,request,BODY
DATE='10 October 2026'

@pytest.mark.parametrize('workflow',['draft','refine'])
@pytest.mark.parametrize('conflict',['metadata','prose'])
def test_supplied_date_conflict_rejected_once(monkeypatch,workflow,conflict):
 current=draft(date=DATE);versions=DocumentVersions.generated(current)
 data={'body':list(BODY)}
 if conflict=='metadata':data['date']='12 October 2026'
 else:data['body']=['The event will be held on 12 October 2026.']
 provider=Mock(return_value=json.dumps(data));monkeypatch.setattr(ai_provider,'generate_chat',provider)
 with pytest.raises(DocumentError) as error:
  generate_draft(request(date=DATE),approved_preferences=(),retry=True) if workflow=='draft' else refine_draft(current,'Make this more formal.',retry=True)
 assert error.value.generation_diagnostic.category=='FACT_PRESERVATION_FAILED'
 assert provider.call_count==1 and versions.current==current and len(versions.history)==1

@pytest.mark.parametrize('date',[DATE,''])
def test_date_omission_assembled_and_exported(monkeypatch,date):
 provider=Mock(return_value=json.dumps({'body':list(BODY),'salutation':'Dear Dean,','closing':'Yours sincerely,'}));monkeypatch.setattr(ai_provider,'generate_chat',provider)
 result=generate_draft(request(date=date),approved_preferences=(),retry=True)
 assert result.date==date and provider.call_count==1
 blocks=dict(visible_blocks(result,'standard_academic'))
 assert (blocks.get('date')==DATE) if date else ('date' not in blocks)
 from docx import Document
 docx_text='\n'.join(p.text for p in Document(io.BytesIO(document_docx_bytes(result))).paragraphs)
 import pdfplumber
 with pdfplumber.open(io.BytesIO(document_pdf_bytes(result))) as pdf:
  pdf_text='\n'.join(p.extract_text() or '' for p in pdf.pages)
 for text in (docx_text,pdf_text):
  assert (DATE in text) if date else (DATE not in text and 'Date:' not in text)


def test_unsupplied_date_not_invented(monkeypatch):
 provider=Mock(return_value=json.dumps({'body':list(BODY),'date':DATE}));monkeypatch.setattr(ai_provider,'generate_chat',provider)
 with pytest.raises(DocumentError):generate_draft(request(),approved_preferences=(),retry=True)
 assert provider.call_count==1
