"""
SQLite-backed job database for Windrush job feed.
"""
import json
import logging
import os
import re
import sqlite3
import uuid
import numpy as np
from datetime import datetime, timezone

logger = logging.getLogger("windrush.jobs_db")

_DB_PATH: str = ""

_CREATE_JOBS_TABLE = """
CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT PRIMARY KEY,
    job_id          TEXT NOT NULL,
    title           TEXT NOT NULL,
    company         TEXT NOT NULL,
    normalized_company TEXT,
    location        TEXT,
    description     TEXT,
    url             TEXT,
    salary_min      REAL,
    salary_max      REAL,
    exposure_score  REAL,
    level           TEXT,
    source          TEXT,
    tags            TEXT,
    semantic_vector BLOB,
    created_at      TEXT NOT NULL,
    updated_at      TEXT,
    expires_at      TEXT
);
"""

_CREATE_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_dedup_jobs
    ON jobs(lower(normalized_company), lower(title), lower(location));
"""

def init_db(db_path: str = "") -> None:
    global _DB_PATH
    if not db_path:
        data_dir = os.environ.get("APP_DATA_PATH", "/tmp")
        db_path = os.path.join(data_dir, "jobs.db")
    _DB_PATH = db_path
    try:
        con = sqlite3.connect(_DB_PATH)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute(_CREATE_JOBS_TABLE)
        
        # Fallbacks for existing tables
        try: con.execute("ALTER TABLE jobs ADD COLUMN updated_at TEXT")
        except sqlite3.OperationalError: pass
        try: con.execute("ALTER TABLE jobs ADD COLUMN expires_at TEXT")
        except sqlite3.OperationalError: pass
        try: con.execute("ALTER TABLE jobs ADD COLUMN normalized_company TEXT")
        except sqlite3.OperationalError: pass
        try: con.execute("ALTER TABLE jobs ADD COLUMN tags TEXT")
        except sqlite3.OperationalError: pass
        try: con.execute("ALTER TABLE jobs ADD COLUMN semantic_vector BLOB")
        except sqlite3.OperationalError: pass
        
        # Ensure older rows have a normalized_company before we create/recreate the index
        con.execute("UPDATE jobs SET normalized_company = lower(company) WHERE normalized_company IS NULL")
        
        # Drop old index if it exists and create the new one
        con.execute("DROP INDEX IF EXISTS idx_dedup_jobs")
        con.execute(_CREATE_INDEX)
        
        con.commit()
        con.close()
        logger.info("Jobs DB initialised at %s", _DB_PATH)
    except Exception as exc:
        logger.error("Failed to initialise jobs DB: %s", exc)

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _normalize_company(name: str) -> str:
    """Strips common legal and regional suffixes to prevent duplicates."""
    n = name.lower()
    n = re.sub(r"[^\w\s]", "", n)
    n = re.sub(r"\b(ltd|limited|inc|corp|corporation|plc|uk|usa|llc)\b", "", n)
    return " ".join(n.split())

def _extract_tags(job: dict) -> str:
    """Extract categorical tags (Role, Domain) from job title and description."""
    tags = set()
    title = job.get("title", "").lower()
    desc = job.get("description", "").lower()
    text = f"{title} {desc}"
    
    # Functional Roles
    if "software" in title: tags.add("software")
    if "engineer" in title: tags.add("engineer")
    if "developer" in title: tags.add("developer")
    if "machine learning" in title or " ml" in title or "ml " in title: tags.add("ml")
    if "data" in title: tags.add("data")
    if any(w in title for w in ["ai ", " ai", "artificial intelligence", "generative"]): tags.add("ai")
    if "backend" in title or "back end" in title: tags.add("backend")
    if "frontend" in title or "front end" in title or "react" in title: tags.add("frontend")
    if "fullstack" in title or "full stack" in title: tags.add("fullstack")
    if any(w in title for w in ["devops", "infrastructure", "sre", "cloud"]): tags.add("devops")
    if "security" in title or "cyber" in title: tags.add("security")
    if "analyst" in title: tags.add("analyst")
    
    # Domains & Traits
    if any(w in text for w in ["fintech", "finance", "trading", "quant", "banking"]): tags.add("fintech")
    if any(w in text for w in ["startup", "start-up", "series a", "series b"]): tags.add("startup")
    if any(w in text for w in ["visa", "sponsorship", "relocation"]): tags.add("sponsorship")
    if any(w in text for w in ["remote", "work from home", "telecommute", "anywhere"]): tags.add("remote")
    
    return json.dumps(list(tags))

from . import semantic

# Tags recognised in the `tags` filter (must match what _extract_tags writes). Role tags are
# OR'd ("ml or data"); domain tags are AND'd ("fintech and sponsorship"). Any other tag is
# free text — the search box sends typed terms as tags — and must appear in the job's
# title, company or description.
ROLE_TAGS = frozenset({"software", "ml", "ai", "data", "backend", "frontend", "fullstack",
                       "devops", "security", "analyst", "engineer", "developer"})
DOMAIN_TAGS = frozenset({"fintech", "startup", "sponsorship", "remote"})

# Most-recent matching rows that are ranked per request. Bounds per-request work (rows,
# vector BLOBs, numpy) as the table grows; matches older than this aren't reachable.
_CANDIDATE_POOL = 2000

# Country-level location aliases. SQL uses them as a LIKE superset; the precise check is a
# word-boundary regex in Python (so 'us' matches "Austin, TX, US" but not "Australia").
_LOCATION_ALIASES = {
    "uk": ["uk", "united kingdom", "england", "scotland", "wales", "northern ireland", "london", "bristol",
           "manchester", "birmingham", "leeds", "edinburgh", "glasgow", "cardiff", "belfast"],
    "us": ["us", "usa", "united states", "new york", "san francisco", "california", "seattle"],
}
_LOCATION_ALIAS_KEYS = {"uk": "uk", "united kingdom": "uk", "gb": "uk", "great britain": "uk",
                        "us": "us", "usa": "us", "united states": "us", "america": "us"}
_REMOTE_TERMS = ["remote", "anywhere", "telecommute"]


def _job_key(job: dict) -> tuple[str, str, str]:
    """The jobs table's dedup key (idx_dedup_jobs)."""
    return (_normalize_company(job.get("company", "")), (job.get("title") or "").lower(),
            (job.get("location") or "").lower())


def _job_text(job: dict) -> str:
    return f"{job.get('title', '')} {job.get('description', '')}"


def add_jobs(jobs: list[dict]) -> tuple[int, int]:
    """
    Upsert jobs: insert new ones, refresh updated_at/tags on existing ones. Embeddings are only
    computed for rows that need one (new, or stored without a vector), in batched Ollama calls,
    and with no DB connection held — so a slow embedder never holds the write lock.
    Blocking: call via asyncio.to_thread() from async code.
    """
    if not _DB_PATH:
        init_db()

    # 1. Classify against what's stored (read-only).
    con = sqlite3.connect(_DB_PATH)
    new_jobs: list[dict] = []
    existing: list[tuple[str, dict, bool]] = []  # (row id, job, needs_vector)
    seen: set[tuple[str, str, str]] = set()
    for job in jobs:
        key = _job_key(job)
        if key in seen:  # duplicate within this batch
            continue
        seen.add(key)
        row = con.execute(
            "SELECT id, semantic_vector IS NULL FROM jobs "
            "WHERE lower(normalized_company)=? AND lower(title)=? AND lower(location)=?", key,
        ).fetchone()
        if row:
            existing.append((row[0], job, bool(row[1])))
        else:
            new_jobs.append(job)
    con.close()

    # 2. Embed only what needs it (no DB handle open).
    to_embed = new_jobs + [job for _, job, needs in existing if needs]
    vectors = semantic.get_embeddings_sync([_job_text(j) for j in to_embed]) if to_embed else []
    blob_for = {
        id(j): (np.array(v, dtype=np.float32).tobytes() if v else None)
        for j, v in zip(to_embed, vectors)
    }

    # 3. Write.
    added = updated = 0
    now_str = _now()
    con = sqlite3.connect(_DB_PATH)
    for job in new_jobs:
        try:
            con.execute(
                """INSERT INTO jobs
                   (id, job_id, title, company, normalized_company, location, description, url,
                    salary_min, salary_max, exposure_score, level, source, tags, semantic_vector, created_at, updated_at, expires_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    uuid.uuid4().hex, str(job.get("job_id", "")), job.get("title", ""), job.get("company", ""),
                    _normalize_company(job.get("company", "")), job.get("location", ""), job.get("description", ""),
                    job.get("url", ""), job.get("salary_min"), job.get("salary_max"), job.get("exposure_score"),
                    job.get("level", "mid"), job.get("source", "unknown"), _extract_tags(job), blob_for.get(id(job)),
                    now_str, now_str, job.get("expires_at"),
                ),
            )
            added += 1
        except sqlite3.IntegrityError:  # inserted concurrently since step 1 — refresh instead
            existing.append(("", job, False))
        except Exception as exc:
            logger.error("Failed to insert job %s: %s", job.get("title"), exc)
    for row_id, job, _ in existing:
        con.execute(
            """UPDATE jobs SET updated_at = ?, tags = ?, semantic_vector = COALESCE(semantic_vector, ?)
               WHERE lower(normalized_company)=? AND lower(title)=? AND lower(location)=?""",
            (now_str, _extract_tags(job), blob_for.get(id(job)), *_job_key(job)),
        )
        updated += 1
    con.commit()
    con.close()
    return added, updated


def purge_expired_jobs(sync_start: str) -> None:
    if not _DB_PATH: return
    con = sqlite3.connect(_DB_PATH)
    cur = con.execute("DELETE FROM jobs WHERE source IN ('ats', 'adzuna', 'workable') AND (updated_at < ? OR updated_at IS NULL)", (sync_start,))
    deleted = cur.rowcount
    con.commit()
    con.close()
    if deleted > 0:
        logger.info("Purged %d expired jobs that were removed from their source ATS.", deleted)


def _like(term: str) -> str:
    """LIKE pattern for a user-supplied term with %, _ and the escape char escaped (ESCAPE '\\')."""
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _location_matcher(location: str):
    """(sql_terms, precise_regex) for a location filter."""
    loc = location.lower().strip()
    terms = _LOCATION_ALIASES.get(_LOCATION_ALIAS_KEYS.get(loc, ""), [loc])
    regex = re.compile(r"(?<![a-z])(" + "|".join(re.escape(t) for t in terms) + r")(?![a-z])")
    return terms, regex


def _parse_tags(tags: list[str]) -> tuple[list[str], list[str], list[str]]:
    roles, domains, text = [], [], []
    for t in tags or []:
        t = t.strip().lower()
        if not t:
            continue
        (roles if t in ROLE_TAGS else domains if t in DOMAIN_TAGS else text).append(t)
    return roles, domains, text


def get_jobs(
    query: str = "",
    location: str = "",
    level: str = "",
    category: str = "",
    remote: bool = False,
    tags: list[str] = None,
    persona_vector: list[float] = None,
    limit: int = 20,
    offset: int = 0,
    exclude: set[tuple[str, str]] | None = None,
) -> tuple[list[dict], bool]:
    """
    Filter in SQL, then rank (semantic similarity to `persona_vector` when given, else
    recency) and paginate. `query`, `category` and free-text `tags` are hard filters; role
    tags are OR'd, domain tags AND'd. `exclude` holds (lower company, lower title) pairs to
    drop *before* pagination (jobs the user already applied to / discarded), so pages stay
    full. Returns (jobs, has_more). Blocking: call via asyncio.to_thread() from async code.
    """
    if not _DB_PATH:
        init_db()

    roles, domains, text_terms = _parse_tags(list(tags or []) + ([category] if category else []))
    text_terms += [w for w in re.split(r"[\s,]+", (query or "").lower()) if len(w) > 1]

    where = ["(expires_at IS NULL OR expires_at > ?)"]
    params: list = [_now()]

    if level:
        where.append("lower(level) = ?")
        params.append(level.lower())

    for term in text_terms:
        where.append("(lower(title) LIKE ? ESCAPE '\\' OR lower(company) LIKE ? ESCAPE '\\' "
                     "OR lower(description) LIKE ? ESCAPE '\\')")
        params += [_like(term)] * 3
    if roles:
        where.append("(" + " OR ".join("tags LIKE ?" for _ in roles) + ")")
        params += [f'%"{r}"%' for r in roles]
    for d in domains:
        where.append("tags LIKE ?")
        params.append(f'%"{d}"%')

    loc_regex = None
    loc_lower = location.lower().strip()
    remote_only = remote or loc_lower == "remote"
    remote_sql = "(" + " OR ".join("lower(location) LIKE ?" for _ in _REMOTE_TERMS) + ")"
    if remote_only and not (location and loc_lower != "remote"):
        where.append(remote_sql)
        params += [f"%{t}%" for t in _REMOTE_TERMS]
    elif location:
        terms, loc_regex = _location_matcher(location)
        loc_sql = "(" + " OR ".join("lower(location) LIKE ? ESCAPE '\\'" for _ in terms) + ")"
        if remote:  # "in <location>, or remote"
            where.append(f"({loc_sql} OR {remote_sql})")
            params += [_like(t) for t in terms] + [f"%{t}%" for t in _REMOTE_TERMS]
        else:
            where.append(loc_sql)
            params += [_like(t) for t in terms]
        # "London" (or the UK alias, which includes it) means London, England — unless the
        # user is explicitly searching for the Canadian / US ones.
        if ("london" in terms) and not any(x in loc_lower for x in ("ontario", "new london", "canada")):
            where.append("lower(location) NOT LIKE '%ontario%' AND lower(location) NOT LIKE '%new london%'")

    columns = "*" if persona_vector else (
        "id, job_id, title, company, normalized_company, location, description, url, salary_min, salary_max, "
        "exposure_score, level, source, tags, created_at, updated_at, expires_at")
    sql = (f"SELECT {columns} FROM jobs WHERE {' AND '.join(where)} "
           f"ORDER BY coalesce(updated_at, created_at) DESC LIMIT {_CANDIDATE_POOL}")

    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(sql, params).fetchall()]
    con.close()

    exclude = exclude or set()
    candidates = []
    for job in rows:
        if exclude and ((job.get("company") or "").lower(), (job.get("title") or "").lower()) in exclude:
            continue
        loc = (job.get("location") or "").lower()
        if loc_regex is not None and not loc_regex.search(loc):
            if not (remote and any(t in loc for t in _REMOTE_TERMS)):
                continue
        candidates.append(job)

    if persona_vector:
        _rank_semantically(candidates, persona_vector)
        candidates.sort(key=lambda j: j["semantic_score"], reverse=True)  # stable: ties stay newest-first
    else:
        for job in candidates:
            job["semantic_score"] = 0.0

    page = candidates[offset: offset + limit]
    return page, len(candidates) > offset + limit


def _rank_semantically(jobs: list[dict], persona_vector: list[float]) -> None:
    """Set job['semantic_score'] = cosine(job vector, persona vector), vectorised with numpy."""
    p = np.asarray(persona_vector, dtype=np.float32)
    p_norm = float(np.linalg.norm(p)) or 1.0
    idx, vecs = [], []
    for i, job in enumerate(jobs):
        blob = job.pop("semantic_vector", None)
        job["semantic_score"] = 0.0
        if blob:
            v = np.frombuffer(blob, dtype=np.float32)
            if v.shape == p.shape:  # skip vectors from a different embedding model
                idx.append(i)
                vecs.append(v)
    if not vecs:
        return
    m = np.vstack(vecs)
    norms = np.linalg.norm(m, axis=1)
    norms[norms == 0] = 1.0
    sims = (m @ p) / (norms * p_norm)
    for i, s in zip(idx, sims):
        jobs[i]["semantic_score"] = round(float(s), 3)


def get_job(job_db_id: str) -> dict | None:
    """Return the stored job row (without its embedding) by primary key, or None."""
    if not _DB_PATH:
        init_db()
    try:
        con = sqlite3.connect(_DB_PATH)
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM jobs WHERE id = ?", (job_db_id,)).fetchone()
        con.close()
    except Exception as exc:
        logger.error("Failed to load job %s: %s", job_db_id, exc)
        return None
    if not row:
        return None
    job = dict(row)
    job.pop("semantic_vector", None)
    return job


def update_description(job_db_id: str, description: str) -> None:
    """Persist a freshly-fetched full description back onto a stored job row."""
    if not _DB_PATH:
        init_db()
    try:
        con = sqlite3.connect(_DB_PATH)
        con.execute(
            "UPDATE jobs SET description = ?, updated_at = ? WHERE id = ?",
            (description, _now(), job_db_id),
        )
        con.commit()
        con.close()
    except Exception as exc:
        logger.error("Failed to update job description %s: %s", job_db_id, exc)


def job_count() -> int:
    """Return the total number of jobs in the database."""
    if not _DB_PATH:
        init_db()
    con = sqlite3.connect(_DB_PATH)
    row = con.execute("SELECT COUNT(*) FROM jobs").fetchone()
    con.close()
    return row[0] if row else 0
