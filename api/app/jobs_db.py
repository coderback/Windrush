"""
SQLite-backed job database for Windrush job feed.
"""
import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone

logger = logging.getLogger("windrush.jobs_db")

_DB_PATH: str = ""

_CREATE_JOBS_TABLE = """
CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT PRIMARY KEY,
    job_id          TEXT NOT NULL,
    title           TEXT NOT NULL,
    company         TEXT NOT NULL,
    location        TEXT,
    description     TEXT,
    url             TEXT,
    salary_min      REAL,
    salary_max      REAL,
    exposure_score  REAL,
    level           TEXT,
    source          TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT,
    expires_at      TEXT
);
"""

_CREATE_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_dedup_jobs
    ON jobs(lower(company), lower(title), lower(location));
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
        con.execute(_CREATE_INDEX)
        try:
            con.execute("ALTER TABLE jobs ADD COLUMN updated_at TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            con.execute("ALTER TABLE jobs ADD COLUMN expires_at TEXT")
        except sqlite3.OperationalError:
            pass
        con.commit()
        con.close()
        logger.info("Jobs DB initialised at %s", _DB_PATH)
    except Exception as exc:
        logger.error("Failed to initialise jobs DB: %s", exc)

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def add_jobs(jobs: list[dict]) -> tuple[int, int]:
    """Insert a list of jobs into the DB, ignoring duplicates.
    Returns (added_count, updated_count).
    """
    added = 0
    updated = 0
    if not _DB_PATH:
        init_db()
    
    con = sqlite3.connect(_DB_PATH)
    for job in jobs:
        now_str = _now()
        try:
            con.execute(
                """INSERT INTO jobs
                   (id, job_id, title, company, location, description, url,
                    salary_min, salary_max, exposure_score, level, source, created_at, updated_at, expires_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    uuid.uuid4().hex,
                    str(job.get("job_id", "")),
                    job.get("title", ""),
                    job.get("company", ""),
                    job.get("location", ""),
                    job.get("description", ""),
                    job.get("url", ""),
                    job.get("salary_min"),
                    job.get("salary_max"),
                    job.get("exposure_score"),
                    job.get("level", "mid"),
                    job.get("source", "unknown"),
                    now_str,
                    now_str,
                    job.get("expires_at"),
                ),
            )
            added += 1
        except sqlite3.IntegrityError:
            # Duplicate based on unique index, just update the heartbeat
            con.execute(
                "UPDATE jobs SET updated_at = ? WHERE lower(company)=lower(?) AND lower(title)=lower(?) AND lower(location)=lower(?)",
                (now_str, job.get("company", ""), job.get("title", ""), job.get("location", ""))
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
    # Purge dynamically synced jobs that haven't been updated in this sync run
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
    limit: int = 20,
    offset: int = 0
) -> list[dict]:
    if not _DB_PATH:
        init_db()
    
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    
    sql = "SELECT * FROM jobs WHERE 1=1"
    params = []
    
    # Hide statically expired jobs
    sql += " AND (expires_at IS NULL OR expires_at > ?)"
    params.append(_now())

    if query:
        # Simple LIKE match on title or description
        sql += " AND (lower(title) LIKE ? OR lower(company) LIKE ?)"
        q = f"%{query.lower()}%"
        params.extend([q, q])
    
    if location:
        loc_lower = location.lower().strip()
        if loc_lower == "remote" or remote:
            sql += " AND lower(location) LIKE '%remote%'"
        else:
            # Handle regional aliases
            if loc_lower in ["uk", "united kingdom", "gb", "great britain"]:
                loc_clause = "(lower(location) LIKE '%uk%' OR lower(location) LIKE '%united kingdom%' OR lower(location) LIKE '%england%' OR lower(location) LIKE '%london%' OR lower(location) LIKE '%bristol%' OR lower(location) LIKE '%manchester%' OR lower(location) LIKE '%birmingham%' OR lower(location) LIKE '%leeds%' OR lower(location) LIKE '%scotland%' OR lower(location) LIKE '%edinburgh%' OR lower(location) LIKE '%glasgow%' OR lower(location) LIKE '%wales%' OR lower(location) LIKE '%cardiff%' OR lower(location) LIKE '%northern ireland%' OR lower(location) LIKE '%belfast%')"
                sql += f" AND ({loc_clause}"
                if remote:
                    sql += " OR lower(location) LIKE '%remote%'"
                sql += ")"
            elif loc_lower in ["england"]:
                loc_clause = "(lower(location) LIKE '%england%' OR lower(location) LIKE '%london%' OR lower(location) LIKE '%bristol%' OR lower(location) LIKE '%manchester%' OR lower(location) LIKE '%birmingham%' OR lower(location) LIKE '%leeds%' OR lower(location) LIKE '%liverpool%' OR lower(location) LIKE '%newcastle%')"
                sql += f" AND ({loc_clause}"
                if remote:
                    sql += " OR lower(location) LIKE '%remote%'"
                sql += ")"
            elif loc_lower in ["scotland"]:
                loc_clause = "(lower(location) LIKE '%scotland%' OR lower(location) LIKE '%edinburgh%' OR lower(location) LIKE '%glasgow%' OR lower(location) LIKE '%aberdeen%' OR lower(location) LIKE '%dundee%')"
                sql += f" AND ({loc_clause}"
                if remote:
                    sql += " OR lower(location) LIKE '%remote%'"
                sql += ")"
            elif loc_lower in ["wales"]:
                loc_clause = "(lower(location) LIKE '%wales%' OR lower(location) LIKE '%cardiff%' OR lower(location) LIKE '%swansea%' OR lower(location) LIKE '%newport%')"
                sql += f" AND ({loc_clause}"
                if remote:
                    sql += " OR lower(location) LIKE '%remote%'"
                sql += ")"
            elif loc_lower in ["ireland", "northern ireland", "roi", "republic of ireland"]:
                loc_clause = "(lower(location) LIKE '%ireland%' OR lower(location) LIKE '%dublin%' OR lower(location) LIKE '%belfast%' OR lower(location) LIKE '%cork%' OR lower(location) LIKE '%galway%')"
                sql += f" AND ({loc_clause}"
                if remote:
                    sql += " OR lower(location) LIKE '%remote%'"
                sql += ")"
            elif loc_lower in ["us", "usa", "united states", "america"]:
                loc_clause = "(lower(location) LIKE '%us%' OR lower(location) LIKE '%usa%' OR lower(location) LIKE '%united states%' OR lower(location) LIKE '%new york%' OR lower(location) LIKE '%san francisco%' OR lower(location) LIKE '%california%' OR lower(location) LIKE '%seattle%' OR lower(location) LIKE '%texas%' OR lower(location) LIKE '%boston%')"
                sql += f" AND ({loc_clause}"
                if remote:
                    sql += " OR lower(location) LIKE '%remote%'"
                sql += ")"
            elif loc_lower in ["eu", "europe", "european union"]:
                loc_clause = "(lower(location) LIKE '%eu%' OR lower(location) LIKE '%europe%' OR lower(location) LIKE '%germany%' OR lower(location) LIKE '%berlin%' OR lower(location) LIKE '%france%' OR lower(location) LIKE '%paris%' OR lower(location) LIKE '%spain%' OR lower(location) LIKE '%barcelona%' OR lower(location) LIKE '%netherlands%' OR lower(location) LIKE '%amsterdam%')"
                sql += f" AND ({loc_clause}"
                if remote:
                    sql += " OR lower(location) LIKE '%remote%'"
                sql += ")"
            elif loc_lower in ["ca", "canada"]:
                loc_clause = "(lower(location) LIKE '%canada%' OR lower(location) LIKE '%toronto%' OR lower(location) LIKE '%vancouver%' OR lower(location) LIKE '%montreal%')"
                sql += f" AND ({loc_clause}"
                if remote:
                    sql += " OR lower(location) LIKE '%remote%'"
                sql += ")"
            elif loc_lower in ["au", "australia"]:
                loc_clause = "(lower(location) LIKE '%australia%' OR lower(location) LIKE '%sydney%' OR lower(location) LIKE '%melbourne%' OR lower(location) LIKE '%brisbane%')"
                sql += f" AND ({loc_clause}"
                if remote:
                    sql += " OR lower(location) LIKE '%remote%'"
                sql += ")"
            else:
                sql += " AND (lower(location) LIKE ?"
                params.append(f"%{loc_lower}%")
                if remote:
                    sql += " OR lower(location) LIKE '%remote%'"
                sql += ")"
    elif remote:
        sql += " AND lower(location) LIKE '%remote%'"
        
    if level:
        sql += " AND lower(level) = ?"
        params.append(level.lower())
        
    if category:
        # e.g. "software engineer"
        sql += " AND lower(title) LIKE ?"
        params.append(f"%{category.lower()}%")
        
    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    rows = con.execute(sql, params).fetchall()
    con.close()
    
    return [dict(row) for row in rows]


def job_count() -> int:
    """Return the total number of jobs in the database."""
    if not _DB_PATH:
        init_db()
    con = sqlite3.connect(_DB_PATH)
    row = con.execute("SELECT COUNT(*) FROM jobs").fetchone()
    con.close()
    return row[0] if row else 0
