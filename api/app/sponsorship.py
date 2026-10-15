"""
Visa sponsorship and security-clearance signals in a job ad.

classify() reads the description sentence by sentence. A sentence that rules sponsorship out ("we
are unable to sponsor", "without sponsorship", "UK nationals only") makes the job 'not_offered',
whatever another sentence says; otherwise one that offers it ("visa sponsorship is available")
makes it 'offered'; otherwise the ad doesn't say (''). The deciding sentence is kept as evidence.

Clearance: SC and DV vetting usually need years of UK residence (often five), so for a candidate
who needs sponsorship they rule a job out as surely as "no sponsorship" does. BPSS, the basic
check, is not flagged.
"""
import html
import re
from dataclasses import dataclass

OFFERED, NOT_OFFERED, UNKNOWN = "offered", "not_offered", ""

_SENTENCE = re.compile(r"(?<=[.!?;])\s+|\n+|\s*[•·]\s*")
_NEGATOR = (r"(?:unable|not\s+able|cannot|can\s*not|can[’']t|do\s+not|don[’']t|does\s+not|doesn[’']t|"
            r"will\s+not|won[’']t|are\s+not|aren[’']t|is\s+not|isn[’']t|not\s+in\s+a\s+position|no\s+longer|"
            r"not\s+require|not\s+currently)")
_NOT_OFFERED = [re.compile(p, re.I) for p in (
    _NEGATOR + r"\b[^.;:!?]{0,60}?\b(?:sponsor|visa\s+(?:support|assistance|applications?))",  # "unable to offer sponsorship"
    r"\bno\s+(?:visa\s+|work\s+permit\s+)?sponsorship\b",                        # "no sponsorship available"
    r"\bsponsorship\s+(?:is\s+|will\s+be\s+)?(?:not\b|unavailable\b)",           # "sponsorship is not available"
    r"\bwithout\s+(?:the\s+)?(?:need\s+(?:for|of)\s+|requiring\s+|requirement\s+(?:for|of)\s+)?(?:any\s+)?"
    r"(?:current\s+or\s+future\s+|future\s+)?(?:visa\s+|employer\s+|company\s+)?sponsorship",  # "...without sponsorship"
    # "able to work in the UK without restrictions": a visa (Graduate, Skilled Worker) is a restriction
    r"\b(?:right|able|eligible|entitled|permitted)\s+to\s+work\s+in\s+the\s+uk\s+without\s+(?:any\s+)?restrictions?\b",
    r"\bunrestricted\s+(?:right|permission|entitlement)\s+to\s+work\b",
    r"\b(?:british|uk)\s+(?:nationals?|citizens?|citizenship|passport\s+holders?)\s+only\b",   # "UK nationals only"
    r"\bmust\s+(?:be|hold)\s+(?:a\s+)?(?:sole\s+)?(?:british|uk)\s+(?:national|citizen|citizenship|passport)",
)]
_OFFERED = [re.compile(p, re.I) for p in (
    r"\bsponsorship\s+(?:is\s+|will\s+be\s+|may\s+be\s+|can\s+be\s+)?(?:available|offered|provided|possible|considered)\b",
    r"\b(?:can|will|able\s+to|happy\s+to|willing\s+to|open\s+to|pleased\s+to)\s+(?:offer\s+|provide\s+|consider\s+)?"
    r"(?:visa\s+|skilled\s+worker\s+(?:visa\s+)?)?sponsor",                     # "we are happy to sponsor"
    r"\b(?:offer|offers|offering|provide|provides|providing|including)\s+(?:full\s+)?(?:visa\s+|skilled\s+worker\s+"
    r"(?:visa\s+)?)sponsorship",                                                 # "we offer visa sponsorship"
    r"\bsponsor(?:s|ing)?\s+(?:work\s+|skilled\s+worker\s+)?visas\b",            # "we sponsor visas"
    r"\bvisa\s+(?:support|assistance)\b",                                        # "relocation and visa support"
)]

_CLEARANCES = [  # most demanding first
    ("DV", re.compile(r"\b(?:e?DV)\b[\s-]*(?:level\s+)?(?:security\s+)?(?:clear|vett|eligib)|\bdeveloped\s+vetting\b", re.I)),
    ("SC", re.compile(r"\bSC\b[\s-]*(?:level\s+)?(?:security\s+)?(?:clear|vett|eligib)|\bsecurity\s+check\s*\(\s*SC\s*\)|"
                      r"\bsecurity\s+check\s+(?:level\s+)?(?:security\s+)?(?:clearance|vetting)", re.I)),
    ("NPPV", re.compile(r"\bNPPV\s*\d?\b", re.I)),
    ("unspecified", re.compile(r"\b(?:security|government)\s+clearance\b", re.I)),
]
_NOT_REQUIRED = re.compile(r"\b(?:no|not|without|isn[’']t)\b[^.;:!?]{0,30}$", re.I)
_BPSS = re.compile(r"\bBPSS\b|baseline\s+personnel\s+security", re.I)
_EVIDENCE_CHARS = 220


@dataclass(frozen=True)
class Signals:
    sponsorship: str = UNKNOWN   # OFFERED | NOT_OFFERED | UNKNOWN
    evidence: str = ""           # the sentence that decided it
    clearance: str = ""          # "DV" | "SC" | "NPPV" | "unspecified" | ""


def _sentences(text: str) -> list[str]:
    text = re.sub(r"<[^>]+>", " ", html.unescape(text or "")).replace("\xa0", " ")
    return [s.strip() for s in _SENTENCE.split(text) if s and s.strip()]


def _evidence(sentence: str) -> str:
    sentence = " ".join(sentence.split())
    return sentence if len(sentence) <= _EVIDENCE_CHARS else sentence[:_EVIDENCE_CHARS - 1].rstrip() + "…"


def _clearance(sentence: str) -> str:
    for level, pattern in _CLEARANCES:
        if level == "unspecified" and _BPSS.search(sentence):    # "BPSS security clearance" is the basic check
            continue
        for m in pattern.finditer(sentence):
            if not _NOT_REQUIRED.search(sentence[:m.start()]):   # "no security clearance needed"
                return level
    return ""


def classify(title: str, description: str) -> Signals:
    """The sponsorship and clearance signals in a job's title and description."""
    offered = not_offered = ""
    clearance_rank = len(_CLEARANCES)
    for sentence in _sentences(f"{title or ''}.\n{description or ''}"):
        if not not_offered and any(p.search(sentence) for p in _NOT_OFFERED):
            not_offered = sentence
        elif not offered and any(p.search(sentence) for p in _OFFERED):
            offered = sentence
        level = _clearance(sentence)
        if level:
            clearance_rank = min(clearance_rank, [name for name, _ in _CLEARANCES].index(level))
    clearance = _CLEARANCES[clearance_rank][0] if clearance_rank < len(_CLEARANCES) else ""
    if not_offered:
        return Signals(NOT_OFFERED, _evidence(not_offered), clearance)
    if offered:
        return Signals(OFFERED, _evidence(offered), clearance)
    return Signals(UNKNOWN, "", clearance)


def rules_out_sponsored_candidates(sponsorship: str, clearance: str) -> bool:
    """Whether a job's own signals rule out a candidate who needs a visa sponsored."""
    return sponsorship == NOT_OFFERED or clearance in ("SC", "DV")
