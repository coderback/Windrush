import csv
import json
import os

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

# --- Task penetration (NLP signal — only non-zero tasks are meaningful) ---
_task_path = os.environ.get("TASK_PENETRATION_PATH", "/data/task_penetration.csv")
_tasks: list[str] = []
_penetrations: list[float] = []
try:
    with open(_task_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            p = float(row["penetration"])
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


def _tfidf_score(skill: str) -> float | None:
    """Tier 1: semantic match against non-zero O*NET task penetration scores.

    Requires ALL content words from the skill name to appear in the matched task
    text to prevent false positives from shared common words (e.g. 'learning' in
    'deep learning' matching educational tasks, 'normalizing' matching records tasks).
    """
    if _VECTORIZER is None or _TASK_MATRIX is None:
        return None

    # Content words: non-stopwords longer than 2 chars
    _sklearn_stops = _VECTORIZER.get_stop_words()
    content_words = [
        w.lower() for w in skill.split()
        if len(w) > 2 and w.lower() not in _sklearn_stops
    ]
    if not content_words:
        return None

    vec = _VECTORIZER.transform([skill])
    sims = cosine_similarity(vec, _TASK_MATRIX)[0]
    # Examine top 20 candidates, then filter by word overlap
    top_idx = np.argsort(sims)[-20:][::-1]
    if sims[top_idx[0]] < 0.15:
        return None

    # Keep only tasks where ALL content words from the skill appear literally
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
    """Return exposure for a job title — used by job_proxy fixture scoring."""
    key = title.lower().strip()
    for code, data in ECONOMIC_INDEX.items():
        occ = data.get("occupation_name", "").lower()
        if key in occ or (len(occ.split()) >= 2 and occ in key):
            return float(data.get("overall_exposure", 0.5))
    return 0.5


def lookup_by_title(title: str) -> dict:
    """3-tier lookup — no hardcoded scores:
    Tier 1: TF-IDF semantic match against 1,354 non-zero O*NET task penetrations
    Tier 2: ONET occupation fuzzy match (economic_index.json)
    Tier 3: default 0.5
    """
    # Tier 1
    score = _tfidf_score(title)
    if score is not None:
        return {"occupation_name": title, "overall_exposure": score}

    # Tier 2
    key = title.lower().strip()
    for code, data in ECONOMIC_INDEX.items():
        occ = data.get("occupation_name", "").lower()
        # Only allow occ-in-key direction if occupation has 2+ words, to prevent
        # short occupation names like "Models" matching inside "Generative Models"
        if key in occ or (len(occ.split()) >= 2 and occ in key):
            return {"onet_code": code, **data}

    # Tier 3
    return {"occupation_name": title, "overall_exposure": 0.5}
