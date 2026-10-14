"""
Seniority of a job listing: "junior", "mid" or "senior".

The title decides when it says so, matching whole words, strongest signal first:
  1. unmistakably senior   — "Senior …", "Principal …", "Head of …", "… Director"
  2. unmistakably junior   — "Graduate …", "… Interns", "Junior …", "Apprenticeships"
  3. associate / "… I"     — "Associate Product Manager", "Software Engineer I", "SDE I"
  4. lead / manager        — "Engineering Manager", "Tech Lead"
so "Associate Director" is senior and "Graduate Project Manager" is junior. Before matching, words
that are not this role's rank are dropped:
  - places, teams and job names ("Head Office", "Principal Investments", "Lead Generation", "Staff
    Nurse"), and an "Office of the CTO" / "reporting to the Head of X" phrase up to the next separator
    (" - ", ",", ":", brackets …), so "Office of the CTO - Senior Engineer" is still senior;
  - the scheme word in the title of someone who runs a scheme ("Apprenticeship Manager", "Placement
    Officer", "Graduate Recruitment Partner", "Graduate Recruiter"). A graduate or apprentice doing
    any other job is still the trainee: "Graduate Administrator", "Graduate Manager".

A neutral title falls back to the description:
  1. Years of experience asked of the candidate. "5+ years (of) … experience" and "Experience: 2-4
     years" count from their lower bound ("between 2 and 5"; "up to 2" is 0; months round down; more
     than 15 is company age). A figure does not count when it is someone else's — the nearest subject
     before it in its clause is the employer or its people ("we have", "our", "a firm with", "engineers
     have", "learn from", "mentored by", "alongside") rather than the candidate ("you", "someone",
     "candidates", "looking for", "must"), or it opens "With 10 years of experience, we …" — or is a
     span of time ("graduated in the last 3 years"). Figures marked preferred / desirable / a plus /
     ideally count only when no required one does. The largest gives senior at 5+, mid at 3-4 and
     junior at 0-1, whatever the wording.
  2. Otherwise junior wording ("graduate scheme", "recent graduates", "entry-level", "no experience
     required") gives junior, unless a negation governs it ("not an entry-level role", "not suitable
     for recent graduates", but not "sponsorship is not available for this graduate role") or it is
     the role's own duty ("you will mentor recent graduates", "help onboard new grads", but not "we
     are hiring recent graduates").
  3. Anything else is mid.
"""
import re
from bisect import bisect_right

# Senior-looking words that name a place, a team or a non-senior job, and "office of the CTO" /
# "reporting to the Head of X" phrases, whose rank is someone else's. The phrase stops at the next
# separator so that "Office of the CTO - Senior Engineer" keeps its own rank.
_NOT_A_RANK = re.compile(
    r"\bhead[ -]?(?:offices?|quarters)\b|\bprincipal investments?\b|\blead[ -]gen(?:eration)?\b"
    r"|\bstaff(?= (?:accountants?|nurses?|auditors?)\b)"
    r"|\b(?:office of|reporting to)\b(?:(?! [-/] )[^,:;()\[\]|–—])*"
)
# The scheme word in the title of someone who runs a scheme: "Apprenticeship Manager",
# "Graduate Recruitment Partner", "Internship Program Coordinator", "Graduate Recruiter". A person
# word before any other job is the trainee doing it: "Graduate Administrator", "Graduate Manager".
_SCHEME = r"(?:apprenticeships?|internships?|placements?|early careers?)"
_PERSON = r"(?:graduates?|grads?|interns?|apprentices?)"
_SCHEME_TEAM = (r"(?:programmes?|programs?|schemes?|recruitment|recruiting|talent|acquisition|outreach|"
                r"attraction|hiring|engagement|relations|skills)")
_STAFF_OR_LEAD = (r"(?:recruiters?|partners?|officers?|assessors?|co-?ordinators?|advis[eo]rs?|administrators?|"
                  r"tutors?|trainers?|coach(?:es)?|managers?|leads?|heads?|directors?|specialists?)")
_PROGRAMME_STAFF = re.compile(
    rf"\b(?:{_SCHEME}|{_PERSON})(?=(?: {_SCHEME_TEAM}){{1,2}} {_STAFF_OR_LEAD}\b)"
    rf"|\b{_SCHEME}(?= {_STAFF_OR_LEAD}\b)|\b{_PERSON}(?= (?:recruiters?|assessors?)\b)"
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
    r"\b(graduate (?:schemes?|programmes?|programs?|roles?|positions?)|recent graduates?|new grads?|"
    r"entry[\s-]level|no (?:prior |previous )?(?:professional |commercial )?experience (?:is )?"
    r"(?:required|needed|necessary)|experience: none|early careers? (?:programmes?|programs?)|"
    r"final[\s-]year students?)\b"
)
# A negation that governs the junior phrase straight after it: "not an entry-level role", "no
# graduates or entry-level applicants", "not suitable for recent graduates", "unable to consider
# recent graduates". "Sponsorship is not available for this graduate role" and "this isn't your
# average graduate scheme" negate something else.
_NEGATED = re.compile(
    r"(?:\b(?:not|no|never|cannot|unable to|unsuitable)|n['’]t)"
    r"(?: (?:suitable|open|intended|aimed|meant)(?: for| to| at)| for| to"
    r"| (?:consider|accept|suit|hire|recruit|take|welcome)\w*)?"
    r"(?: (?:a|an|the|any))?(?: [\w-]+ or)? $"
)
# A junior phrase that is the object of a duty: "mentor recent graduates", "supporting our graduate
# programme", "recruit new grads". Not a hyphenated adjective ("market-leading") or a participle
# ("fully supported").
_DUTY_OBJECT = re.compile(
    r"(?<![\w-])(?:(?P<coaching>mentor|coach|support|onboard|train|supervis|manag|lead|run|teach|guid|"
    r"oversee|develop)|recruit|hir)(?:e|es|s|ing|ning)?(?: (?:our|the|a|an|its|their|your|this|these))* $"
)
# The role is the one doing it: "you will …", "you'll be …", "responsible for …".
_ROLE_SUBJECT = re.compile(r"\byou\b|\bresponsible for\b")

_NUMBER_WORDS = {w: i for i, w in enumerate(
    "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen".split(), 1)}
# Not part of a bigger figure ("100 years" is not 0, "150 years" is not 50, "2.5" is not 5).
_NUMBER = r"(?:(?<![\d.,])\d{1,2}(?!\d)|\b(?:" + "|".join(_NUMBER_WORDS) + r")\b)"
# "5 years", "5+ yrs", "5 or more years", "2-4 years'", "between two and five years", "up to 2
# years", "6 months". Text is whitespace-collapsed first and each optional space is followed by its
# own literal, so a long run of spaces cannot make the engine backtrack.
_AMOUNT = (
    rf"(?P<up_to>up to )?(?P<n>{_NUMBER})(?: ?\+| plus| or more)?(?: ?(?:-|–|—|to|and) ?{_NUMBER}\+?)?"
    r" ?(?P<unit>years?|yrs?|months?)['’]?"
)
# A pronoun or preposition between the figure and "experience" means they are not one phrase:
# "3 years you'll gain experience", "after 3 years based on experience".
_GAP_STOP = r"(?:you|your|we|our|they|their|it|its|in|on|at|for|from|with|by|as|after|to)(?![\w-])"
# "3+ years of non-internship professional software development experience", "at least five
# years' experience", "a minimum of 7 years commercial experience" — but not "Programme length: 3
# years / Experience: none", where "Experience:" starts the next field.
_AMOUNT_THEN_EXPERIENCE = re.compile(
    _AMOUNT + rf"(?: of)?(?: (?!{_GAP_STOP})[\w'’/-]+){{0,4}}? experience(?! ?:)"
)
# "Experience: 5+ years", "Experience required: 3 years", "experience of at least 5 years"
_EXPERIENCE_THEN_AMOUNT = re.compile(
    r"\bexperience(?: [a-z]+){0,2}(?: ?[:–—-] ?| (?=at least |a minimum |minimum |min\b))"
    r"(?:at least |a minimum of |minimum (?:of )?|min\.? )?" + _AMOUNT
)

# Whose experience a figure is: the candidate's, or the employer's and its people's. The last of
# these before a figure in its clause decides.
_SUBJECT = re.compile(
    r"\b(?:(?P<candidate>you(?:rs?|rself)?|someone|somebody|candidates?|applicants?|individuals?|"
    r"looking for|seek\w*|requir\w*|need\w*|want\w*|expect\w*|must|should|ideal\w*)"
    r"|we|our|they|their|its|firm|company|agency|alongside|[a-z]+s ha(?:ve|d)"
    r"|(?:learn\w*|mentored|coached|supported|trained|taught|guided|led|managed)(?: \w+)? (?:from|by))\b"
)
_OPENER = re.compile(r" ?with\b")
_TIME_SPAN = re.compile(r"\b(?:after|(?:in|within|during|over) the (?:last|past|next|first)) $")
# A figure marked as optional: in its sentence before it ("Nice to have: 3+ years") or in its clause
# after it ("5 years experience preferred").
_SOFT = re.compile(
    r"\b(?:ideally|preferabl[ey]|preferred|desirable|desired|nice to have|bonus|a plus|advantageous|"
    r"an advantage|beneficial)(?![\w-])"
)

# Where clauses and sentences end. Not at a bracket: "5+ years of experience (preferred)".
_CLAUSE_END = re.compile(r"[.!?;:,•|]| [-–—] ")
_SENTENCE_END = re.compile(r"[.!?;•|]")
_REACH = 80  # how far back a clause is read


def _starts(pattern: re.Pattern, d: str) -> list[int]:
    """Where each clause (or sentence) of d starts: 0 and the end of every boundary."""
    return [0, *(m.end() for m in pattern.finditer(d))]


def _start_of(starts: list[int], i: int) -> int:
    """Where the clause holding position i starts, at most _REACH characters back."""
    return max(starts[bisect_right(starts, i) - 1], i - _REACH)


def _end_of(starts: list[int], i: int) -> int:
    """Where the clause after position i starts."""
    k = bisect_right(starts, i)
    return starts[k] if k < len(starts) else i + _REACH


def _any_in(positions: list[int], lo: int, hi: int) -> bool:
    """Whether any of the sorted positions is in [lo, hi)."""
    k = bisect_right(positions, lo - 1)
    return k < len(positions) and positions[k] < hi


def _years(m: re.Match) -> int:
    """A figure's lower bound in whole years: "2-4 years" is 2, "up to 2 years" 0, "18 months" 1."""
    n = m["n"]
    years = 0 if m["up_to"] else int(n) if n.isdigit() else _NUMBER_WORDS[n]
    return years // 12 if m["unit"].startswith("month") else years


def _years_required(d: str, clauses: list[int]) -> int | None:
    """The headline years of experience the description asks for, or None if it names none."""
    figures = [(_years(m), m) for pattern in (_AMOUNT_THEN_EXPERIENCE, _EXPERIENCE_THEN_AMOUNT)
               for m in pattern.finditer(d)]
    if not figures:
        return None
    # Found once for the whole text, so each figure costs a few lookups rather than a scan.
    sentences = _starts(_SENTENCE_END, d)
    subjects = list(_SUBJECT.finditer(d))
    subject_ends = [s.end() for s in subjects]
    softs = [m.start() for m in _SOFT.finditer(d)]

    def asked_of_candidate(m: re.Match) -> bool:
        clause = _start_of(clauses, m.start())
        if _TIME_SPAN.search(d, max(clause, m.start() - 20), m.start()):
            return False
        k = bisect_right(subject_ends, m.start()) - 1
        if k >= 0 and subjects[k].start() >= clause:  # the nearest subject before it in its clause
            return bool(subjects[k]["candidate"])
        if not _OPENER.match(d, clause):
            return True
        # "With over 10 years of experience in fintech, we …": the subject comes after the figure.
        after = subjects[k + 1] if k + 1 < len(subjects) else None
        return bool(after and after.start() < _end_of(sentences, m.end()) and after["candidate"])

    def is_soft(m: re.Match) -> bool:
        return (_any_in(softs, _start_of(sentences, m.start()), m.start())
                or _any_in(softs, m.end(), _end_of(clauses, m.end())))

    # The largest required figure ("5+ years of engineering, 1+ year of AWS" is a 5-year role), or
    # failing that the largest optional one.
    largest_soft = None
    for years, m in sorted(figures, key=lambda f: f[0], reverse=True):
        if years > 15 or not asked_of_candidate(m):  # more than 15 is company age
            continue
        if not is_soft(m):
            return years
        if largest_soft is None:
            largest_soft = years
    return largest_soft


def _has_junior_wording(d: str, clauses: list[int]) -> bool:
    for m in _JUNIOR_DESCRIPTION.finditer(d):
        clause = _start_of(clauses, m.start())
        if _NEGATED.search(d, max(clause, m.start() - 40), m.start()):
            continue
        duty = _DUTY_OBJECT.search(d, max(clause, m.start() - 40), m.start())
        # "you will mentor …", or a bullet / imperative ("Mentor recent graduates", "Help onboard new
        # grads", "Responsibilities: supporting our graduate programme"); a bare "Hiring recent
        # graduates" is the employer's headline.
        if duty and (_ROLE_SUBJECT.search(d, clause, duty.start())
                     or duty["coaching"] and d[clause:duty.start()].strip() in ("", "help")):
            continue
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
    clauses = _starts(_CLAUSE_END, d)
    need = _years_required(d, clauses)
    if need is not None and need >= 5:
        return "senior"
    if need is not None and need >= 3:
        return "mid"
    if (need is not None and need <= 1) or _has_junior_wording(d, clauses):
        return "junior"
    return "mid"
