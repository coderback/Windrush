"""
Merging what a source says about the user (a parsed CV, a LinkedIn export, their website or GitHub)
into the persona without overwriting anything the user has entered or edited.
"""
import re
from collections import Counter

from .company_names import normalise_company_name as _normalise_company_name
from .models import (Persona, WorkExperience, Education, Project, Certification, SkillCategory,
                     is_present_end_date)


# Between the two dates of a CV role. Spaced separators first, then en/em dashes, then a bare hyphen,
# so "2020-01 - 2021-03" and "2020-01–2021-06" split between the dates rather than inside the first one.
_DATE_RANGE_SEPS = (re.compile(r"\s+(?:-|–|—|to|till|until)\s+", re.I), re.compile(r"\s*[–—]\s*"),
                    re.compile(r"\s*-\s*"))
# The pieces of an end date that is itself a range or a list of stints.
_END_DATE_PIECES = re.compile(r"[-–—,]|\s+(?:to|till|until)\s+", re.I)


def _split_cv_dates(dates) -> tuple[str, str, bool]:
    """(start_date, end_date, is_current) from a parsed CV role's free-text dates. An end such as
    "Present" or "Now" means the role is current, so it isn't kept as an end date."""
    text = str(dates or "").strip()
    for sep in _DATE_RANGE_SEPS:
        parts = sep.split(text, maxsplit=1)
        if len(parts) == 2:
            start, end = parts[0].strip(), parts[1].strip()
            if is_present_end_date(end):
                return start, "", True
            # "Mid-2019-Present" splits at its first hyphen and "2010 – 2012, 2013 – Present" lists
            # stints: still current when the end's last piece is a present word. The end is kept, as
            # it holds a date the user may want.
            return start, end, is_present_end_date(_END_DATE_PIECES.split(end)[-1].strip())
    return "", "", is_present_end_date(text)


def _norm(text) -> str:
    """Lower-case words only, for matching CV entries to persona ones."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).split())


def _str_list(value) -> list[str]:
    """A model-returned list of strings, cleaned; a lone string becomes a one-item list."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [" ".join(str(v).split()) for v in value if isinstance(v, (str, int, float)) and str(v).strip()]


def _text(value) -> str:
    return " ".join(str(value).split()) if isinstance(value, (str, int, float)) else ""


def _fill(obj, field: str, value) -> None:
    """Set a field only when the persona has nothing in it."""
    if value and not getattr(obj, field):
        setattr(obj, field, value)


def org_key(name) -> str:
    """An employer's or institution's name for matching: no bracketed aside, leading "the", legal suffix,
    case or spacing, so 'Nomensa (via GAIN)' and 'NoMensa' agree, as do 'The University of the West of
    England, Bristol' and 'University of the West of England, Bristol'."""
    words = _normalise_company_name(re.sub(r"\([^)]*\)", " ", str(name or ""))).split()
    if words[:1] == ["the"]:
        words = words[1:]
    return "".join(words)


def project_key(name) -> str:
    """A project's short name, before its tagline: 'Algorender: DSA Visualiser' -> 'algorender'."""
    head = re.split(r"\s*[:·|]\s*|\s+[-–—]\s+", str(name or ""), maxsplit=1)[0]
    return re.sub(r"[^a-z0-9]+", "", head.lower())


def url_key(url) -> str:
    """A link without scheme, www, trailing slash or case, for telling two links to one page apart."""
    url = re.sub(r"^(?:https?://)?(?:www\.)?", "", str(url or "").strip().lower())
    return url.rstrip("/").removesuffix(".git")


def _skill_words(skill) -> str:
    """A skill's name, lower-case, punctuation other than + and # dropped (so 'C' isn't 'C++')."""
    return " ".join(re.sub(r"[^a-z0-9+#]+", " ", str(skill or "").lower()).split())


def has_skill(names, skill: str) -> bool:
    """Whether `skill` is already among `names`: the same name, the same name before a bracketed detail
    ('French' and 'French (limited working)'), or named inside a longer entry ('pandas' in 'Data analysis
    (pandas, NumPy)'), the last only for names of four letters or more so 'Go' isn't found in 'Google Ads'."""
    want = _skill_words(skill)
    base = _skill_words(str(skill).split("(", 1)[0])
    for name in names:
        have = _skill_words(name)
        if have == want or (base and _skill_words(str(name).split("(", 1)[0]) == base)                 or (len(want) >= 4 and f" {want} " in f" {have} "):
            return True
    return False


def _matching_role(history: list[WorkExperience], role: WorkExperience, only_one_at_employer: bool):
    """The persona's entry for a CV role: same employer (legal suffixes ignored) and title, else the
    employer's only entry when the CV also has one role there, so a reworded title still matches."""
    employer = org_key(role.employer)
    same = [h for h in history if org_key(h.employer) == employer]
    titled = next((h for h in same if _norm(h.title) == _norm(role.title)), None)
    return titled or (same[0] if len(same) == 1 and only_one_at_employer else None)


def matching_education(education: list[Education], edu: Education) -> Education | None:
    """The same institution, or one named with its city after it ('University of the West of England' and
    '…, Bristol'): a long name that starts another is taken as the same place."""
    key = org_key(edu.institution)

    def same(other: str) -> bool:
        short, long = sorted((key, org_key(other)), key=len)
        return bool(short) and (short == long or (len(short) >= 12 and long.startswith(short)))
    return next((x for x in education if same(x.institution)), None)


def matching_project(projects: list[Project], proj: Project) -> Project | None:
    """The persona's entry for a project: same name, same link, or the same short name before the
    tagline ('Algorender' and 'Algorender: DSA Visualiser')."""
    key = project_key(proj.name)
    return next((x for x in projects if _norm(x.name) == _norm(proj.name)
                 or (proj.url and url_key(x.url) == url_key(proj.url))
                 or (len(key) >= 4 and project_key(x.name) == key)), None)


def matching_certification(certifications: list[Certification], name: str) -> Certification | None:
    return next((x for x in certifications if _norm(x.name) == _norm(name)), None)


def merge_cv(persona: Persona, cv: dict) -> None:
    """
    Merge a parsed CV into the persona without overwriting anything the user has entered or edited:
    entries the persona lacks (a role, a project, a qualification) are added, and ones it has gain
    only the details they're missing. Re-uploading a CV therefore completes an earlier import.
    """
    core = persona.core_info
    name = _text(cv.get("name")).split()
    _fill(core, "first_name", name[0] if name else "")
    _fill(core, "last_name", " ".join(name[1:]))
    for field, key in (("email", "email"), ("phone", "phone"), ("address_line_1", "address"),
                       ("city", "location"), ("linkedin", "linkedin"), ("github", "github")):
        _fill(core, field, _text(cv.get(key)))
    website = _text(cv.get("website"))
    if "." in website and " " not in website:
        _fill(core, "website", website)
    _fill(persona, "summary", _text(cv.get("summary")))

    # A skill the persona has in any category is kept where it is: the CV's categories needn't match
    # the persona's (an earlier import, or the user, may have grouped them differently).
    have = [s for c in persona.skills for s in c.skills]
    for cat in cv.get("skills") or []:
        # Categorised ({category, skills}); an older flat list of names goes under "Uncategorized".
        category = (_text(cat.get("category")) or "Uncategorized") if isinstance(cat, dict) else "Uncategorized"
        new = []
        for skill in _str_list(cat.get("skills") if isinstance(cat, dict) else cat):
            if not has_skill(have, skill):
                have.append(skill)
                new.append(skill)
        if not new:
            continue
        target = next((c for c in persona.skills if c.category.lower() == category.lower()), None)
        if target is None:
            persona.skills.append(SkillCategory(category=category, skills=new))
        else:
            target.skills.extend(new)

    roles = [r for r in cv.get("experience") or [] if isinstance(r, dict) and (r.get("employer") or r.get("title"))]
    per_employer = Counter(org_key(_text(r.get("employer"))) for r in roles)
    for r in roles:
        start, end, current = _split_cv_dates(r.get("dates"))
        role = WorkExperience(employer=_text(r.get("employer")), title=_text(r.get("title")),
                              start_date=start, end_date=end, is_current=current, summary=_text(r.get("summary")),
                              achievements=_str_list(r.get("achievements")), tech_stack=_str_list(r.get("tech_stack")))
        match = _matching_role(persona.history, role, per_employer[org_key(role.employer)] == 1)
        if match is None:
            persona.history.append(role)
            continue
        for field in ("summary", "achievements", "tech_stack"):
            _fill(match, field, getattr(role, field))
        if not (match.start_date or match.end_date):
            match.start_date, match.end_date, match.is_current = start, end, current

    for e in cv.get("education") or []:
        if not isinstance(e, dict) or not _text(e.get("institution")):
            continue
        dates = _text(e.get("dates"))
        start, end, current = _split_cv_dates(dates)
        if not (start or end or current):
            end = dates  # a lone year is when the course ended
        edu = Education(institution=_text(e.get("institution")), degree=_text(e.get("degree")), start_date=start,
                        end_date=end, grade=_text(e.get("grade")), is_currently_enrolled=current)
        match = matching_education(persona.education, edu)
        if match is None:
            persona.education.append(edu)
            continue
        for field in ("degree", "grade"):
            _fill(match, field, getattr(edu, field))
        if not (match.start_date or match.end_date):
            match.start_date, match.end_date, match.is_currently_enrolled = start, end, current

    for p in cv.get("projects") or []:
        if not isinstance(p, dict) or not _text(p.get("name")):
            continue
        proj = Project(name=_text(p.get("name")), url=_text(p.get("url")) or None,
                       problem_solved=_text(p.get("description")), outcomes=_text(p.get("outcomes")),
                       technologies=_str_list(p.get("technologies")))
        match = matching_project(persona.projects, proj)
        if match is None:
            persona.projects.append(proj)
            continue
        for field in ("url", "problem_solved", "outcomes", "technologies"):
            _fill(match, field, getattr(proj, field))

    for c in cv.get("certifications") or []:
        cert_name = _text(c.get("name")) if isinstance(c, dict) else ""
        if cert_name and not matching_certification(persona.certifications, cert_name):
            persona.certifications.append(Certification(
                name=cert_name, issuing_organization=_text(c.get("issuer")), issue_date=_text(c.get("date")),
                credential_id=_text(c.get("credential_id")), credential_url=_text(c.get("url"))))
