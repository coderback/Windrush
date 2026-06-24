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
import re
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
_MAX_SKILL_GROUPS = 6
_MAX_SKILL_ITEMS = 14
_MAX_PROJECTS = 3
_MAX_PROJECT_DESC_CHARS = 420
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
        if idx > limit * 0.35:  # prefer ending on a whole sentence over a mid-clause '…'
            return cut[: idx + 1].strip()
    idx = cut.rfind(" ")
    return (cut[:idx] if idx > 0 else cut).strip() + "…"


def _clean_text(text: str) -> str:
    """Strip stray HTML (literal <br>, leftover tags) and collapse whitespace — guards
    against verbose persona fields leaking markup into a rendered description."""
    t = re.sub(r"(?i)<br\s*/?>", " ", text or "")
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _short_url(url: str) -> str:
    """Display form for a profile link: drop scheme + leading www."""
    u = (url or "").strip()
    if not u:
        return ""
    u = u.split("://", 1)[-1]
    return u[4:] if u.startswith("www.") else u


def _abs_url(url: str) -> str:
    """Ensure a profile link is an absolute URL so it is clickable in the PDF."""
    u = (url or "").strip()
    if not u:
        return ""
    if u.startswith("http://") or u.startswith("https://"):
        return u
    return "https://" + u.lstrip("/")


def _project_link_label(url: str) -> str:
    """Human label for a project link, by host, so it renders as a clickable word
    ("GitHub" / "Live Demo") instead of a long raw URL — consistent with the
    labelled contact links."""
    host = _short_url(url).lower()
    if not host:
        return ""
    if "github.com" in host:
        return "GitHub"
    if "gitlab.com" in host:
        return "GitLab"
    if "bitbucket" in host:
        return "Bitbucket"
    return "Live Demo"


def _contact_items(contact: dict) -> list[dict]:
    """
    Header contact entries as {text, href?} objects. Profile links render as
    labelled, clickable hyperlinks ("LinkedIn Profile" / "GitHub" / "Website")
    rather than long raw URLs; email/phone become mailto:/tel: links; location is
    plain text. Order: location, phone, email, then profile links.
    """
    if not isinstance(contact, dict):
        return []
    items: list[dict] = []
    loc = (contact.get("location") or "").strip()
    phone = (contact.get("phone") or "").strip()
    email = (contact.get("email") or "").strip()
    if loc:
        items.append({"text": loc})
    if phone:
        items.append({"text": phone, "href": "tel:" + re.sub(r"[^\d+]", "", phone)})
    if email:
        items.append({"text": email, "href": "mailto:" + email})
    for key, label in (("linkedin", "LinkedIn Profile"), ("github", "GitHub"), ("website", "Website")):
        url = _abs_url(contact.get(key, ""))
        if url:
            items.append({"text": label, "href": url})
    return items


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
            "description": _truncate(_clean_text(p.get("description", "")), _MAX_PROJECT_DESC_CHARS),
            "tech": [t for t in (p.get("tech") or []) if t],
            "link": _short_url(p.get("link", "")),
            "link_href": _abs_url(p.get("link", "")),
            "link_label": _project_link_label(p.get("link", "")),
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

    # Section order is seniority-aware (2026 graduate strategy): juniors lead with
    # Education and place Skills lower; experienced candidates lead with Skills and
    # keep Education near the end. Falls back to a sensible inference if unset.
    seniority = (cv.get("seniority") or "").lower()
    if seniority not in ("junior", "experienced"):
        seniority = "junior" if (education and len(experience) <= 1) else "experienced"
    if seniority == "junior":
        sections = ["summary", "education", "experience", "projects", "skills", "certifications"]
    else:
        sections = ["summary", "skills", "experience", "projects", "education", "certifications"]

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
        "seniority": seniority,
        "sections": sections,
    }


def _letter_contact_lines(contact: dict) -> list[dict]:
    """Vertical contact block for a cover letter: address, city+postcode, phone, email."""
    if not isinstance(contact, dict):
        return []
    lines: list[dict] = []
    addr = (contact.get("address_line_1") or "").strip()
    city = (contact.get("city") or contact.get("location") or "").strip()
    postcode = (contact.get("postcode") or "").strip()
    phone = (contact.get("phone") or "").strip()
    email = (contact.get("email") or "").strip()
    if addr:
        lines.append({"text": addr + ","})
    city_line = " ".join(x for x in [city, postcode] if x).strip()
    if city_line:
        lines.append({"text": city_line + "."})
    if phone:
        lines.append({"text": phone, "href": "tel:" + re.sub(r"[^\d+]", "", phone)})
    if email:
        lines.append({"text": email, "href": "mailto:" + email})
    return lines


def build_letter_template_data(letter: dict) -> dict:
    letter = letter or {}
    paragraphs = [p.strip() for p in (letter.get("paragraphs") or []) if p and p.strip()][:_MAX_PARAGRAPHS]
    return {
        "candidate_name": (letter.get("candidate_name") or "").strip(),
        "headline": (letter.get("headline") or "").strip(),
        "company": (letter.get("company") or "").strip(),
        "job_title": (letter.get("job_title") or "").strip(),
        "company_location": (letter.get("company_location") or "").strip(),
        "date": (letter.get("date") or "").strip(),
        "contact_lines": _letter_contact_lines(letter.get("contact", {})),
        "salutation": (letter.get("salutation") or "Dear Hiring Manager,").strip(),
        "paragraphs": paragraphs,
        "signoff": (letter.get("signoff") or "Yours faithfully,").strip(),
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
        head = [data["candidate_name"]]
        if data["headline"]:
            head.append(data["headline"])
        head += [c["text"] for c in data["contact_lines"]]
        body = [data["salutation"], *data["paragraphs"], data["signoff"], data["candidate_name"]]
        text = "\n".join(head) + "\n\n" + "\n\n".join(body)
        meta = {"name": data["candidate_name"], "job_title": data["job_title"], "company": data["company"]}
        return pdf_generator.generate_pdf("cover_letter", text, meta)
    data = build_cv_template_data(doc)
    lines: list[str] = []
    if data["name"]:
        lines.append(f"# {data['name']}")
    if data["headline"]:
        lines.append(data["headline"])
    if data["contact_items"]:
        lines.append(" | ".join(c["text"] for c in data["contact_items"]))
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
