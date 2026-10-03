import io
from docx import Document as DocxDocument
from fpdf import FPDF


def sanitize_text(text):
    """
    Replaces common 'smart' characters (from AI-generated text or
    typed titles) with plain ASCII equivalents that FPDF's default
    font can actually render. Anything else unsupported gets dropped
    safely instead of crashing.
    """
    replacements = {
        "—": "-",   # em dash
        "–": "-",   # en dash
        "‘": "'",   # curly single quote
        "’": "'",
        "“": '"',   # curly double quote
        "”": '"',
        "…": "...",
    }
    for bad_char, good_char in replacements.items():
        text = text.replace(bad_char, good_char)

    # Final safety net: drop any remaining character the font can't handle
    return text.encode("latin-1", errors="ignore").decode("latin-1")


def safe_multicell(pdf, height, text):
    # multi_cell can leave x at the right edge; reset it before every paragraph.
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, height, sanitize_text(text))


def generate_docx_bytes(text):
    """
    Converts plain text (like a generated notice) into a real .docx
    file, kept in memory so it can be offered as a download without
    ever writing to disk.
    """
    doc = DocxDocument()
    for line in text.split("\n"):
        doc.add_paragraph(line)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer


def generate_quiz_pdf_bytes(questions, title="Quiz"):
    """
    Builds a real PDF containing the quiz on one page and the
    answer key on a separate page — exactly how a professor would
    want to print/distribute it.
    """
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, sanitize_text(title), ln=True)
    pdf.set_font("Helvetica", size=12)

    for i, q in enumerate(questions, start=1):
        safe_multicell(pdf, 8, f"Q{i}. {q['question']}")
        if "options" in q:
            for letter, opt in q["options"].items():
                safe_multicell(pdf, 8, f"   {letter}) {opt}")
        pdf.ln(2)

    # Answer key on a fresh page, separated from the questions
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "Answer Key", ln=True)
    pdf.set_font("Helvetica", size=12)

    for i, q in enumerate(questions, start=1):
        if "correct_answer" in q:
            safe_multicell(pdf, 8, f"Q{i}: {q['correct_answer']} - {q.get('explanation', '')}")
        else:
            safe_multicell(pdf, 8, f"Q{i}: {q.get('model_answer', '')}")

    pdf_bytes = bytes(pdf.output())
    return io.BytesIO(pdf_bytes)

def generate_question_paper_pdf_bytes(paper, title="Question Paper"):
    """
    Builds a properly formatted question paper PDF with sections,
    per-question marks, and a total — plus a separate answer key page.
    """
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, sanitize_text(title), ln=True)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 10, f"Total Marks: {paper['total_marks']}", ln=True)
    pdf.ln(3)

    # Section A: MCQs
    if paper["mcq_section"]:
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 10, "Section A: Multiple Choice Questions", ln=True)
        pdf.set_font("Helvetica", size=12)
        for i, q in enumerate(paper["mcq_section"], start=1):
            safe_multicell(pdf, 8, f"Q{i}. [{q['marks']} marks] {q['question']}")
            for letter, opt in q["options"].items():
                safe_multicell(pdf, 8, f"   {letter}) {opt}")
            pdf.ln(1)

    # Section B: Descriptive
    if paper["descriptive_section"]:
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 10, "Section B: Descriptive Questions", ln=True)
        pdf.set_font("Helvetica", size=12)
        for i, q in enumerate(paper["descriptive_section"], start=1):
            safe_multicell(pdf, 8, f"Q{i}. [{q['marks']} marks] {q['question']}")
            pdf.ln(1)

    # Answer key on separate pages
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "Answer Key", ln=True)
    pdf.set_font("Helvetica", size=12)

    if paper["mcq_section"]:
        pdf.cell(0, 10, "Section A", ln=True)
        for i, q in enumerate(paper["mcq_section"], start=1):
            safe_multicell(pdf, 8, f"Q{i}: {q['correct_answer']} - {q.get('explanation', '')}")

    if paper["descriptive_section"]:
        pdf.cell(0, 10, "Section B", ln=True)
        for i, q in enumerate(paper["descriptive_section"], start=1):
            safe_multicell(pdf, 8, f"Q{i}: {q.get('model_answer', '')}")

    pdf_bytes = bytes(pdf.output())
    return io.BytesIO(pdf_bytes)