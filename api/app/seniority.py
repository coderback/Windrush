"""
Seniority of a job listing: "junior", "mid" or "senior".

The title decides when it says so, matching whole words, strongest signal first:
  1. unmistakably senior   — "Senior …", "Principal …", "Head of …", "… Director"
  2. unmistakably junior   — "Graduate …", "… Interns", "Junior …", "Apprenticeships"
  3. associate / "… I"     — "Associate Product Manager", "Software Engineer I", "SDE I"
  4. lead / manager        — "Engineering Manager", "Tech Lead"
so "Associate Director" is senior and "Graduate Project Manager" is junior. Before matching, words
that are not a rank are dropped: places and team names ("Head Office", "Principal Investments",
"Lead Generation", "Staff Nurse", "… - Office of the CTO") and the scheme word in the job title of
the people who run a scheme ("Early Careers Manager" is a manager, "Placement Officer" is mid).

A neutral title falls back to the description. Its headline years of experience — the largest
lower bound it asks for, "5+ years" or "Experience: 2-4 years"; months round down to years; more
than 15 is company age, not the role's bar — gives senior at 5+ and mid at 3-4, overriding any
junior wording. Otherwise 0-1 years, or graduate-scheme / entry-level wording that is neither
negated ("not an entry-level role") nor a duty ("mentor recent graduates"), gives junior; anything
else is mid.
"""
import re

# Senior-looking words that name a place, a team or a non-senior job, and "office of the CTO" /
# "reporting to the Head of X" clauses, whose rank is someone else's.
_NOT_A_RANK = re.compile(
    r"\bhead[ -]?(?:offices?|quarters)\b|\bprincipal investments?\b|\blead[ -]gen(?:eration)?\b"
    r"|\bstaff(?= (?:accountants?|nurses?|auditors?)\b)|\b(?:office of|reporting to)\b.*"
)
# The scheme word in the title of someone who runs a scheme: "Apprenticeship Manager",
# "Graduate Recruitment Partner", "Internship Program Coordinator". A person word ("Graduate")
# straight before manager / lead is still the trainee: "Graduate Manager".
_SCHEME = r"(?:apprenticeships?|internships?|placements?|early careers?)"
_PERSON = r"(?:graduates?|grads?|interns?|apprentices?)"
_SCHEME_TEAM = (r"(?:programmes?|programs?|schemes?|recruitment|recruiting|talent|acquisition|outreach|"
                r"attraction|hiring|engagement|relations)")
_STAFF = (r"(?:recruiters?|partners?|officers?|assessors?|co-?ordinators?|advis[eo]rs?|administrators?|"
          r"tutors?|trainers?|coaches?)")
_STAFF_OR_LEAD = rf"(?:{_STAFF}|managers?|leads?|heads?|directors?|specialists?)"
_PROGRAMME_STAFF = re.compile(
    rf"\b(?:{_SCHEME}|{_PERSON})(?=(?: {_SCHEME_TEAM}){{1,2}} {_STAFF_OR_LEAD}\b)"
    rf"|\b{_SCHEME}(?= {_STAFF_OR_LEAD}\b)|\b{_PERSON}(?= {_STAFF}\b)"
)

_STRONG_SENIOR = re.compile(r"\b(senior|sr|principal|staff|head|director|vp|vice president|chief)\b")
_STRONG_JUNIOR = re.compile(
    r"\b(junior|jr|graduates?|grads?|entry[ -]level|interns?|internships?|apprentices?|apprenticeships?|"
    r"trainees?|placements?|new grads?|early careers?|industrial year|year in industry)\b"
)
_WEAK_JUNIOR = re.compile(
    r"\bassociate\b"
    # "Software Engineer I" / "SDE 1" — the first rung of a numbered ladder, but not "I/II" or "1-2".
    r"|\b(?:engineer|developer|analyst|scientist|consultant|swe|sde) (?:i|1)\b"
    r"(?! ?[-/–] ?(?:i{1,3}|iv|v|\d)\b)"
)
_WEAK_SENIOR = re.compile(r"\b(lead|manager|architect)\b")

_JUNIOR_DESCRIPTION = re.compile(
    r"\b(graduate (?:scheme|programme|program|role|position)|recent graduates?|new grads?|"
    r"entry[\s-]level|no (?:prior |previous )?(?:professional |commercial )?experience (?:is )?(?:required|needed)|"
    r"early careers? (?:programme|program)|final[\s-]year students?)\b"
)
# Searched in the ~25 characters before a junior phrase, within its clause. A duty is the role's
# ("you will mentor recent graduates"), not the company's ("we run a graduate scheme").
_NEGATED = re.compile(r"(?:\b(?:not|no|never|cannot|unsuitable)\b|n['’]t\b)[^.,!?;:•|]*$")
_DUTY = re.compile(
    r"(?<!\bwe )\b(?:mentor|coach|support|onboard|train|supervis|manag|lead|run|recruit|hir|teach|guid|"
    r"oversee|develop)(?:e|es|s|ed|ing|ning)? (?:(?:our|the|a|an|its|their|your|this|these) )*$"
)

_NUMBER_WORDS = {w: i for i, w in enumerate(
    "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen".split(), 1)}
# Not part of a bigger figure ("100 years" is not 0, "150 years" is not 50, "2.5" is not 5).
_NUMBER = r"(?:(?<![\d.,])\d{1,2}(?!\d)|\b(?:" + "|".join(_NUMBER_WORDS) + r")\b)"
# "5 years", "5+ yrs", "5 or more years", "2-4 years'", "three to five years", "6 months". Text is
# whitespace-collapsed first and each optional space is followed by its own literal, so a long run of
# spaces cannot make the engine backtrack.
_AMOUNT = (
    rf"(?P<n>{_NUMBER})(?: ?\+| plus| or more)?(?: ?(?:-|–|—|to) ?{_NUMBER}\+?)?"
    r" ?(?P<unit>years?|yrs?|months?)['’]?"
)
# "3+ years of non-internship professional software development experience", "at least five
# years' experience", "a minimum of 7 years commercial experience"
_AMOUNT_THEN_EXPERIENCE = re.compile(_AMOUNT + r"(?: [\w'’/-]+){0,5}? experience")
# "Experience: 5+ years", "Experience required: 3 years", "experience of at least 5 years"
_EXPERIENCE_THEN_AMOUNT = re.compile(
    r"\bexperience(?: [a-z]+){0,2}(?: ?[:–—-] ?| (?=at least |a minimum |minimum |min\b))"
    r"(?:at least |a minimum of |minimum (?:of )?|min\.? )?" + _AMOUNT
)


def _years_required(d: str) -> int | None:
    """The headline years of experience the description asks for, or None if it names none."""
    needs = []
    for pattern in (_AMOUNT_THEN_EXPERIENCE, _EXPERIENCE_THEN_AMOUNT):
        for m in pattern.finditer(d):
            n = m["n"]
            years = int(n) if n.isdigit() else _NUMBER_WORDS[n]  # a range counts from its lower bound
            if m["unit"].startswith("month"):
                years //= 12
            if years <= 15:  # more is company age or a team's combined experience
                needs.append(years)
    # The largest: "5+ years of engineering, 1+ year of AWS" is a 5-year role.
    return max(needs, default=None)


def _has_junior_wording(d: str) -> bool:
    for m in _JUNIOR_DESCRIPTION.finditer(d):
        start = max(0, m.start() - 25)
        if not (_NEGATED.search(d, start, m.start()) or _DUTY.search(d, start, m.start())):
            return True
    return False


def infer_level(title: str, description: str = "") -> str:
    t = " ".join((title or "").split()).lower()
    t = _PROGRAMME_STAFF.sub("", _NOT_A_RANK.sub("", t))
    for pattern, level in ((_STRONG_SENIOR, "senior"), (_STRONG_JUNIOR, "junior"),
                           (_WEAK_JUNIOR, "junior"), (_WEAK_SENIOR, "senior")):
        if pattern.search(t):
            return level

    d = " ".join((description or "").split()).lower()
    need = _years_required(d)
    if need is not None and need >= 5:
        return "senior"
    if need is not None and need >= 3:
        return "mid"
    if (need is not None and need <= 1) or _has_junior_wording(d):
        return "junior"
    return "mid"
