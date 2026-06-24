"""
Structured document rendering for Windrush CVs and cover letters.

The LLM emits a typed CVDoc / LetterDoc (see agent.py). This module:
  1. turns that doc into trimmed, render-ready template data (the *authoritative*
     1–2 page guarantee — slicing here holds even if the model ignores the prompt),
  2. renders it to HTML via Jinja (reused by both the live preview and the PDF),
  3. renders that HTML to a PDF via WeasyPrint, falling back to the legacy fpdf2
     renderer if WeasyPrint is unavailable or errors.

The same HTML drives the in-app preview and the PDF, so what the user sees is what
recruiters get (modulo small font-metric differences between Blink and WeasyPrint).
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import pdf_generator
from .templates import registry

logger = logging.getLogger("windrush.doc_render")

import os

_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")

_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

# ── Length limits (the real 1–2 page guarantee) ─────────────────────────────────
_MAX_SUMMARY_CHARS = 420
_MAX_ROLES = 4
_MAX_BULLETS = 4
_MAX_SKILL_GROUPS = 5
_MAX_SKILL_ITEMS = 12
_MAX_PROJECTS = 3
_MAX_EDUCATION = 4
_MAX_CERTS = 6
_MAX_PARAGRAPHS = 4


# ── helpers ─────────────────────────────────────────────────────────────────────

def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    # prefer ending on a sentence boundary, else a word boundary
    for sep in (". ", "; "):
        idx = cut.rfind(sep)
        if idx > limit * 0.5:
            return cut[: idx + 1].strip()
    idx = cut.rfind(" ")
    return (cut[:idx] if idx > 0 else cut).strip() + "…"


def _short_url(url: str) -> str:
    """Display form for a profile link: drop scheme + leading www."""
    u = (url or "").strip()
    if not u:
        return ""
    u = u.split("://", 1)[-1]
    return u[4:] if u.startswith("www.") else u


def _contact_items(contact: dict) -> list[str]:
    if not isinstance(contact, dict):
        return []
    items = [
        (contact.get("email") or "").strip(),
        (contact.get("phone") or "").strip(),
        (contact.get("location") or "").strip(),
        _short_url(contact.get("linkedin", "")),
        _short_url(contact.get("github", "")),
        _short_url(contact.get("website", "")),
    ]
    return [i for i in items if i]


def _role_dates(role: dict) -> str:
    start = (role.get("start_date") or "").strip()
    end = (role.get("end_date") or "").strip() or ("Present" if role.get("is_current") else "")
    if start and end:
        return f"{start} – {end}"
    return start or end


# ── template-data builders (apply trimming/defaults) ────────────────────────────

def build_cv_template_data(cv: dict) -> dict:
    cv = cv or {}
    skills = []
    for grp in (cv.get("skills") or [])[:_MAX_SKILL_GROUPS]:
        items = [s for s in (grp.get("items") or []) if s][:_MAX_SKILL_ITEMS]
        if items:
            skills.append({"category": (grp.get("category") or "Skills").strip(), "items": items})

    experience = []
    for role in (cv.get("experience") or [])[:_MAX_ROLES]:
        bullets = [b.strip() for b in (role.get("bullets") or []) if b and b.strip()][:_MAX_BULLETS]
        experience.append({
            "title": (role.get("title") or "").strip(),
            "employer": (role.get("employer") or "").strip(),
            "location": (role.get("location") or "").strip(),
            "dates": _role_dates(role),
            "bullets": bullets,
        })

    projects = []
    for p in (cv.get("projects") or [])[:_MAX_PROJECTS]:
        projects.append({
            "name": (p.get("name") or "").strip(),
            "description": (p.get("description") or "").strip(),
            "tech": [t for t in (p.get("tech") or []) if t],
            "link": _short_url(p.get("link", "")),
        })

    education = []
    for e in (cv.get("education") or [])[:_MAX_EDUCATION]:
        education.append({
            "degree": (e.get("degree") or "").strip(),
            "institution": (e.get("institution") or "").strip(),
            "year": (e.get("year") or "").strip(),
            "grade": (e.get("grade") or "").strip(),
        })

    certifications = []
    for c in (cv.get("certifications") or [])[:_MAX_CERTS]:
        certifications.append({
            "name": (c.get("name") or "").strip(),
            "issuer": (c.get("issuer") or "").strip(),
            "year": (c.get("year") or "").strip(),
        })

    return {
        "name": (cv.get("name") or "").strip(),
        "headline": (cv.get("headline") or "").strip(),
        "contact_items": _contact_items(cv.get("contact", {})),
        "summary": _truncate(cv.get("summary", ""), _MAX_SUMMARY_CHARS),
        "skills": skills,
        "experience": experience,
        "projects": projects,
        "education": education,
        "certifications": certifications,
    }


def build_letter_template_data(letter: dict) -> dict:
    letter = letter or {}
    paragraphs = [p.strip() for p in (letter.get("paragraphs") or []) if p and p.strip()][:_MAX_PARAGRAPHS]
    return {
        "candidate_name": (letter.get("candidate_name") or "").strip(),
        "company": (letter.get("company") or "").strip(),
        "job_title": (letter.get("job_title") or "").strip(),
        "date": (letter.get("date") or "").strip(),
        "contact_items": _contact_items(letter.get("contact", {})),
        "salutation": (letter.get("salutation") or "Dear Hiring Manager,").strip(),
        "paragraphs": paragraphs,
        "signoff": (letter.get("signoff") or "Sincerely,").strip(),
    }


# ── HTML rendering ───────────────────────────────────────────────────────────────

def render_cv_html(cv: dict, template_id: str | None = None) -> str:
    tpl = registry.resolve(template_id)
    return _env.get_template(tpl["cv"]).render(cv=build_cv_template_data(cv))


def render_letter_html(letter: dict, template_id: str | None = None) -> str:
    tpl = registry.resolve(template_id)
    return _env.get_template(tpl["letter"]).render(letter=build_letter_template_data(letter))


def render_html(doc_type: str, doc: dict, template_id: str | None = None) -> str:
    if doc_type == "cover_letter":
        return render_letter_html(doc, template_id)
    return render_cv_html(doc, template_id)


# ── PDF rendering ────────────────────────────────────────────────────────────────

def _weasyprint_pdf(html: str) -> str:
    """Render HTML to a PDF on disk via WeasyPrint. Returns a 32-hex doc_id."""
    from weasyprint import HTML  # imported lazily so a missing dep doesn't break import

    doc_id = uuid.uuid4().hex
    HTML(string=html, base_url=_TEMPLATES_DIR).write_pdf(pdf_generator.get_pdf_path(doc_id))
    return doc_id


def _fallback_pdf(doc_type: str, doc: dict) -> str:
    """Legacy fpdf2 path used only if WeasyPrint is unavailable/errors."""
    if doc_type == "cover_letter":
        data = build_letter_template_data(doc)
        text = "\n\n".join([data["salutation"], *data["paragraphs"], data["signoff"], data["candidate_name"]])
        meta = {"name": data["candidate_name"], "job_title": data["job_title"], "company": data["company"]}
        return pdf_generator.generate_pdf("cover_letter", text, meta)
    data = build_cv_template_data(doc)
    lines: list[str] = []
    if data["name"]:
        lines.append(f"# {data['name']}")
    if data["headline"]:
        lines.append(data["headline"])
    if data["contact_items"]:
        lines.append(" | ".join(data["contact_items"]))
    if data["summary"]:
        lines += ["", "## Summary", data["summary"]]
    if data["skills"]:
        lines += ["", "## Skills"]
        lines += [f"**{g['category']}:** {', '.join(g['items'])}" for g in data["skills"]]
    if data["experience"]:
        lines += ["", "## Experience"]
        for r in data["experience"]:
            head = " — ".join(p for p in [r["title"], r["employer"]] if p)
            if r["dates"]:
                head += f" ({r['dates']})"
            lines.append(f"### {head}")
            lines += [f"- {b}" for b in r["bullets"]]
    if data["projects"]:
        lines += ["", "## Projects"]
        for p in data["projects"]:
            lines.append(f"### {p['name']}")
            if p["description"]:
                lines.append(p["description"])
    if data["education"]:
        lines += ["", "## Education"]
        for e in data["education"]:
            head = " — ".join(p for p in [e["degree"], e["institution"]] if p)
            if e["grade"]:
                head += f" ({e['grade']})"
            lines.append(f"### {head}")
    return pdf_generator.generate_pdf("cv", "\n".join(lines), {})


async def render_pdf(doc_type: str, doc: dict, template_id: str | None = None) -> str:
    """
    Render a CV/cover-letter doc to a PDF and return its 32-hex doc_id.
    WeasyPrint runs in a worker thread (it is synchronous + CPU-bound). On any
    failure we degrade to the fpdf2 renderer so the feature never hard-fails.
    """
    try:
        html = render_html(doc_type, doc, template_id)
        return await asyncio.to_thread(_weasyprint_pdf, html)
    except Exception as exc:  # noqa: BLE001 — broad on purpose; we want the fallback
        logger.warning("WeasyPrint render failed (%s); falling back to fpdf2: %s", doc_type, exc)
        return await asyncio.to_thread(_fallback_pdf, doc_type, doc)
