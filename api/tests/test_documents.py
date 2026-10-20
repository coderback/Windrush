"""CV and cover-letter documents: profile → CVDoc / LetterDoc → HTML → PDF."""
import asyncio
import copy
import datetime
import json
import os
import re

import fitz  # pymupdf
import pytest

from app import agent, doc_render, pdf_generator

# A graduate profile shaped like a real one: portfolio-style project prose (headers, <br>, first
# person, a "Technologies" section), one internship, and more skill groups than the CV has room for.
GRADUATE = {
    "core_info": {"first_name": "Sam", "last_name": "Okafor", "email": "sam@example.com",
                  "phone": "+44 7700 900456", "city": "Bristol", "linkedin": "linkedin.com/in/sam-okafor",
                  "github": "github.com/samokafor", "website": "samokafor.dev"},
    "summary": "I am a Computer Science graduate who builds full-stack web apps and data pipelines, "
               "seeking a role where I can grow my skills.",
    "education": [{"institution": "Northfield University", "degree": "BSc (Hons) Computer Science",
                   "start_date": "09/2022", "end_date": "06/2025", "grade": "2:1"}],
    "history": [{"employer": "Brightwave Analytics", "title": "Software Engineering Intern",
                 "start_date": "06/2024", "end_date": "09/2024",
                 "achievements": ["Built a FastAPI service that ingests 40k sensor readings a day into PostgreSQL",
                                  "Cut dashboard load time from 6 s to 1.5 s by adding Redis caching",
                                  "Wrote integration tests that raised coverage from 52% to 81%"]}],
    "projects": [
        {"name": "Pantry Planner", "url": "https://github.com/samokafor/pantry-planner",
         "problem_solved": "What problem did you solve?<br>I built a meal planner that turns the food already in a "
                           "kitchen into a week of recipes, so less of it is thrown away. It matches pantry items "
                           "against 12,000 recipes with TF-IDF similarity and ranks them by what expires first."
                           "<br>How it works<br>1) Scan a receipt 2) Match recipes",
         "outcomes": "Outcomes: Used by 300 people a week during a university trial.<br>Technologies Frontend: "
                     "Next.js, React Backend: FastAPI, PostgreSQL ML: scikit-learn"},
        {"name": "Rail Delay Forecaster", "url": "rail-delays.example.app", "technologies": ["Python", "PyTorch"],
         "problem_solved": "Forecasts arrival delays for 40 stations from live rail feeds. A gradient-boosted "
                           "model retrains nightly on the previous month of running data.",
         "outcomes": "Mean absolute error of 2.1 minutes on held-out weeks."},
        {"name": "Campus Lost & Found",
         "problem_solved": "A web app where students report and claim lost items, with image matching to suggest "
                           "likely owners. Built with Django and PostgreSQL in Docker.",
         "outcomes": "450 items returned in the first term."},
        {"name": "Chess Engine · Personal project",
         "problem_solved": "I wrote a chess engine in Java using alpha-beta search with move ordering and a "
                           "transposition table. It plays at about 1900 on Lichess."},
    ],
    "skills": [
        {"category": "Languages", "skills": ["Python", "TypeScript", "Java", "SQL"]},
        {"category": "Frontend", "skills": ["React", "Next.js", "Tailwind CSS"]},
        {"category": "Backend", "skills": ["FastAPI", "Node.js", "Spring Boot"]},
        {"category": "Data", "skills": ["PostgreSQL", "Redis", "pandas"]},
        {"category": "Machine Learning", "skills": ["scikit-learn", "PyTorch"]},
        {"category": "Testing", "skills": ["pytest", "Jest", "Playwright"]},
        {"category": "Cloud", "skills": ["AWS", "Docker"]},
        {"category": "Tools", "skills": ["Git", "GitHub Actions", "CI/CD"]},
    ],
    "certifications": [{"name": "AWS Cloud Practitioner", "issuing_organization": "Amazon Web Services",
                        "issue_date": "2025-03"}],
}
JOB = {"job_id": "1", "title": "Graduate Software Engineer", "company": "Acme Robotics", "location": "Cambridge, UK",
       "description": "Python, FastAPI and PostgreSQL services for our robot fleet; machine learning a plus."}

_WORDS = ("designed shipped measured reduced automated migrated profiled documented tested deployed "
          "monitored refactored").split()


def _sentence(n_words: int, seed: int) -> str:
    return " ".join(_WORDS[(seed + i) % len(_WORDS)] for i in range(n_words)).capitalize()


def _letter_paragraphs(words_each=(60, 80, 140, 40)) -> list[str]:
    return [_sentence(n, i) + "." for i, n in enumerate(words_each)]


# Prose at the density of the candidate's own letter (about 5.2 characters a word; _WORDS run to 8), for
# measuring what a page holds.
_PROSE = ("I designed a scheduling service that cut deployment latency from forty minutes to nine by caching every "
          "build step, checking which inputs changed and rerunning only the affected tests, which taught me to "
          "measure before optimising and to explain each compromise clearly to reviewers on the team").split()


def _prose_paragraphs(words_each) -> list[str]:
    return [" ".join(_PROSE[(7 * p + i) % len(_PROSE)] for i in range(n)).capitalize() + "."
            for p, n in enumerate(words_each)]


def _full_cvdoc(seniority: str) -> dict:
    """A CVDoc at every length limit: what a verbose model can hand the renderer."""
    return {
        "name": "Sam Okafor", "seniority": seniority,
        "contact": {"email": "sam@example.com", "phone": "+44 7700 900456", "location": "Bristol",
                    "linkedin": "linkedin.com/in/sam-okafor", "github": "github.com/samokafor"},
        "summary": " ".join(_sentence(25, i) + "." for i in range(3)),
        "skills": [{"category": f"Group {g}", "items": [f"Skill{g}{i}" for i in range(14)]} for g in range(6)],
        "experience": [{"title": f"Engineer {r}", "employer": f"Employer {r}", "location": "London",
                        "start_date": f"01/{2015 + 2 * r}", "end_date": f"12/{2016 + 2 * r}",
                        "bullets": [_sentence(24, r + b) for b in range(4)]} for r in range(4)],
        "projects": [{"name": f"Project {p}", "description": _sentence(80, p) + ".",
                      "tech": ["Python", "FastAPI", "PostgreSQL", "Docker", "React", "Redis", "AWS", "pytest"],
                      "link": f"github.com/samokafor/p{p}"} for p in range(3)],
        "education": [{"degree": "BSc (Hons) Computer Science", "institution": "Northfield University",
                       "year": "06/2014", "grade": "First"}],
        "certifications": [{"name": f"Certificate {c}", "issuer": "Issuer", "year": "2020"} for c in range(3)],
    }


@pytest.fixture
def llm(monkeypatch):
    """The model's reply: set llm.reply to the raw text it returns. Prompts are kept in llm.prompts."""
    class Fake:
        reply = "{}"
        prompts: list[str] = []

    async def fake_llm(system, user, max_tokens=2048):
        Fake.prompts.append(system + "\n" + user)
        return Fake.reply

    async def no_research(*args, **kwargs):
        return ""
    monkeypatch.setattr(agent, "_llm", fake_llm)
    monkeypatch.setattr(agent, "_research_company", no_research)
    return Fake


def _tailored_cv(persona=GRADUATE) -> dict:
    return asyncio.run(agent.execute_tool("generate_tailored_cv", {"job": JOB, "persona": persona}))["cv"]


def _cover_letter(persona=GRADUATE) -> dict:
    return asyncio.run(agent.execute_tool("generate_cover_letter", {"job": JOB, "persona": persona}))["letter"]


def _headings(html: str) -> list[str]:
    return re.findall(r"<h2>(.*?)</h2>", html)


def _letter_body(html: str) -> list[str]:
    """The letter's right-hand column: the salutation heading, then each paragraph."""
    main = re.search(r'<td class="main">(.*?)<div class="signoff">', html, re.S).group(1)
    return re.findall(r"<h2>(.*?)</h2>", main, re.S) + re.findall(r'<p class="para">(.*?)</p>', main, re.S)


# ── CV: profile → document ───────────────────────────────────────────────────────

def test_certifications_keep_issuer_and_date_through_to_the_rendered_cv():
    persona = {"core_info": {"first_name": "Ada", "last_name": "Lovelace"},
               "certifications": [{"name": "AWS Solutions Architect", "issuing_organization": "Amazon",
                                   "issue_date": "2024-05"},
                                  {"name": "Legacy Cert", "issuer": "Old Co", "year": "2021"}]}
    cv = agent._persona_to_cvdoc(persona)
    assert cv["certifications"] == [
        {"name": "AWS Solutions Architect", "issuer": "Amazon", "year": "05/2024"},
        {"name": "Legacy Cert", "issuer": "Old Co", "year": "2021"},
    ]
    html = doc_render.render_cv_html(cv)
    assert "AWS Solutions Architect" in html and "Amazon" in html and "05/2024" in html


def _entry(html: str, title: str) -> str:
    """The dates shown beside an entry title ("" when none)."""
    m = re.search(rf'<span class="cv-entry-title">{re.escape(title)}</span>\s*(?:<span class="cv-dates">(.*?)</span>)?',
                  html)
    assert m, f"no entry titled {title!r}"
    return m.group(1) or ""


def test_a_graduate_cv_follows_the_candidates_design(llm):
    llm.reply = "not json"  # the model failed: the CV is built straight from the profile
    html = doc_render.render_cv_html(_tailored_cv())

    assert _headings(html) == ["Professional Summary", "Education", "Experience", "Projects",
                               "Skills &amp; Technical Proficiency"]
    assert '<h1 class="cv-name">Sam Okafor</h1>' in html
    contact = re.search(r'<p class="cv-contact">(.*?)</p>', html, re.S).group(1)
    assert re.sub(r"<[^>]+>|\s+", " ", contact).split() == "Bristol | +44 7700 900456 | sam@example.com | LinkedIn | GitHub | Website".split()
    for href in ("mailto:sam@example.com", "https://linkedin.com/in/sam-okafor", "https://github.com/samokafor",
                 "https://samokafor.dev"):
        assert f'href="{href}"' in contact
    assert "tel:" not in contact                                            # the phone is plain text
    assert _entry(html, "BSc (Hons) Computer Science | Northfield University") == "09/2022 – 06/2025"
    assert "<p>Grade: 2:1</p>" in html
    assert _entry(html, "Software Engineering Intern | Brightwave Analytics") == "06/2024 – 09/2024"
    assert "Cut dashboard load time from 6 s to 1.5 s" in html
    education = html.split("<h2>Education</h2>")[1].split("</section>")[0]
    assert "AWS Cloud Practitioner | Amazon Web Services" in education    # certifications sit under Education
    assert _entry(education, "AWS Cloud Practitioner | Amazon Web Services") == "03/2025"


def test_the_summary_loses_its_pronouns(llm):
    llm.reply = "{}"
    summary = re.search(r"<h2>Professional Summary</h2>\s*<p>(.*?)</p>", doc_render.render_cv_html(_tailored_cv())).group(1)
    assert summary == "Computer Science graduate who builds full-stack web apps and data pipelines."


def test_projects_show_a_titled_paragraph_and_a_technologies_line(llm):
    llm.reply = "{}"
    html = doc_render.render_cv_html(_tailored_cv())
    projects = html.split("<h2>Projects</h2>")[1].split("</section>")[0]

    assert re.findall(r'<span class="cv-entry-title">(.*?)</span>', projects) == [
        "Pantry Planner", "Rail Delay Forecaster", "Campus Lost &amp; Found", "Chess Engine"]   # four, escaped
    assert '<span class="cv-entry-title">Chess Engine</span><span class="cv-muted"> · Personal project</span>' in projects
    assert ("Built a meal planner that turns the food already in a kitchen into a week of recipes, so less of it "
            "is thrown away. It matches pantry items against 12,000 recipes with TF-IDF similarity and ranks them "
            "by what expires first.") in projects
    assert "What problem" not in projects and "How it works" not in projects and "&lt;br" not in projects
    assert '<p class="cv-muted">Technologies: Python, PyTorch</p>' in projects
    assert "<a " not in projects                                            # no project links in this design


def test_the_model_tailors_the_cv_but_cannot_touch_contact_details_education_or_links(llm):
    llm.reply = "Here is the CV:\n```json\n" + json.dumps({
        "name": "Sam Okafor", "headline": "",
        "contact": {"email": "invented@example.org", "phone": "+1 555 0100"},
        "summary": "Computer Science graduate specialising in Python back-end services.",
        "skills": [{"category": "Languages", "items": ["Python"]}],
        "experience": [{"title": "Software Engineering Intern", "employer": "Brightwave Analytics",
                        "start_date": "06/2024", "end_date": "09/2024",
                        "bullets": ["Built a FastAPI service ingesting 40k sensor readings a day into PostgreSQL"]}],
        "education": GRADUATE["education"],
        "projects": [{"name": "Rail Delay Forecaster", "description": "Forecasts delays.", "tech": [],
                      "link": "https://elsewhere.example"},
                     {"name": "Pantry Planner (meal planning)", "description": "Plans meals.", "tech": ["Next.js"],
                      "link": ""}],
    }) + "\n```"
    cv = _tailored_cv()
    base = agent._persona_to_cvdoc(GRADUATE)

    assert cv["summary"] == "Computer Science graduate specialising in Python back-end services."  # tailored
    assert cv["contact"] == base["contact"]
    assert cv["education"] == base["education"]                 # the model was sent the profile's own shape
    assert cv["skills"] == base["skills"]                       # one skill is too few to be a choice
    assert [(p["name"], p["link"], p["tech"]) for p in cv["projects"]] == [
        ("Rail Delay Forecaster", "rail-delays.example.app", ["Python", "PyTorch"]),
        ("Pantry Planner (meal planning)", "https://github.com/samokafor/pantry-planner", ["Next.js"]),
    ]
    assert cv["seniority"] == "junior"
    assert "sam@example.com" not in llm.prompts[-1] and "7700 900456" not in llm.prompts[-1]


def test_roles_keep_the_profiles_dates(llm):
    llm.reply = json.dumps(agent._persona_to_cvdoc(GRADUATE) | {"experience": [
        {"title": "Software Engineering Intern", "employer": "Brightwave Analytics", "start_date": "Jun 2024",
         "end_date": "Sep 2024", "bullets": ["Built a FastAPI service"]}]})
    role = _tailored_cv()["experience"][0]
    assert (role["start_date"], role["end_date"], role["bullets"]) == ("06/2024", "09/2024", ["Built a FastAPI service"])


def test_without_the_models_choice_every_profile_skill_reaches_the_cv(llm):
    html = doc_render.render_cv_html(_tailored_cv())   # the model failed: the profile's 8 groups as they are
    skills = html.split("<h2>Skills &amp; Technical Proficiency</h2>")[1].split("</section>")[0]
    missing = [s for grp in GRADUATE["skills"] for s in grp["skills"] if s not in skills]
    assert missing == [] and skills.count("<p>") == doc_render.MAX_SKILL_GROUPS


def _choosing(groups: dict[str, list[str]]) -> str:
    """The model's reply: the base CV with the skills it chose for the job."""
    cv = agent._persona_to_cvdoc(GRADUATE)
    return json.dumps(cv | {"skills": [{"category": c, "items": items} for c, items in groups.items()]})


CHOSEN = {   # 13 of the profile's 23 skills, the way the candidate's own CV groups them
    "Languages": ["Python", "SQL"],
    "Backend & Data": ["FastAPI", "PostgreSQL", "Redis"],
    "ML & AI": ["scikit-learn", "PyTorch", "pandas"],
    "Tools": ["Docker", "Git", "GitHub Actions", "AWS", "pytest"],
}


def test_the_model_chooses_the_skills_for_the_job(llm):
    llm.reply = _choosing({**CHOSEN, "Languages": ["python", "SQL"]})
    cv = _tailored_cv()
    assert cv["skills"] == [{"category": c, "items": items} for c, items in CHOSEN.items()]   # profile spelling
    assert "choose the 20-30 skills" in llm.prompts[-1] and "Leave out spoken languages" in llm.prompts[-1]


@pytest.mark.parametrize("change", [
    pytest.param(lambda g: g["Tools"].append("Kubernetes"), id="invents one"),
    pytest.param(lambda g: g["Tools"].append("Python"), id="repeats one"),
    pytest.param(lambda g: g["Tools"].append("GitHub Actions CI/CD pipelines"), id="renames one"),
])
def test_skills_the_model_invents_renames_or_repeats_are_dropped(llm, change):
    groups = copy.deepcopy(CHOSEN)
    change(groups)
    llm.reply = _choosing(groups)
    assert _tailored_cv()["skills"] == [{"category": c, "items": items} for c, items in CHOSEN.items()]


def test_an_unnamed_row_is_called_other():
    base = [{"category": "All", "items": [f"Skill {i}" for i in range(12)]}]
    chosen = agent._chosen_skills([{"category": "", "items": [f"Skill {i}" for i in range(12)]}], base)
    assert chosen == [{"category": "Other", "items": [f"Skill {i}" for i in range(12)]}]


@pytest.mark.parametrize("n, used", [(9, False), (10, True), (40, True), (41, False)])
def test_too_few_real_skills_or_too_many_falls_back_to_the_full_list(n, used):
    base = [{"category": "All", "items": [f"Skill {i}" for i in range(50)]}]
    chosen = agent._chosen_skills([{"category": "All", "items": [f"Skill {i}" for i in range(n)]}], base)
    assert (chosen is not None) is used


@pytest.mark.parametrize("core, location", [
    ({"city": "Bristol", "country": "United Kingdom"}, "Bristol, United Kingdom"),
    ({"city": "London, United Kingdom", "country": "United Kingdom"}, "London, United Kingdom"),
    ({"city": "Bristol"}, "Bristol"),
    ({"country": "United Kingdom"}, "United Kingdom"),
])
def test_the_cv_shows_city_and_country(core, location):
    assert agent._cv_location(core) == location


@pytest.mark.parametrize("categories, rows", [
    (["A", "B", "C", "D", "E", "F", "G", "H"], ["A", "B", "C", "D", "Other"]),
    (["A", "Other", "B", "C", "D", "E", "F"], ["A", "B", "C", "D", "Other"]),   # absorbs, moves last
    (["A", "B", "C"], ["A", "B", "C"]),
])
def test_extra_skill_groups_fold_into_other(categories, rows):
    groups = [{"category": c, "items": [f"{c}1", f"{c}2", "Shared"]} for c in categories]
    out = doc_render._skill_rows(groups)
    assert [r["category"] for r in out] == rows
    every = {s for g in groups for s in g["items"]}
    assert {s for r in out for s in r["items"]} == every
    if len(categories) > doc_render.MAX_SKILL_GROUPS:
        assert out[-1]["items"].count("Shared") == 1      # folded once, not once per group


def test_length_limits_hold_whatever_the_model_returns():
    cv = _full_cvdoc("experienced")
    cv["summary"] = " ".join(_sentence(20, i) + "." for i in range(6))
    cv["experience"] += [{"title": f"Old role {r}", "start_date": "2001", "end_date": "2003",
                          "bullets": ["x"] * 6} for r in range(2)]
    cv["experience"][0]["bullets"] += ["Fifth bullet", "Sixth bullet"]
    cv["projects"] += [{"name": "Project 3"}, {"name": "Project 4"}]
    cv["projects"][0]["description"] = " ".join(_sentence(30, i) + "." for i in range(8))
    cv["skills"][0]["items"] += ["Overflow skill"]
    cv["education"] *= 6
    cv["certifications"] *= 3

    data = doc_render.build_cv_template_data(cv)
    assert [r["title"] for r in data["experience"]] == ["Engineer 3", "Engineer 2", "Engineer 1", "Engineer 0"]
    assert max(len(r["bullets"]) for r in data["experience"]) == 4
    assert len(data["projects"]) == 4 and len(data["education"]) == 4 and len(data["certifications"]) == 6
    assert len(data["skills"][0]["items"]) == 15                                    # skills are never cut
    assert len(data["summary"]) <= 420 and data["summary"].endswith(".")          # ends on a whole sentence
    assert len(data["projects"][0]["description"]) <= 520 and data["projects"][0]["description"].endswith(".")


# ── Fitting a CV to its page target ─────────────────────────────────────────────

def _one_role_junior() -> dict:
    cv = _full_cvdoc("junior")
    cv["experience"] = cv["experience"][:1]
    return cv


@pytest.fixture
def pages(monkeypatch):
    """Stand-in for WeasyPrint's page count: `pages.rule(html) -> int`; every measured step is recorded."""
    class Pages:
        rule = staticmethod(lambda html: 1)
        steps: list[str] = []

    def count(html):
        classes = re.search(r"<body(?: class=\"([^\"]*)\")?>", html).group(1) or ""
        Pages.steps.append(classes.removeprefix("cv").strip())
        return Pages.rule(html)
    monkeypatch.setattr(doc_render, "_page_count", count)
    return Pages


def test_a_cv_that_fits_is_left_as_written(pages):
    html = doc_render.render_cv_html(_one_role_junior())
    assert pages.steps == [""] and '<body class="cv">' in html and html.count("<li>") == 4 and "Technologies:" in html


def test_spacing_then_type_tighten_before_anything_is_trimmed(pages):
    pages.rule = staticmethod(lambda html: 1 if 'tight small"' in html else 2)
    html = doc_render.render_cv_html(_one_role_junior())
    assert pages.steps == ["", "tight", "tight small"]
    assert html.count("<li>") == 4 and "Technologies:" in html


def test_trimming_goes_tech_lists_then_fourth_bullets_then_descriptions(pages):
    def rule(html):  # fits once each role has at most 3 bullets
        return 1 if html.count("<li>") <= 3 else 2
    pages.rule = staticmethod(rule)
    cv = _one_role_junior()
    for p in cv["projects"]:
        p["description"] = "What it does. How it works."
    html = doc_render.render_cv_html(cv)
    assert pages.steps == ["", "tight", "tight small", "tight small", "tight small"]
    assert "Technologies:" not in html and html.count("<li>") == 3
    assert "What it does. How it works." in html                           # descriptions kept whole


def test_when_nothing_fits_every_trim_is_applied_and_logged(pages, caplog):
    pages.rule = staticmethod(lambda html: 2)
    cv = _one_role_junior()
    for p in cv["projects"]:
        p["description"] = "What it does. How it works."
    html = doc_render.render_cv_html(cv)
    assert len(pages.steps) == 6 and "Technologies:" not in html and html.count("<li>") == 3
    assert "What it does." in html and "How it works." not in html
    assert "still runs to 2 pages (target 1)" in caplog.text


def test_an_experienced_cv_may_run_to_two_pages(pages):
    pages.rule = staticmethod(lambda html: 2)
    assert '<body class="cv">' in doc_render.render_cv_html(_full_cvdoc("experienced")) and pages.steps == [""]


def test_a_long_letter_tightens_its_layout_but_keeps_every_paragraph(pages):
    pages.rule = staticmethod(lambda html: 1 if 'class="tight small"' in html else 2)
    paragraphs = _letter_paragraphs((70, 95, 160, 55))
    html = doc_render.render_letter_html({"candidate_name": "Sam Okafor", "paragraphs": paragraphs})
    assert pages.steps == ["", "tight", "tight small"] and _letter_body(html)[1:] == paragraphs


def test_the_preview_is_fitted_like_the_pdf(client, pages):
    pages.rule = staticmethod(lambda html: 1 if 'class="cv tight"' in html else 2)
    html = client.post("/documents/preview", json={"type": "cv", "doc": _one_role_junior()}).json()["html"]
    assert '<body class="cv tight">' in html


def test_text_is_escaped_not_rendered_as_markup():
    cv = {"name": "Sam <script>alert(1)</script>",
          "experience": [{"title": "Intern", "bullets": ["Cut p99 latency to <50ms & halved cost"]}]}
    html = doc_render.render_cv_html(cv)
    assert "<script>alert" not in html and "Sam &lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "Cut p99 latency to &lt;50ms &amp; halved cost" in html


@pytest.mark.parametrize("raw, clean", [
    ("I am a backend engineer focused on payments.", "Backend engineer focused on payments."),
    ("I'm an analyst who automates reporting, looking for a team where I can learn.",
     "Analyst who automates reporting."),
    ("She is a designer working across print and web", "Designer working across print and web."),
    ("Data engineer with three years of Spark.", "Data engineer with three years of Spark."),
    ("", ""),
])
def test_summaries_are_depersonalised(raw, clean):
    assert doc_render._depersonalise(raw) == clean


# ── Cover letter ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("salutation, heading", [
    ("Dear Hiring Manager,", "Dear Hiring Manager"),
    ("Dear Ms Patel,", "Dear Ms Patel"),                        # a named contact is kept
    ("", "Dear Hiring Manager"),
])
def test_cover_letter_signs_off_as_the_candidate_does(llm, salutation, heading):
    llm.reply = json.dumps({"headline": "Computer Science Graduate", "salutation": salutation,
                            "paragraphs": _letter_paragraphs(), "signoff": "Yours faithfully,"})
    letter = _cover_letter()
    assert (letter["salutation"], letter["signoff"]) == (heading, "Kind Regards,")


def test_cover_letter_renders_every_paragraph_and_the_contact_block(llm):
    paragraphs = _letter_paragraphs() + ["A fifth, closing paragraph the model added."]
    llm.reply = json.dumps({"headline": "Computer Science Graduate", "salutation": "Dear Hiring Manager,",
                            "paragraphs": paragraphs, "signoff": "Kind Regards,"})
    html = doc_render.render_letter_html(_cover_letter())

    closing = f"{paragraphs[-1]} {agent._CLOSING_LINE}"                    # the closing paragraph isn't dropped
    assert _letter_body(html) == ["Dear Hiring Manager", *paragraphs[:-1], closing]
    assert 'Sam <span class="last">Okafor</span></h1>' in html            # the surname in the accent colour
    assert '<p class="headline">Computer Science Graduate</p>' in html
    assert ">Bristol.</p>" in html and 'href="mailto:sam@example.com"' in html and 'href="tel:+447700900456"' in html
    assert re.search(r'<p>Kind Regards,</p>\s*<p class="sig-name">Sam Okafor.</p>', html)

    # The left column: contact, then who it's to; the letter has no date and no "Re:" line.
    order = ["<h2>Contact</h2>", ">Bristol.</p>", "<p>Recruitment Team,</p>", "<p>Acme Robotics,</p>",
             "<p>Cambridge.</p>", '<td class="main">', "<h2>Dear Hiring Manager</h2>"]
    assert [html.index(s) for s in order] == sorted(html.index(s) for s in order)
    assert datetime.date.today().strftime("%d %B %Y") not in html and "Re:" not in html


@pytest.mark.parametrize("close", [
    "I'd welcome the chance to talk. Thank you for your consideration.",
    "I'd welcome the chance to talk. Thank you for your time. I look forward to hearing from you.",
    "I'd welcome the chance to talk.",
    "I'd welcome the chance to talk. Thank you for your time and consideration and I hope to hear from you soon.",
])
def test_the_letter_ends_on_the_candidates_closing_line(llm, close):
    llm.reply = json.dumps({"headline": "Computer Science Graduate", "salutation": "Dear Hiring Manager",
                            "paragraphs": _letter_paragraphs()[:3] + [close], "signoff": "Kind Regards,"})
    assert _cover_letter()["paragraphs"][-1] == (
        "I'd welcome the chance to talk. Thank you for your time and consideration and I hope to hear from you soon.")


def test_the_hook_says_why_the_employer_draws_the_candidate(llm):
    llm.reply = json.dumps({"headline": "Computer Science Graduate", "salutation": "Dear Hiring Manager",
                            "paragraphs": _letter_paragraphs(), "signoff": "Kind Regards,"})
    _cover_letter()
    assert "why that fact draws THIS candidate" in llm.prompts[0]


def test_c_plus_plus_stays_on_one_line():
    html = doc_render.render_letter_html({"candidate_name": "Sam Okafor", "paragraphs": ["I write C++ daily."]})
    assert "C+⁠+ daily" in html                                     # a word joiner between the plus signs


def test_the_letter_leaves_out_the_street_address():
    contact = {"address_line_1": "1 High Street", "city": "Bristol", "postcode": "BS1 1AA",
               "phone": "+44 7700 900456", "email": "sam@example.com"}
    html = doc_render.render_letter_html({"candidate_name": "Sam Okafor", "contact": contact, "paragraphs": ["Hi."]})
    assert "<p>Bristol BS1 1AA.</p>" in html and "High Street" not in html


@pytest.mark.parametrize("location, lines", [
    ("Cambridge, UK", ["Recruitment Team,", "Acme Robotics,", "Cambridge."]),
    ("London, UK (Hybrid)", ["Recruitment Team,", "Acme Robotics,", "London."]),
    ("London / Remote", ["Recruitment Team,", "Acme Robotics,", "London."]),
    ("", ["Recruitment Team,", "Acme Robotics."]),
])
def test_the_letter_is_addressed_to_the_employers_recruitment_team(location, lines):
    assert doc_render._letter_recipient_lines("Acme Robotics", location) == lines


def test_a_job_without_a_location_leaves_the_employers_location_blank(llm):
    persona = copy.deepcopy(GRADUATE)
    persona["core_info"]["country"] = "Nigeria"
    letter = asyncio.run(agent.execute_tool("generate_cover_letter",
                                            {"job": {**JOB, "location": ""}, "persona": persona}))["letter"]
    assert letter["company"] == "Acme Robotics" and letter["company_location"] == ""


def test_a_letter_without_contact_or_employer_has_no_empty_block():
    html = doc_render.render_letter_html({"candidate_name": "Sam Okafor", "paragraphs": ["Hello."]})
    page = html.split("</style>")[1]
    assert 'class="to"' not in page and "<h2>Contact</h2>" not in page


def test_cover_letter_without_the_model_still_reads_as_a_letter(llm):
    llm.reply = ""
    letter = _cover_letter()
    assert letter["headline"] == "Computer Science Graduate"      # from the degree
    assert letter["paragraphs"] == [GRADUATE["summary"]]
    assert (letter["salutation"], letter["signoff"]) == ("Dear Hiring Manager", "Kind Regards,")


# ── PDFs ─────────────────────────────────────────────────────────────────────────

def _weasyprint_loads() -> bool:
    try:
        import weasyprint  # noqa: F401
        return True
    except Exception:  # ImportError, or OSError when Pango is missing (Windows without GTK)
        return False


# Runs wherever WeasyPrint loads (CI and the API image); skipped elsewhere, but never in CI.
needs_weasyprint = pytest.mark.skipif(not _weasyprint_loads() and not os.environ.get("CI"),
                                      reason="WeasyPrint can't load here (it needs Pango)")


@pytest.fixture
def pdf_dir(tmp_path):
    pdf_generator.init_pdf_dir(str(tmp_path))
    return tmp_path


def _open(doc_id: str) -> fitz.Document:
    return fitz.open(pdf_generator.get_pdf_path(doc_id))


def _weasy(doc_type: str, doc: dict) -> fitz.Document:
    return _open(doc_render._weasyprint_pdf(doc_render.render_html(doc_type, doc)))


@needs_weasyprint
def test_the_graduate_cv_is_one_page_in_the_designs_type_with_live_links(pdf_dir):
    cv = agent._persona_to_cvdoc(GRADUATE) | {"seniority": "junior"}
    assert '<body class="cv">' in doc_render.render_cv_html(cv)          # fits without tightening
    pdf = _weasy("cv", cv)
    assert pdf.page_count == 1
    text = pdf[0].get_text()
    assert "Sam Okafor" in text and "Pantry Planner" in text and "Northfield University" in text
    assert any(f[3].endswith("+Caladea") for f in pdf[0].get_fonts())    # Cambria's metric twin, not a fallback
    spans = {s["text"].strip(): (round(s["size"], 1), "Bold" in s["font"], f"#{s['color']:06x}")
             for b in pdf[0].get_text("dict")["blocks"] for line in b.get("lines", []) for s in line["spans"]}
    assert spans["Sam Okafor"] == (25.8, False, "#1a1a1a")              # the candidate's CV, measured
    assert spans["Professional Summary"] == (13.2, True, "#1a1a1a")
    assert spans["Software Engineering Intern | Brightwave Analytics"] == (10.2, True, "#1a1a1a")
    assert spans["06/2024 – 09/2024"] == (9.0, False, "#595959")
    uris = {link.get("uri") for link in pdf[0].get_links()}
    assert {"mailto:sam@example.com", "https://github.com/samokafor"} <= uris


@needs_weasyprint
def test_a_full_graduate_cv_fits_one_page(pdf_dir):
    # Everything the tailoring prompt allows a junior: a 3-sentence summary, three roles with 2 bullets of
    # ~35 words, 4 projects of ~60 words with 8 technologies, 35 skills in 5 rows, 3 certificates.
    cv = _full_cvdoc("junior")
    cv["experience"] = cv["experience"][:3]
    for r in cv["experience"]:
        r["bullets"] = [_sentence(35, 1) + ".", _sentence(35, 2) + "."]
    cv["skills"] = [{"category": f"Group {g}", "items": [f"Skill{g}{i}" for i in range(7)]} for g in range(5)]
    cv["projects"] = [dict(cv["projects"][0], name=f"Project {i}", description=_sentence(30, 1) + ". " + _sentence(30, 2) + ".")
                      for i in range(4)]
    assert _weasy("cv", cv).page_count == 1


@needs_weasyprint
def test_an_experienced_cv_at_every_limit_fits_two_pages(pdf_dir):
    assert _weasy("cv", _full_cvdoc("experienced")).page_count <= 2


@needs_weasyprint
def test_a_full_length_cover_letter_fits_one_page(pdf_dir):
    letter = {"candidate_name": "Sam Okafor", "headline": "Computer Science Graduate",
              "contact": {"address_line_1": "1 High Street", "city": "Bristol", "postcode": "BS1 1AA",
                          "phone": "+44 7700 900456", "email": "sam@example.com"},
              "date": "15 October 2026", "company": "Acme Robotics", "company_location": "Cambridge, UK",
              "job_title": "Graduate Software Engineer (2027 start)",
              "paragraphs": _prose_paragraphs((110, 130, 110, 70))}   # longer than the ~380 words asked for
    assert '<body>' in doc_render.render_letter_html(letter)            # fits without tightening
    pdf = _weasy("cover_letter", letter)
    assert pdf.page_count == 1
    assert any(f[3].endswith("+Gelasio-Bold") for f in pdf[0].get_fonts())   # the bundled serif, not a fallback
    spans = {s["text"].strip(): (round(s["size"], 1), f"#{s['color']:06x}")
             for b in pdf[0].get_text("dict")["blocks"] for line in b.get("lines", []) for s in line["spans"]}
    assert spans["Okafor"] == (45.0, "#648276") and spans["Contact"] == (14.0, "#648276")   # the candidate's letter,
    assert spans["Kind Regards,"] == (10.0, "#648276")                                      # measured
    assert "High Street" not in pdf[0].get_text()
    mm = 25.4 / 72
    band = [d["rect"] for d in pdf[0].get_drawings() if d["rect"].y0 * mm > 280]
    assert band and round(band[0].y1 * mm) == 297                       # the sage band sits on the page's foot


@needs_weasyprint
def test_a_five_paragraph_letter_at_full_length_fits_one_page(pdf_dir):
    letter = {"candidate_name": "Sam Okafor", "headline": "Computer Science Graduate",
              "contact": {"address_line_1": "1 High Street", "city": "Bristol", "postcode": "BS1 1AA",
                          "phone": "+44 7700 900456", "email": "sam@example.com"},
              "date": "15 October 2026", "company": "Acme Robotics", "company_location": "Cambridge, UK",
              "job_title": "Graduate Software Engineer (2027 start)",
              "paragraphs": _prose_paragraphs((60, 75, 120, 70, 55))}   # 380 words, the prompt's top end
    pdf = _weasy("cover_letter", letter)
    assert pdf.page_count == 1
    assert letter["paragraphs"][-1] in " ".join(pdf[0].get_text().split())   # the last paragraph is on the page


@pytest.mark.parametrize("doc_type, doc, expected", [
    ("cv", agent._persona_to_cvdoc(GRADUATE),
     ["Sam Okafor", "Software Engineering Intern", "Pantry Planner", "BSc (Hons) Computer Science"]),
    ("cover_letter", {"candidate_name": "Sam Okafor", "job_title": "Graduate Software Engineer",
                      "company": "Acme Robotics", "company_location": "Cambridge, UK", "date": "15 October 2026",
                      "paragraphs": ["I would like to join Acme Robotics."]},
     ["Sam Okafor", "Recruitment Team, Acme Robotics, Cambridge.", "Dear Hiring Manager",
      "I would like to join Acme Robotics.", "Kind Regards, Sam Okafor."]),
])
def test_a_failing_weasyprint_falls_back_to_a_plain_pdf(pdf_dir, monkeypatch, doc_type, doc, expected):
    def broken(html):
        raise RuntimeError("cairo exploded")
    monkeypatch.setattr(doc_render, "_weasyprint_pdf", broken)
    text = " ".join(page.get_text() for page in _open(asyncio.run(doc_render.render_pdf(doc_type, doc))))
    text = re.sub(r"\s+", " ", text)
    assert [s for s in expected if s not in text] == []


# ── HTTP ─────────────────────────────────────────────────────────────────────────

def test_preview_pdf_and_download(client):
    cv = copy.deepcopy(agent._persona_to_cvdoc(GRADUATE))
    preview = client.post("/documents/preview", json={"type": "cv", "doc": cv})
    assert preview.status_code == 200 and "Sam Okafor" in preview.json()["html"]

    made = client.post("/documents/pdf", json={"type": "cv", "doc": cv}).json()
    assert made["download_url"] == f"/api/documents/{made['doc_id']}/download"
    pdf = client.get(f"/documents/{made['doc_id']}/download")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")


def test_pdf_requests_are_validated(client):
    assert client.post("/documents/pdf", json={"type": "cv"}).status_code == 400
    assert client.get("/documents/not-a-doc-id/download").status_code == 400
    assert client.get(f"/documents/{'0' * 32}/download").status_code == 404
