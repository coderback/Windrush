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

def add_jobs(jobs: list[dict]) -> tuple[int, int]:
    """Insert a list of jobs into the DB, ignoring duplicates."""
    added = 0
    updated = 0
    if not _DB_PATH:
        init_db()
    
    con = sqlite3.connect(_DB_PATH)
    for job in jobs:
        now_str = _now()
        normalized_co = _normalize_company(job.get("company", ""))
        tags_json = _extract_tags(job)
        
        # Calculate semantic vector for the job (title + desc)
        job_text = f"{job.get('title', '')} {job.get('description', '')}"
        embedding = semantic.get_embedding_sync(job_text)
        vector_blob = None
        if embedding:
            vector_blob = np.array(embedding, dtype=np.float32).tobytes()
        
        try:
            con.execute(
                """INSERT INTO jobs
                   (id, job_id, title, company, normalized_company, location, description, url,
                    salary_min, salary_max, exposure_score, level, source, tags, semantic_vector, created_at, updated_at, expires_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    uuid.uuid4().hex,
                    str(job.get("job_id", "")),
                    job.get("title", ""),
                    job.get("company", ""),
                    normalized_co,
                    job.get("location", ""),
                    job.get("description", ""),
                    job.get("url", ""),
                    job.get("salary_min"),
                    job.get("salary_max"),
                    job.get("exposure_score"),
                    job.get("level", "mid"),
                    job.get("source", "unknown"),
                    tags_json,
                    vector_blob,
                    now_str,
                    now_str,
                    job.get("expires_at"),
                ),
            )
            added += 1
        except sqlite3.IntegrityError:
            con.execute(
                """UPDATE jobs SET updated_at = ?, tags = ?, 
                   semantic_vector = COALESCE(semantic_vector, ?) 
                   WHERE lower(normalized_company)=? AND lower(title)=lower(?) AND lower(location)=lower(?)""",
                (now_str, tags_json, vector_blob, normalized_co, job.get("title", ""), job.get("location", ""))
            )
            updated += 1
        except Exception as exc:
            logger.error("Failed to insert job %s: %s", job.get("title"), exc)
    
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

def get_jobs(
    query: str = "",
    location: str = "",
    level: str = "",
    category: str = "",
    remote: bool = False,
    tags: list[str] = None,
    persona_vector: list[float] = None,
    limit: int = 20,
    offset: int = 0
) -> list[dict]:
    if not _DB_PATH:
        init_db()
    
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    
    # Categorise tags for Collection (OR) logic within Role group
    # Level is now handled by the separate dropdown, not by tags.
    s_roles = {"software", "ml", "ai", "data", "backend", "frontend", "fullstack", "devops", "security", "analyst", "engineer", "developer"}
    
    active_roles = []
    active_others = []
    
    if tags:
        for t in tags:
            t_low = t.lower()
            if t_low in s_roles: active_roles.append(t_low)
            else: active_others.append(t_low)

    sql = "SELECT * FROM jobs WHERE 1=1"
    params = []
    sql += " AND (expires_at IS NULL OR expires_at > ?)"
    params.append(_now())

    # LEVEL and LOCATION remain strict "Hard Filters" (Deal-breakers)
    if level:
        sql += " AND lower(level) = ?"
        params.append(level.lower())
    
    if location:
        loc_lower = location.lower().strip()
        if "london" in loc_lower and "uk" in loc_lower:
            sql += " AND lower(location) NOT LIKE '%ontario%' AND lower(location) NOT LIKE '%new london%'"
        
        if loc_lower == "remote" or remote:
            sql += " AND (lower(location) LIKE '%remote%' OR lower(location) LIKE '%anywhere%' OR lower(location) LIKE '%telecommute%')"
        else:
            loc_clause = ""
            if loc_lower in ["uk", "united kingdom", "gb", "great britain"]:
                loc_clause = "(lower(location) LIKE '%uk%' OR lower(location) LIKE '%united kingdom%' OR lower(location) LIKE '%england%' OR lower(location) LIKE '%london%' OR lower(location) LIKE '%bristol%' OR lower(location) LIKE '%manchester%' OR lower(location) LIKE '%birmingham%' OR lower(location) LIKE '%leeds%' OR lower(location) LIKE '%scotland%' OR lower(location) LIKE '%edinburgh%' OR lower(location) LIKE '%glasgow%' OR lower(location) LIKE '%wales%' OR lower(location) LIKE '%cardiff%' OR lower(location) LIKE '%northern ireland%' OR lower(location) LIKE '%belfast%')"
            elif loc_lower in ["us", "usa", "united states", "america"]:
                loc_clause = "(lower(location) LIKE '%us%' OR lower(location) LIKE '%usa%' OR lower(location) LIKE '%united states%' OR lower(location) LIKE '%new york%' OR lower(location) LIKE '%san francisco%' OR lower(location) LIKE '%california%' OR lower(location) LIKE '%seattle%')"
            else:
                loc_clause = "(lower(location) LIKE ?)"
                params.append(f"%{loc_lower}%")
            
            if remote:
                sql += f" AND ({loc_clause} OR lower(location) LIKE '%remote%')"
            else:
                sql += f" AND {loc_clause}"

    # Roles and Domains are now "Semantic Interests" handled in Python ranking,
    # so we no longer apply them in SQL.

    # To keep semantic search snappy but accurate, we pull more than the limit 
    # then rank and return the page. Capping at 500 for performance.
    fetch_limit = 500 if persona_vector else limit + offset
    sql += f" LIMIT {fetch_limit}"

    rows = con.execute(sql, params).fetchall()
    con.close()
    
    candidates = []
    for row in rows:
        job = dict(row)
        sim = 0.0
        if persona_vector and job.get("semantic_vector"):
            try:
                job_v = np.frombuffer(job["semantic_vector"], dtype=np.float32).tolist()
                sim = semantic.cosine_similarity(persona_vector, job_v)
            except: pass
            
        job.pop("semantic_vector", None)
        job["semantic_score"] = round(sim, 3)
        candidates.append(job)

    # Sort and Limit
    if persona_vector:
        candidates.sort(key=lambda x: x.get("semantic_score", 0), reverse=True)
    else:
        candidates.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        
    return candidates[offset : offset + limit]

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
