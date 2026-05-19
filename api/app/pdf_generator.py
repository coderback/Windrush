"""
PDF generation for Windrush documents (CV and cover letter).
Uses fpdf2 for layout with Unicode normalisation for Helvetica compatibility.
"""
import logging
import os
import re
import unicodedata
import uuid

from fpdf import FPDF

logger = logging.getLogger("windrush.pdf")

_PDF_DIR: str = ""


def init_pdf_dir(base_path: str) -> None:
    global _PDF_DIR
    _PDF_DIR = os.path.join(base_path, "pdfs")
    os.makedirs(_PDF_DIR, exist_ok=True)
    logger.info("PDF dir: %s", _PDF_DIR)


def get_pdf_path(doc_id: str) -> str:
    return os.path.join(_PDF_DIR or "/tmp", f"{doc_id}.pdf")


# ── Unicode safety ─────────────────────────────────────────────────────────────

_UNICODE_MAP = {
    "‘": "'", "’": "'",   # smart single quotes
    "“": '"', "”": '"',   # smart double quotes
    "–": "-", "—": "--",  # en/em dash
    "…": "...",                 # ellipsis
    " ": " ",                   # non-breaking space
    "•": "-",                   # bullet
    "·": "-",                   # middle dot
    "→": "->",                  # right arrow
}


def _safe(text: str) -> str:
    """Normalise Unicode to something Helvetica/Latin-1 can render."""
    for ch, sub in _UNICODE_MAP.items():
        text = text.replace(ch, sub)
    # NFKD decomposition, then drop anything that won't encode to latin-1
    text = unicodedata.normalize("NFKD", text)
    return text.encode("latin-1", errors="replace").decode("latin-1")


# ── Inline Markdown parser ─────────────────────────────────────────────────────

def _inline(text: str) -> list[tuple[bool, bool, str]]:
    """Return list of (bold, italic, segment) tuples."""
    segs: list[tuple[bool, bool, str]] = []
    pat = re.compile(r"\*\*(.+?)\*\*|\*(.+?)\*|__(.+?)__|_(.+?)_")
    cur = 0
    for m in pat.finditer(text):
        if m.start() > cur:
            segs.append((False, False, text[cur:m.start()]))
        if m.group(1) is not None:
            segs.append((True, False, m.group(1)))
        elif m.group(2) is not None:
            segs.append((False, True, m.group(2)))
        elif m.group(3) is not None:
            segs.append((True, False, m.group(3)))
        elif m.group(4) is not None:
            segs.append((False, True, m.group(4)))
        cur = m.end()
    if cur < len(text):
        segs.append((False, False, text[cur:]))
    return segs


# ── PDF document class ─────────────────────────────────────────────────────────

_MARGIN = 18
_PAGE_W = 210 - _MARGIN * 2

_C_DARK  = (15, 15, 15)
_C_TEAL  = (15, 118, 110)
_C_MUTED = (100, 100, 100)
_C_RULE  = (210, 210, 210)


class _Doc(FPDF):
    def header(self):
        pass

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(*_C_MUTED)
        self.cell(0, 5, f"Page {self.page_no()}", align="C")
        self.set_text_color(*_C_DARK)

    # ── helpers ────────────────────────────────────────────────────────────────

    def rule(self):
        self.set_draw_color(*_C_RULE)
        self.set_line_width(0.3)
        y = self.get_y() + 1
        self.line(_MARGIN, y, _MARGIN + _PAGE_W, y)
        self.ln(4)

    def h1(self, text: str):
        self.set_font("Helvetica", "B", 20)
        self.set_text_color(*_C_DARK)
        self.set_x(_MARGIN)
        self.multi_cell(_PAGE_W, 10, _safe(text), align="L")
        self.ln(1)

    def h2(self, text: str):
        self.ln(3)
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*_C_TEAL)
        self.set_x(_MARGIN)
        self.multi_cell(_PAGE_W, 7, _safe(text).upper(), align="L")
        self.rule()

    def h3(self, text: str):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*_C_DARK)
        self.set_x(_MARGIN)
        self.multi_cell(_PAGE_W, 6, _safe(text), align="L")

    def para(self, text: str):
        """Render a paragraph with inline bold/italic."""
        segs = _inline(_safe(text))
        self.set_x(_MARGIN)
        for bold, italic, seg in segs:
            style = ("B" if bold else "") + ("I" if italic else "")
            self.set_font("Helvetica", style, 10)
            self.set_text_color(*_C_DARK)
            self.write(5, seg)
        self.ln(5)

    def bullet(self, text: str, level: int = 0):
        indent = _MARGIN + level * 4
        self.set_x(indent)
        self.set_font("Helvetica", "", 10)
        self.set_text_color(*_C_TEAL)
        self.write(5, "- ")
        segs = _inline(_safe(text))
        for bold, italic, seg in segs:
            style = ("B" if bold else "") + ("I" if italic else "")
            self.set_font("Helvetica", style, 10)
            self.set_text_color(*_C_DARK)
            self.write(5, seg)
        self.ln(5)

    def muted(self, text: str):
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*_C_MUTED)
        self.set_x(_MARGIN)
        self.multi_cell(_PAGE_W, 5, _safe(text), align="L")
        self.set_text_color(*_C_DARK)


# ── CV PDF ─────────────────────────────────────────────────────────────────────

def _cv_pdf(text: str) -> str:
    doc = _Doc("P", "mm", "A4")
    doc.set_margins(_MARGIN, 15, _MARGIN)
    doc.set_auto_page_break(auto=True, margin=15)
    doc.add_page()
    doc.set_font("Helvetica", "", 10)

    in_contact = True
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line:
            if in_contact:
                in_contact = False
                doc.ln(4)
            else:
                doc.ln(2)
            continue
        if line.startswith("### "):
            in_contact = False
            doc.h3(line[4:])
        elif line.startswith("## "):
            in_contact = False
            doc.h2(line[3:])
        elif line.startswith("# "):
            doc.h1(line[2:])
        elif re.match(r"^[\-\*] ", line):
            in_contact = False
            level = (len(line) - len(line.lstrip())) // 2
            doc.bullet(line.lstrip()[2:], level)
        else:
            if in_contact:
                doc.muted(line)
            else:
                doc.para(line)

    doc_id = uuid.uuid4().hex
    doc.output(get_pdf_path(doc_id))
    return doc_id


# ── Cover letter PDF ───────────────────────────────────────────────────────────

def _letter_pdf(text: str, name: str = "", job_title: str = "", company: str = "") -> str:
    doc = _Doc("P", "mm", "A4")
    doc.set_margins(_MARGIN, 20, _MARGIN)
    doc.set_auto_page_break(auto=True, margin=20)
    doc.add_page()
    doc.set_font("Helvetica", "", 10)

    if name:
        doc.set_font("Helvetica", "B", 16)
        doc.set_text_color(*_C_DARK)
        doc.set_x(_MARGIN)
        doc.multi_cell(_PAGE_W, 9, _safe(name), align="L")
    if job_title and company:
        doc.set_font("Helvetica", "", 10)
        doc.set_text_color(*_C_MUTED)
        doc.set_x(_MARGIN)
        doc.multi_cell(_PAGE_W, 6, _safe(f"Application for {job_title} at {company}"), align="L")
        doc.set_text_color(*_C_DARK)
    if name or (job_title and company):
        doc.rule()
        doc.ln(2)

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line:
            doc.ln(3)
            continue
        if line.startswith("## "):
            doc.h2(line[3:])
        elif line.startswith("# "):
            doc.h1(line[2:])
        elif re.match(r"^[\-\*] ", line):
            doc.bullet(line.lstrip()[2:])
        else:
            doc.para(line)

    doc_id = uuid.uuid4().hex
    doc.output(get_pdf_path(doc_id))
    return doc_id


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_pdf(doc_type: str, text: str, metadata: dict | None = None) -> str:
    """Generate a PDF and return its doc_id. Raises on failure."""
    meta = metadata or {}
    try:
        if doc_type == "cv":
            return _cv_pdf(text)
        elif doc_type == "cover_letter":
            return _letter_pdf(
                text,
                name=meta.get("name", ""),
                job_title=meta.get("job_title", ""),
                company=meta.get("company", ""),
            )
        else:
            raise ValueError(f"Unknown doc_type: {doc_type!r}")
    except Exception as exc:
        logger.error("PDF generation failed (type=%s): %s", doc_type, exc, exc_info=True)
        raise
