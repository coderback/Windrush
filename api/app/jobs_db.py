"""
SQLite-backed job database for Windrush job feed.
"""
import functools
import json
import logging
import os
import re
import sqlite3
import uuid
import numpy as np
from datetime import datetime, timedelta, timezone

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
    expires_at      TEXT,
    sponsorship     TEXT,
    sponsorship_evidence TEXT,
    clearance       TEXT,
    sponsor_key     TEXT,
    years_min       INTEGER,
    degree          TEXT,
    attributes_version INTEGER,
    attributes_tries   INTEGER
);
"""

# The Home Office register of licensed sponsors, Skilled Worker route (see sponsor_register.py),
# keyed by company_names.normalise_company_name — what jobs.sponsor_key holds.
_CREATE_SPONSORS_TABLE = """
CREATE TABLE IF NOT EXISTS sponsors (
    norm_name TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    town      TEXT
);
"""
_CREATE_SPONSOR_REGISTER_TABLE = """
CREATE TABLE IF NOT EXISTS sponsor_register (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    fetched_at    TEXT NOT NULL,
    source_url    TEXT,
    organisations INTEGER
);
"""

# Scheduled collections (discovery.keep_collecting): kept so the schedule survives restarts and the
# feed can say when it was last refreshed.
_CREATE_COLLECTIONS_TABLE = """
CREATE TABLE IF NOT EXISTS collections (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    searches    TEXT,
    locations   TEXT,
    found       INTEGER,
    added       INTEGER,
    refreshed   INTEGER,
    expired     INTEGER,
    error       TEXT
);
"""
# Job boards (see job_searcher.find_board / check_board): every board checked or found, whether it's
# gone, and which employers have been looked up, so a lookup isn't repeated every collection.
_CREATE_BOARDS_TABLE = """
CREATE TABLE IF NOT EXISTS boards (
    ats        TEXT NOT NULL,
    slug       TEXT NOT NULL,
    company    TEXT,
    origin     TEXT NOT NULL,          -- 'listed' (in job_searcher) or 'found'
    gone       INTEGER NOT NULL DEFAULT 0,
    jobs       INTEGER,
    found_at   TEXT,
    checked_at TEXT,
    PRIMARY KEY (ats, slug)
);
"""
_CREATE_BOARD_LOOKUPS_TABLE = """
CREATE TABLE IF NOT EXISTS board_lookups (
    company_key TEXT PRIMARY KEY,
    company     TEXT,
    looked_at   TEXT NOT NULL,
    found       TEXT
);
"""
# When a rate-limited source last ran, whoever ran it (see discovery: the web search is once a day).
_CREATE_SOURCE_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS source_runs (
    source TEXT PRIMARY KEY,
    ran_at TEXT NOT NULL
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
        for column in ("sponsorship TEXT", "sponsorship_evidence TEXT", "clearance TEXT", "sponsor_key TEXT",
                       "years_min INTEGER", "degree TEXT", "attributes_version INTEGER", "attributes_tries INTEGER"):
            try: con.execute(f"ALTER TABLE jobs ADD COLUMN {column}")
            except sqlite3.OperationalError: pass
        con.execute(_CREATE_SPONSORS_TABLE)
        con.execute(_CREATE_SPONSOR_REGISTER_TABLE)
        con.execute(_CREATE_COLLECTIONS_TABLE)
        con.execute(_CREATE_SOURCE_RUNS_TABLE)
        con.execute(_CREATE_BOARDS_TABLE)
        con.execute(_CREATE_BOARD_LOOKUPS_TABLE)

        # Ensure older rows have a normalized_company before we create/recreate the index
        con.execute("UPDATE jobs SET normalized_company = lower(company) WHERE normalized_company IS NULL")
        
        # Drop old index if it exists and create the new one
        con.execute("DROP INDEX IF EXISTS idx_dedup_jobs")
        con.execute(_CREATE_INDEX)

        version = con.execute("PRAGMA user_version").fetchone()[0]
        if version < 1:
            _reclassify_levels(con)
        if version < 2:
            _classify_sponsorship(con)
            con.execute("PRAGMA user_version = 2")

        con.commit()
        con.close()
        logger.info("Jobs DB initialised at %s", _DB_PATH)
    except Exception as exc:
        logger.error("Failed to initialise jobs DB: %s", exc)

def _reclassify_levels(con: sqlite3.Connection) -> None:
    """One-off: re-derive every stored job's level with seniority.infer_level (older rows used a
    title-only substring match)."""
    rows = con.execute("SELECT id, title, description, level FROM jobs").fetchall()
    changes = [(new, row_id) for row_id, title, desc, old in rows
               if (new := seniority.infer_level(title or "", desc or "")) != old]
    con.executemany("UPDATE jobs SET level = ? WHERE id = ?", changes)
    if changes:
        logger.info("Reclassified the seniority of %d of %d stored jobs", len(changes), len(rows))


def _sponsorship_columns(company: str, title: str, description: str) -> tuple[str, str, str, str]:
    """(sponsorship, sponsorship_evidence, clearance, sponsor_key) for a job."""
    found = signals.classify(title, description)
    return found.sponsorship, found.evidence, found.clearance, normalise_company_name(company)


def _classify_sponsorship(con: sqlite3.Connection) -> None:
    """One-off: sponsorship / clearance signals and sponsor keys for jobs stored before they existed."""
    rows = con.execute("SELECT id, company, title, description FROM jobs").fetchall()
    con.executemany(
        "UPDATE jobs SET sponsorship = ?, sponsorship_evidence = ?, clearance = ?, sponsor_key = ? WHERE id = ?",
        [(*_sponsorship_columns(company or "", title or "", desc or ""), row_id)
         for row_id, company, title, desc in rows])
    if rows:
        logger.info("Read the sponsorship signals of %d stored jobs", len(rows))


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
    # Only an ad that offers it: "we cannot sponsor" mentions sponsorship too.
    if signals.classify(job.get("title", ""), job.get("description", "")).sponsorship == signals.OFFERED:
        tags.add("sponsorship")
    if any(w in text for w in ["remote", "work from home", "telecommute", "anywhere"]): tags.add("remote")
    
    return json.dumps(list(tags))

from . import semantic
from . import seniority
from . import sponsorship as signals
from .company_names import normalise_company_name
from .job_attributes import ATTRIBUTES_VERSION

# Tags recognised in the `tags` filter (must match what _extract_tags writes). Role tags are
# OR'd ("ml or data"); domain tags are AND'd ("fintech and sponsorship"). Any other tag is
# free text — the search box sends typed terms as tags — and must appear in the job's
# title, company or description.
ROLE_TAGS = frozenset({"software", "ml", "ai", "data", "backend", "frontend", "fullstack",
                       "devops", "security", "analyst", "engineer", "developer"})
DOMAIN_TAGS = frozenset({"fintech", "startup", "sponsorship", "remote"})

# The feed's sponsorship filter, for a candidate who needs a visa sponsored:
#   any      - no filter
#   possible - hide jobs that rule them out (the ad says no sponsorship, or needs SC/DV clearance)
#   likely   - only jobs that offer it or whose employer is a licensed sponsor, and don't rule it out
SPONSORSHIP_FILTERS = ("any", "possible", "likely")
_LICENSED = "(sponsor_key IN (SELECT norm_name FROM sponsors))"
# SQL twin of sponsorship.rules_out_sponsored_candidates.
_NOT_RULED_OUT = "(coalesce(sponsorship, '') != 'not_offered' AND coalesce(clearance, '') NOT IN ('SC', 'DV'))"


def _sponsorship_filter(mode: str, marks: dict[str, str]) -> tuple[str, list]:
    """WHERE clause for a sponsorship filter mode; the user's marks win over the ad and the register."""
    auto = _NOT_RULED_OUT if mode == "possible" else f"({_NOT_RULED_OUT} AND (sponsorship = 'offered' OR {_LICENSED}))"
    marked_yes = [job_id for job_id, mark in marks.items() if mark == signals.OFFERED]
    marked_no = [job_id for job_id, mark in marks.items() if mark == signals.NOT_OFFERED]
    if marked_no:
        auto = f"(id NOT IN ({','.join('?' * len(marked_no))}) AND {auto})"
    if marked_yes:
        auto = f"(id IN ({','.join('?' * len(marked_yes))}) OR {auto})"
    return auto, marked_yes + marked_no

# Most-recent matching rows that are ranked per request. Bounds per-request work (rows,
# vector BLOBs, numpy) as the table grows; matches older than this aren't reachable.
_CANDIDATE_POOL = 2000

# Country-level location aliases. SQL uses them as a LIKE superset; the precise check is a
# word-boundary regex in Python (so 'us' matches "Austin, TX, US" but not "Australia").
# UK towns an ad may name on its own ("Cambridge", "Melbourn" for Cambridge Consultants), beyond the
# cities in the alias. Left out: names a bigger place abroad has (Boston, Washington, Richmond, Greenwich,
# Perth, Portland, Kingston, York as in New York). A place counts as the UK only where nothing beside it
# says it's abroad (_ABROAD: "Cambridge, MA" isn't).
_UK_TOWNS = [
    "cambridge", "oxford", "reading", "bath", "guildford", "milton keynes", "harwell", "didcot", "abingdon",
    "melbourn", "bracknell", "slough", "basingstoke", "swindon", "nottingham", "sheffield", "liverpool",
    "newcastle", "sunderland", "southampton", "portsmouth", "brighton", "coventry", "leicester", "derby",
    "exeter", "plymouth", "norwich", "ipswich", "colchester", "chelmsford", "peterborough", "aberdeen", "dundee",
    "stirling", "inverness", "swansea", "warwick", "leamington spa", "cheltenham", "gloucester", "stevenage",
    "hatfield", "watford", "st albans", "crawley", "farnborough", "woking", "maidenhead", "luton", "northampton",
    "solihull", "wolverhampton", "stoke-on-trent", "loughborough", "durham", "lancaster", "preston", "bolton",
    "hull", "bradford", "huddersfield", "salford", "stockport", "chester", "bournemouth", "poole", "canary wharf",
    "lincoln", "worcester", "telford", "warrington", "wakefield", "middlesbrough", "darlington", "harrogate",
]
_LOCATION_ALIASES = {
    "uk": ["uk", "united kingdom", "england", "scotland", "wales", "northern ireland", "london", "bristol",
           "manchester", "birmingham", "leeds", "edinburgh", "glasgow", "cardiff", "belfast", *_UK_TOWNS],
    "us": ["us", "usa", "united states", "new york", "san francisco", "california", "seattle"],
}
_UK_TERMS = frozenset(_LOCATION_ALIASES["uk"])
# Beside a UK place name, these mean it's the other one: a country, a US state / Canadian province /
# Australian state (named, or as a code after a comma: "Cambridge, MA 02139", not "London, on-site").
_STATE_CODES = ("al|ak|az|ar|ca|co|ct|dc|de|fl|ga|hi|ia|id|il|in|ks|ky|la|ma|md|me|mi|mn|mo|ms|mt|nc|nd|ne|nh|nj|"
                "nm|nv|ny|oh|ok|or|pa|ri|sc|sd|tn|tx|ut|va|vt|wa|wi|wv|wy|on|bc|qc|ab|nsw|vic|qld")
_ABROAD = re.compile(
    r"\b(?:usa|u\.s\.a?\.?|united states|america|canada|australia|new zealand|india|singapore|hong kong|"
    r"germany|france|netherlands|spain|italy|switzerland|poland|portugal|sweden|denmark|norway|finland|belgium|"
    r"austria|japan|china|brazil|mexico|uae|dubai|israel|(?<!northern )ireland|new south wales|ontario|"
    r"massachusetts|connecticut|new hampshire|new jersey|pennsylvania|virginia|texas|maryland|north carolina|"
    r"mississippi|alabama|ohio|washington,? ?d\.?c\.?)\b"
    rf"|,\s*(?:{_STATE_CODES})(?=\s*(?:$|[,;)/|(]|\d))", re.I)
# One location string may list several places: "London, UK; Boston, MA", "Stamford/New York".
_LOCATION_PARTS = re.compile(r";|\||/|\bor\b|&", re.I)
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
                    salary_min, salary_max, exposure_score, level, source, tags, semantic_vector, created_at, updated_at,
                    expires_at, sponsorship, sponsorship_evidence, clearance, sponsor_key)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    uuid.uuid4().hex, str(job.get("job_id", "")), job.get("title", ""), job.get("company", ""),
                    _normalize_company(job.get("company", "")), job.get("location", ""), job.get("description", ""),
                    job.get("url", ""), job.get("salary_min"), job.get("salary_max"), job.get("exposure_score"),
                    job.get("level") or seniority.infer_level(job.get("title", ""), job.get("description", "")),
                    job.get("source", "unknown"), _extract_tags(job), blob_for.get(id(job)),
                    now_str, now_str, job.get("expires_at"),
                    *_sponsorship_columns(job.get("company", ""), job.get("title", ""), job.get("description", "")),
                ),
            )
            added += 1
        except sqlite3.IntegrityError:  # inserted concurrently since step 1 — refresh instead
            existing.append(("", job, False))
        except Exception as exc:
            logger.error("Failed to insert job %s: %s", job.get("title"), exc)
    for row_id, job, _ in existing:
        # Seen again, so still open: a job expire_unseen() hid comes back.
        con.execute(
            """UPDATE jobs SET updated_at = ?, tags = ?, semantic_vector = COALESCE(semantic_vector, ?), expires_at = ?
               WHERE lower(normalized_company)=? AND lower(title)=? AND lower(location)=?""",
            (now_str, _extract_tags(job), blob_for.get(id(job)), job.get("expires_at"), *_job_key(job)),
        )
        updated += 1
    con.commit()
    con.close()
    return added, updated


def expire_unseen(before: str) -> int:
    """Expire every live job last seen before `before` (an ISO time): it has closed, or no search looks
    for it any more. It leaves the feed and autopilot but keeps its row, so a job page, a mark or an
    application that points at it still works, and add_jobs revives it if a source lists it again."""
    if not _DB_PATH:
        init_db()
    con = sqlite3.connect(_DB_PATH)
    with con:
        cur = con.execute("UPDATE jobs SET expires_at = ? WHERE expires_at IS NULL "
                          "AND coalesce(updated_at, created_at) < ?", (_now(), before))
    con.close()
    return cur.rowcount


# ── Collections and rate-limited sources (see discovery.py) ──────────────────

def start_collection(searches: list[str], locations: list[str]) -> int:
    if not _DB_PATH:
        init_db()
    con = sqlite3.connect(_DB_PATH)
    with con:
        cur = con.execute("INSERT INTO collections (started_at, searches, locations) VALUES (?, ?, ?)",
                          (_now(), json.dumps(searches), json.dumps(locations)))
    con.close()
    return cur.lastrowid


def finish_collection(run_id: int, *, found: int = 0, added: int = 0, refreshed: int = 0, expired: int = 0,
                      error: str = "") -> None:
    con = sqlite3.connect(_DB_PATH)
    with con:
        con.execute("UPDATE collections SET finished_at = ?, found = ?, added = ?, refreshed = ?, expired = ?, "
                    "error = ? WHERE id = ?", (_now(), found, added, refreshed, expired, error or None, run_id))
    con.close()


def last_collection() -> dict | None:
    """The latest collection, finished or not, else None."""
    if not _DB_PATH:
        init_db()
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT * FROM collections ORDER BY id DESC LIMIT 1").fetchone()
    con.close()
    if not row:
        return None
    run = dict(row)
    run["searches"], run["locations"] = json.loads(run["searches"] or "[]"), json.loads(run["locations"] or "[]")
    return run


# ── Job boards (see job_searcher.find_board) ─────────────────────────────────

# Jobs from these come from an employer's own board already; anything else (the aggregators, the web
# search, Workable's job board, career pages) names an employer whose board may be worth finding.
_FROM_A_BOARD = "(job_id LIKE 'gh-%' OR job_id LIKE 'ashby-%' OR job_id LIKE 'lever-%' OR job_id LIKE 'sr-%' " \
                "OR (job_id LIKE 'workable-%' AND job_id NOT LIKE 'workable-global-%'))"


def found_boards() -> list[tuple[str, str, str]]:
    """(ats, slug, company) of the boards find_board found that are still there."""
    if not _DB_PATH:
        init_db()
    con = sqlite3.connect(_DB_PATH)
    rows = con.execute("SELECT ats, slug, company FROM boards WHERE origin = 'found' AND gone = 0").fetchall()
    con.close()
    return [tuple(r) for r in rows]


def gone_boards() -> set[tuple[str, str]]:
    """(ats, slug) of the boards a check found removed."""
    if not _DB_PATH:
        init_db()
    con = sqlite3.connect(_DB_PATH)
    rows = con.execute("SELECT ats, slug FROM boards WHERE gone = 1").fetchall()
    con.close()
    return {tuple(r) for r in rows}


def boards_due_check(listed: list[tuple[str, str, str]], every_days: float, limit: int) -> list[tuple[str, str]]:
    """Up to `limit` (ats, slug) of the listed and found boards not checked for `every_days`, the
    longest-unchecked first (never-checked before all)."""
    if not _DB_PATH:
        init_db()
    con = sqlite3.connect(_DB_PATH)
    known = {(a, s): (gone, checked) for a, s, gone, checked in
             con.execute("SELECT ats, slug, gone, checked_at FROM boards").fetchall()}
    con.close()
    boards = list(dict.fromkeys([(a, s) for a, s, _ in listed] + [(a, s) for a, s, _ in found_boards()]))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=every_days)).isoformat()
    due = [b for b in boards if not known.get(b, (0, None))[0] and (known.get(b, (0, None))[1] or "") < cutoff]
    due.sort(key=lambda b: known.get(b, (0, None))[1] or "")
    return due[:limit]


def record_board_checks(alive: list[tuple[str, str, int]], gone: list[tuple[str, str]],
                        listed: list[tuple[str, str, str]]) -> None:
    if not _DB_PATH:
        init_db()
    company = {(a, s): c for a, s, c in listed}
    now = _now()
    con = sqlite3.connect(_DB_PATH)
    with con:
        for (ats, slug, jobs), is_gone in [*((b, 0) for b in alive), *(((a, s, None), 1) for a, s in gone)]:
            con.execute("INSERT INTO boards (ats, slug, company, origin, gone, jobs, checked_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT(ats, slug) DO UPDATE SET gone = excluded.gone, "
                        "jobs = coalesce(excluded.jobs, boards.jobs), checked_at = excluded.checked_at",
                        (ats, slug, company.get((ats, slug)), "listed" if (ats, slug) in company else "found",
                         is_gone, jobs, now))
    con.close()


def save_found_boards(found: list[tuple[str, str, str, int]]) -> None:
    """Store boards find_board found ((ats, slug, company, jobs)); one found again comes back if gone."""
    if not _DB_PATH:
        init_db()
    now = _now()
    con = sqlite3.connect(_DB_PATH)
    with con:
        for ats, slug, company, jobs in found:
            con.execute("INSERT INTO boards (ats, slug, company, origin, gone, jobs, found_at, checked_at) "
                        "VALUES (?, ?, ?, 'found', 0, ?, ?, ?) ON CONFLICT(ats, slug) DO UPDATE SET gone = 0, "
                        "jobs = excluded.jobs, checked_at = excluded.checked_at", (ats, slug, company, jobs, now, now))
    con.close()


def employers_to_look_up(limit: int, retry_days: float, have_boards: list[tuple[str, str, str]]) -> list[str]:
    """Up to `limit` employers named by live jobs that didn't come from a board, whose board isn't known
    (`have_boards`: (ats, slug, company)) and who haven't been looked up for `retry_days`: licensed
    sponsors first, then those with the most jobs."""
    if not _DB_PATH:
        init_db()
    con = sqlite3.connect(_DB_PATH)
    rows = con.execute(
        f"SELECT company, count(*) AS n, max({_LICENSED}) AS sponsor FROM jobs "
        f"WHERE expires_at IS NULL AND coalesce(company, '') != '' AND NOT {_FROM_A_BOARD} "
        "GROUP BY lower(company) ORDER BY sponsor DESC, n DESC").fetchall()
    looked = {k: t for k, t in con.execute("SELECT company_key, looked_at FROM board_lookups").fetchall()}
    con.close()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retry_days)).isoformat()
    have = {normalise_company_name(c) for _, _, c in have_boards}
    out, seen = [], set()
    for company, _, _ in rows:
        key = normalise_company_name(company)
        if not key or key in seen or key in have or looked.get(key, "") >= cutoff:
            continue
        seen.add(key)
        out.append(company)
        if len(out) >= limit:
            break
    return out


def mark_looked_up(companies: list[str], found: dict[str, str]) -> None:
    """Record that `companies` were looked up; `found` maps a company to "ats/slug" for the hits."""
    if not _DB_PATH:
        init_db()
    now = _now()
    con = sqlite3.connect(_DB_PATH)
    with con:
        con.executemany("INSERT INTO board_lookups (company_key, company, looked_at, found) VALUES (?, ?, ?, ?) "
                        "ON CONFLICT(company_key) DO UPDATE SET looked_at = excluded.looked_at, found = excluded.found",
                        [(normalise_company_name(c), c, now, found.get(c)) for c in companies])
    con.close()


def source_due(source: str, every_s: float) -> bool:
    """Whether `source` last ran over `every_s` seconds ago (or never)."""
    if not _DB_PATH:
        init_db()
    con = sqlite3.connect(_DB_PATH)
    row = con.execute("SELECT ran_at FROM source_runs WHERE source = ?", (source,)).fetchone()
    con.close()
    if not row:
        return True
    return (datetime.now(timezone.utc) - datetime.fromisoformat(row[0])).total_seconds() >= every_s


def mark_source_run(source: str) -> None:
    if not _DB_PATH:
        init_db()
    con = sqlite3.connect(_DB_PATH)
    with con:
        con.execute("INSERT INTO source_runs (source, ran_at) VALUES (?, ?) "
                    "ON CONFLICT(source) DO UPDATE SET ran_at = excluded.ran_at", (source, _now()))
    con.close()


def _like(term: str) -> str:
    """LIKE pattern for a user-supplied term with %, _ and the escape char escaped (ESCAPE '\\')."""
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _location_matcher(location: str):
    """(sql, params, matches) for one location filter: a LIKE clause as a SQL superset, and a
    precise whole-word check of a job's location string."""
    loc = location.lower().strip()
    terms = _LOCATION_ALIASES.get(_LOCATION_ALIAS_KEYS.get(loc, ""), [loc])
    regex = re.compile(r"(?<![a-z])(" + "|".join(re.escape(t) for t in terms) + r")(?![a-z])")
    # "London" (or the UK alias, which includes it) means London, England — unless the user is
    # explicitly searching for the Canadian / US ones.
    exclude_other_londons = "london" in terms and not any(x in loc for x in ("ontario", "new london", "canada"))

    sql = "(" + " OR ".join("lower(location) LIKE ? ESCAPE '\\'" for _ in terms) + ")"
    params = [_like(t) for t in terms]
    if exclude_other_londons:
        # Also in SQL, scoped to this location's clause: otherwise those rows fill the candidate
        # pool and push UK jobs out, while another location (e.g. Toronto) may still want Ontario.
        sql = f"({sql} AND lower(location) NOT LIKE '%ontario%' AND lower(location) NOT LIKE '%new london%')"

    # The UK or a place in it: each listed place is checked on its own, and one that also names somewhere
    # abroad doesn't count ("Cambridge, MA", "Sydney, New South Wales").
    uk_place = all(t in _UK_TERMS for t in terms)

    def matches(job_location: str) -> bool:
        for part in (_LOCATION_PARTS.split(job_location) if uk_place else [job_location]):
            if not regex.search(part):
                continue
            if exclude_other_londons and ("ontario" in part or "new london" in part):
                continue
            if uk_place and _ABROAD.search(part):
                continue
            return True
        return False
    return sql, params, matches


def _locations_clause(location: str | list[str], remote: bool = False) -> tuple[str, list, list, bool]:
    """(sql, params, matchers, remote) for a location filter: one location or a list (any of them matches;
    "remote" in it means remote jobs too). The SQL is a LIKE superset; `matchers` are the precise checks.
    sql is "" when nothing is filtered."""
    locations = [loc.strip() for loc in ([location] if isinstance(location, str) else location or [])
                 if loc and loc.strip()]
    if any(loc.lower() == "remote" for loc in locations):
        remote = True
        locations = [loc for loc in locations if loc.lower() != "remote"]
    matchers = [_location_matcher(loc) for loc in locations]
    remote_sql = "(" + " OR ".join("lower(location) LIKE ?" for _ in _REMOTE_TERMS) + ")"
    remote_params = [f"%{t}%" for t in _REMOTE_TERMS]
    if not matchers:
        return (remote_sql, remote_params, matchers, remote) if remote else ("", [], matchers, remote)
    loc_sql = "(" + " OR ".join(sql for sql, _, _ in matchers) + ")"
    loc_params = [p for _, ps, _ in matchers for p in ps]
    if remote:  # "in <location>, or remote"
        return f"({loc_sql} OR {remote_sql})", loc_params + remote_params, matchers, remote
    return loc_sql, loc_params, matchers, remote


def in_locations(job_location: str, locations: list[str]) -> bool:
    """Whether a job belongs to a search over `locations`: it's in one of them (as the feed's location
    filter reads them), remote, or its source didn't say where."""
    loc = (job_location or "").lower().strip()
    wanted = [l for l in locations or [] if l and l.strip() and l.strip().lower() != "remote"]
    if not loc or not wanted or any(t in loc for t in _REMOTE_TERMS):
        return True
    return any(matches(loc) for _, _, matches in map(_location_matcher, wanted))


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
    location: str | list[str] = "",
    level: str = "",
    category: str = "",
    remote: bool = False,
    tags: list[str] = None,
    persona_vector: list[float] = None,
    limit: int = 20,
    offset: int = 0,
    exclude: set[tuple[str, str]] | None = None,
    sponsorship: str = "",
    marks: dict[str, str] | None = None,
    max_years: int | None = None,
    no_degree: bool = False,
    career_stage: str = "",
    needs_sponsorship: bool = False,
) -> tuple[list[dict], bool]:
    """
    Filter in SQL, then rank and paginate: by `rank_score` (similarity to `persona_vector`, nudged
    by the searched words in the title, the job's level against `career_stage` ("junior" or
    "experienced"), sponsorship when `needs_sponsorship`, and freshness) when a vector is given, else
    by recency. `semantic_score` stays the plain similarity. `location` is one location or a list (any
    of them matches; "remote" in it means remote jobs too). `query`, `category` and free-text `tags`
    are hard filters, matched as words with their other forms (see search_groups); role
    tags are OR'd, domain tags AND'd. `exclude` holds (lower company, lower title) pairs to
    drop *before* pagination (jobs the user already applied to / discarded), so pages stay
    full. `sponsorship` is one of SPONSORSHIP_FILTERS ("" = any); `marks` ({job id: OFFERED or
    NOT_OFFERED}) are the user's own calls, which win over the ad and the register. `max_years` hides
    jobs asking for more years of experience and `no_degree` jobs requiring a degree; a job whose ad
    doesn't say (or hasn't been read yet, see job_attributes.py) is kept.
    Returns (jobs, has_more). Blocking: call via asyncio.to_thread() from async code.
    """
    candidates, groups = _matching(
        "*" if persona_vector else _ROW_COLUMNS, query=query, location=location, level=level, category=category,
        remote=remote, tags=tags, exclude=exclude, sponsorship=sponsorship, marks=marks, max_years=max_years,
        no_degree=no_degree)

    if persona_vector:
        _rank_semantically(candidates, persona_vector)
        context = _RankContext(groups, career_stage, needs_sponsorship, marks or {})
        for job in candidates:
            job["rank_score"] = round(job["semantic_score"] + _boost(job, context), 4)
        candidates.sort(key=lambda j: j["rank_score"], reverse=True)  # stable: ties stay newest-first
    else:
        for job in candidates:
            job["semantic_score"] = 0.0

    page = candidates[offset: offset + limit]
    return page, len(candidates) > offset + limit


# ── Search words ──────────────────────────────────────────────────────────────
# A search matches words, not a phrase: "ml engineer" finds "Machine Learning Engineer". Each word
# (or a known phrase) must appear in the title, company or description, in any of the ways people
# write it.

_SYNONYM_GROUPS: list[tuple[str, ...]] = [
    ("ml", "machine learning"),
    ("ai", "artificial intelligence"),
    ("llm", "large language model"),
    ("genai", "generative ai", "gen ai"),
    ("nlp", "natural language processing"),
    ("quant", "quantitative"),
    ("dev", "developer"),
    ("frontend", "front end"),
    ("backend", "back end"),
    ("fullstack", "full stack"),
    ("devops", "dev ops"),
    ("sre", "site reliability"),
    ("grad", "graduate"),
    ("js", "javascript"),
    ("ts", "typescript"),
]
# Looked up with hyphens as spaces: "front-end" is "front end". (A form's pattern already takes a
# space, a hyphen or nothing between its words.)
_FORM_GROUP = {form: group for group in _SYNONYM_GROUPS for form in group}
_LONGEST_FORM = max(len(form.split()) for form in _FORM_GROUP)
_SEARCH_STOP_WORDS = {"a", "an", "the", "and", "or", "of", "for", "in", "at", "to", "with", "on"}
_SEARCHED_FIELDS = ("title", "company", "description")
_SEARCHED_TEXT = "lower(title) || ' ' || lower(company) || ' ' || lower(coalesce(description, ''))"


def search_groups(text: str) -> list[tuple[str, ...]]:
    """The word groups a search must all match, each the interchangeable forms of one word or known
    phrase: "ML engineer" -> [("ml", "machine learning"), ("engineer",)]."""
    words = [w for w in re.findall(r"[a-z0-9+#]+(?:[.-][a-z0-9+#]+)*", (text or "").lower())
             if w not in _SEARCH_STOP_WORDS]
    groups, i = [], 0
    while i < len(words):
        for n in range(min(_LONGEST_FORM, len(words) - i), 0, -1):
            phrase = " ".join(words[i:i + n])
            known = _FORM_GROUP.get(phrase.replace("-", " "))
            if n == 1 or known:
                groups.append(known or (phrase,))
                i += n
                break
    return list(dict.fromkeys(groups))


def _first_word(form: str) -> str:
    return re.split(r"[\s-]+", form)[0]


def _form_pattern(form: str) -> str:
    """A form as words: "front end" also matches "front-end" and "frontend"; words of 5+ letters may run
    on ("engineer" -> "engineering"), shorter ones only take a plural ("ml" isn't the end of "html")."""
    parts = [p for p in re.split(r"[\s-]+", form) if p]
    body = r"[\s-]*".join(re.escape(p) for p in parts)
    tail = "" if len(parts[-1]) >= 5 else r"s?(?![a-z0-9])"
    return r"(?<![a-z0-9])" + body + tail


def _group_pattern(group: tuple[str, ...]) -> str:
    return "(?:" + "|".join(_form_pattern(form) for form in group) + ")"


@functools.lru_cache(maxsize=256)
def _compiled(pattern: str) -> re.Pattern:
    return re.compile(pattern)


def _words_match(pattern: str, text: str) -> int:
    """SQL function words_match(pattern, text): 1 when the lower-cased text has the pattern."""
    return 1 if text and _compiled(pattern).search(text) else 0


# ── Ranking ───────────────────────────────────────────────────────────────────
# Similarity to the persona (and what's searched for) decides the order, nudged by what the
# similarity can't see. The nudges are sized against its spread on a real feed (median 0.70,
# standard deviation 0.04), so each moves a job a little, never past a far better match.

_TITLE_BOOST = 0.04             # x the share of searched words in the title
_LEVEL_BOOST = {"junior": {"junior": 0.03, "senior": -0.05}, "experienced": {"junior": -0.02}}
_OFFERED_BOOST = 0.03           # the ad (or the user's mark) says it sponsors visas
_LICENSED_BOOST = 0.02          # the employer is a licensed sponsor
_FRESH_BOOST = ((3, 0.02), (7, 0.01))   # first seen within N days


class _RankContext:
    def __init__(self, groups, career_stage, needs_sponsorship, marks):
        self.title_patterns = [_compiled(_group_pattern(g)) for g in groups]
        self.level_boost = _LEVEL_BOOST.get(career_stage or "", {})
        self.needs_sponsorship = needs_sponsorship
        self.marks = marks
        self.now = datetime.now(timezone.utc)


def _boost(job: dict, ctx: _RankContext) -> float:
    boost = ctx.level_boost.get((job.get("level") or "").lower(), 0.0)
    if ctx.title_patterns:
        title = (job.get("title") or "").lower()
        boost += _TITLE_BOOST * sum(1 for p in ctx.title_patterns if p.search(title)) / len(ctx.title_patterns)
    if ctx.needs_sponsorship:
        mark = ctx.marks.get(job.get("id"), "")
        if mark == signals.OFFERED or (job.get("sponsorship") == signals.OFFERED and mark != signals.NOT_OFFERED):
            boost += _OFFERED_BOOST
        if job.get("licensed_sponsor"):
            boost += _LICENSED_BOOST
    try:
        age_days = (ctx.now - datetime.fromisoformat(job.get("created_at") or "")).total_seconds() / 86400
    except (TypeError, ValueError):
        age_days = None
    if age_days is not None:
        boost += next((b for days, b in _FRESH_BOOST if age_days <= days), 0.0)
    return boost


_ROW_COLUMNS = (
    "id, job_id, title, company, normalized_company, location, description, url, salary_min, salary_max, "
    "exposure_score, level, source, tags, created_at, updated_at, expires_at, sponsorship, sponsorship_evidence, "
    "clearance, sponsor_key, years_min, degree")
_COUNT_COLUMNS = "id, title, company, location"  # what the checks after SQL read


def count_jobs(query: str = "", location: str | list[str] = "", level: str = "", category: str = "",
               remote: bool = False, tags: list[str] = None, exclude: set[tuple[str, str]] | None = None,
               sponsorship: str = "", marks: dict[str, str] | None = None, max_years: int | None = None,
               no_degree: bool = False) -> int:
    """How many jobs get_jobs would find with these filters (up to its candidate pool), without
    loading or ranking them. Blocking: call via asyncio.to_thread() from async code."""
    return len(_matching(_COUNT_COLUMNS, query=query, location=location, level=level, category=category,
                         remote=remote, tags=tags, exclude=exclude, sponsorship=sponsorship, marks=marks,
                         max_years=max_years, no_degree=no_degree)[0])


def _matching(columns: str, *, query, location, level, category, remote, tags, exclude, sponsorship, marks,
              max_years, no_degree) -> tuple[list[dict], list[tuple[str, ...]]]:
    """(the jobs passing every filter, newest first, up to _CANDIDATE_POOL; the searched word groups)."""
    if not _DB_PATH:
        init_db()

    roles, domains, text_terms = _parse_tags(list(tags or []) + ([category] if category else []))
    groups = [g for term in text_terms for g in (search_groups(term) or [(term,)])] + search_groups(query)
    groups = list(dict.fromkeys(groups))

    where = ["(expires_at IS NULL OR expires_at > ?)"]
    params: list = [_now()]

    if level:
        where.append("lower(level) = ?")
        params.append(level.lower())

    # Every searched word (or one of its other forms) somewhere in the job, as a word: LIKE narrows
    # the rows cheaply, then words_match checks word boundaries ("ML" isn't the end of "HTML").
    for group in groups:
        likes = " OR ".join(f"lower({field}) LIKE ? ESCAPE '\\'" for _ in group for field in _SEARCHED_FIELDS)
        where.append(f"(({likes}) AND words_match(?, {_SEARCHED_TEXT}))")
        params += [_like(_first_word(form)) for form in group for _ in _SEARCHED_FIELDS] + [_group_pattern(group)]
    if roles:
        where.append("(" + " OR ".join("tags LIKE ?" for _ in roles) + ")")
        params += [f'%"{r}"%' for r in roles]
    for d in domains:
        where.append("tags LIKE ?")
        params.append(f'%"{d}"%')
    if max_years is not None:
        where.append("(years_min IS NULL OR years_min <= ?)")
        params.append(max_years)
    if no_degree:
        where.append("coalesce(degree, '') != 'required'")
    if sponsorship in SPONSORSHIP_FILTERS and sponsorship != "any":
        sql, sql_params = _sponsorship_filter(sponsorship, marks or {})
        where.append(sql)
        params += sql_params

    loc_sql, loc_params, matchers, remote = _locations_clause(location, remote)
    if loc_sql:
        where.append(loc_sql)
        params += loc_params

    sql = (f"SELECT {columns}, {_LICENSED} AS licensed_sponsor FROM jobs WHERE {' AND '.join(where)} "
           f"ORDER BY coalesce(updated_at, created_at) DESC LIMIT {_CANDIDATE_POOL}")

    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    con.create_function("words_match", 2, _words_match, deterministic=True)
    rows = [dict(r) for r in con.execute(sql, params).fetchall()]
    con.close()
    for job in rows:
        job["licensed_sponsor"] = bool(job["licensed_sponsor"])

    exclude = exclude or set()
    candidates = []
    for job in rows:
        if exclude and ((job.get("company") or "").lower(), (job.get("title") or "").lower()) in exclude:
            continue
        loc = (job.get("location") or "").lower()
        if matchers and not any(matches(loc) for _, _, matches in matchers):
            if not (remote and any(t in loc for t in _REMOTE_TERMS)):
                continue
        candidates.append(job)

    return candidates, groups


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
    sponsor = licensed_sponsor(job.get("sponsor_key") or "")
    job["licensed_sponsor"] = bool(sponsor)
    job["sponsor_name"] = sponsor[0] if sponsor else ""
    return job


# ── The sponsor register (see sponsor_register.py) ───────────────────────────

def licensed_sponsor(sponsor_key: str) -> tuple[str, str] | None:
    """(organisation name, town) of the licensed Skilled Worker sponsor with this key, else None."""
    if not sponsor_key:
        return None
    if not _DB_PATH:
        init_db()
    con = sqlite3.connect(_DB_PATH)
    row = con.execute("SELECT name, town FROM sponsors WHERE norm_name = ?", (sponsor_key,)).fetchone()
    con.close()
    return (row[0], row[1] or "") if row else None


def replace_sponsors(sponsors: dict[str, tuple[str, str]], source_url: str) -> None:
    """Swap in a freshly parsed register ({normalised name: (name, town)}) in one transaction."""
    if not _DB_PATH:
        init_db()
    con = sqlite3.connect(_DB_PATH)
    with con:
        con.execute("DELETE FROM sponsors")
        con.executemany("INSERT INTO sponsors (norm_name, name, town) VALUES (?, ?, ?)",
                        [(key, name, town) for key, (name, town) in sponsors.items()])
        con.execute("INSERT OR REPLACE INTO sponsor_register (id, fetched_at, source_url, organisations) "
                    "VALUES (1, ?, ?, ?)", (_now(), source_url, len(sponsors)))
    con.close()


def sponsor_register_fetched_at() -> datetime | None:
    """When the stored register was downloaded, or None if there isn't one."""
    if not _DB_PATH:
        init_db()
    con = sqlite3.connect(_DB_PATH)
    row = con.execute("SELECT fetched_at FROM sponsor_register WHERE id = 1").fetchone()
    con.close()
    return datetime.fromisoformat(row[0]) if row else None


def update_description(job_db_id: str, description: str) -> None:
    """Persist a freshly-fetched full description back onto a stored job row."""
    if not _DB_PATH:
        init_db()
    try:
        con = sqlite3.connect(_DB_PATH)
        title, company = con.execute("SELECT title, company FROM jobs WHERE id = ?", (job_db_id,)).fetchone() or ("", "")
        # The full ad often says what the stored snippet didn't (sponsorship is usually near the end).
        status, evidence, clearance, sponsor_key = _sponsorship_columns(company or "", title or "", description)
        con.execute(
            "UPDATE jobs SET description = ?, level = ?, updated_at = ?, sponsorship = ?, sponsorship_evidence = ?, "
            "clearance = ?, sponsor_key = ?, attributes_version = NULL, attributes_tries = 0 WHERE id = ?",
            (description, seniority.infer_level(title, description), _now(), status, evidence, clearance,
             sponsor_key, job_db_id),
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


# ── LLM-read attributes (see job_attributes.py) ───────────────────────────────

_MAX_ATTRIBUTE_TRIES = 3


def jobs_needing_attributes(limit: int, locations: list[str] | None = None) -> list[dict]:
    """Newest jobs not yet read by the current attribute extractor, skipping ones it has given up on.
    With `locations`, only jobs a feed over them could show (see get_jobs; "remote" in it adds remote
    jobs): each read is an LLM call, so jobs elsewhere, or that don't say where, keep the regex
    readings. The location check is the SQL superset only, so a job it lets through is never left at
    the head of the queue."""
    if not _DB_PATH:
        init_db()
    where = "coalesce(attributes_version, 0) < ? AND coalesce(attributes_tries, 0) < ?"
    params: list = [ATTRIBUTES_VERSION, _MAX_ATTRIBUTE_TRIES]
    if locations is not None:
        loc_sql, loc_params, _, _ = _locations_clause(locations)
        if loc_sql:
            where += f" AND {loc_sql}"
            params += loc_params
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        f"SELECT id, title, company, description FROM jobs WHERE {where} "
        "ORDER BY created_at DESC LIMIT ?", (*params, limit)).fetchall()
    con.close()
    return [dict(r) for r in rows]


def store_attributes(job_db_id: str, attributes: dict | None) -> None:
    """Save a job's merged attributes (job_attributes.merge), or, for None, count a failed read: after
    _MAX_ATTRIBUTE_TRIES the job keeps its regex values and isn't tried again until its ad changes."""
    if not _DB_PATH:
        init_db()
    con = sqlite3.connect(_DB_PATH)
    with con:
        if attributes is None:
            con.execute("UPDATE jobs SET attributes_tries = coalesce(attributes_tries, 0) + 1 WHERE id = ?",
                        (job_db_id,))
        else:
            con.execute(
                "UPDATE jobs SET level = ?, sponsorship = ?, sponsorship_evidence = ?, clearance = ?, years_min = ?, "
                "degree = ?, attributes_version = ? WHERE id = ?",
                (attributes["level"], attributes["sponsorship"], attributes["sponsorship_evidence"],
                 attributes["clearance"], attributes["years_min"], attributes["degree"], ATTRIBUTES_VERSION,
                 job_db_id))
    con.close()


async def ensure_full_description(job: dict) -> dict:
    """
    Make sure a job has its real, full description before we analyse it.

    Stored descriptions are capped at 500 chars at sync time (and Brave results
    are only a web snippet), so anything that short is re-fetched from the live
    listing page. The result is persisted back to the DB so re-runs and revisits
    are instant.

    The jobs table is shared by all users, so the client-supplied job is never
    trusted for the write: we only persist when the id matches a stored row, and
    then we fetch that row's *stored* URL — never the URL from the request body.
    """
    desc = (job.get("description") or "").strip()
    if len(desc) > 600:          # already a full description (e.g. previously fetched)
        return job

    from .job_searcher import fetch_full_description
    db_id = str(job.get("id") or "")
    stored = get_job(db_id) if db_id else None
    if stored:
        stored_desc = (stored.get("description") or "").strip()
        if len(stored_desc) > 600:   # another request already fetched it
            return {**job, "description": stored_desc}
        full = await fetch_full_description(stored.get("url") or "")
        if full and len(full) > len(stored_desc):
            update_description(db_id, full)
            return {**job, "description": full}
        return job

    # Not a stored job (e.g. pasted via /jobs/from-url): enrich this request only.
    full = await fetch_full_description(job.get("url", ""))
    if full and len(full) > len(desc):
        job = {**job, "description": full}
    return job
