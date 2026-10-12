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


class ContentExtractionError(ValueError):
    """Expected file/OCR failure suitable for display without a traceback."""


def normalize_ocr_text(text):
    import re
    lines = [re.sub(r"[^\S\n]+", " ", line).strip()
             for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def extract_content(path, file_type=None):
    """Return text from PDF or a validated image using local, bounded OCR.

    PDF page markers remain unchanged. Image content is never sent to an LLM.
    """
    from pathlib import Path
    import warnings
    from PIL import Image
    extension = (file_type or Path(path).suffix).lower().lstrip('.')
    if extension == 'pdf':
        try:
            return extract_text_from_pdf(path)
        except Exception as exc:
            raise ContentExtractionError('PDF could not be read.') from exc
    expected = {'png': 'PNG', 'jpg': 'JPEG', 'jpeg': 'JPEG'}.get(extension)
    if not expected:
        raise ContentExtractionError('Supported formats are PDF, PNG, JPG and JPEG.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(path) as image:
                if image.format != expected:
                    raise ContentExtractionError('Image content does not match its PNG/JPEG extension.')
                image.load()
                # Copy pixels only; do not pass file metadata to the OCR command.
                pixels = image.convert('RGB')
    except ContentExtractionError:
        raise
    except Exception as exc:
        raise ContentExtractionError('Image is corrupt, unsupported or too large to decode safely.') from exc
    try:
        import pytesseract
    except ImportError as exc:
        pixels.close()
        raise ContentExtractionError('Image OCR is unavailable: pytesseract is not installed.') from exc
    try:
        text = pytesseract.image_to_string(pixels, timeout=30)
    except pytesseract.TesseractNotFoundError as exc:
        raise ContentExtractionError('Image OCR is unavailable because Tesseract is not installed or configured.') from exc
    except Exception as exc:
        raise ContentExtractionError('Local image OCR failed or timed out.') from exc
    finally:
        pixels.close()
    return normalize_ocr_text(text)


# This block only runs if you execute this file directly (not when imported later)
if __name__ == "__main__":
    pdf_path = "sample_lecture.pdf"  # we'll add a real file next
    text = extract_text_from_pdf(pdf_path)
    print(text)