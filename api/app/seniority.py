"""
Seniority of a job listing: "junior", "mid" or "senior".

The title decides when it says so, matching whole words, strongest signal first:
  1. unmistakably senior   — "Senior …", "Principal …", "Head of …", "… Director"
  2. unmistakably junior   — "Graduate …", "… Intern", "Junior …", "Apprentice …"
  3. associate / "… I"     — "Associate Product Manager", "Software Engineer I"
  4. lead / manager        — "Engineering Manager", "Tech Lead"
so "Associate Director" is senior and "Graduate Project Manager" is junior. A neutral title
falls back to the description: graduate-scheme / entry-level wording, then the years of
experience it asks for.
"""
import re

_STRONG_SENIOR = re.compile(r"\b(senior|sr|principal|staff|head|director|vp|vice president|chief)\b")
_STRONG_JUNIOR = re.compile(
    r"\b(junior|jr|graduate|grad|entry[\s-]level|intern|internship|apprentice|apprenticeship|trainee|"
    r"placement|new grad|early careers?|industrial year|year in industry)\b"
)
_WEAK_JUNIOR = re.compile(
    r"\bassociate\b"
    # "Software Engineer I" / "Analyst 1" — the first rung of a numbered ladder.
    r"|\b(?:engineer|developer|analyst|scientist|consultant)\s+(?:i|1)\b(?!\s*(?:i|[-/]))"
)
_WEAK_SENIOR = re.compile(r"\b(lead|manager|architect)\b")

_JUNIOR_DESCRIPTION = re.compile(
    r"\b(graduate (?:scheme|programme|program|role|position)|recent graduates?|new grads?|"
    r"entry[\s-]level|no (?:prior |previous )?(?:professional |commercial )?experience (?:is )?(?:required|needed)|"
    r"early careers? (?:programme|program)|final[\s-]year students?)\b"
)
# "3+ years of experience", "2-4 years' experience", "5 years commercial experience"
_YEARS = re.compile(
    r"(\d{1,2})\s*(?:\+|plus)?\s*(?:(?:-|–|to)\s*\d{1,2}\s*)?\+?\s*years?['’]?\s*(?:of\s+)?"
    r"(?:\w+\s+){0,4}?experience"
)


def infer_level(title: str, description: str = "") -> str:
    t = (title or "").lower()
    for pattern, level in ((_STRONG_SENIOR, "senior"), (_STRONG_JUNIOR, "junior"),
                           (_WEAK_JUNIOR, "junior"), (_WEAK_SENIOR, "senior")):
        if pattern.search(t):
            return level

    d = (description or "").lower()
    if _JUNIOR_DESCRIPTION.search(d):
        return "junior"
    years = [int(m.group(1)) for m in _YEARS.finditer(d)]
    if years:
        need = min(years)  # the lowest bar the listing sets
        if need >= 5:
            return "senior"
        if need <= 1:
            return "junior"
    return "mid"
