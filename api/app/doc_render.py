"""
Structured document rendering for Windrush CVs and cover letters.

The LLM emits a typed CVDoc / LetterDoc (see agent.py). This module:
  1. turns that doc into trimmed, render-ready template data (the length limits hold
     even if the model ignores the prompt),
  2. renders it to HTML via Jinja (reused by both the live preview and the PDF), fitting it
     to its page target — a cover letter or a graduate's CV to one page, other CVs to two — by
     measuring it in WeasyPrint and tightening (then, for a CV, trimming) until it fits,
  3. renders that HTML to a PDF via WeasyPrint, falling back to the legacy fpdf2
     renderer if WeasyPrint is unavailable or errors.

The same HTML drives the in-app preview and the PDF, so what the user sees is what
recruiters get (modulo small font-metric differences between Blink and WeasyPrint).
"""
from __future__ import annotations

import asyncio
import functools
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

# ── Length limits ────────────────────────────────────────────────────────────────
# These bound what any doc can put on the page; fitting a CV to its page target is _fitted_cv_html's job.
_MAX_SUMMARY_CHARS = 420
_MAX_ROLES = 4
_MAX_BULLETS = 4
MAX_SKILL_GROUPS = 5           # rows, as in the candidate's CV design; extra groups fold into "Other"
_MAX_PROJECTS = 4
_MAX_PROJECT_DESC_CHARS = 520  # room for 2-3 sentences (what it is, how it works, a result)
_MAX_EDUCATION = 4
_MAX_CERTS = 6

# Pages a CV must fit: one for a graduate / early-career candidate, two otherwise.
_PAGE_TARGET = {"junior": 1, "experienced": 2}

# When a CV runs over its page target, these steps are tried in order until it fits. Each adds to
# the one before: tighter spacing, then 10pt type (the floor), then trimming the least important
# content — project technology lists, each role's 4th bullet, project descriptions after their
# first sentence. "tight" and "small" are CSS classes on <body> (base.css); the rest trim the data.
_FIT_STEPS: tuple[tuple[str, ...], ...] = (
    (),
    ("tight",),
    ("tight", "small"),
    ("tight", "small", "no_tech"),
    ("tight", "small", "no_tech", "three_bullets"),
    ("tight", "small", "no_tech", "three_bullets", "one_sentence"),
)
_LAYOUT_STEPS = ("tight", "small")
# A cover letter is one page and is never trimmed: only its layout tightens.
_LETTER_FIT_STEPS: tuple[tuple[str, ...], ...] = ((), ("tight",), ("tight", "small"))
_OTHER_CATEGORIES = ("other", "others", "additional", "miscellaneous", "misc")


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


def _render_recency(entry: dict) -> tuple[int, int]:
    """Reverse-chronological sort key (year, month); current/ongoing entries rank first.
    Mirrors agent._recency_key but works on rendered CVDoc fields (end_date / year)."""
    end = str(entry.get("end_date") or entry.get("year") or entry.get("start_date") or "").strip().lower()
    if entry.get("is_current") or end in ("present", "current", "ongoing", "now"):
        return (9999, 13)
    ym = re.search(r"(19|20)\d{2}", end)
    year = int(ym.group(0)) if ym else 0
    m1 = re.search(r"\b(0?[1-9]|1[0-2])[/-](?:19|20)\d{2}", end)
    m2 = re.search(r"(?:19|20)\d{2}[-/](0?[1-9]|1[0-2])\b", end)
    month = int(m1.group(1)) if m1 else (int(m2.group(1)) if m2 else 0)
    return (year, month)


# Leading "I am a / I'm an / He is a / She is / They are …" subject+verb opener.
_LEAD_SUBJECT_RE = re.compile(
    r"(?i)^\s*(i\s*['’]?\s*a?m|he\s+is|he['’]?s|she\s+is|she['’]?s|they\s+are|they['’]?re)\s+(an?\s+)?")
# Trailing pronoun-bearing aspirational filler clause ("…, seeking a role where I can …").
# Tolerates a trailing period so the final '.' doesn't defeat the end anchor.
_FILLER_CLAUSE_RE = re.compile(
    r"(?i)[;,]\s*(seeking|looking|hoping|aiming|eager|wanting|keen)\b[^.]*\b(i|my|me|we|our)\b[^.]*\.?\s*$")


def _depersonalise(text: str) -> str:
    """
    Strip personal pronouns from a CV summary (LSE guidance: avoid pronouns entirely).
    Conservative — handles the common cases without mangling grammar: removes a leading
    'I am a / He is a …' subject opener and drops a trailing pronoun-bearing aspirational
    filler clause (e.g. '…, seeking a role where I can apply my skills'). Other wording is
    left intact (the prompt is the primary guard; this is the safety net).
    """
    t = (text or "").strip()
    if not t:
        return t
    t = _LEAD_SUBJECT_RE.sub("", t)
    t = _FILLER_CLAUSE_RE.sub("", t).strip()
    if t and t[0].islower():
        t = t[0].upper() + t[1:]
    t = t.rstrip(" ,;")
    if t and t[-1] not in ".!?":
        t += "."
    return t


def _clean_text(text: str) -> str:
    """Strip stray HTML (literal <br>, leftover tags) and collapse whitespace — guards
    against verbose persona fields leaking markup into a rendered description."""
    t = re.sub(r"(?i)<br\s*/?>", " ", text or "")
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _abs_url(url: str) -> str:
    """Ensure a profile link is an absolute URL so it is clickable in the PDF."""
    u = (url or "").strip()
    if not u:
        return ""
    if u.startswith("http://") or u.startswith("https://"):
        return u
    return "https://" + u.lstrip("/")


def _contact_items(contact: dict) -> list[dict]:
    """
    Header contact entries as {text, href?} objects, in the order of the candidate's CV design:
    location and phone as plain text, then the email (a mailto: link) and labelled profile links
    ("LinkedIn" / "GitHub" / "Website") rather than long raw URLs.
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
        items.append({"text": phone})
    if email:
        items.append({"text": email, "href": "mailto:" + email})
    for key, label in (("linkedin", "LinkedIn"), ("github", "GitHub"), ("website", "Website")):
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


def _skill_rows(groups: list) -> list[dict]:
    """
    The CV's skill rows, at most MAX_SKILL_GROUPS of them, without losing a skill: past the limit,
    the extra groups fold into one "Other" row (an existing "Other"-like group absorbs them, last).
    """
    rows = []
    for grp in groups or []:
        items = [str(s).strip() for s in (grp.get("items") or []) if s and str(s).strip()]
        if items:
            rows.append({"category": (grp.get("category") or "Skills").strip() or "Skills", "items": items})
    if len(rows) <= MAX_SKILL_GROUPS:
        return rows
    other = next((r for r in rows if r["category"].lower() in _OTHER_CATEGORIES), None)
    rest = [r for r in rows if r is not other]
    kept, folded = rest[:MAX_SKILL_GROUPS - 1], rest[MAX_SKILL_GROUPS - 1:]
    items, seen = [], set()
    for s in (other["items"] if other else []) + [s for r in folded for s in r["items"]]:
        if s.lower() not in seen:
            seen.add(s.lower())
            items.append(s)
    return kept + [{"category": "Other", "items": items}]


def _first_sentence(text: str) -> str:
    return re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]


# ── template-data builders (apply trimming/defaults) ────────────────────────────

def build_cv_template_data(cv: dict, fit: tuple[str, ...] = ()) -> dict:
    """Render-ready CV data. `fit` is a step from _FIT_STEPS: the layout classes and trims to apply."""
    cv = cv or {}
    skills = _skill_rows(cv.get("skills") or [])
    max_bullets = 3 if "three_bullets" in fit else _MAX_BULLETS

    experience = []
    for role in sorted(cv.get("experience") or [], key=_render_recency, reverse=True)[:_MAX_ROLES]:
        bullets = [b.strip() for b in (role.get("bullets") or []) if b and b.strip()][:max_bullets]
        experience.append({
            "title": (role.get("title") or "").strip(),
            "employer": (role.get("employer") or "").strip(),
            "dates": _role_dates(role),
            "bullets": bullets,
        })

    projects = []
    for p in (cv.get("projects") or [])[:_MAX_PROJECTS]:
        description = _truncate(_clean_text(p.get("description", "")), _MAX_PROJECT_DESC_CHARS)
        # "Name · context" renders the context as a grey subtitle, as in the candidate's CV.
        title, _, subtitle = (p.get("name") or "").partition(" · ")
        projects.append({
            "title": title.strip(),
            "subtitle": subtitle.strip(),
            "description": _first_sentence(description) if "one_sentence" in fit else description,
            "tech": [] if "no_tech" in fit else [t for t in (p.get("tech") or []) if t],
        })

    education = []
    for e in sorted(cv.get("education") or [], key=_render_recency, reverse=True)[:_MAX_EDUCATION]:
        education.append({
            "degree": (e.get("degree") or "").strip(),
            "institution": (e.get("institution") or "").strip(),
            "dates": _role_dates({"start_date": e.get("start_date"), "end_date": e.get("year")}),
            "grade": (e.get("grade") or "").strip(),
        })

    certifications = []
    for c in (cv.get("certifications") or [])[:_MAX_CERTS]:
        certifications.append({
            "name": (c.get("name") or "").strip(),
            "issuer": (c.get("issuer") or "").strip(),
            "year": (c.get("year") or "").strip(),
        })

    # Section order is seniority-aware: juniors follow the candidate's CV design (education first,
    # skills last); experienced candidates lead with experience and keep education near the end.
    # Certifications are listed under Education. Falls back to a sensible inference if unset.
    seniority = (cv.get("seniority") or "").lower()
    if seniority not in ("junior", "experienced"):
        seniority = "junior" if (education and len(experience) <= 1) else "experienced"
    if seniority == "junior":
        sections = ["summary", "education", "experience", "projects", "skills"]
    else:
        sections = ["summary", "experience", "projects", "skills", "education"]

    return {
        "name": (cv.get("name") or "").strip(),
        "headline": (cv.get("headline") or "").strip(),
        "contact_items": _contact_items(cv.get("contact", {})),
        "summary": _truncate(_depersonalise(cv.get("summary", "")), _MAX_SUMMARY_CHARS),
        "skills": skills,
        "experience": experience,
        "projects": projects,
        "education": education,
        "certifications": certifications,
        "seniority": seniority,
        "sections": sections,
        "page_target": _PAGE_TARGET[seniority],
        "body_class": " ".join(s for s in fit if s in _LAYOUT_STEPS),
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


def build_letter_template_data(letter: dict, fit: tuple[str, ...] = ()) -> dict:
    """Render-ready letter data. `fit` is a step from _LETTER_FIT_STEPS: layout classes only."""
    letter = letter or {}
    # Every paragraph is kept (the model may write five, the editor can add more); fitting the
    # letter to one page is _fitted_html's job, which only ever tightens the layout.
    paragraphs = [p.strip() for p in (letter.get("paragraphs") or []) if p and p.strip()]
    return {
        "page_target": 1,
        "body_class": " ".join(fit),
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

@functools.lru_cache(maxsize=1)
def _weasyprint_html():
    """WeasyPrint's HTML class, or None where it can't load (ImportError, or OSError without Pango)."""
    try:
        from weasyprint import HTML
        return HTML
    except Exception:
        return None


def _page_count(html: str) -> int | None:
    """Pages the HTML lays out to in WeasyPrint, or None where WeasyPrint can't load."""
    weasy = _weasyprint_html()
    return None if weasy is None else len(weasy(string=html, base_url=_TEMPLATES_DIR).render().pages)


def _fitted_html(doc_type: str, doc: dict, template: str) -> str:
    """
    The document's HTML at the first fit step (_FIT_STEPS for a CV, _LETTER_FIT_STEPS for a
    letter) that keeps it within its page target, so the preview and the PDF agree. Without
    WeasyPrint to measure with, it's rendered as written.
    """
    tpl = _env.get_template(template)
    if doc_type == "cover_letter":
        steps, build, name = _LETTER_FIT_STEPS, build_letter_template_data, "letter"
    else:
        steps, build, name = _FIT_STEPS, build_cv_template_data, "cv"
    for fit in steps:
        data = build(doc, fit)
        html = tpl.render(**{name: data})
        pages = _page_count(html)
        if pages is None or pages <= data["page_target"]:
            return html
    logger.warning("%s still runs to %d pages (target %d) after every fit step", name, pages, data["page_target"])
    return html


def render_cv_html(cv: dict, template_id: str | None = None) -> str:
    return _fitted_html("cv", cv, registry.resolve(template_id)["cv"])


def render_letter_html(letter: dict, template_id: str | None = None) -> str:
    return _fitted_html("cover_letter", letter, registry.resolve(template_id)["letter"])


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
        # fpdf2 prints the name as the heading; the date, employer and role open the text.
        head = ([data["headline"]] if data["headline"] else []) + [c["text"] for c in data["contact_lines"]]
        recipient = "\n".join(x for x in (data["company"], data["company_location"]) if x)
        subject = f"Re: {data['job_title']}" if data["job_title"] else ""
        body = [x for x in (data["date"], recipient, subject) if x]
        body += [data["salutation"], *data["paragraphs"], data["signoff"], data["candidate_name"]]
        text = "\n".join(head) + "\n\n" + "\n\n".join(body)
        return pdf_generator.generate_pdf("cover_letter", text, {"name": data["candidate_name"]})
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
            lines.append(f"### {p['title']}" + (f" · {p['subtitle']}" if p["subtitle"] else ""))
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

    We log a *missing-dependency* fallback at WARNING (expected in some envs) but a
    template/render failure at ERROR with a traceback — a Jinja or template bug must
    not slip out as a silently unstyled PDF.
    """
    try:
        html = render_html(doc_type, doc, template_id)
    except Exception:
        logger.exception("Template render failed (%s); falling back to fpdf2", doc_type)
        return await asyncio.to_thread(_fallback_pdf, doc_type, doc)

    try:
        return await asyncio.to_thread(_weasyprint_pdf, html)
    except ImportError as exc:
        logger.warning("WeasyPrint unavailable (%s); falling back to fpdf2", exc)
    except Exception:
        logger.exception("WeasyPrint render failed (%s); falling back to fpdf2", doc_type)
    return await asyncio.to_thread(_fallback_pdf, doc_type, doc)
