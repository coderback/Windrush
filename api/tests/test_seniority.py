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
    # Student work-experience programmes
    ("Summer Analyst – Global Markets 2027", "junior"),
    ("Spring Insight Week 2027 – Investment Banking", "junior"),
    ("Insight Day – Technology (First Years)", "junior"),
    ("Vacation Scheme 2027 – Commercial Law", "junior"),
    ("Working Student – Data Engineering (20h/week)", "junior"),
    ("Co-op Student, Software Engineering (Fall 2027)", "junior"),
    ("Werkstudent Softwareentwicklung (m/w/d)", "junior"),
    ("Praktikum Data Science (m/w/d)", "junior"),
    ("Alternance – Développeur Web (H/F)", "junior"),
    ("Stage – Développeur Full Stack (H/F)", "junior"),
    ("Vacation Scheme Coordinator", "mid"),  # runs the scheme
    ("Stage Technician", "mid"),
    ("Insight Analyst", "mid"),
    # Graduate cohorts and entry grades
    ("Software Engineer - Class of 2027", "junior"),
    ("Emerging Talent Programme – Data Analyst", "junior"),
    ("Early Talent Software Engineer", "junior"),
    ("Civil Service Fast Stream 2027", "junior"),
    ("Technology Analyst Programme 2027", "junior"),
    ("Newly Qualified Solicitor (NQ) – Corporate", "junior"),
    ("Early Talent Recruitment Partner", "mid"),
    ("Fast Stream Assessor", "mid"),
    ("Head of Emerging Talent", "senior"),
    ("Solicitor NQ+3", "mid"),
    # Partner and professor grades, and a qualified Associate Solicitor
    ("Associate Partner – Financial Services", "senior"),
    ("Associate Professor of Computer Science", "senior"),
    ("Junior Partner – Strategy Practice", "senior"),
    ("Associate Solicitor", "mid"),
    # A figure in the title, when there is no description
    ("Software Engineer (0-1 yrs)", "junior"),
    ("Software Engineer, 0–2 YOE", "junior"),
    ("Software Engineer (7+ yrs exp)", "senior"),
    ("Software Engineer - 5+ Years Experience", "senior"),
    ("Associate Solicitor – Employment (3 PQE)", "mid"),
    ("Software Engineer – 12 Month Contract", "mid"),
    ("Software Engineer - 2 Year Fixed Term Contract", "mid"),
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
    # The employer hiring someone with a figure: the figure is the candidate's
    ("We are hiring engineers with 5+ years of experience.", "senior"),
    ("We pay up to £120k for engineers with 8+ years of experience.", "senior"),
    ("We're hiring a backend engineer with 6+ years of experience.", "senior"),
    ("We'd love to hear from engineers with 5+ years of experience.", "senior"),
    ("We welcome applications from engineers with 6+ years' experience.", "senior"),
    ("The person we hire will have 6+ years of experience.", "senior"),
    ("They will have 5+ years of experience.", "senior"),
    ("Successful hires have 7+ years of experience.", "senior"),
    ("We hire engineers with 0-1 years of experience.", "junior"),
    ("We welcome people with up to 1 year of experience.", "junior"),
    # ... but the employer's people with a figure are not the candidate
    ("Graduate scheme. Engineers with 10+ years of experience will mentor you.", "junior"),
    ("Graduate scheme. You'll join a team of engineers with 10+ years of experience.", "junior"),
    ("Graduate scheme. The team has 12 years of experience.", "junior"),
    ("Graduate scheme. Senior engineers bring 8 years of experience.", "junior"),
    ("Get support from engineers with 10+ years of experience. Entry-level role.", "junior"),
    ("We are looking for engineers with 5+ years of experience.", "senior"),
    ("Applicants with 5+ years of experience.", "senior"),
    # A figure the candidate is told they do not need
    ("You don't need 5+ years of experience — recent graduates welcome.", "junior"),
    ("Unlike most roles, this one doesn't require 5+ years of experience. Recent graduates welcome.", "junior"),
    ("No need for 3+ years of experience; entry-level applicants welcome.", "junior"),
    ("We do not require sponsorship. 5+ years of experience required.", "senior"),
    ("You don't need a degree, but you need 5+ years of experience.", "senior"),
    # A soft word said of something else does not make a required figure optional
    ("Knowledge of Kafka is a plus and you must have 5+ years of backend experience. "
     "You need 1+ year of AWS experience.", "senior"),
    ("Desirable: 5+ years of experience. Essential: 1+ year of experience.", "junior"),
    ("Preferred: 5+ years of experience. Required: 2+ years of experience.", "mid"),
    # Upper bounds count from 0; ranges and Indeed's per-skill list after "Experience:"
    ("Experience: between 1 and 2 years in any programming language.", "junior"),
    ("Experience: between 5 and 8 years.", "senior"),
    ("Less than 5 years' experience.", "junior"),
    ("You'll have no more than 2 years' work experience since graduating.", "junior"),
    ("Under 2 years of experience.", "junior"),
    ("Maximum of 2 years' experience.", "junior"),
    ("Job details\nJob type: Full-time\nExperience:\n• Python: 1 year (preferred)\nEducation:\n"
     "• Bachelor's (required)", "junior"),
    ("Experience:\n• Python: 5 years (required)", "senior"),
    # Figures without the word "experience"
    ("Entry-level candidates should apply via our Early Careers page instead. "
     "This role requires 6+ years in a similar position.", "senior"),
    ("7+ yrs exp required", "senior"),
    ("5yrs+ experience with AWS.", "senior"),
    ("Experience of 5 years+ in a commercial setting.", "senior"),
    ("0-1 years in a similar role.", "junior"),
    ("Minimum 7 PQE in banking and finance.", "senior"),
    ("We are seeking a Senior Associate with 6+ years' PQE.", "senior"),
    ("We have been in business 6+ years in a similar market.", "mid"),
    # Junior wording: placements, apprenticeships, trainee and junior positions
    ("This is a 12-month industrial placement for students.", "junior"),
    ("We're looking for a placement year student to join us.", "junior"),
    ("A year in industry with our data team.", "junior"),
    ("Summer Internship 2027: a 10-week paid internship for undergraduates.", "junior"),
    ("This is a Level 4 Software Developer apprenticeship.", "junior"),
    ("Open to school leavers with A-levels.", "junior"),
    ("Trainee position — full training is provided.", "junior"),
    ("This is a junior position. You'll learn SQL.", "junior"),
    ("We're hiring a junior engineer to learn from our team.", "junior"),
    # ... but not someone else's apprentices, a refusal, or a duty
    ("5+ years of experience required. Nice to have: experience mentoring graduates and apprentices.", "senior"),
    ("We are not offering internships this year.", "mid"),
    ("You'll onboard new apprentices.", "mid"),
    ("You will support the apprenticeship programme.", "mid"),
    ("This is not a junior role.", "mid"),
    ("You'll mentor junior engineers.", "mid"),
    # Graduate cohorts and graduation years
    ("As part of our 2027 graduate intake you'll be paired with a mentor.", "junior"),
    ("Join our graduate cohort in September.", "junior"),
    ("Applicants must be on track to graduate in summer 2027.", "junior"),
    ("Requirements: 1. Graduating in 2027 with a degree in Computer Science.", "junior"),
    ("Open to 2026 and 2027 graduates.", "junior"),
    ("You will help onboard the 2027 graduate intake.", "mid"),
    ("This role is not open to 2027 graduates.", "mid"),
])
def test_neutral_title_falls_back_to_description(description, expected):
    assert infer_level("Software Engineer", description) == expected


@pytest.mark.parametrize("title, description, expected", [
    # "Associate" is junior unless the description asks for 3+ years
    ("Associate", "Candidates will have 6+ years' experience as an Analyst.", "senior"),
    ("Associate", "Candidates will have 3–4 years' experience as an Analyst.", "mid"),
    ("Investment Banking Associate", "Minimum 4 years' experience.", "mid"),
    ("Associate Software Engineer", "1-2 years of experience.", "junior"),
    ("Associate Software Engineer", "Join our team in London.", "junior"),
    # The title's figure counts only when the description gives none
    ("Software Engineer (0-1 yrs)", "5+ years of experience required.", "senior"),
])
def test_weak_title_and_description(title, description, expected):
    assert infer_level(title, description) == expected


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
    ("you don't need 5+ years of experience ", 210),
    ("a plus and you must have 5+ years of experience ", 160),
    ("ideally a plus nice to have 5 years experience ", 170),
    ("we are hiring engineers with 5 years experience ", 165),
    ("experience: • python: 1 year ", 270),
    ("a b c d e ", 800),
])
def test_many_figures_and_phrases_are_fast(phrase, times):
    description = phrase * times  # about 8,000 characters
    # Each figure and phrase looks at its own clause; that must not rescan the text each time.
    start = time.perf_counter()
    infer_level("Software Engineer", description)
    infer_level(description)  # a title with no description is read for a figure too
    assert time.perf_counter() - start < 0.2


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
