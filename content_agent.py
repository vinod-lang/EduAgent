import pdfplumber

def extract_text_from_pdf(pdf_path):
    """
    Takes the path to a PDF file and returns all its text as one big string.
    """
    full_text = ""

    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text()
            if page_text:  # some pages might be blank/images, so we check
                full_text += f"\n--- Page {page_number} ---\n"
                full_text += page_text

    return full_text


# This block only runs if you execute this file directly (not when imported later)
if __name__ == "__main__":
    pdf_path = "sample_lecture.pdf"  # we'll add a real file next
    text = extract_text_from_pdf(pdf_path)
    print(text)