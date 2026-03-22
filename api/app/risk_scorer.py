import csv
import json
import os
import re

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# --- Economic Index (occupation-level ONET lookup) ---
_index_path = os.environ.get("ECONOMIC_INDEX_PATH", "/data/economic_index.json")
try:
    with open(_index_path) as f:
        ECONOMIC_INDEX: dict = json.load(f)
except FileNotFoundError:
    ECONOMIC_INDEX = {}

# --- Task penetration ---
# Non-zero tasks drive TF-IDF scoring; all tasks drive keyword scoring.
_task_path = os.environ.get("TASK_PENETRATION_PATH", "/data/task_penetration.csv")
_tasks: list[str] = []          # non-zero penetration only (TF-IDF corpus)
_penetrations: list[float] = [] # matching non-zero penetrations
_all_tasks: list[str] = []      # full corpus (keyword search)
_all_penetrations: list[float] = []

try:
    with open(_task_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            p = float(row["penetration"])
            _all_tasks.append(row["task"])
            _all_penetrations.append(p)
            if p > 0:
                _tasks.append(row["task"])
                _penetrations.append(p)
except FileNotFoundError:
    pass

_PENETRATIONS = np.array(_penetrations) if _penetrations else np.array([])
_VECTORIZER: TfidfVectorizer | None = None
_TASK_MATRIX = None

if _tasks:
    _VECTORIZER = TfidfVectorizer(ngram_range=(1, 2), stop_words="english")
    _TASK_MATRIX = _VECTORIZER.fit_transform(_tasks)

# --- Occupation name matching helpers ---

# Words stripped before matching job titles against ONET occupation names
_TITLE_NOISE = frozenset({
    "graduate", "junior", "senior", "lead", "principal", "associate",
    "trainee", "entry", "level", "new", "intern", "programme", "program",
    "2025", "2026", "2027", "fy27", "fy26", "fy25", "the", "and", "or",
    "for", "with", "except",
})

# Words too common across ONET occupation names to be discriminative on their own.
# Domain words (software, financial, data, teaching) are kept — role words that
# appear in dozens of occupations are filtered so they can't drive a solo match.
_WEAK_WORDS = frozenset({
    "machine", "service", "process", "processing", "workers", "worker",
    "operators", "operator", "other", "general", "special", "all",
    "engineer", "engineering",   # appears in 40+ occupations spanning all domains
})


def _stem(word: str) -> str:
    """Lightweight suffix normalisation — collapses common English plurals/agents."""
    if len(word) > 5 and word.endswith("ers"):
        return word[:-1]   # 'programmers' → 'programmer' (drop 's' not 'ers')
    if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]   # 'developers' → 'developer', 'analysts' → 'analyst'
    return word


def _title_words(text: str) -> set[str]:
    """Stemmed, noise-stripped content words from a title/occupation string."""
    words = re.sub(r"[^a-z0-9\s]", " ", text.lower()).split()
    return {
        _stem(w) for w in words
        if w not in _TITLE_NOISE and w not in _WEAK_WORDS and len(w) > 2
    }


def _onet_word_overlap(title: str) -> tuple[str, dict] | None:
    """Find best ONET occupation by stemmed content-word overlap.

    Minimum overlap scales with query length: queries with ≥ 3 content words
    require ≥ 2 shared words to avoid single-generic-word false positives
    (e.g. 'machine' in 'Machine Learning Engineer' matching 'Machine Operators').
    """
    query_words = _title_words(title)
    if not query_words:
        return None

    # Scale minimum required overlap with query length
    min_overlap = 2 if len(query_words) >= 3 else 1

    best_code: str | None = None
    best_data: dict | None = None
    best_overlap = 0

    for code, data in ECONOMIC_INDEX.items():
        occ_words = _title_words(data.get("occupation_name", ""))
        overlap = len(query_words & occ_words)
        if overlap > best_overlap:
            best_overlap = overlap
            best_code = code
            best_data = data

    return (best_code, best_data) if best_overlap >= min_overlap else None


def _keyword_task_score(term: str) -> float | None:
    """Average penetration across ALL tasks that contain `term` as a phrase.

    Uses the full task corpus (including zero-penetration tasks) so skills
    linked to low-AI-penetration work score lower than ones linked to
    high-penetration work.

    Note: ONET task descriptions are phrased generically and do NOT name
    specific programming languages or tools. This function is meaningful
    only for multi-word occupational phrases that do appear in task text
    (e.g. "machine learning", "financial analysis").
    """
    if not _all_tasks:
        return None

    key = term.lower().strip()
    # Require word-boundary match for short terms to avoid false positives
    if len(key) <= 5:
        pattern = re.compile(r"\b" + re.escape(key) + r"\b")
        indices = [i for i, t in enumerate(_all_tasks) if pattern.search(t.lower())]
    else:
        indices = [i for i, t in enumerate(_all_tasks) if key in t.lower()]

    if len(indices) < 3:   # too few matches → unreliable
        return None

    avg = sum(_all_penetrations[i] for i in indices) / len(indices)
    return float(round(avg, 4))


def _tfidf_score(skill: str) -> float | None:
    """TF-IDF semantic match against non-zero O*NET task penetration scores.

    Requires ALL content words from the skill name to appear in the matched
    task text to prevent false positives.
    """
    if _VECTORIZER is None or _TASK_MATRIX is None:
        return None

    _sklearn_stops = _VECTORIZER.get_stop_words()
    content_words = [
        w.lower() for w in skill.split()
        if len(w) > 2 and w.lower() not in _sklearn_stops
    ]
    if not content_words:
        return None

    vec = _VECTORIZER.transform([skill])
    sims = cosine_similarity(vec, _TASK_MATRIX)[0]
    top_idx = np.argsort(sims)[-20:][::-1]
    if sims[top_idx[0]] < 0.15:
        return None

    valid = [
        i for i in top_idx
        if sims[i] >= 0.15 and all(w in _tasks[i].lower() for w in content_words)
    ]
    if not valid:
        return None

    valid = valid[:5]
    weights = sims[valid]
    scores = _PENETRATIONS[valid]
    return float(round(np.average(scores, weights=weights), 4))


def lookup_onet(onet_code: str) -> dict:
    return ECONOMIC_INDEX.get(onet_code, {"occupation_name": "Unknown", "overall_exposure": 0.5})


def occupation_exposure(title: str) -> float:
    """Return exposure for a job title — used by job_proxy fixture scoring.

    Uses word-overlap matching so titles like 'Graduate Software Engineer'
    correctly resolve to 'Software Developers' instead of defaulting to 0.5.
    """
    match = _onet_word_overlap(title)
    if match:
        return float(match[1].get("overall_exposure", 0.5))
    return 0.5


def lookup_by_title(title: str) -> dict:
    """4-tier data-driven exposure lookup.

    Tier 1: Keyword search across all O*NET tasks — reliable for multi-word
            occupational phrases that appear in task descriptions
            (e.g. 'machine learning', 'financial analysis').
            Single-word tech tool names (Python, Docker, React) do NOT appear
            in ONET task text; they fall through to lower tiers.

    Tier 2: TF-IDF semantic match against 1,354 non-zero O*NET task penetrations.

    Tier 3: ONET occupation word-overlap match — strips noise words (graduate,
            junior, senior…) and finds the occupation with the most shared
            content words. Effective for job-title-phrased skills.

    Tier 4: Default 0.5 (no data to differentiate).
    """
    # Tier 1 — keyword task search (meaningful for multi-word occupational terms)
    score = _keyword_task_score(title)
    if score is not None:
        return {"occupation_name": title, "overall_exposure": score}

    # Tier 2 — TF-IDF
    score = _tfidf_score(title)
    if score is not None:
        return {"occupation_name": title, "overall_exposure": score}

    # Tier 3 — ONET word-overlap
    match = _onet_word_overlap(title)
    if match:
        return {"onet_code": match[0], **match[1]}

    # Tier 4
    return {"occupation_name": title, "overall_exposure": 0.5}
