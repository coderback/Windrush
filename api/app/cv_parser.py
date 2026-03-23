import fitz  # PyMuPDF


def extract_text(pdf_bytes: bytes) -> str:
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        return "\n".join(page.get_text() for page in doc)
    except Exception as exc:
        raise ValueError(f"Could not parse PDF: {exc}") from exc
