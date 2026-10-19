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

from . import crypto

logger = logging.getLogger("windrush.tracker")

_DB_PATH: str = ""

VALID_STATUSES = {
    "Saved", "Pending Review", "Evaluated", "Applied", "Responded", "Interview", "Offer", "Rejected", "Discarded"
}

_CREATE_USERS_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    id                  TEXT PRIMARY KEY,
    email               TEXT UNIQUE NOT NULL,
    password_hash       TEXT NOT NULL,
    persona             TEXT DEFAULT '{}',
    onboarding_complete INTEGER DEFAULT 0,
    created_at          TEXT NOT NULL
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
    tailored_cv     TEXT,
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

# A user's own call on whether a job sponsors visas ('offered' / 'not_offered'), which wins over
# what the ad and the sponsor register suggest. job_id is the jobs.db row id.
_CREATE_JOB_MARKS_TABLE = """
CREATE TABLE IF NOT EXISTS job_marks (
    user_id     TEXT NOT NULL,
    job_id      TEXT NOT NULL,
    sponsorship TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (user_id, job_id)
);
"""
JOB_MARKS = ("offered", "not_offered")

# The answer bank: the user's own answers to application-form questions, reused on later forms (see
# answers.py). question_key is the question as answers.question_key() normalises it, for exact matches;
# company is set when the answer is about one employer, so only that employer's forms reuse it.
_CREATE_ANSWER_BANK_TABLE = """
CREATE TABLE IF NOT EXISTS answer_bank (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    question     TEXT NOT NULL,
    question_key TEXT NOT NULL,
    answer       TEXT NOT NULL,
    kind         TEXT NOT NULL,
    company      TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
"""
ANSWER_KINDS = ("fact", "written")

# Autopilot (see autopilot.py): each user's settings, and one row per job it has tried. job_id is the
# jobs.db row id; a job is tried once, so a retry replaces its row. practice is 1 when the run filled the
# form without being allowed to send it. reasons (a JSON list of sentences) says why it wasn't sent.
_CREATE_AUTOPILOT_SETTINGS_TABLE = """
CREATE TABLE IF NOT EXISTS autopilot_settings (
    user_id     TEXT PRIMARY KEY,
    settings    TEXT NOT NULL DEFAULT '{}',
    last_run_at TEXT
);
"""
_CREATE_AUTOPILOT_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS autopilot_runs (
    id             TEXT PRIMARY KEY,
    user_id        TEXT NOT NULL,
    job_id         TEXT NOT NULL,
    job_title      TEXT NOT NULL,
    company        TEXT NOT NULL,
    location       TEXT,
    job_url        TEXT,
    outcome        TEXT NOT NULL,
    practice       INTEGER NOT NULL DEFAULT 0,
    fit_score      REAL,
    reasons        TEXT NOT NULL DEFAULT '[]',
    questions      TEXT NOT NULL DEFAULT '[]',
    notes          TEXT,
    cv_doc_id      TEXT,
    letter_doc_id  TEXT,
    application_id TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
"""
# running   - being worked on now
# submitted - sent, and the page confirmed it
# unconfirmed - the submit button was clicked but the page didn't confirm it: the user checks
# ready     - practice mode: everything checked out, and it would have been sent
# needs_you - filled in but held back (see reasons)
# skipped   - not tried: the fit was too low, say
# failed    - something broke before the form was filled
# dismissed - the user cleared it from the queue
AUTOPILOT_OUTCOMES = ("running", "submitted", "unconfirmed", "ready", "needs_you", "skipped", "failed", "dismissed")


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
        con.execute(_CREATE_JOB_MARKS_TABLE)
        con.execute(_CREATE_ANSWER_BANK_TABLE)
        con.execute("CREATE INDEX IF NOT EXISTS idx_answer_bank_user ON answer_bank(user_id)")
        con.execute(_CREATE_AUTOPILOT_SETTINGS_TABLE)
        con.execute(_CREATE_AUTOPILOT_RUNS_TABLE)
        _gmail_tables(con)
        _suggestion_tables(con)
        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_autopilot_job ON autopilot_runs(user_id, job_id)")
        # Migrations — safe to run on existing DBs
        for stmt in [
            "ALTER TABLE users ADD COLUMN persona TEXT DEFAULT '{}'",
            "ALTER TABLE users ADD COLUMN onboarding_complete INTEGER DEFAULT 0",
            "ALTER TABLE applications ADD COLUMN tailored_cv TEXT",
            "ALTER TABLE applications ADD COLUMN user_id TEXT",
            "ALTER TABLE users ADD COLUMN job_password_enc TEXT",
            # The questions the agent met on the application's form, with each answer and its source.
            "ALTER TABLE applications ADD COLUMN questions TEXT",
        ]:
            try:
                con.execute(stmt)
            except sqlite3.OperationalError:
                pass
        _migrate_plaintext_job_passwords(con)
        if con.execute("PRAGMA user_version").fetchone()[0] < 1:
            _clear_default_eligibility_answers(con)
            con.execute("PRAGMA user_version = 1")
        # Create index after migrations so user_id column is guaranteed to exist
        try:
            con.execute(_CREATE_INDEX)
        except sqlite3.OperationalError:
            pass
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


def feed_locations() -> list[str] | None:
    """Every user's preferred locations together: the places some feed can show jobs from. None when a
    user has none, since their feed isn't limited to a place."""
    con = sqlite3.connect(_DB_PATH)
    rows = con.execute("SELECT persona FROM users").fetchall()
    con.close()
    out: list[str] = []
    for (raw,) in rows:
        try:
            persona = json.loads(raw or "{}")
        except json.JSONDecodeError:
            persona = {}
        places = [str(p).strip() for p in ((persona.get("preferences") or {}).get("preferred_locations") or [])
                  if str(p or "").strip()] if isinstance(persona, dict) else []
        if not places:
            return None
        out += [p for p in places if p.lower() not in {o.lower() for o in out}]
    return out or None


def _strip_job_password(persona: dict) -> str:
    """Remove core_info.job_password from a persona dict in place; return what was there."""
    core = persona.get("core_info")
    if isinstance(core, dict):
        return core.pop("job_password", "") or ""
    return ""


def _migrate_plaintext_job_passwords(con: sqlite3.Connection) -> None:
    """One-off: move job passwords that older versions stored in the persona JSON into job_password_enc."""
    rows = con.execute("SELECT id, persona FROM users WHERE persona LIKE '%job_password%'").fetchall()
    for user_id, raw in rows:
        try:
            persona = json.loads(raw or "{}")
        except json.JSONDecodeError:
            continue
        plaintext = _strip_job_password(persona)
        if plaintext:
            con.execute("UPDATE users SET job_password_enc=? WHERE id=?", (crypto.encrypt(plaintext), user_id))
        con.execute("UPDATE users SET persona=? WHERE id=?", (json.dumps(persona), user_id))
    if rows:
        logger.info("Moved job passwords for %d user(s) out of persona JSON into encrypted storage", len(rows))


# No version of the UI could set these, so any stored value is an old model default
# (right to work: yes, sponsorship: no, in person: yes) rather than the user's answer.
_NEVER_USER_SET = (("core_info", "right_to_work_uk"), ("core_info", "require_sponsorship"),
                   ("preferences", "can_work_in_person"))

# Settable in the UI, but every save stored the full model, so these old defaults were written for
# everyone. A value still equal to its default can't be told apart from one never answered; any
# other value was chosen by the user and is kept.
_OLD_DEFAULTS = (("core_info", "has_government_ties", False), ("preferences", "relocation_willingness", False),
                 ("preferences", "can_start_immediately", False), ("preferences", "needs_accommodations", False),
                 ("preferences", "has_reliable_transportation", True))


def _clear_default_eligibility_answers(con: sqlite3.Connection) -> None:
    """One-off: forget yes/no answers that were only ever defaults, so they read as unanswered."""
    cleared = 0
    for user_id, raw in con.execute("SELECT id, persona FROM users").fetchall():
        try:
            persona = json.loads(raw or "{}")
        except json.JSONDecodeError:
            continue
        changed = False
        for section, field in _NEVER_USER_SET:
            block = persona.get(section)
            if isinstance(block, dict) and block.get(field) is not None:
                block[field] = None
                changed = True
        for section, field, default in _OLD_DEFAULTS:
            block = persona.get(section)
            if isinstance(block, dict) and block.get(field) is default:
                block[field] = None
                changed = True
        if changed:
            con.execute("UPDATE users SET persona=? WHERE id=?", (json.dumps(persona), user_id))
            cleared += 1
    if cleared:
        logger.info("Cleared default yes/no application answers for %d user(s)", cleared)


def update_user_persona(user_id: str, persona: dict) -> bool:
    # The job-site password never lives in the persona JSON — see set_job_password().
    persona = json.loads(json.dumps(persona))
    _strip_job_password(persona)
    try:
        con = sqlite3.connect(_DB_PATH)
        con.execute("UPDATE users SET persona=? WHERE id=?", (json.dumps(persona), user_id))
        con.commit()
        con.close()
        return True
    except Exception as exc:
        logger.error("update_user_persona failed: %s", exc)
        return False


def set_job_password(user_id: str, plaintext: str) -> None:
    """Store (encrypted) or clear ('' ) the user's job-site password."""
    con = sqlite3.connect(_DB_PATH)
    con.execute(
        "UPDATE users SET job_password_enc=? WHERE id=?",
        (crypto.encrypt(plaintext) if plaintext else None, user_id),
    )
    con.commit()
    con.close()


def get_job_password(user_id: str) -> str:
    """Decrypted job-site password, or '' if none is stored. Only for handing to the browser agent."""
    con = sqlite3.connect(_DB_PATH)
    row = con.execute("SELECT job_password_enc FROM users WHERE id=?", (user_id,)).fetchone()
    con.close()
    return crypto.decrypt(row[0]) if row and row[0] else ""


def has_job_password(user_id: str) -> bool:
    con = sqlite3.connect(_DB_PATH)
    row = con.execute("SELECT job_password_enc FROM users WHERE id=?", (user_id,)).fetchone()
    con.close()
    return bool(row and row[0])


def get_onboarding_status(user_id: str) -> bool:
    con = sqlite3.connect(_DB_PATH)
    row = con.execute("SELECT onboarding_complete FROM users WHERE id=?", (user_id,)).fetchone()
    con.close()
    return bool(row and row[0])


def set_onboarding_complete(user_id: str) -> None:
    con = sqlite3.connect(_DB_PATH)
    con.execute("UPDATE users SET onboarding_complete=1 WHERE id=?", (user_id,))
    con.commit()
    con.close()


def add_application(
    user_id: str,
    job: dict,
    cv_profile: dict,
    cover_letter: str,
    score_data: dict,
    tailored_cv: str = "",
    status: str = "Pending Review",
) -> str | None:
    """
    Insert a new application row for a specific user.
    Returns the new id, or None if this (company, job_title) already exists for this user.
    score_data: {composite_score, exposure_score, fit_score, skill_gaps, level_match}
    """
    if status not in VALID_STATUSES:
        status = "Pending Review"

    app_id = uuid.uuid4().hex
    # Always close: a failed INSERT leaves its implicit transaction open, and an unclosed
    # connection would hold the DB write lock ("database is locked" for the next writer).
    con = sqlite3.connect(_DB_PATH)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute(
            """INSERT INTO applications
               (id, user_id, job_id, job_title, company, location, job_url,
                status, cv_profile, cover_letter, tailored_cv,
                composite_score, exposure_score, fit_score,
                skill_gaps, level_match, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                app_id,
                user_id,
                str(job.get("job_id", "")),
                job.get("title", ""),
                job.get("company", ""),
                job.get("location", ""),
                job.get("url", ""),
                status,
                json.dumps(cv_profile),
                cover_letter,
                tailored_cv,
                score_data.get("composite_score"),
                score_data.get("exposure_score"),
                score_data.get("fit_score"),
                json.dumps(score_data.get("skill_gaps", [])),
                score_data.get("level_match", "ok"),
                _now(),
            ),
        )
        con.commit()
        logger.info("Tracker: added application %s for user %s (%s @ %s)", app_id, user_id, job.get("title"), job.get("company"))
        return app_id
    except sqlite3.IntegrityError:
        logger.info("Tracker: duplicate skipped for user %s (%s @ %s)", user_id, job.get("title"), job.get("company"))
        return None
    except Exception as exc:
        logger.error("Tracker add_application failed: %s", exc)
        return None
    finally:
        con.close()


def get_user_application_statuses(user_id: str) -> dict[tuple[str, str], str]:
    """Returns a dict mapping (lower_company, lower_title) -> status."""
    try:
        con = sqlite3.connect(_DB_PATH)
        rows = con.execute(
            "SELECT lower(company), lower(job_title), status FROM applications WHERE user_id=?", 
            (user_id,)
        ).fetchall()
        con.close()
        return {(row[0], row[1]): row[2] for row in rows}
    except Exception as exc:
        logger.error("get_user_application_statuses failed: %s", exc)
        return {}


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
            d["questions"] = json.loads(d.get("questions") or "[]")
            # Don't expose full CV/cover letter in list view
            d.pop("cv_profile", None)
            d.pop("cover_letter", None)
            result.append(d)
        return result
    except Exception as exc:
        logger.error("Tracker list_applications failed: %s", exc)
        return []


def find_application_id(user_id: str, company: str, job_title: str) -> str | None:
    """Id of this user's existing application for (company, title) — the dedup key — if any."""
    con = sqlite3.connect(_DB_PATH)
    row = con.execute(
        "SELECT id FROM applications WHERE user_id=? AND lower(company)=lower(?) AND lower(job_title)=lower(?)",
        (user_id, company or "", job_title or ""),
    ).fetchone()
    con.close()
    return row[0] if row else None


def update_status(app_id: str, status: str, notes: str | None = None, *, user_id: str) -> bool:
    """Update one of `user_id`'s applications. False if the status is invalid or no such row
    belongs to that user (so ids from other accounts can't be modified)."""
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
        params += [app_id, user_id]
        cur = con.execute(f"UPDATE applications SET {', '.join(updates)} WHERE id=? AND user_id=?", params)
        con.commit()
        con.close()
        return cur.rowcount == 1
    except Exception as exc:
        logger.error("Tracker update_status failed: %s", exc)
        return False


def set_job_mark(user_id: str, job_id: str, sponsorship: str | None) -> None:
    """Record the user's call on whether a job sponsors visas (one of JOB_MARKS), or clear it (None)."""
    if sponsorship is not None and sponsorship not in JOB_MARKS:
        raise ValueError(f"sponsorship mark must be one of {JOB_MARKS} or None")
    con = sqlite3.connect(_DB_PATH)
    with con:
        if sponsorship is None:
            con.execute("DELETE FROM job_marks WHERE user_id = ? AND job_id = ?", (user_id, job_id))
        else:
            con.execute("INSERT OR REPLACE INTO job_marks (user_id, job_id, sponsorship, updated_at) "
                        "VALUES (?, ?, ?, ?)", (user_id, job_id, sponsorship, _now()))
    con.close()


def get_job_marks(user_id: str) -> dict[str, str]:
    """{job id: 'offered' | 'not_offered'} for the jobs the user has marked."""
    con = sqlite3.connect(_DB_PATH)
    rows = con.execute("SELECT job_id, sponsorship FROM job_marks WHERE user_id = ?", (user_id,)).fetchall()
    con.close()
    return dict(rows)


def set_application_questions(app_id: str, questions: list[dict], *, user_id: str) -> bool:
    """Record the questions the agent met on this application's form (see answers.answer_questions)."""
    con = sqlite3.connect(_DB_PATH)
    with con:
        cur = con.execute("UPDATE applications SET questions=? WHERE id=? AND user_id=?",
                          (json.dumps(questions, ensure_ascii=False), app_id, user_id))
    con.close()
    return cur.rowcount == 1


# ── The answer bank ───────────────────────────────────────────────────────────

_ANSWER_COLUMNS = "id, question, question_key, answer, kind, company, created_at, updated_at"


def list_answers(user_id: str) -> list[dict]:
    """The user's saved answers, most recently changed first."""
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(f"SELECT {_ANSWER_COLUMNS} FROM answer_bank WHERE user_id=? ORDER BY updated_at DESC",
                       (user_id,)).fetchall()
    con.close()
    return [dict(r) for r in rows]


def get_answer(user_id: str, answer_id: str) -> dict | None:
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    row = con.execute(f"SELECT {_ANSWER_COLUMNS} FROM answer_bank WHERE id=? AND user_id=?",
                      (answer_id, user_id)).fetchone()
    con.close()
    return dict(row) if row else None


def save_answer(user_id: str, question: str, question_key: str, answer: str, kind: str, company: str = "") -> dict:
    """Save an answer, replacing the one already saved for the same question (and employer, if any)."""
    if kind not in ANSWER_KINDS:
        raise ValueError(f"kind must be one of {ANSWER_KINDS}")
    now = _now()
    con = sqlite3.connect(_DB_PATH)
    with con:
        row = con.execute("SELECT id FROM answer_bank WHERE user_id=? AND question_key=? AND lower(company)=lower(?)",
                          (user_id, question_key, company)).fetchone()
        if row:
            answer_id = row[0]
            con.execute("UPDATE answer_bank SET question=?, answer=?, kind=?, company=?, updated_at=? WHERE id=?",
                        (question, answer, kind, company, now, answer_id))
        else:
            answer_id = uuid.uuid4().hex
            con.execute(f"INSERT INTO answer_bank ({_ANSWER_COLUMNS}, user_id) VALUES (?,?,?,?,?,?,?,?,?)",
                        (answer_id, question, question_key, answer, kind, company, now, now, user_id))
    con.close()
    return get_answer(user_id, answer_id)


def update_answer(user_id: str, answer_id: str, answer: str) -> dict | None:
    """Change a saved answer's text; None if the user has no such answer."""
    con = sqlite3.connect(_DB_PATH)
    with con:
        cur = con.execute("UPDATE answer_bank SET answer=?, updated_at=? WHERE id=? AND user_id=?",
                          (answer, _now(), answer_id, user_id))
    con.close()
    return get_answer(user_id, answer_id) if cur.rowcount == 1 else None


def delete_answer(user_id: str, answer_id: str) -> bool:
    con = sqlite3.connect(_DB_PATH)
    with con:
        cur = con.execute("DELETE FROM answer_bank WHERE id=? AND user_id=?", (answer_id, user_id))
    con.close()
    return cur.rowcount == 1


# ── Autopilot ─────────────────────────────────────────────────────────────────

def get_autopilot_settings(user_id: str) -> dict:
    """The user's autopilot settings as saved ({} if never saved); autopilot.py fills in the defaults."""
    con = sqlite3.connect(_DB_PATH)
    row = con.execute("SELECT settings FROM autopilot_settings WHERE user_id=?", (user_id,)).fetchone()
    con.close()
    try:
        settings = json.loads(row[0]) if row else {}
    except json.JSONDecodeError:
        settings = {}
    return settings if isinstance(settings, dict) else {}


def save_autopilot_settings(user_id: str, settings: dict) -> None:
    con = sqlite3.connect(_DB_PATH)
    with con:
        con.execute("INSERT INTO autopilot_settings (user_id, settings) VALUES (?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET settings=excluded.settings", (user_id, json.dumps(settings)))
    con.close()


def mark_autopilot_run(user_id: str) -> None:
    """Record that an autopilot run started now (the scheduler spaces runs by it)."""
    con = sqlite3.connect(_DB_PATH)
    with con:
        con.execute("INSERT INTO autopilot_settings (user_id, last_run_at) VALUES (?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET last_run_at=excluded.last_run_at", (user_id, _now()))
    con.close()


def autopilot_schedules() -> list[tuple[str, dict, str | None]]:
    """(user id, saved settings, last run started at) for every user who has saved autopilot settings."""
    con = sqlite3.connect(_DB_PATH)
    rows = con.execute("SELECT user_id, settings, last_run_at FROM autopilot_settings").fetchall()
    con.close()
    out = []
    for user_id, raw, last_run_at in rows:
        try:
            settings = json.loads(raw or "{}")
        except json.JSONDecodeError:
            settings = {}
        out.append((user_id, settings if isinstance(settings, dict) else {}, last_run_at))
    return out


def _autopilot_run(row: sqlite3.Row) -> dict:
    run = dict(row)
    run["practice"] = bool(run["practice"])
    run["reasons"] = json.loads(run["reasons"] or "[]")
    run["questions"] = json.loads(run["questions"] or "[]")
    return run


def start_autopilot_run(user_id: str, job: dict, outcome: str = "running", *, practice: bool = False,
                        fit_score: float | None = None, reasons: list[str] = ()) -> str:
    """Record that autopilot is trying (or skipped) a job; replaces an earlier row for the same job."""
    if outcome not in AUTOPILOT_OUTCOMES:
        raise ValueError(f"outcome must be one of {AUTOPILOT_OUTCOMES}")
    run_id, now = uuid.uuid4().hex, _now()
    con = sqlite3.connect(_DB_PATH)
    with con:
        con.execute("DELETE FROM autopilot_runs WHERE user_id=? AND job_id=?", (user_id, str(job.get("id", ""))))
        con.execute(
            "INSERT INTO autopilot_runs (id, user_id, job_id, job_title, company, location, job_url, outcome, "
            "practice, fit_score, reasons, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, user_id, str(job.get("id", "")), job.get("title") or "", job.get("company") or "",
             job.get("location") or "", job.get("url") or "", outcome, int(practice), fit_score,
             json.dumps(list(reasons), ensure_ascii=False), now, now))
    con.close()
    return run_id


_RUN_FIELDS = {"outcome", "practice", "fit_score", "reasons", "questions", "notes", "cv_doc_id", "letter_doc_id",
               "application_id"}


def update_autopilot_run(run_id: str, *, user_id: str, **fields) -> bool:
    unknown = set(fields) - _RUN_FIELDS
    if unknown:
        raise ValueError(f"unknown autopilot run fields: {sorted(unknown)}")
    if "outcome" in fields and fields["outcome"] not in AUTOPILOT_OUTCOMES:
        raise ValueError(f"outcome must be one of {AUTOPILOT_OUTCOMES}")
    for name in ("reasons", "questions"):
        if name in fields:
            fields[name] = json.dumps(list(fields[name]), ensure_ascii=False)
    if "practice" in fields:
        fields["practice"] = int(bool(fields["practice"]))
    fields["updated_at"] = _now()
    con = sqlite3.connect(_DB_PATH)
    with con:
        cur = con.execute(f"UPDATE autopilot_runs SET {', '.join(f'{k}=?' for k in fields)} WHERE id=? AND user_id=?",
                          [*fields.values(), run_id, user_id])
    con.close()
    return cur.rowcount == 1


def get_autopilot_run(user_id: str, run_id: str) -> dict | None:
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT * FROM autopilot_runs WHERE id=? AND user_id=?", (run_id, user_id)).fetchone()
    con.close()
    return _autopilot_run(row) if row else None


def list_autopilot_runs(user_id: str, limit: int = 200) -> list[dict]:
    """The user's autopilot runs, latest first."""
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT * FROM autopilot_runs WHERE user_id=? ORDER BY updated_at DESC LIMIT ?",
                       (user_id, limit)).fetchall()
    con.close()
    return [_autopilot_run(r) for r in rows]


def autopilot_tried(user_id: str, *, count_practice: bool = True) -> set[str]:
    """Job ids autopilot has already dealt with. With count_practice=False, jobs it only filled in practice
    mode don't count, so a live run tries them for real."""
    sql = "SELECT job_id FROM autopilot_runs WHERE user_id=?"
    if not count_practice:
        sql += " AND NOT (practice=1 AND outcome IN ('ready', 'needs_you'))"
    con = sqlite3.connect(_DB_PATH)
    rows = con.execute(sql, (user_id,)).fetchall()
    con.close()
    return {r[0] for r in rows}


def autopilot_sent_since(user_id: str, since: str) -> int:
    """Applications autopilot sent (or clicked submit on) since `since`, an ISO timestamp."""
    con = sqlite3.connect(_DB_PATH)
    row = con.execute("SELECT count(*) FROM autopilot_runs WHERE user_id=? AND outcome IN ('submitted', 'unconfirmed') "
                      "AND updated_at >= ?", (user_id, since)).fetchone()
    con.close()
    return row[0]


def finish_stale_autopilot_runs() -> None:
    """Runs left 'running' by a restart are over: nothing is working on them now."""
    con = sqlite3.connect(_DB_PATH)
    with con:
        con.execute("UPDATE autopilot_runs SET outcome='failed', reasons=?, updated_at=? WHERE outcome='running'",
                    (json.dumps(["Windrush restarted while this was in progress."]), _now()))
    con.close()


# ── Gmail tracking (see gmail.py) ─────────────────────────────────────────────
# One connected Gmail account per user (its refresh token encrypted), and one row per email that was read
# as being about an application, with what it meant and what Windrush did about it.

def _gmail_tables(con: sqlite3.Connection) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS gmail_accounts (
        user_id           TEXT PRIMARY KEY,
        email             TEXT NOT NULL,
        refresh_token_enc TEXT NOT NULL,
        connected_at      TEXT NOT NULL,
        synced_until      INTEGER,
        last_sync_at      TEXT,
        problem           TEXT
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS email_events (
        id             TEXT PRIMARY KEY,
        user_id        TEXT NOT NULL,
        gmail_id       TEXT NOT NULL,
        thread_id      TEXT,
        received_at    TEXT NOT NULL,
        sender         TEXT NOT NULL,
        subject        TEXT NOT NULL,
        snippet        TEXT NOT NULL DEFAULT '',
        kind           TEXT NOT NULL,
        company        TEXT NOT NULL DEFAULT '',
        role           TEXT NOT NULL DEFAULT '',
        summary        TEXT NOT NULL DEFAULT '',
        application_id TEXT,
        proposed       TEXT,
        decision       TEXT NOT NULL,
        status_before  TEXT,
        created_at     TEXT NOT NULL
    )""")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_email_events_msg ON email_events(user_id, gmail_id)")


# What an email says happened. 'other' is about an application but changes nothing (we're reviewing it…).
EMAIL_KINDS = ("received", "assessment", "interview", "offer", "rejected", "other")
# applied: Windrush changed the application's status · suggested: a change that waits for the user ·
# unmatched: about an application Windrush couldn't pin down · noted: matched, nothing to change ·
# confirmed / dismissed / undone: what the user did with it.
EMAIL_DECISIONS = ("applied", "suggested", "unmatched", "noted", "confirmed", "dismissed", "undone")


def _gmail_con() -> sqlite3.Connection:
    con = sqlite3.connect(_DB_PATH)
    _gmail_tables(con)
    return con


def save_gmail_account(user_id: str, email: str, refresh_token: str) -> None:
    con = _gmail_con()
    with con:
        con.execute("INSERT INTO gmail_accounts (user_id, email, refresh_token_enc, connected_at) VALUES (?,?,?,?) "
                    "ON CONFLICT(user_id) DO UPDATE SET email=excluded.email, refresh_token_enc=excluded.refresh_token_enc, "
                    "connected_at=excluded.connected_at, problem=NULL",
                    (user_id, email, crypto.encrypt(refresh_token), _now()))
    con.close()


def get_gmail_account(user_id: str) -> dict | None:
    """{email, refresh_token, connected_at, synced_until, last_sync_at, problem}, or None if not connected."""
    con = _gmail_con()
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT * FROM gmail_accounts WHERE user_id=?", (user_id,)).fetchone()
    con.close()
    if not row:
        return None
    account = dict(row)
    account["refresh_token"] = crypto.decrypt(account.pop("refresh_token_enc") or "")
    return account


def gmail_users() -> list[str]:
    con = _gmail_con()
    rows = con.execute("SELECT user_id FROM gmail_accounts WHERE problem IS NULL").fetchall()
    con.close()
    return [r[0] for r in rows]


def update_gmail_account(user_id: str, **fields) -> None:
    allowed = {"synced_until", "last_sync_at", "problem"}
    if set(fields) - allowed:
        raise ValueError(f"unknown gmail account fields: {sorted(set(fields) - allowed)}")
    con = _gmail_con()
    with con:
        con.execute(f"UPDATE gmail_accounts SET {', '.join(f'{k}=?' for k in fields)} WHERE user_id=?",
                    [*fields.values(), user_id])
    con.close()


def delete_gmail_account(user_id: str) -> None:
    con = _gmail_con()
    with con:
        con.execute("DELETE FROM gmail_accounts WHERE user_id=?", (user_id,))
    con.close()


def email_seen(user_id: str, gmail_id: str) -> bool:
    con = _gmail_con()
    row = con.execute("SELECT 1 FROM email_events WHERE user_id=? AND gmail_id=?", (user_id, gmail_id)).fetchone()
    con.close()
    return row is not None


def add_email_event(user_id: str, event: dict) -> str:
    if event["kind"] not in EMAIL_KINDS + ("unrelated",):
        raise ValueError(f"kind must be one of {EMAIL_KINDS}")
    if event["decision"] not in EMAIL_DECISIONS + ("ignored",):
        raise ValueError(f"decision must be one of {EMAIL_DECISIONS}")
    event_id = uuid.uuid4().hex
    con = _gmail_con()
    with con:
        con.execute(
            "INSERT OR IGNORE INTO email_events (id, user_id, gmail_id, thread_id, received_at, sender, subject, snippet, "
            "kind, company, role, summary, application_id, proposed, decision, status_before, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (event_id, user_id, event["gmail_id"], event.get("thread_id"), event["received_at"], event["sender"][:300],
             event["subject"][:300], event.get("snippet", "")[:300], event["kind"], event.get("company", "")[:200],
             event.get("role", "")[:200], event.get("summary", "")[:300], event.get("application_id"),
             event.get("proposed"), event["decision"], event.get("status_before"), _now()))
    con.close()
    return event_id


def list_email_events(user_id: str, limit: int = 200) -> list[dict]:
    """The user's email events about applications (not the ones read as unrelated), latest email first."""
    con = _gmail_con()
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT e.*, a.job_title AS app_title, a.company AS app_company, a.status AS app_status "
                       "FROM email_events e LEFT JOIN applications a ON a.id = e.application_id AND a.user_id = e.user_id "
                       "WHERE e.user_id=? AND e.decision != 'ignored' ORDER BY e.received_at DESC LIMIT ?",
                       (user_id, limit)).fetchall()
    con.close()
    return [dict(r) for r in rows]


def get_email_event(user_id: str, event_id: str) -> dict | None:
    con = _gmail_con()
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT * FROM email_events WHERE id=? AND user_id=?", (event_id, user_id)).fetchone()
    con.close()
    return dict(row) if row else None


def update_email_event(user_id: str, event_id: str, **fields) -> bool:
    allowed = {"decision", "application_id", "proposed", "status_before"}
    if set(fields) - allowed:
        raise ValueError(f"unknown email event fields: {sorted(set(fields) - allowed)}")
    con = _gmail_con()
    with con:
        cur = con.execute(f"UPDATE email_events SET {', '.join(f'{k}=?' for k in fields)} WHERE id=? AND user_id=?",
                          [*fields.values(), event_id, user_id])
    con.close()
    return cur.rowcount == 1


def get_application(user_id: str, app_id: str) -> dict | None:
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT id, job_title, company, status, date_applied, created_at FROM applications "
                      "WHERE id=? AND user_id=?", (app_id, user_id)).fetchone()
    con.close()
    return dict(row) if row else None


# ── Profile suggestions (see enrich.py) ───────────────────────────────────────
# What the user's GitHub, website or LinkedIn export say that the persona doesn't, one row per change it
# would make. fingerprint names the change (not its wording), so a dismissed one isn't offered again when
# the source is read again. data is the suggestion as enrich.py builds it.

def _suggestion_tables(con: sqlite3.Connection) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS profile_suggestions (
        id          TEXT PRIMARY KEY,
        user_id     TEXT NOT NULL,
        source      TEXT NOT NULL,
        fingerprint TEXT NOT NULL,
        data        TEXT NOT NULL,
        status      TEXT NOT NULL DEFAULT 'pending',
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    )""")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_profile_suggestions_fp ON profile_suggestions(user_id, fingerprint)")


# pending: waiting on the user · accepted: added to the persona · dismissed: the user said no ·
# outdated: the persona already has it now (the user added it themselves, or accepted another suggestion).
SUGGESTION_STATUSES = ("pending", "accepted", "dismissed", "outdated")


def _suggestion_con() -> sqlite3.Connection:
    con = sqlite3.connect(_DB_PATH)
    _suggestion_tables(con)
    return con


def _suggestion_row(row: sqlite3.Row) -> dict:
    return {**json.loads(row["data"]), "id": row["id"], "source": row["source"], "status": row["status"],
            "created_at": row["created_at"]}


def save_suggestions(user_id: str, source: str, suggestions: list[dict]) -> int:
    """Store what a fresh read of `source` suggests: changes not seen before are added; ones still waiting
    from an earlier read that this one no longer suggests are dropped. Returns how many were added."""
    now = _now()
    fresh = {s["fingerprint"]: s for s in suggestions}
    con = _suggestion_con()
    with con:
        seen = {fp for (fp,) in con.execute("SELECT fingerprint FROM profile_suggestions WHERE user_id=?", (user_id,))}
        stale = [fp for (fp,) in con.execute(
            "SELECT fingerprint FROM profile_suggestions WHERE user_id=? AND source=? AND status='pending'",
            (user_id, source)) if fp not in fresh]
        con.executemany("DELETE FROM profile_suggestions WHERE user_id=? AND fingerprint=?",
                        [(user_id, fp) for fp in stale])
        new = [s for fp, s in fresh.items() if fp not in seen]
        con.executemany(
            "INSERT INTO profile_suggestions (id, user_id, source, fingerprint, data, status, created_at, updated_at) "
            "VALUES (?,?,?,?,?,'pending',?,?)",
            [(uuid.uuid4().hex, user_id, source, s["fingerprint"], json.dumps(s), now, now) for s in new])
    con.close()
    return len(new)


def list_suggestions(user_id: str, status: str = "pending") -> list[dict]:
    con = _suggestion_con()
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT * FROM profile_suggestions WHERE user_id=? AND status=? ORDER BY rowid",
                       (user_id, status)).fetchall()
    con.close()
    return [_suggestion_row(r) for r in rows]


def get_suggestions(user_id: str, ids: list[str]) -> list[dict]:
    if not ids:
        return []
    con = _suggestion_con()
    con.row_factory = sqlite3.Row
    rows = con.execute(f"SELECT * FROM profile_suggestions WHERE user_id=? AND id IN ({','.join('?' * len(ids))}) "
                       "ORDER BY rowid", (user_id, *ids)).fetchall()
    con.close()
    return [_suggestion_row(r) for r in rows]


def set_suggestion_status(user_id: str, ids: list[str], status: str) -> int:
    if status not in SUGGESTION_STATUSES:
        raise ValueError(f"unknown suggestion status: {status}")
    if not ids:
        return 0
    con = _suggestion_con()
    with con:
        cur = con.execute(f"UPDATE profile_suggestions SET status=?, updated_at=? "
                          f"WHERE user_id=? AND id IN ({','.join('?' * len(ids))})", (status, _now(), user_id, *ids))
    con.close()
    return cur.rowcount
