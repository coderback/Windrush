"""The published AI exposure of a job: the Anthropic Economic Index's score for the occupation its title belongs to.

Nothing here is estimated. A title is matched to an occupation by O*NET's own list of job titles, and the score is the
one Anthropic publishes for that occupation. When the title doesn't clearly belong to one occupation, or the index saw
too little usage to score it (it publishes a zero, which doesn't mean safe), the answer is "not enough data": None.
"""
import csv
import html
import json
import os
import re
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).resolve().parents[2] / "data"  # /data in the container, data/ in a checkout


def _load_json(variable: str, name: str) -> dict:
    try:
        with open(os.environ.get(variable) or _DATA / name, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


ECONOMIC_INDEX: dict = _load_json("ECONOMIC_INDEX_PATH", "economic_index.json")
EVIDENCE: dict = _load_json("OCCUPATION_EVIDENCE_PATH", "occupation_evidence.json")

# Say nothing about the occupation: left out of both sides before comparing
_NOISE = frozenset({
    "graduate", "grad", "junior", "jr", "senior", "sr", "lead", "principal", "staff", "associate", "trainee", "apprentice",
    "apprenticeship", "intern", "internship", "entry", "level", "new", "programme", "program", "scheme", "placement",
    "fresh", "early", "career", "careers", "year", "job", "jobs", "ii", "iii", "iv", "the", "and", "of", "for", "in", "with",
    "at", "a", "an",
})

# Titles O*NET leaves out or spreads across several occupations, placed the way the US occupation definitions do.
# Only the occupation is chosen here: the score is still the published one.
_SOFTWARE, _WEB, _SECURITY = "15-1252", "15-1254", "15-1212"
_RESEARCH_SCIENTIST, _DATA_SCIENTIST, _DATABASE = "15-1221", "15-2051", "15-1243"
_ROLES = {
    "backend": _SOFTWARE, "back end": _SOFTWARE, "full stack": _SOFTWARE, "fullstack": _SOFTWARE, "devops": _SOFTWARE,
    "site reliability": _SOFTWARE, "sre": _SOFTWARE, "platform engineer": _SOFTWARE, "infrastructure engineer": _SOFTWARE,
    "cloud engineer": _SOFTWARE, "software engineer": _SOFTWARE, "software developer": _SOFTWARE, "software engineering": _SOFTWARE,
    "software development": _SOFTWARE, "quant developer": _SOFTWARE, "quantitative developer": _SOFTWARE,
    "frontend": _WEB, "front end": _WEB, "web developer": _WEB,
    "machine learning engineer": _RESEARCH_SCIENTIST, "ml engineer": _RESEARCH_SCIENTIST, "ai engineer": _RESEARCH_SCIENTIST,
    "ai ml engineer": _RESEARCH_SCIENTIST, "research engineer": _RESEARCH_SCIENTIST, "research scientist": _RESEARCH_SCIENTIST,
    "data scientist": _DATA_SCIENTIST, "data science": _DATA_SCIENTIST, "data analyst": _DATA_SCIENTIST,
    "data engineer": _DATABASE, "analytics engineer": _DATABASE,
    "security engineer": _SECURITY, "cyber security": _SECURITY, "cybersecurity": _SECURITY, "cyber security engineer": _SECURITY,
    "quantitative analyst": "13-2099", "quantitative researcher": "13-2099", "quant researcher": "13-2099", "quant analyst": "13-2099",
    "business analyst": "13-1111", "financial analyst": "13-2051", "investment analyst": "13-2051",
    "back end engineer": _SOFTWARE, "back end developer": _SOFTWARE, "forward deployed engineer": _SOFTWARE,
    "deployment engineer": _SOFTWARE, "mlops": _SOFTWARE, "ml ops": _SOFTWARE, "python engineer": _SOFTWARE,
    "python developer": _SOFTWARE, "java engineer": _SOFTWARE, "java developer": _SOFTWARE, "c++ engineer": _SOFTWARE,
    "c++ developer": _SOFTWARE, "computer vision engineer": _RESEARCH_SCIENTIST, "machine learning researcher": _RESEARCH_SCIENTIST,
    "ml researcher": _RESEARCH_SCIENTIST, "electronic engineer": "17-2072", "fire engineer": "17-2111",
    "mechanical engineering": "17-2141",
}

# Entries in O*NET's list that send a title somewhere it plainly doesn't belong, seen on real job titles:
# "AI Consultant" to detectives, "Stack Engineer" to mechanical engineers, "Developer Advocate" to urban planners.
_UNRELIABLE = {"stack engineer", "developer advocate", "ai consultant", "market maker", "automation specialist",
               "structure engineer", "algorithm developer"}

# A field of work, not a job: O*NET lists "Engineering" under aerospace engineers and "Marketing" under one occupation
_A_FIELD = re.compile(r"(ing|tion|sion|ment|ance|ence|ology|ity|analytic|technology|science|service|chain)$")


def _words(text: str) -> tuple[str, ...]:
    """A title's meaningful words, singular."""
    words = re.sub(r"[^a-z0-9+#]+", " ", html.unescape(text).lower()).split()
    kept = (w for w in words if w not in _NOISE and not re.fullmatch(r"\d+|fy\d+", w))
    return tuple(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in kept)


def _load_titles() -> dict[tuple[str, ...], str]:
    """Each title that belongs to exactly one occupation. One O*NET gives to several says nothing on its own."""
    occupations: dict[tuple[str, ...], set[str]] = {}
    unreliable = {_words(phrase) for phrase in _UNRELIABLE}
    try:
        with open(os.environ.get("OCCUPATION_TITLES_PATH") or _DATA / "occupation_titles.csv", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                words = _words(row["title"])
                if words and words not in unreliable and not _A_FIELD.search(words[-1]):
                    occupations.setdefault(words, set()).add(row["soc"])
    except FileNotFoundError:
        pass
    titles = {words: next(iter(codes)) for words, codes in occupations.items() if len(codes) == 1}
    titles.update({_words(phrase): code for phrase, code in _ROLES.items()})
    return titles


_TITLES = _load_titles()
_ROLE_WORDS = {_words(phrase) for phrase in _ROLES}
_LONGEST = max((len(t) for t in _TITLES), default=0)


def _occupation_code(title: str) -> str | None:
    words = _words(title)
    if not words:
        return None
    if words in _TITLES:
        return _TITLES[words]
    # A longer title holding known ones ("Technology Programme (Data Engineer)"). Longest first, and they have to agree:
    # "Software Engineer / Data Scientist" is two occupations, so it isn't scored.
    found: set[str] = set()
    free = [True] * len(words)
    for size in range(min(_LONGEST, len(words)), 0, -1):
        for start in range(len(words) - size + 1):
            span = words[start:start + size]
            # A single word is too thin to go on unless it's a role word: "Sales Engineer" isn't "engineer"
            if span in _TITLES and all(free[start:start + size]) and (size > 1 or span in _ROLE_WORDS):
                found.add(_TITLES[span])
                free[start:start + size] = [False] * size
    return found.pop() if len(found) == 1 else None


@lru_cache(maxsize=20_000)
def occupation_for(title: str) -> dict | None:
    """{code, name, exposure} of the occupation a title belongs to, or None when it doesn't clearly belong to one.
    exposure is 0-1, or None when the index has too little usage to score the occupation."""
    code = _occupation_code(title or "")
    entry = ECONOMIC_INDEX.get(code) if code else None
    if not entry:
        return None
    return {"code": code, "name": entry["occupation_name"], "exposure": entry.get("overall_exposure") or None}


def occupation_exposure(title: str) -> float | None:
    """The published score of a job title's occupation, 0-1, or None for not enough data."""
    occupation = occupation_for(title)
    return occupation["exposure"] if occupation else None


def exposure_fields(title: str) -> dict:
    """What a job carries: its score, and the occupation it comes from so a wrong match can be seen."""
    occupation = occupation_for(title)
    return {"exposure_score": occupation["exposure"] if occupation else None,
            "exposure_occupation": occupation["name"] if occupation else None}


def target_evidence(titles: list[str]) -> dict | None:
    """What people hand to AI in the first of these roles the index has task data for."""
    for title in titles:
        occupation = occupation_for(title)
        if occupation and occupation["code"] in EVIDENCE:
            return {"role": title, "occupation": occupation["name"], **EVIDENCE[occupation["code"]]}
    return None


def career_exposure(persona: dict) -> dict:
    """The published score of each role someone is aiming for or has done, and the evidence for their target."""
    targets = [t for t in (persona.get("preferences") or {}).get("target_titles") or [] if t]
    past = [h.get("title") for h in persona.get("history") or [] if h.get("title")]
    roles, seen = [], set()
    for kind, titles in (("target", targets), ("past", past)):
        for title in titles:
            if title.lower() in seen:
                continue
            seen.add(title.lower())
            occupation = occupation_for(title)
            exposure = occupation["exposure"] if occupation else None
            roles.append({"title": title, "kind": kind, "occupation": occupation["name"] if occupation else None,
                          "exposure": round(exposure * 100) if exposure else None})
    return {"roles": roles, "evidence": target_evidence(targets)}
