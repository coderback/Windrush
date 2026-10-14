"""Seniority classification of job listings, and that every stored job goes through it."""
import sqlite3
import time

import pytest

from app import jobs_db, seniority
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
    # Plurals and the first rung of a ladder
    ("Technology Graduates 2027", "junior"),
    ("Summer Interns - Software Engineering", "junior"),
    ("Software Engineering Internships 2027", "junior"),
    ("Apprenticeships", "junior"),
    ("Placements", "junior"),
    ("SWE I", "junior"),
    ("SDE I", "junior"),
    ("Software Engineer I - Payments", "junior"),
    # Senior wording, including ones that also contain a junior-ish word
    ("Senior Backend Engineer", "senior"),
    ("Associate Director, Engineering", "senior"),
    ("Associate Director", "senior"),
    ("Senior Associate", "senior"),
    ("Head of Data", "senior"),
    ("Engineering Manager", "senior"),
    ("Principal Scientist", "senior"),
    ("Staff Engineer", "senior"),
    # Senior-looking words that are a place, team or job name, not a rank
    ("Graduate Programme - Head Office", "junior"),
    ("Summer Intern - Head Office", "junior"),
    ("Finance Assistant - Head Quarters", "mid"),
    ("Graduate Analyst - Principal Investments", "junior"),
    ("Junior Staff Accountant", "junior"),
    ("Graduate Staff Nurse", "junior"),
    ("Graduate Engineer - Office of the Chief Technology Officer", "junior"),
    ("Analyst, reporting to the Head of Finance", "mid"),
    ("Lead Generation Executive", "mid"),
    # People who run a scheme are not on it
    ("Apprenticeship Manager", "senior"),
    ("Early Careers Manager", "senior"),
    ("Placement Manager", "senior"),
    ("Graduate Recruitment Partner", "mid"),
    ("Early Careers Recruiter", "mid"),
    ("Placement Officer", "mid"),
    ("Apprenticeship Assessor", "mid"),
    ("Internship Program Coordinator", "mid"),
    ("Graduate Recruitment Consultant", "junior"),  # the agency trainee role
    # Words that merely contain a signal must not trigger it
    ("International Sales Executive", "mid"),
    ("Internal Communications Officer", "mid"),
    ("Sentry Platform Engineer", "mid"),
    ("Software Engineer II", "mid"),
    ("Engineer I/II", "mid"),
    ("Engineer I-II", "mid"),
    ("Analyst 1-2", "mid"),
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
    # A figure inside a bigger number, or above 15, is the company's age, not the role's bar
    ("We have over 100 years of experience in banking.", "mid"),
    ("Our 150 years of experience in banking.", "mid"),
    ("We have 20 years of experience in fintech.", "mid"),
    # The headline requirement, not the smallest
    ("5+ years of software engineering experience. 1+ year of experience with AWS.", "senior"),
    ("3+ years of non-internship professional software development experience. "
     "1+ years of experience as a mentor.", "mid"),
    # A real years requirement beats junior wording; 2 years alone is mid
    ("Our team includes recent graduates; you bring 3+ years of experience.", "mid"),
    ("Work alongside recent graduates. 6+ years of experience required.", "senior"),
    ("Graduate scheme. 2 years of experience preferred.", "junior"),
    # Junior wording that is negated or describes a duty
    ("This is not an entry-level role.", "mid"),
    ("Please note this is not a graduate scheme.", "mid"),
    ("No graduates or entry-level applicants, please.", "mid"),
    ("You will mentor recent graduates.", "mid"),
    ("You will support our graduate programme.", "mid"),
    ("Help onboard new grads.", "mid"),
    ("We run a graduate scheme for STEM students.", "junior"),
    ("No visa sponsorship, recent graduates welcome.", "junior"),
    # Other ways of stating years
    ("Five years of experience in Python.", "senior"),
    ("5+ yrs experience with Go.", "senior"),
    ("5 or more years of experience.", "senior"),
    ("At least five years' experience in a similar role.", "senior"),
    ("Experience: at least 5 years.", "senior"),
    ("Experience: minimum of 5 years in finance.", "senior"),
    ("Experience: 5+ years", "senior"),
    ("Experience required: 3 years. Recent graduates welcome.", "mid"),
    ("6 months experience", "junior"),
    ("12 months' experience with Excel.", "junior"),
    # Years that are not experience
    ("Must have lived in the UK for at least 5 years.", "mid"),
])
def test_neutral_title_falls_back_to_description(description, expected):
    assert infer_level("Software Engineer", description) == expected


def test_long_whitespace_run_is_fast():
    start = time.perf_counter()
    assert infer_level("Software Engineer", "5" + "\xa0" * 8000 + " x") == "mid"
    assert time.perf_counter() - start < 0.1


@pytest.mark.parametrize("pattern", [seniority._AMOUNT_THEN_EXPERIENCE, seniority._EXPERIENCE_THEN_AMOUNT])
def test_years_patterns_do_not_backtrack_on_raw_whitespace(pattern):
    # infer_level collapses whitespace first; the patterns must be safe without it too.
    start = time.perf_counter()
    for text in ("5" + "\xa0" * 8000 + "x", "experience" + " " * 8000 + "x", "5 years" + "\t" * 8000 + "x"):
        pattern.search(text)
    assert time.perf_counter() - start < 0.1


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
