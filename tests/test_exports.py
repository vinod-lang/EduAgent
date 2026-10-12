import io
import zipfile
import pdfplumber
from docx import Document
from export_utils import generate_docx_bytes,generate_quiz_pdf_bytes,generate_question_paper_pdf_bytes

def test_docx_and_batch_letter(tmp_path):
    for name,text in [("notice","Synthetic — notice"),("warning","Synthetic attendance warning")]:
        path=tmp_path/(name+".docx");path.write_bytes(generate_docx_bytes(text).getvalue())
        assert Document(path).paragraphs[0].text==text

def test_quiz_pdf(tmp_path,mcq):
    mcq=dict(mcq,question="Synthetic — question?",explanation="Smart ‘quotes’ work.")
    path=tmp_path/"quiz.pdf";path.write_bytes(generate_quiz_pdf_bytes([mcq],title="Synthetic — Quiz").getvalue())
    with pdfplumber.open(path) as pdf:
        assert len(pdf.pages)>=2
        text="\n".join(page.extract_text() or "" for page in pdf.pages)
        assert "Synthetic - question" in text and "Answer Key" in text

def test_paper_pdf(tmp_path,mcq):
    paper={"mcq_section":[dict(mcq,marks=2)],"descriptive_section":[{"question":"Synthetic — describe","model_answer":"Synthetic answer","marks":5}],"total_marks":7}
    path=tmp_path/"paper.pdf";path.write_bytes(generate_question_paper_pdf_bytes(paper,title="Synthetic — Paper").getvalue())
    with pdfplumber.open(path) as pdf:
        text="\n".join(page.extract_text() or "" for page in pdf.pages)
        assert "Total Marks: 7" in text and "Synthetic answer" in text
