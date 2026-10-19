"""
Application questions: how Windrush answers what a job application form asks.

answer_questions() answers each question from one of these places, and says which (`source`):
  saved     - the answer bank: what the user answered or approved on an earlier form (tracker.answer_bank);
  profile   - a fact in the persona: right to work, notice period, nationality, a degree, a role's dates…;
  drafted   - a written answer (why this role, a time you…, a project) drafted for this job from the
              persona, its stories and saved written answers, and checked for claims the persona doesn't
              back. Drafts are for the user to read before anything is sent;
  needs_you - a fact that neither the bank nor the persona states. It is never guessed: the form leaves it
              blank, and once the user answers it the answer is saved for the next form.

A model reads the questions, since their wording varies endlessly, and says which known fact answers
each. Code then checks that reading before anything goes on a form: an answer must cite a fact, be one of
the form's options, keep a yes/no fact's polarity, and not carry a UK fact to another country. Contact
details, salary and equality-monitoring answers never reach the model: it sees only that the fact exists,
and the value is filled in from the persona.
"""
import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime

from . import agent, doc_check, tracker
from .models import is_present_end_date

logger = logging.getLogger("windrush.answers")

SOURCES = ("saved", "profile", "drafted", "needs_you")

_MAX_QUESTIONS = 40     # one form page rarely has more; a call with more is cut, not refused
_MAX_OPTIONS = 1000     # a nationality dropdown lists every country; a university one, 350 UK institutions
_MAX_DETAILS = 800      # the start of a statement under a question says what it is about
_DRAFTS_AT_ONCE = 4


# ── Questions, normalised ──────────────────────────────────────────────────────────────────────

_KEY_NOISE = re.compile(r"\((?:required|optional)\)|\*", re.I)
# A dropdown's prompt or hint, not a choice: "Select...", "Please choose", "--", "You can choose more than one".
_PLACEHOLDER = re.compile(
    r"^\W*(?:please\s+)?(?:select|choose|pick)\b|^\W*$|^\W*you\s+(?:can|may)\s+(?:select|choose|pick)\b|"
    r"^\W*(?:start typing|type to search|no options)\b", re.I)


def question_key(question: str) -> str:
    """The question as matched against saved ones: lower case, without punctuation or 'required' marks."""
    text = _KEY_NOISE.sub(" ", str(question or "").lower())
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _norm(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def mentions(name: str, text: str) -> bool:
    """Whether `text` names `name` (a company), as whole words."""
    name = _norm(name)
    return bool(name) and re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", _norm(text)) is not None


def _clean_questions(questions) -> list[dict]:
    out, seen = [], set()
    for raw in (questions or [])[:_MAX_QUESTIONS]:
        if isinstance(raw, str):
            raw = {"question": raw}
        if not isinstance(raw, dict):
            continue
        text = " ".join(str(raw.get("question") or "").split())[:500]
        key = question_key(text)
        if not key or key in seen:
            continue
        seen.add(key)
        options = [" ".join(str(o).split())[:200] for o in raw.get("options") or []
                   if not _PLACEHOLDER.search(str(o))][:_MAX_OPTIONS]
        limit = raw.get("max_length")
        question = {"question": text, "options": options,
                    "max_length": int(limit) if isinstance(limit, (int, float)) and limit > 0 else None}
        # The text the form shows with it: a bare "GDPR Statement" says what it asks only there.
        details = " ".join(str(raw.get("details") or "").split())[:_MAX_DETAILS]
        if details:
            question["details"] = details
        # A plain form field ("School") rather than a question: only the user's own answer to that very
        # field fills it, never the model.
        if raw.get("saved_only"):
            question["saved_only"] = True
        out.append(question)
    return out


# ── What Windrush knows: facts from the persona and the answer bank ────────────────────────────

@dataclass(frozen=True)
class Fact:
    id: str
    label: str              # what the fact is about: "Right to work / work authorisation in the UK"
    value: str              # its answer as a form takes it: "Yes", "2 weeks", "British"
    private: bool = False   # the value never goes into a model prompt
    source: str = "profile"     # "saved" for answer-bank entries
    uk: bool = False        # only says something about the UK (right to work, sponsorship)
    yes_no: bool = False
    bank_id: str = ""
    # A line of several details (a degree with its dates and grade, every skill): an answer may take a part
    # of it, but it never goes on the form whole in place of what the question asked.
    summary: bool = False


# (section, field, label, about the UK only). Unanswered (None) ones are left out entirely, so nothing
# is ever stated that the user hasn't told us.
_YES_NO_FACTS = (
    ("core_info", "right_to_work_uk", "Right to work / work authorisation in the UK", True),
    ("core_info", "require_sponsorship", "Require visa sponsorship to work in the UK, now or in the future", True),
    ("core_info", "has_government_ties", "Has government ties", False),
    ("core_info", "holds_other_nationality", "Currently holds another (dual) nationality or citizenship", False),
    ("core_info", "held_other_nationality", "Previously held another nationality or citizenship", False),
    ("preferences", "relocation_willingness", "Willing to relocate", False),
    ("preferences", "can_work_in_person", "Can work in-person", False),
    ("preferences", "can_start_immediately", "Can start immediately", False),
    ("preferences", "has_reliable_transportation", "Has reliable transportation", False),
    ("preferences", "needs_accommodations", "Needs adjustments or accommodations", False),
)

# (field, label, private)
_CORE_TEXT_FACTS = (
    ("first_name", "First name", False),
    ("last_name", "Last name", False),
    ("preferred_name", "Preferred name", False),
    ("email", "Email address", True),
    ("phone", "Phone number", True),
    ("address_line_1", "Street address", True),
    ("postcode", "Postcode", True),
    ("city", "Town or city where they live", False),
    ("country", "Country where they live", False),
    ("linkedin", "LinkedIn profile URL", False),
    ("github", "GitHub profile URL", False),
    ("twitter", "Twitter / X profile", False),
    ("portfolio", "Portfolio URL", False),
    ("website", "Personal website URL", False),
    ("visa_status", "Visa details / immigration status in full: the visa, when it ends, what it allows and any "
                    "sponsorship needed later (their own words)", False),
    ("visa_type", "Visa type (the visa's name only)", False),
    # The label's words may phrase an answer joined with the type ("Graduate visa, valid until 11/2027").
    ("visa_expiry", "Visa expiry date: when it expires, valid until (month/year)", False),
    ("nationality", "Nationality", False),
    ("security_clearance", "Security clearance held", False),
    ("dob", "Date of birth", True),
)

# An address's facts, in the order a form writes them.
_ADDRESS_PARTS = ("address_line_1", "city", "postcode", "country")

_DISABILITY = {"yes": "Yes", "no": "No", "prefer_not_to_say": "Prefer not to say"}
_DECLINE = "Prefer not to say"

# A year (19xx/20xx) in a role's end date: the role has actually ended — unless a present word is
# in it too, as when "Mid-2019-Present" splits at its first hyphen or a CV lists stints ("Nov 2012,
# Dec 2012 – Present").
_END_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_PRESENT_WORD = re.compile(r"\b(?:present|current(?:ly)?|now|ongoing|today|(?:to|till|until)\s+date)\b", re.I)

# A degree's qualification, around its subject: "BSc (Hons) Computer Science", "Bachelor of Science in Physics",
# "Economics BA", "MEng Mechanical Engineering".
_QUALIFICATION = (r"(?:[BM]\.?(?:Sc|A|Eng|Ed|Arch|Phil|Res|Math|Comp|Mus|Des)\.?|Ph\.?D\.?|D\.?Phil|LL\.?[BM]\.?|MBA|BBA|"
                  r"HN[CD]|(?:Integrated\s+)?(?:Bachelor|Master|Doctor)(?:'?s)?(?:\s+of\s+(?:Science|Arts|Engineering|"
                  r"Philosophy|Laws|Education|Music))?(?:\s+degree)?|Foundation\s+degree|Hons|Honours)")
_QUALIFICATION_AT = re.compile(rf"^\s*{_QUALIFICATION}(?![\w.])\.?\s*(?:(?:in|of)\s+)?|\s+{_QUALIFICATION}\.?\s*$", re.I)


def degree_subject(degree: str) -> str:
    """The subject a degree is in ("Computer Science" from "BSc (Hons) Computer Science"); "" when the degree
    doesn't name its qualification, so the subject can't be told from it."""
    whole = " ".join(re.sub(r"\([^)]*\)", " ", degree or "").split())
    subject = whole
    while (shorter := _QUALIFICATION_AT.sub("", subject, count=1).strip(" ,-–")) != subject:
        subject = shorter
    return subject if subject != whole else ""


def _has_ended(end_date) -> bool:
    end = str(end_date or "")
    return bool(_END_YEAR.search(end)) and not _PRESENT_WORD.search(end)


_MONTHS = {m: n for n, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                       "dec"), 1)}


def _end_month(end_date) -> tuple[int, int] | None:
    """(year, month) an end date names: "11/2025", "2025-11", "Nov 2025"; a bare year is its December. None
    without a year, or with a present word in it."""
    end = str(end_date or "")
    year = _END_YEAR.search(end)
    if not year or _PRESENT_WORD.search(end):
        return None
    numeric = re.search(r"(?<!\d)(0?[1-9]|1[0-2])\s*[/.-]\s*(?:19|20)\d{2}|(?:19|20)\d{2}\s*[/.-]\s*(0?[1-9]|1[0-2])(?!\d)",
                        end)
    named = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", end, re.I)
    month = int(numeric.group(1) or numeric.group(2)) if numeric else _MONTHS[named.group(1).lower()] if named else 12
    return int(year.group()), month


def _birth_date(raw: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %B %Y", "%d %b %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _age(born: date, today: date) -> int:
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def _dates(entry: dict, start: str, end: str, current: str) -> str:
    finish = "Present" if entry.get(current) else (entry.get(end) or "")
    span = " – ".join(p for p in (entry.get(start) or "", finish) if p)
    return f" ({span})" if span else ""


def profile_facts(persona: dict, today: date | None = None) -> list[Fact]:
    """Every fact the persona states that a form might ask for, as the answer a form takes."""
    core = persona.get("core_info") or {}
    prefs = persona.get("preferences") or {}
    screening = persona.get("screening") or {}
    diversity = persona.get("diversity") or {}
    sections = {"core_info": core, "preferences": prefs}
    facts: list[Fact] = []

    def add(fact_id, label, value, **kw):
        value = " ".join(str(value or "").split())
        if value:
            facts.append(Fact(fact_id, label, value, **kw))

    add("full_name", "Full name", " ".join(p for p in (core.get("first_name"), core.get("last_name")) if p))
    for field, label, private in _CORE_TEXT_FACTS:
        add(field, label, core.get(field), private=private)
    for section, field, label, uk in _YES_NO_FACTS:
        value = sections[section].get(field)
        if isinstance(value, bool):
            facts.append(Fact(field, label, "Yes" if value else "No", uk=uk, yes_no=True))
    # The details only follow a "Yes": text left over from an earlier answer says nothing.
    if core.get("holds_other_nationality") is True:
        add("other_nationalities", "Other current nationalities / citizenships", core.get("other_nationalities"))
    if core.get("held_other_nationality") is True:
        add("previous_nationalities", "Previously held nationalities / citizenships", core.get("previous_nationalities"))
    born = _birth_date(str(core.get("dob") or "")) if core.get("dob") else None
    if born:
        facts.append(Fact("over_18", "Is 18 or older", "Yes" if _age(born, today or date.today()) >= 18 else "No",
                          yes_no=True))

    if prefs.get("remote_preference"):
        add("remote_preference", "Preferred work setting (remote / hybrid / on-site)", prefs["remote_preference"])
    add("preferred_locations", "Preferred work locations",
        ", ".join(loc for loc in prefs.get("preferred_locations") or [] if loc))
    add("notice_period", "Notice period", screening.get("notice_period_canonical") or prefs.get("notice_period"))
    # Salary is the candidate's call (a figure, a range, "Negotiable"): with none in the profile it is
    # left for them rather than answered for them.
    add("salary_annual", "Salary expectations (Annual)", screening.get("salary_canonical") or prefs.get("min_salary"),
        private=True)
    add("salary_hourly", "Salary expectations (Hourly)", prefs.get("expected_hourly_rate"), private=True)

    # Declining to answer is always a true statement, so it's the fallback for equality monitoring.
    add("gender", "Gender (equality monitoring)", diversity.get("gender") or _DECLINE, private=True)
    add("ethnicity", "Ethnicity (equality monitoring)", diversity.get("ethnicity") or _DECLINE, private=True)
    add("disability", "Disability (equality monitoring)",
        _DISABILITY.get(diversity.get("disability_status") or "", _DECLINE), private=True)
    add("veteran_status", "Veteran status (equality monitoring)", diversity.get("veteran_status") or _DECLINE,
        private=True)
    add("sexual_orientation", "Sexual orientation (equality monitoring)",
        diversity.get("sexual_orientation") or _DECLINE, private=True)

    # Parsed CVs often leave is_current off and put "Present" (or nothing) in end_date, so "No" needs
    # every role to have really ended — an end date with a year in it; anything less certain is left
    # for the user (an end date we don't recognise may still mean "present").
    history = [job for job in persona.get("history") or [] if isinstance(job, dict)]
    current = [job for job in history if job.get("is_current") or is_present_end_date(job.get("end_date"))]
    if current:
        facts.append(Fact("currently_employed", "Are you currently employed", "Yes", yes_no=True))
        add("current_employer", "Current employer", current[0].get("employer"))
        add("current_title", "Current job title", current[0].get("title"))
    elif history and all(_has_ended(job.get("end_date")) for job in history):
        facts.append(Fact("currently_employed", "Are you currently employed", "No", yes_no=True))
    for i, job in enumerate(history):
        add(f"role_{i + 1}", "Work history", f"{job.get('title', '')} at {job.get('employer', '')}"
            + _dates(job, "start_date", "end_date", "is_current"), summary=True)
    # Left to the model, "already graduated" was read off a degree's end date on some runs and not on others. "Yes"
    # needs every degree to have finished: not enrolled, with an end date that has passed. "No" needs one still
    # going. Anything less certain (an end date still to come but not marked as enrolled) is left out.
    education = [e for e in persona.get("education") or [] if isinstance(e, dict)]
    ends = [_end_month(e.get("end_date")) for e in education]
    now = (today or date.today()).timetuple()[:2]
    if any(e.get("is_currently_enrolled") or is_present_end_date(e.get("end_date")) for e in education):
        facts.append(Fact("graduated", "Has already graduated (finished their studies)", "No", yes_no=True))
    elif education and all(end and end < now for end in ends):
        last = max(ends)
        facts.append(Fact("graduated", f"Has already graduated (finished their studies, last in {last[1]:02d}/{last[0]})",
                          "Yes", yes_no=True))
    for i, edu in enumerate(education):
        grade = f", {edu['grade']}" if edu.get("grade") else ""
        add(f"education_{i + 1}", "Education", f"{edu.get('degree', '')} at {edu.get('institution', '')}"
            + _dates(edu, "start_date", "end_date", "is_currently_enrolled") + grade, summary=True)
        # On its own, as a form asks for it ("Undergrad Discipline(s)", "Subject", "Major"): the education line
        # names it only inside the degree, and the model didn't always take it from there.
        add(f"education_{i + 1}_subject", f"Subject / discipline / major of their {edu.get('degree', '')} at "
            f"{edu.get('institution', '')}", degree_subject(edu.get("degree", "")))
    skills = [s for group in persona.get("skills") or [] for s in group.get("skills") or []]
    add("skills", "Skills", ", ".join(dict.fromkeys(skills)), summary=True)
    certs = [f"{c.get('name', '')} ({c.get('issuing_organization', '')})".replace(" ()", "")
             for c in persona.get("certifications") or [] if c.get("name")]
    add("certifications", "Certifications held", "; ".join(certs), summary=True)
    # How they heard about a job isn't in the persona: it's the user's to say, and the answer bank keeps it.
    return facts


def bank_facts(bank: list[dict], company: str = "") -> list[Fact]:
    """Saved fact answers this form may reuse: general ones, and those saved for this employer."""
    facts = []
    for n, entry in enumerate(e for e in bank if e.get("kind") == "fact" and _bank_applies(e, company)):
        about = f" (for {entry['company']})" if entry.get("company") else ""
        facts.append(Fact(f"saved_{n + 1}", f"Saved answer to “{entry['question']}”{about}", entry["answer"],
                          source="saved", yes_no=_polarity(entry["answer"]) is not None
                          and len(_norm(entry["answer"]).split()) == 1, bank_id=entry["id"]))
    return facts


def _bank_applies(entry: dict, company: str) -> bool:
    return not entry.get("company") or _norm(entry["company"]) == _norm(company)


# ── Reading answers against a question ─────────────────────────────────────────────────────────

_YES = {"yes", "y", "true"}
_NO = {"no", "n", "false"}


def _polarity(text: str) -> bool | None:
    """True for an answer that starts 'Yes', False for 'No', None for anything else."""
    words = _norm(text).split()
    if not words:
        return None
    return True if words[0] in _YES else False if words[0] in _NO else None


_NEGATED = re.compile(r"\b(?:not|without|never|unable|no longer|neither|nor)\b|n['’]t\b", re.I)
_DECLINE_RE = re.compile(r"prefer not|rather not|decline|don['’]?t wish|do not wish|not to (?:say|disclose|answer)", re.I)


def _in_options(answer: str, options: list[str]) -> str | None:
    """The option `answer` names, compared without case or punctuation."""
    wanted = _norm(answer)
    return next((o for o in options if _norm(o) == wanted), None) if wanted else None


def pick_option(value: str, options: list[str]) -> str | None:
    """The one option that states `value`, or None when no option or more than one does."""
    if not options:
        return value
    v = _norm(value)
    if not v:
        return None
    normed = [(_norm(o), o) for o in options]
    exact = [o for n, o in normed if n == v]
    if exact:
        return exact[0]
    pol = _polarity(v)
    if pol is not None and len(v.split()) == 1:
        same = [o for n, o in normed if _polarity(n) is pol]
        return same[0] if len(same) == 1 else None
    if _DECLINE_RE.search(value):
        declines = [o for n, o in normed if _DECLINE_RE.search(o)]
        return declines[0] if len(declines) == 1 else None
    for match in (lambda n: n.startswith(v + " ") or v.startswith(n + " "),
                  lambda n: f" {v} " in f" {n} " or f" {n} " in f" {v} "):
        found = [o for n, o in normed if n and match(n)]
        if len(found) == 1:
            return found[0]
        if found:
            break
    return _covering_option(value, options)


_OPTION_STOP = {"the", "of", "and", "a", "an", "in", "at", "for", "to", "or", "on"}


def _option_words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", str(text or "").lower())) - _OPTION_STOP


def _initials(value: str) -> dict[str, set[str]]:
    """{initials: the words they stand for} for each comma-separated part of `value` of two or more words:
    'University of the West of England' → {'uwe': {'university', 'west', 'england'}}."""
    out = {}
    for part in str(value).split(","):
        words = [w for w in re.findall(r"[a-z0-9]+", part.lower()) if w not in _OPTION_STOP]
        if len(words) >= 2:
            out["".join(w[0] for w in words)] = set(words)
    return out


def _covering_option(value: str, options: list[str]) -> str | None:
    """
    When no option states `value` outright: the one option holding every word of it, with the fewest other
    words ('Black African' → 'Black (including African American, African, …)'; 'Bristol, United Kingdom' →
    'Bristol, England, United Kingdom', not 'Little Bristol, England, …'), or the one option inside the value
    that covers most of it. "University of Bristol" sits word for word in "The University of the West of
    England, Bristol" and is a different university, so it doesn't count; initials stand for their words, so
    "Bristol, UWE" does. None when that isn't one option.
    """
    v = _option_words(value)
    if not v:
        return None
    holding = sorted((len(_option_words(o) - v), o) for o in options if v <= _option_words(o))
    if holding:
        return holding[0][1] if len(holding) == 1 or holding[0][0] < holding[1][0] else None
    initials = _initials(value)
    scored = []
    for o in options:
        words = _option_words(o)
        if len(words) < 2 or not words <= v | set(initials):
            continue
        covered = set().union(*(initials.get(w, {w}) for w in words)) & v
        if len(covered) / len(v) >= 0.75:
            scored.append((len(covered) / len(v), o))
    scored.sort()
    return scored[-1][1] if scored and (len(scored) == 1 or scored[-1][0] > scored[-2][0]) else None


_AMOUNT = re.compile(r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*(k\b|thousand\b)?", re.I)
_OPEN_TOP = re.compile(r"\+|\b(?:above|over|more than|or more|plus|at least|minimum)\b", re.I)
_OPEN_BOTTOM = re.compile(r"\b(?:up to|under|below|less than|or less|max(?:imum)?)\b", re.I)


def _money_range(text: str) -> tuple[float, float] | None:
    """The amounts a salary answer or band states, as (low, high): "£30k-£35k", "£35,000+", "Up to £25,000"."""
    amounts = [float(n.replace(",", "")) * (1000 if unit else 1) for n, unit in _AMOUNT.findall(text)]
    if not amounts:
        return None
    if len(amounts) >= 2:
        return min(amounts[:2]), max(amounts[:2])
    if _OPEN_TOP.search(text):
        return amounts[0], float("inf")
    if _OPEN_BOTTOM.search(text):
        return 0.0, amounts[0]
    return amounts[0], amounts[0]


def pick_band(value: str, options: list[str]) -> str | None:
    """The one salary band that holds the whole of `value` ("£31,500" is in "£30,000-£35,000"); None when no
    band or more than one does (31,500 on a band boundary, a range that straddles two, "Negotiable")."""
    wanted = _money_range(value)
    if not wanted:
        return None
    holding = [o for o in options if (band := _money_range(o)) and band[0] <= wanted[0] and wanted[1] <= band[1]]
    return holding[0] if len(holding) == 1 else None


_UK_RE = re.compile(r"\b(?:uk|u\.k\.|united kingdom|great britain|britain|british|england|english|scotland|"
                    r"scottish|wales|welsh|northern ireland|gb)\b", re.I)
# Bare "us" counts only in capitals ("the US"): "tell us", "join us".
_US_RE = re.compile(r"\bUS\b")
_ELSEWHERE_RE = re.compile(
    r"\b(?:u\.s\.a?\.?|usa|united states|america|american|canada|canadian|ireland|irish|republic of ireland|"
    r"eu|e\.u\.|european union|eea|europe|european|schengen|australia|australian|new zealand|india|indian|"
    r"germany|german|france|french|netherlands|dutch|spain|spanish|italy|italian|switzerland|swiss|singapore|"
    r"hong kong|japan|china|uae|united arab emirates|dubai|israel|poland|sweden|denmark|norway|finland|belgium|"
    r"austria|portugal|brazil|mexico|south africa|nigeria|kenya|h-?1b|green card)\b", re.I)


# Job locations outside the UK that name no country: big tech cities, and US "City, ST" addresses.
_ELSEWHERE_PLACE_RE = re.compile(
    r"(?i:\b(?:new york|nyc|san francisco|bay area|seattle|boston|austin|chicago|los angeles|denver|toronto|"
    r"vancouver|montreal|berlin|munich|paris|amsterdam|dublin|madrid|barcelona|lisbon|stockholm|copenhagen|"
    r"zurich|warsaw|sydney|melbourne|bangalore|bengaluru|tokyo|tel aviv)\b)|,\s*[A-Z]{2}\b(?!\s*\w)")


def about_uk(question: str, job_location: str = "") -> bool:
    """Whether a UK fact can answer this question: it names the UK, or names no country and the job isn't
    elsewhere. A job with no location, or a remote one, is taken to be in the UK, where Windrush searches."""
    def elsewhere(text):
        return bool(_ELSEWHERE_RE.search(text) or _US_RE.search(text))
    if _UK_RE.search(question):
        return True
    if elsewhere(question):
        return False
    location = job_location or ""
    if _UK_RE.search(location):
        return True
    return not (elsewhere(location) or _ELSEWHERE_PLACE_RE.search(location))


_STOP = {"a", "an", "the", "of", "in", "at", "and", "or", "to", "for", "with", "on", "i", "am", "have", "has",
         "my", "is", "be", "s", "it", "as"}


def _supported(answer: str, facts: list[Fact]) -> bool:
    """A free-text answer the model wrote from shown facts may only use their words, and a yes or no."""
    source = set(re.findall(r"[a-z0-9]+", " ".join(f"{f.label} {f.value}" for f in facts).lower()))
    return set(re.findall(r"[a-z0-9]+", answer.lower())) - _STOP - _YES - _NO <= source


# A question that asks for something other than a yes or no: "What year did you graduate?", "Please provide
# your ideal start date", "If yes, please give your visa type".
_ASKS_FOR_CONTENT = re.compile(
    r"^(?:if\b[^,?]*,\s*)?(?:please\s+)?(?:what|when|which|where|who|whose|why|how|provide|give|list|describe|"
    r"enter|specify|explain|tell|name|add)\b|^(?:if\b[^,?]*,\s*)?(?:please\s+)?state\b(?!\s+whether)", re.I)
# An option that says no option fits: no fact ever states one.
_NONE_FITS = re.compile(r"^\W*(?:other\b|none of the above|not listed|n/?a\W*$)", re.I)


def _parts(value: str) -> list[str]:
    """The things a summary fact names: each skill, a role's title and employer, a degree and its university."""
    return [p for p in re.split(r"[,;]|\sat\s", re.sub(r"\([^)]*\)", " ", value)) if _norm(p)]


# A degree's level, as a form's options name it ("Bachelor's Degree") and as a degree line does ("BSc (Hons)").
_LEVELS = (
    (re.compile(r"\bbachelor", re.I), re.compile(r"\b(?:B\.?(?:Sc|A|Eng|Ed|Arch|Mus|Des)\.?|Bachelor)\b", re.I)),
    (re.compile(r"\bmaster", re.I), re.compile(r"\b(?:M\.?(?:Sc|A|Eng|Res|Phil|Math|Comp)\.?|MBA|Master)\b", re.I)),
    (re.compile(r"\b(?:doctor|ph\.?d)", re.I), re.compile(r"\b(?:Ph\.?D|D\.?Phil|Doctor)\b", re.I)),
)


def _names_option(option: str, cited: list[Fact], options: list[str]) -> bool:
    """
    Whether the cited facts name this option. A summary fact (a degree, a role, the skills) only does when the option
    is in it word for word ("Computer Science", "2025"), one of its parts picks it from the form's options ("The
    University of the West of England" is "Bristol, UWE"), or it's the degree's level. On DV Trading the model chose
    "University of Bristol" for a degree at the University of the West of England, Bristol: every word of it is in
    the education line.
    """
    wanted = f" {_norm(option)} "
    for fact in cited:
        if not fact.summary:
            return True
        if wanted.strip() and wanted in f" {_norm(fact.value)} ":
            return True
        # Neighbouring parts together too: the institution is "The University of the West of England, Bristol".
        # Each run holds a part of two words or more, so "Bristol" alone never picks an option.
        parts = _parts(fact.value)
        runs = [", ".join(parts[i:j]) for i in range(len(parts)) for j in range(i + 1, len(parts) + 1)
                if any(len(_norm(p).split()) >= 2 for p in parts[i:j])]
        if any(pick_option(run, options) == option for run in runs):
            return True
        if any(level.search(option) and degree.search(fact.value) for level, degree in _LEVELS):
            return True
    return False


def _says_yes_or_no(answer: str, cited: list[Fact], question: str) -> bool:
    """
    Whether the cited facts can give this answer's yes or no. A yes/no fact or a saved answer can. A list of
    skills, roles or degrees says yes only to a thing it names that the question names too ("experience in
    Python?" from skills that list Python), and leaving something off a CV never says no.
    """
    polarity = _polarity(answer)
    if polarity is None:
        return True
    if any(f.yes_no or f.source == "saved" or _polarity(f.value) is polarity for f in cited):
        return True
    return polarity and any(mentions(part, question) for f in cited if f.summary for part in _parts(f.value))


def resolve_fact(question: dict, reading: dict, facts: dict[str, Fact], job_location: str = "") -> tuple[str, list[Fact]] | None:
    """
    The answer to a fact question that a model's `reading` ({fact_ids, answer}) supports, with the facts
    it rests on — or None when it can't be trusted, which leaves the question for the user.
    """
    cited = [facts[i] for i in reading.get("fact_ids") or [] if isinstance(i, str) and i in facts]
    if not cited:
        return None
    text, options = question["question"], question["options"]
    if any(f.uk for f in cited) and not about_uk(text, job_location):
        return None
    said = str(reading.get("answer") or "").strip()
    first = cited[0]

    if not options and len(cited) > 1 and {f.id for f in cited} <= set(_ADDRESS_PARTS) and \
            any(f.private for f in cited):
        # "Address" read as the street, town and postcode together: put together here, as the model never saw them.
        by_id = {f.id: f.value for f in cited}
        return ", ".join(by_id[part] for part in _ADDRESS_PARTS if part in by_id), cited

    if len(cited) == 1 and first.private:
        # The model never saw the value, so it can only have said which fact applies. A salary goes in the band
        # that holds it.
        if first.id.startswith("salary_") and any(_money_range(o) for o in options):
            answer = pick_band(first.value, options)
        else:
            answer = pick_option(first.value, options)
        return (answer, cited) if answer else None

    if options:
        answer = _in_options(said, options)
        if answer is None and said and _polarity(said) is None and _supported(said, cited):
            # What the facts say, in other words than the form's: "The University of the West of England" is
            # "Bristol, UWE".
            answer = pick_option(said, options)
        if answer is None and len(cited) == 1:
            answer = pick_option(first.value, options)
        # "Other" says no option states the fact; a saved answer may still have chosen it.
        if answer is None or (_NONE_FITS.search(answer) and not any(f.source == "saved" for f in cited)):
            return None
        if _polarity(answer) is None and not _names_option(answer, cited, options):
            return None
    elif said:
        answer = said
        if not _supported(said, cited):
            # Only the yes or no is backed, or else the fact's own value, when that is the whole answer.
            if _polarity(said) is not None:
                answer = "Yes" if _polarity(said) else "No"
            elif len(cited) == 1 and not first.summary:
                answer = first.value
            else:
                return None
    else:
        if len(cited) != 1 or first.summary:
            return None
        answer = first.value

    # A yes or no doesn't answer "Please provide your ideal start date".
    if not options and _polarity(answer) is not None and _ASKS_FOR_CONTENT.search(text):
        return None
    if not _says_yes_or_no(answer, cited, text):
        return None

    # A yes/no fact keeps its polarity unless the question turns it round ("…without sponsorship?").
    if len(cited) == 1 and first.yes_no and not _NEGATED.search(text):
        if _polarity(answer) is not None and _polarity(answer) != _polarity(first.value):
            return None
    return answer, cited


# ── The model's reading of the questions ───────────────────────────────────────────────────────

_READ_SYSTEM = (
    "You read the questions on a job application form for one candidate and match each to the facts Windrush "
    "holds about them. You never answer from general knowledge, from what is typical, or by guessing; only by "
    "a plain reading of the facts.\n"
    "For each question decide its kind:\n"
    "- \"written\": it asks the candidate to write in their own words: why they want the role or to join the "
    "company, their interest, experience, skills or achievements, a time they did something, a project, "
    "strengths, goals, or anything else they'd like to add.\n"
    "- \"fact\": anything else: eligibility, right to work, visas, status, availability, notice, salary, "
    "preferences, contact details, education, work history, how they heard about the job (and its details), a "
    "number, a choice between options about them, equality monitoring, consent or a declaration.\n"
    "For a \"fact\" give fact_ids, the ids of the facts that state the answer, and answer, the answer they give "
    "in the form's terms: when options are listed, exactly one option copied word for word. If no fact states "
    "it, fact_ids is [] and answer is \"\". A question may come with what the form says with it (a statement or "
    "a hint): read the question as that text explains it. Rules:\n"
    "- A fact about one country never answers a question about another. The job's location is given for "
    "questions about 'this country' or 'the country where this role is based'.\n"
    "- A fact marked (private) has its value hidden: cite its id when it is the fact asked for, and leave "
    "answer \"\"; Windrush fills in the value.\n"
    "- Don't compute or estimate: years of experience, counts, grades or dates are answered only by a fact "
    "that states them. The one exception: a salary question whose options are bands or ranges is answered by "
    "the salary expectations fact; cite it and Windrush picks the band that holds the figure.\n"
    "- Read the question's direction: 'Will you require sponsorship?' and 'Can you work without "
    "sponsorship?' take opposite answers from the same fact.\n"
    "- Answer just what is asked, taken from the fact: the year from a degree's dates, not the whole degree "
    "line; 'Immediately' for a start date when the candidate can start immediately, never 'Yes'.\n"
    "- When the question asks for more than the facts state (a visa's type and its expiry date, when only the "
    "type is known), or only applies in a case the facts don't show ('If you hold a US visa…'), "
    "fact_ids is [].\n"
    "- Never choose 'Other' or 'None of the above': no fact states one.\n"
    "- A declaration or consent (a privacy notice, that the information is accurate, background or reference "
    "checks, criminal convictions, conflicts of interest) is answered only by a saved answer to it, or to the "
    "same consent in other words: a saved consent to their personal data being processed for recruitment "
    "answers a privacy or GDPR statement about processing their application data for recruitment. A saved "
    "acknowledgement of one named document (a company's disclosure or policy) answers only that document.\n"
    'Return ONLY JSON: {"answers": [{"n": int, "kind": "fact" | "written", "fact_ids": [str], "answer": str}]} '
    "with one entry per question."
)


def _fact_lines(facts: list[Fact]) -> str:
    return "\n".join(f"- {f.id}: {f.label} (private)" if f.private else f"- {f.id}: {f.label}: {f.value}"
                     for f in facts)


def _question_lines(questions: list[dict]) -> str:
    lines = []
    for n, q in enumerate(questions, 1):
        line = f"{n}. {q['question']}"
        if q.get("details"):
            line += "\n   the form says with it: " + q["details"]
        if q["options"]:
            line += "\n   options: " + " | ".join(q["options"])
        lines.append(line)
    return "\n".join(lines)


async def _read(questions: list[dict], facts: list[Fact], job: dict) -> dict[int, dict]:
    """The model's reading of each question, by its 1-based position; {} if the call failed."""
    data = await agent._llm_json(
        system=_READ_SYSTEM,
        user=(f"JOB: {job.get('title', '')} at {job.get('company', '')}, located in: "
              f"{job.get('location') or 'not stated'}\n\nFACTS:\n{_fact_lines(facts)}\n\n"
              f"QUESTIONS:\n{_question_lines(questions)}"),
        max_tokens=4000, label="read_questions")
    readings = {}
    for item in (data or {}).get("answers") or []:
        if isinstance(item, dict) and isinstance(item.get("n"), int) and item.get("kind") in ("fact", "written"):
            ids = item.get("fact_ids")
            readings[item["n"]] = {"kind": item["kind"], "fact_ids": ids if isinstance(ids, list) else [],
                                   "answer": str(item.get("answer") or "")}
    return readings


# ── Written answers ────────────────────────────────────────────────────────────────────────────

_WORD_LIMIT = re.compile(r"(\d{2,4})\s*(?:-\s*\d{2,4}\s*)?words?\b", re.I)
_CHAR_LIMIT = re.compile(r"(\d{2,5})\s*(?:characters|chars)\b", re.I)


def _limits(question: dict) -> tuple[int | None, int | None]:
    """(max words, max characters) the question or its text box sets. A box limit equal to the question's word
    limit is that word limit read as characters (the fill agent did so in a live run), so it's ignored."""
    words = _WORD_LIMIT.search(question["question"])
    max_words = int(words.group(1)) if words else None
    chars = _CHAR_LIMIT.search(question["question"])
    box = question.get("max_length")
    if box is not None and box == max_words:
        box = None
    max_chars = min(filter(None, [int(chars.group(1)) if chars else None, box]), default=None)
    return max_words, max_chars


def _length_rule(max_words: int | None, max_chars: int | None) -> str:
    if max_chars:
        return f"at most {max_chars} characters including spaces (aim for about {int(max_chars * 0.85)})"
    if max_words:
        return f"at most {max_words} words (aim for about {max(20, int(max_words * 0.85))})"
    return "80-150 words"


def _fit(text: str, max_words: int | None, max_chars: int | None) -> str:
    """Cut an answer that runs over its limit at the last whole sentence that fits."""
    def fits(t):
        return (not max_chars or len(t) <= max_chars) and (not max_words or len(t.split()) <= max_words)
    if fits(text):
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text)
    while len(sentences) > 1 and not fits(" ".join(sentences)):
        sentences.pop()
    kept = " ".join(sentences)
    if not fits(kept):
        kept = kept[:max_chars] if max_chars else " ".join(kept.split()[:max_words])
    return kept.strip()


def _similar(question: str, entries: list[dict], limit: int = 3) -> list[dict]:
    want = set(question_key(question).split()) - _STOP
    scored = []
    for e in entries:
        have = set(question_key(e["question"]).split()) - _STOP
        overlap = len(want & have) / max(1, len(want | have))
        if overlap >= 0.2:
            scored.append((overlap, e))
    return [e for _, e in sorted(scored, key=lambda s: -s[0])[:limit]]


_WRITE_SYSTEM = (
    "You write one candidate's answer to one question on a job application form: first person, plain UK "
    "English, as the candidate would write it. Use ONLY facts in the candidate data, their saved answers and "
    "their cover letter: never invent a number, technology, employer, project, result or experience, and "
    "never claim more than the data says. Answer the question in the first sentence, then back it with one or "
    "two specific pieces of evidence (a named project, role or story and its real result). For a behavioural "
    "question ('a time when…'), tell one story from the story bank in situation, task, action, result order, "
    "without those labels. For why this role or company, tie what the advert says this team "
    "does to the candidate's own experience, so that no other company's name could replace this one. Where a "
    "saved answer fits, keep its substance and adapt it to this job. Length: {length}. No greeting, sign-off, "
    "headings or bullet points. Don't use these words: {banned}. "
    'Return ONLY JSON: {{"answer": str}}'
)


async def _write(question: dict, persona: dict, job: dict, cover_letter: str, saved: list[dict],
                 fix: str = "", draft: str = "") -> str:
    max_words, max_chars = _limits(question)
    user = (f"QUESTION: {question['question']}\n\n"
            f"JOB: {job.get('title', '')} at {job.get('company', '')}\n"
            f"ADVERT: {(job.get('description') or '')[:3000]}\n\n"
            + ("SAVED ANSWERS TO SIMILAR QUESTIONS:\n"
               + "\n".join(f"- {e['question']}: {e['answer']}" for e in saved) + "\n\n" if saved else "")
            + (f"COVER LETTER FOR THIS JOB:\n{cover_letter[:3000]}\n\n" if cover_letter.strip() else "")
            + f"CANDIDATE DATA (JSON): {json.dumps(agent._llm_persona(persona), ensure_ascii=False)}")
    if fix:
        user = f"YOUR DRAFT:\n{draft}\n\nFIX ONLY THESE ISSUES, keeping everything else:\n{fix}\n\n" + user
    data = await agent._llm_json(
        system=_WRITE_SYSTEM.format(length=_length_rule(max_words, max_chars),
                                    banned=", ".join(doc_check.BANNED_WORDS)),
        user=user, max_tokens=2000, label="revise_answer" if fix else "write_answer")
    answer = (data or {}).get("answer")
    return " ".join(answer.split()) if isinstance(answer, str) else ""


def _findings(answer: str, persona: dict, job: dict, extra_source: str) -> list[dict]:
    doc = {"paragraphs": [answer]}
    return (doc_check.check_facts("cover_letter", doc, persona, job, extra_source)
            + doc_check.check_style("cover_letter", doc))


async def draft_answer(question: dict, persona: dict, job: dict, cover_letter: str = "",
                       saved: list[dict] | None = None) -> tuple[str, list[str]]:
    """A written answer for this job, and what the document check still flags in it. One revision runs
    when the check flags something, and is kept only if it clears findings without adding any."""
    saved = saved or []
    extra = "\n".join([cover_letter] + [e["answer"] for e in saved])
    answer = await _write(question, persona, job, cover_letter, saved)
    if not answer:
        return "", []
    found = _findings(answer, persona, job, extra)
    if found:
        revised = await _write(question, persona, job, cover_letter, saved,
                               fix=agent._issue_lines(found), draft=answer)
        if revised:
            after = _findings(revised, persona, job, extra)
            if agent._better(found, after):
                answer, found = revised, after
    max_words, max_chars = _limits(question)
    return _fit(answer, max_words, max_chars), [f"{f['label']}: {f['message']}" for f in found]


# ── Answering a form's questions ───────────────────────────────────────────────────────────────

def _result(question: dict, kind: str, source: str, answer: str = "", because: str = "",
            bank_id: str = "", flags: list[str] | None = None) -> dict:
    return {"question": question["question"], "options": question["options"], "kind": kind, "source": source,
            "answer": answer if source != "needs_you" else "", "because": because, "bank_id": bank_id,
            "flags": flags or []}


def _saved_match(question: dict, bank: list[dict], company: str) -> dict | None:
    """The saved answer to this very question, preferring one saved for this employer."""
    key = question_key(question["question"])
    matches = [e for e in bank if e.get("question_key") == key and _bank_applies(e, company)]
    return max(matches, key=lambda e: bool(e.get("company")), default=None)


def _because(facts: list[Fact]) -> str:
    def one(f):
        if f.source == "saved":
            return f.label
        return f"Your profile: {f.label}" + ("" if f.private else f" = {f.value}")
    return "; ".join(one(f) for f in facts)


async def answer_questions(questions, persona: dict, bank: list[dict], job: dict, cover_letter: str = "") -> list[dict]:
    """
    Answers for a form's questions, in order: each {question, options, kind ('fact' | 'written'), source (one
    of SOURCES), answer ('' when needs_you), because (what it rests on), bank_id, flags (what the document
    check still flags in a draft)}. `questions` are {question, options?, max_length?} or plain strings.
    """
    questions = _clean_questions(questions)
    company = job.get("company", "")
    results: list[dict | None] = [None] * len(questions)

    # The very question answered before: reused as saved, when it fits the form's options.
    for i, q in enumerate(questions):
        entry = _saved_match(q, bank, company)
        if entry:
            answer = pick_option(entry["answer"], q["options"]) if entry["kind"] == "fact" else entry["answer"]
            if not answer and q.get("saved_only"):
                # A searchable list shows only its first results (DV Trading's School: 100 of thousands, "Other"
                # among them only once typed): the field's own search finds the saved answer, so it goes as saved.
                answer = entry["answer"]
            if answer:
                results[i] = _result(q, entry["kind"], "saved", answer, f"Saved answer to “{entry['question']}”",
                                     entry["id"])
    for i, q in enumerate(questions):
        if results[i] is None and q.get("saved_only"):
            results[i] = _result(q, "fact", "needs_you", "", "No saved answer to this field")

    pending = [i for i, r in enumerate(results) if r is None]
    if not pending:
        return results
    facts = profile_facts(persona) + bank_facts(bank, company)
    by_id = {f.id: f for f in facts}
    readings = await _read([questions[i] for i in pending], facts, job)

    written = []
    for n, i in enumerate(pending, 1):
        q, reading = questions[i], readings.get(n)
        if reading is None:
            # Unread (the model call failed): nothing is stated for it.
            results[i] = _result(q, "fact", "needs_you", because="Windrush couldn't read this question")
        elif reading["kind"] == "written":
            written.append(i)
        else:
            resolved = resolve_fact(q, reading, by_id, job.get("location", ""))
            if resolved:
                answer, rests_on = resolved
                saved = next((f for f in rests_on if f.source == "saved"), None)
                results[i] = _result(q, "fact", "saved" if saved else "profile", answer, _because(rests_on),
                                     saved.bank_id if saved else "")
            else:
                results[i] = _result(q, "fact", "needs_you", because="Nothing you've saved says this")

    saved_written = [e for e in bank if e.get("kind") == "written" and _bank_applies(e, company)]
    gate = asyncio.Semaphore(_DRAFTS_AT_ONCE)

    async def draft(i):
        async with gate:
            q = questions[i]
            similar = _similar(q["question"], saved_written)
            try:
                answer, flags = await draft_answer(q, persona, job, cover_letter, similar)
            except Exception as exc:
                logger.warning("drafting an answer failed: %s", exc)
                answer, flags = "", []
            if not answer:
                return _result(q, "written", "needs_you", because="Windrush couldn't draft this one")
            basis = (f"Drafted for this job from your persona and saved answers to “{similar[0]['question']}”"
                     if similar else "Drafted for this job from your persona")
            return _result(q, "written", "drafted", answer, basis, similar[0]["id"] if similar else "", flags)

    for i, result in zip(written, await asyncio.gather(*(draft(i) for i in written))):
        results[i] = result
    return results


# ── The answer bank ────────────────────────────────────────────────────────────────────────────

def save(user_id: str, question: str, answer: str, kind: str = "fact", company: str = "") -> dict:
    """Save (or replace) the user's answer to a question. It is kept for one employer only when the question
    or the answer names that employer ("Why do you want to join Acme?"), so other forms never reuse it."""
    question = " ".join(str(question or "").split())
    answer = str(answer or "").strip()
    if not question_key(question) or not answer:
        raise ValueError("a question and an answer are both needed")
    if kind not in tracker.ANSWER_KINDS:
        raise ValueError(f"kind must be one of {tracker.ANSWER_KINDS}")
    company = company.strip() if company and mentions(company, f"{question}\n{answer}") else ""
    return tracker.save_answer(user_id, question, question_key(question), answer, kind, company)
