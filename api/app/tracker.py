"""
SQLite-backed application tracker for Windrush.
DB path: APP_DATA_PATH env var (default /tmp) + /applications.db
"""
import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone

logger = logging.getLogger("windrush.tracker")

_DB_PATH: str = ""

VALID_STATUSES = {
    "Evaluated", "Applied", "Responded", "Interview", "Offer", "Rejected", "Discarded"
}

_CREATE_USERS_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,
    email           TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    persona         TEXT DEFAULT '{}',
    created_at      TEXT NOT NULL
);
"""

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS applications (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    job_id          TEXT NOT NULL,
    job_title       TEXT NOT NULL,
    company         TEXT NOT NULL,
    location        TEXT,
    job_url         TEXT,
    status          TEXT NOT NULL DEFAULT 'Evaluated',
    date_applied    TEXT,
    cv_profile      TEXT,
    cover_letter    TEXT,
    composite_score REAL,
    exposure_score  REAL,
    fit_score       REAL,
    skill_gaps      TEXT,
    level_match     TEXT,
    notes           TEXT,
    created_at      TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);
"""

_CREATE_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_dedup
    ON applications(user_id, lower(company), lower(job_title));
"""


def init_db(db_path: str = "") -> None:
    global _DB_PATH
    if not db_path:
        data_dir = os.environ.get("APP_DATA_PATH", "/tmp")
        db_path = os.path.join(data_dir, "applications.db")
    _DB_PATH = db_path
    try:
        con = sqlite3.connect(_DB_PATH)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute(_CREATE_USERS_TABLE)
        con.execute(_CREATE_TABLE)
        con.execute(_CREATE_INDEX)
        # Migration: add persona column if it doesn't exist
        try:
            con.execute("ALTER TABLE users ADD COLUMN persona TEXT DEFAULT '{}'")
        except sqlite3.OperationalError:
            pass # column already exists
        con.commit()
        con.close()
        logger.info("Tracker DB initialised at %s", _DB_PATH)
    except Exception as exc:
        logger.error("Failed to initialise tracker DB: %s", exc)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_user(email: str, password_hash: str) -> str:
    user_id = uuid.uuid4().hex
    con = sqlite3.connect(_DB_PATH)
    con.execute(
        "INSERT INTO users (id, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
        (user_id, email.lower(), password_hash, _now()),
    )
    con.commit()
    con.close()
    return user_id


def get_user_by_email(email: str) -> dict | None:
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT * FROM users WHERE email=?", (email.lower(),)).fetchone()
    con.close()
    return dict(row) if row else None


def get_user_by_id(user_id: str) -> dict | None:
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    con.close()
    return dict(row) if row else None


def get_user_persona(user_id: str) -> dict:
    con = sqlite3.connect(_DB_PATH)
    row = con.execute("SELECT persona FROM users WHERE id=?", (user_id,)).fetchone()
    con.close()
    if row and row[0]:
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return {}
    return {}


def update_user_persona(user_id: str, persona: dict) -> bool:
    try:
        con = sqlite3.connect(_DB_PATH)
        con.execute("UPDATE users SET persona=? WHERE id=?", (json.dumps(persona), user_id))
        con.commit()
        con.close()
        return True
    except Exception as exc:
        logger.error("update_user_persona failed: %s", exc)
        return False


def add_application(
    user_id: str,
    job: dict,
    cv_profile: dict,
    cover_letter: str,
    score_data: dict,
) -> str | None:
    """
    Insert a new application row for a specific user.
    Returns the new id, or None if this (company, job_title) already exists for this user.
    score_data: {composite_score, exposure_score, fit_score, skill_gaps, level_match}
    """
    app_id = uuid.uuid4().hex
    try:
        con = sqlite3.connect(_DB_PATH)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute(
            """INSERT INTO applications
               (id, user_id, job_id, job_title, company, location, job_url,
                status, cv_profile, cover_letter,
                composite_score, exposure_score, fit_score,
                skill_gaps, level_match, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                app_id,
                user_id,
                str(job.get("job_id", "")),
                job.get("title", ""),
                job.get("company", ""),
                job.get("location", ""),
                job.get("url", ""),
                "Evaluated",
                json.dumps(cv_profile),
                cover_letter,
                score_data.get("composite_score"),
                score_data.get("exposure_score"),
                score_data.get("fit_score"),
                json.dumps(score_data.get("skill_gaps", [])),
                score_data.get("level_match", "ok"),
                _now(),
            ),
        )
        con.commit()
        con.close()
        logger.info("Tracker: added application %s for user %s (%s @ %s)", app_id, user_id, job.get("title"), job.get("company"))
        return app_id
    except sqlite3.IntegrityError:
        logger.info("Tracker: duplicate skipped for user %s (%s @ %s)", user_id, job.get("title"), job.get("company"))
        return None
    except Exception as exc:
        logger.error("Tracker add_application failed: %s", exc)
        return None


def list_applications(user_id: str, status: str | None = None) -> list[dict]:
    try:
        con = sqlite3.connect(_DB_PATH)
        con.row_factory = sqlite3.Row
        if status and status in VALID_STATUSES:
            rows = con.execute(
                "SELECT * FROM applications WHERE user_id=? AND status=? ORDER BY created_at DESC", (user_id, status)
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM applications WHERE user_id=? ORDER BY created_at DESC", (user_id,)
            ).fetchall()
        con.close()
        result = []
        for row in rows:
            d = dict(row)
            d["skill_gaps"] = json.loads(d.get("skill_gaps") or "[]")
            # Don't expose full CV/cover letter in list view
            d.pop("cv_profile", None)
            d.pop("cover_letter", None)
            result.append(d)
        return result
    except Exception as exc:
        logger.error("Tracker list_applications failed: %s", exc)
        return []


def update_status(app_id: str, status: str, notes: str | None = None) -> bool:
    if status not in VALID_STATUSES:
        logger.warning("Tracker: invalid status %r", status)
        return False
    try:
        con = sqlite3.connect(_DB_PATH)
        updates = ["status=?"]
        params: list = [status]
        if status == "Applied":
            updates.append("date_applied=?")
            params.append(_now()[:10])  # date only
        if notes is not None:
            updates.append("notes=?")
            params.append(notes)
        params.append(app_id)
        con.execute(f"UPDATE applications SET {', '.join(updates)} WHERE id=?", params)
        con.commit()
        con.close()
        return True
    except Exception as exc:
        logger.error("Tracker update_status failed: %s", exc)
        return False
