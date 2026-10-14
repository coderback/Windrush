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
    ("Analyst - Office of the Co-Head of Engineering", "mid"),
    ("Lead Generation Executive", "mid"),
    # ... but only up to the next separator, so the role's own rank still counts
    ("Office of the CTO - Graduate Software Engineer", "junior"),
    ("Office of the CTO - Senior Software Engineer", "senior"),
    ("Office of the CFO: Senior Analyst", "senior"),
    ("Reporting to CEO - Head of Strategy", "senior"),
    ("Office of the General Counsel - Trainee Solicitor", "junior"),
    # People who run a scheme are not on it
    ("Apprenticeship Manager", "senior"),
    ("Early Careers Manager", "senior"),
    ("Placement Manager", "senior"),
    ("Graduate Recruitment Partner", "mid"),
    ("Early Careers Recruiter", "mid"),
    ("Placement Officer", "mid"),
    ("Apprenticeship Assessor", "mid"),
    ("Apprenticeship Skills Coach", "mid"),
    ("Internship Program Coordinator", "mid"),
    ("Graduate Recruiter", "mid"),
    ("Graduate Recruitment Consultant", "junior"),  # the agency trainee role
    # ... but a graduate or apprentice doing any other job is the trainee
    ("Graduate Administrator", "junior"),
    ("Apprentice Administrator", "junior"),
    ("Graduate Tutor", "junior"),
    ("Graduate Adviser - Financial Planning", "junior"),
    ("Graduate Coordinator - Logistics", "junior"),
    # Words that merely contain a signal must not trigger it
    ("International Sales Executive", "mid"),
    ("Internal Communications Officer", "mid"),
    ("Sentry Platform Engineer", "mid"),
    ("Software Engineer II", "mid"),
    ("Engineer I/II", "mid"),
    ("Engineer I-II", "mid"),
    ("Analyst 1-2", "mid"),
    ("Data Engineer", "mid"),
    # Non-breaking spaces, line breaks and doubled spaces
    ("Vice\xa0President,  Engineering", "senior"),
    ("Entry\nLevel Analyst", "junior"),
    ("Head\xa0Office Assistant", "mid"),
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
    ("5+ years of software engineering experience. 1+ year with AWS.", "senior"),
    ("3+ years of non-internship professional software development experience. "
     "1+ years of experience as a mentor.", "mid"),
    # A real years requirement beats junior wording; 2 years alone is mid
    ("Our team includes recent graduates; you bring 3+ years of experience.", "mid"),
    ("Work alongside recent graduates. 6+ years of experience required.", "senior"),
    ("Graduate scheme. 2 years of experience preferred.", "junior"),
    # ... but a figure that is someone else's, or a span of time, is not a requirement
    ("Learn from engineers with 6+ years of experience.", "mid"),
    ("Entry-level role. Learn from engineers with 6+ years of experience.", "junior"),
    ("Our engineers have 10+ years of experience.", "mid"),
    ("Acme is a specialist recruitment firm with over 10 years of experience.", "mid"),
    ("1-2 years of experience. You'll learn from mentors with 8 years of experience.", "junior"),
    ("Join our graduate programme. We have 12 years of experience in consulting.", "junior"),
    ("0-2 years of experience required; managers have 7 years of experience.", "junior"),
    ("With over 10 years of experience in fintech, we hire recent graduates every year.", "junior"),
    ("With 5+ years of experience in Go, you will lead our platform team.", "senior"),
    ("We're looking for an engineer with 5+ years of experience in Go.", "senior"),
    ("Recent graduates welcome. You must have graduated in the last 3 years and have some work experience.",
     "junior"),
    ("Over 3 years you'll gain experience in four business areas as part of our graduate scheme.", "junior"),
    ("Graduate Scheme\nProgramme length: 3 years\nExperience: none required", "junior"),
    # A required figure beats a preferred one
    ("Minimum 2 years experience; 5 years experience preferred.", "mid"),
    ("Required: 1-2 years of experience. Nice to have: 3+ years of experience with Kubernetes.", "junior"),
    ("5+ years of experience (preferred). 2+ years of experience required.", "mid"),
    ("Ideally 5+ years of experience.", "senior"),
    # Junior wording that is negated or describes a duty
    ("This is not an entry-level role.", "mid"),
    ("Please note this is not a graduate scheme.", "mid"),
    ("No graduates or entry-level applicants, please.", "mid"),
    ("This role is not suitable for recent graduates.", "mid"),
    ("We are unable to consider recent graduates - this is not an entry-level position.", "mid"),
    ("You will mentor recent graduates.", "mid"),
    ("You will support our graduate programme.", "mid"),
    ("You'll be onboarding new grads.", "mid"),
    ("You will be responsible for mentoring recent graduates.", "mid"),
    ("Responsible for mentoring recent graduates.", "mid"),
    ("Help onboard new grads.", "mid"),
    ("Responsibilities: mentoring recent graduates and reviewing code.", "mid"),
    ("We run a graduate scheme for STEM students.", "junior"),
    ("No visa sponsorship, recent graduates welcome.", "junior"),
    # ... but not a negation of something else
    ("Experience not essential - entry level role with full training.", "junior"),
    ("Visa sponsorship is not available for this graduate programme.", "junior"),
    ("This isn't your average graduate scheme.", "junior"),
    ("Never coded before? No problem - this entry-level role includes training.", "junior"),
    ("You don't need a degree - recent graduates are encouraged to apply.", "junior"),
    ("No degree needed - entry-level role with full training.", "junior"),
    # ... nor the employer hiring or training graduates, nor an adjective
    ("We are hiring recent graduates for this role.", "junior"),
    ("We're recruiting recent graduates for our 2027 intake.", "junior"),
    ("Hiring recent graduates into our data team.", "junior"),
    ("We'll train recent graduates from any discipline.", "junior"),
    ("Join our market-leading graduate programme in London.", "junior"),
    ("Our industry-leading graduate scheme starts in September 2027.", "junior"),
    ("We offer a fully supported graduate programme.", "junior"),
    ("Our long-running graduate scheme has trained 2,000 engineers.", "junior"),
    ("You'll join our market-leading graduate programme.", "junior"),
    ("You'll join a fully supported graduate programme.", "junior"),
    ("Join one of the UK's leading graduate programmes.", "junior"),
    ("No experience necessary.", "junior"),
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
    ("Between two and five years of experience.", "mid"),
    ("Up to 2 years of experience.", "junior"),
    ("0-2 years of experience.", "junior"),
    ("Experience: none required", "junior"),
    # Years that are not experience
    ("Must have lived in the UK for at least 5 years.", "mid"),
    # Non-breaking spaces, line breaks and doubled spaces
    ("Requirements:\n- 5+ years of\n  experience with Python", "senior"),
    ("6+\xa0years of  experience", "senior"),
    ("We run a graduate\nscheme for STEM students.", "junior"),
])
def test_neutral_title_falls_back_to_description(description, expected):
    assert infer_level("Software Engineer", description) == expected


def test_long_whitespace_run_is_fast():
    start = time.perf_counter()
    assert infer_level("Software Engineer", "5" + "\xa0" * 8000 + " x") == "mid"
    assert time.perf_counter() - start < 0.1


@pytest.mark.parametrize("phrase, times", [
    ("5 years experience ", 420),
    ("we have 5 years of experience ", 270),
    ("5 years experience preferred ", 280),
    ("with 5 years of experience ", 300),
    ("not recent graduates ", 380),
    ("you will mentor recent graduates ", 240),
])
def test_many_figures_and_phrases_are_fast(phrase, times):
    description = phrase * times  # about 8,000 characters
    # Each figure and phrase looks at its own clause; that must not rescan the text each time.
    start = time.perf_counter()
    infer_level("Software Engineer", description)
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
