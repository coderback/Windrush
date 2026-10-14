"""Seniority classification of job listings, and that every stored job goes through it."""
import sqlite3

import pytest

from app import jobs_db
from app.seniority import infer_level

from conftest import make_job


@pytest.mark.parametrize("title, expected", [
    # Graduate / entry-level wording
    ("Graduate Software Engineer", "junior"),
    ("Junior Data Analyst", "junior"),
    ("Software Engineering Intern", "junior"),
    ("Summer Internship - Technology", "junior"),
    ("Apprentice Developer", "junior"),
    ("Associate Software Engineer", "junior"),
    ("Associate Product Manager", "junior"),
    ("Graduate Project Manager", "junior"),
    ("Software Engineer I", "junior"),
    ("Year in Industry Placement - Data", "junior"),
    # Senior wording, including ones that also contain a junior-ish word
    ("Senior Backend Engineer", "senior"),
    ("Associate Director, Engineering", "senior"),
    ("Senior Associate", "senior"),
    ("Head of Data", "senior"),
    ("Engineering Manager", "senior"),
    ("Principal Scientist", "senior"),
    # Words that merely contain a signal must not trigger it
    ("International Sales Executive", "mid"),
    ("Internal Communications Officer", "mid"),
    ("Sentry Platform Engineer", "mid"),
    ("Software Engineer II", "mid"),
    ("Data Engineer", "mid"),
])
def test_title(title, expected):
    assert infer_level(title) == expected


@pytest.mark.parametrize("description, expected", [
    ("Join our 2027 graduate programme in London.", "junior"),
    ("Ideal for recent graduates with a passion for data.", "junior"),
    ("This is an entry-level role.", "junior"),
    ("No prior experience required — full training given.", "junior"),
    ("You will have 5+ years of experience building APIs.", "senior"),
    ("Minimum of 7 years commercial experience.", "senior"),
    ("2-4 years' experience with Python.", "mid"),
    ("1 year of experience with SQL preferred.", "junior"),
    ("Founded 25 years ago, we build great software.", "mid"),
    ("", "mid"),
])
def test_neutral_title_falls_back_to_description(description, expected):
    assert infer_level("Software Engineer", description) == expected


def test_title_outranks_description():
    assert infer_level("Senior Engineer", "Great for recent graduates") == "senior"
    assert infer_level("Graduate Engineer", "8+ years of experience") == "junior"


def test_add_jobs_classifies_jobs_that_arrive_without_a_level(db, ollama):
    job = make_job(1, title="Data Analyst", description="Our graduate scheme starts in September.")
    job.pop("level")
    jobs_db.add_jobs([job])
    stored, _ = jobs_db.get_jobs(level="junior")
    assert [j["title"] for j in stored] == ["Data Analyst"]


def test_full_description_reclassifies(db, ollama):
    job = make_job(2, title="Software Engineer", description="Short blurb.")
    job.pop("level")
    jobs_db.add_jobs([job])
    (row_id,) = sqlite3.connect(jobs_db._DB_PATH).execute("SELECT id FROM jobs").fetchone()
    jobs_db.update_description(row_id, "You bring 6+ years of experience leading teams.")
    assert jobs_db.get_job(row_id)["level"] == "senior"


def test_existing_rows_are_reclassified_once(db, ollama, tmp_path):
    path = str(tmp_path / "old_jobs.db")
    jobs_db.init_db(path)
    con = sqlite3.connect(path)
    con.execute("PRAGMA user_version = 0")
    con.execute("INSERT INTO jobs (id, job_id, title, company, normalized_company, location, level, source, "
                "created_at) VALUES ('a', '1', 'International Sales Executive', 'Co', 'co', 'London', 'junior', "
                "'ats', '2026-01-01')")
    con.commit()
    con.close()

    jobs_db.init_db(path)

    con = sqlite3.connect(path)
    assert con.execute("SELECT level FROM jobs WHERE id='a'").fetchone()[0] == "mid"
    assert con.execute("PRAGMA user_version").fetchone()[0] == 1
