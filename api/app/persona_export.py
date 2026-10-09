"""
Human-readable Markdown export of a user's Persona ("Digital Twin").

Renders the persona dict (same shape as `models.Persona`) into a clean,
copy-pasteable Markdown document covering every section the profile editor
exposes. Missing/empty fields are skipped so the output stays tidy regardless
of how much of the persona the user has filled in.
"""
from __future__ import annotations


def _full_name(core: dict) -> str:
    name = f"{core.get('first_name', '')} {core.get('last_name', '')}".strip()
    preferred = core.get("preferred_name", "").strip()
    if preferred and preferred not in name:
        name = f"{name} ({preferred})".strip()
    return name


def _date_range(start: str, end: str, ongoing: bool) -> str:
    end_label = "Present" if ongoing else (end or "")
    parts = [p for p in (start, end_label) if p]
    return " – ".join(parts)


def _join(values, sep: str = ", ") -> str:
    if isinstance(values, (list, tuple)):
        return sep.join(str(v) for v in values if str(v).strip())
    return str(values or "")


def persona_to_markdown(persona: dict) -> str:
    """Render a persona dict as a Markdown document."""
    core = persona.get("core_info", {}) or {}
    lines: list[str] = []

    name = _full_name(core) or "Persona Twin"
    lines.append(f"# {name}")
    lines.append("")

    summary = (persona.get("summary") or "").strip()
    if summary:
        lines.append("## Professional Summary")
        lines.append("")
        lines.append(summary)
        lines.append("")

    # ── Core Info ─────────────────────────────────────────────────────────────
    contact_rows: list[tuple[str, str]] = [
        ("Email", core.get("email", "")),
        ("Phone", core.get("phone", "")),
        ("Location", ", ".join(p for p in [core.get("city", ""), core.get("country", "")] if p)),
        ("LinkedIn", core.get("linkedin", "")),
        ("GitHub", core.get("github", "")),
        ("Portfolio", core.get("portfolio", "") or core.get("website", "")),
        ("Visa status", core.get("visa_status", "")),
    ]
    contact_rows = [(k, v) for k, v in contact_rows if str(v).strip()]
    if contact_rows:
        lines.append("## Core Info")
        lines.append("")
        for label, value in contact_rows:
            lines.append(f"- **{label}:** {value}")
        lines.append("")

    # ── Preferences ───────────────────────────────────────────────────────────
    prefs = persona.get("preferences", {}) or {}
    pref_rows: list[tuple[str, str]] = [
        ("Target roles", _join(prefs.get("target_titles", []))),
        ("Min salary", str(prefs.get("min_salary") or "")),
        ("Remote preference", prefs.get("remote_preference", "")),
        ("Preferred locations", _join(prefs.get("preferred_locations", []))),
        ("Industries", _join(prefs.get("industries", []))),
        ("Employment type", prefs.get("employment_type", "")),
        ("Notice period", prefs.get("notice_period", "")),
    ]
    pref_rows = [(k, v) for k, v in pref_rows if str(v).strip()]
    if pref_rows:
        lines.append("## Job Preferences")
        lines.append("")
        for label, value in pref_rows:
            lines.append(f"- **{label}:** {value}")
        lines.append("")

    # ── Skills ────────────────────────────────────────────────────────────────
    skills = persona.get("skills", []) or []
    skill_lines = [
        f"- **{c.get('category', 'Skills')}:** {_join(c.get('skills', []))}"
        for c in skills
        if c.get("skills")
    ]
    if skill_lines:
        lines.append("## Skills")
        lines.append("")
        lines.extend(skill_lines)
        lines.append("")

    # ── Work Experience ───────────────────────────────────────────────────────
    history = persona.get("history", []) or []
    if history:
        lines.append("## Work Experience")
        lines.append("")
        for exp in history:
            title = exp.get("title", "")
            employer = exp.get("employer", "")
            header = " — ".join(p for p in [title, employer] if p) or "Role"
            dates = _date_range(exp.get("start_date", ""), exp.get("end_date", ""), exp.get("is_current", False))
            lines.append(f"### {header}" + (f"  \n*{dates}*" if dates else ""))
            if exp.get("summary"):
                lines.append("")
                lines.append(exp["summary"])
            achievements = exp.get("achievements", [])
            if isinstance(achievements, list):
                for a in achievements:
                    if str(a).strip():
                        lines.append(f"- {a}")
            elif str(achievements).strip():
                lines.append(f"- {achievements}")
            if exp.get("metrics"):
                lines.append(f"- {_join(exp['metrics'])}")
            if exp.get("tech_stack"):
                lines.append(f"- *Tech:* {_join(exp['tech_stack'])}")
            lines.append("")

    # ── Education ─────────────────────────────────────────────────────────────
    education = persona.get("education", []) or []
    if education:
        lines.append("## Education")
        lines.append("")
        for edu in education:
            degree = edu.get("degree", "")
            inst = edu.get("institution", "")
            header = " — ".join(p for p in [degree, inst] if p) or "Education"
            dates = _date_range(edu.get("start_date", ""), edu.get("end_date", ""), edu.get("is_currently_enrolled", False))
            detail = "  \n".join(p for p in [f"*{dates}*" if dates else "", f"Grade: {edu['grade']}" if edu.get("grade") else ""] if p)
            lines.append(f"### {header}" + (f"  \n{detail}" if detail else ""))
            lines.append("")

    # ── Projects ──────────────────────────────────────────────────────────────
    projects = persona.get("projects", []) or []
    if projects:
        lines.append("## Projects")
        lines.append("")
        for p in projects:
            name_p = p.get("name", "Project")
            url = p.get("url")
            lines.append(f"### {name_p}" + (f"  \n{url}" if url else ""))
            desc = p.get("summary") or p.get("problem_solved") or ""
            if desc:
                lines.append("")
                lines.append(desc)
            if p.get("outcomes"):
                lines.append(f"- *Outcomes:* {p['outcomes']}")
            if p.get("technologies"):
                lines.append(f"- *Tech:* {_join(p['technologies'])}")
            lines.append("")

    # ── Certifications ────────────────────────────────────────────────────────
    certs = persona.get("certifications", []) or []
    cert_lines = []
    for c in certs:
        bits = [c.get("name", ""), c.get("issuing_organization", "")]
        label = " — ".join(b for b in bits if b)
        if c.get("issue_date"):
            label += f" ({c['issue_date']})"
        if label.strip():
            cert_lines.append(f"- {label}")
    if cert_lines:
        lines.append("## Certifications")
        lines.append("")
        lines.extend(cert_lines)
        lines.append("")

    # ── Story Bank ────────────────────────────────────────────────────────────
    stories = persona.get("story_bank", []) or []
    if stories:
        lines.append("## Story Bank")
        lines.append("")
        for s in stories:
            lines.append(f"### {s.get('title', 'Story')}")
            if s.get("scenario"):
                lines.append(f"- **Scenario:** {s['scenario']}")
            if s.get("action"):
                lines.append(f"- **Action:** {s['action']}")
            if s.get("result"):
                lines.append(f"- **Result:** {s['result']}")
            if s.get("tags"):
                lines.append(f"- **Tags:** {_join(s['tags'])}")
            lines.append("")

    return "\n".join(lines).strip() + "\n"
