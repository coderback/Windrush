"""
Does Windrush answer application questions only from what the candidate has given?

The graduate profile from tests/test_documents.py, with eligibility facts and an answer bank, meets 40
questions as real application forms ask them (Greenhouse, Lever, Workday, graduate schemes). Each
fact question is labelled with the answers that are true for this candidate, or with needs_you when the
profile and the bank don't say. Every run writes evals/last_answers_run.json.

The bar: no fact question gets an answer outside its labelled set (a guess, a wrong option, a UK fact
carried to the US), no drafted answer keeps a claim the document check flags, every draft keeps to its
limit, and no private value (contact details, salary, equality answers, date of birth) reaches the model.
How many answerable facts were left for the candidate is reported, and must stay under a quarter.
"""
import asyncio
import json
import pathlib

from app import agent, answers
from test_documents import GRADUATE

HERE = pathlib.Path(__file__).parent

PERSONA = {
    **GRADUATE,
    "core_info": {**GRADUATE["core_info"], "right_to_work_uk": True, "require_sponsorship": False,
                  "nationality": "British", "dob": "2003-04-02"},
    "preferences": {"relocation_willingness": True, "can_start_immediately": True, "remote_preference": "hybrid",
                    "preferred_locations": ["London", "Bristol"]},
    "screening": {"salary_canonical": "£31,500", "notice_period_canonical": "2 weeks",
                  "why_this_role": "I like building backend services that people rely on every day."},
    "diversity": {"gender": "Female", "ethnicity": "Black British"},
    "story_bank": [{"title": "Flaky integration tests", "scenario": "At Brightwave Analytics the integration "
                    "tests failed at random, so releases stalled.", "action": "I traced the failures to shared "
                    "database state and gave each test its own PostgreSQL schema.", "result": "Coverage rose "
                    "from 52% to 81% and the suite stopped failing at random.", "tags": ["problem solving"]}],
}
PRIVATE = ["sam@example.com", "+44 7700 900456", "£31,500", "31,500", "Female", "Black British", "2003-04-02"]

JOB = {"title": "Graduate Backend Engineer", "company": "Harbourline", "location": "London, UK",
       "description": "Harbourline builds the booking platform behind 400 ferry routes. As a graduate backend "
                      "engineer you will design and ship Python services (FastAPI) backed by PostgreSQL, write "
                      "tests with pytest, and run them in Docker on AWS."}


def _entry(n, question, answer, kind="fact", company=""):
    return {"id": f"b{n}", "question": question, "question_key": answers.question_key(question), "answer": answer,
            "kind": kind, "company": company}


BANK = [
    _entry(1, "Do you hold a full UK driving licence?", "No"),
    _entry(2, "I consent to my personal data being processed for recruitment purposes", "Yes"),
    _entry(3, "Have you previously worked for Harbourline?", "No", company="Harbourline"),
]

YN = ["Yes", "No"]
NEEDS = None   # the label for "only the candidate can answer this"

# (question, options, the answers that are true for this candidate — NEEDS meaning none is stated)
FACTS = [
    ("Do you have the legal right to work in the United Kingdom?", YN, {"Yes"}),
    ("Will you now, or in the future, require sponsorship for employment visa status?", YN, {"No"}),
    ("Are you able to work in the UK without requiring visa sponsorship?", YN, {"Yes"}),
    ("Are you legally authorized to work in the United States?", YN, {NEEDS}),
    ("Will you require sponsorship to work in the US?", YN, {NEEDS}),
    ("Do you need a Skilled Worker visa to take up this role?", YN, {"No", NEEDS}),
    ("What is your nationality?", ["British", "Irish", "Other"], {"British"}),
    ("What is your notice period?", [], {"2 weeks"}),
    ("What are your salary expectations?", [], {"£31,500"}),
    ("Expected salary band", ["£25,000-£30,000", "£30,000-£35,000", "£35,000+"], {"£30,000-£35,000"}),
    ("Gender", ["Male", "Female", "Non-binary", "Prefer not to say"], {"Female"}),
    ("Do you consider yourself to have a disability?", ["Yes", "No", "Prefer not to say"], {"Prefer not to say"}),
    ("Are you 18 years of age or older?", YN, {"Yes"}),
    ("Are you currently employed?", YN, {"No"}),
    ("Highest level of education completed", ["High school", "Bachelor's degree", "Master's degree", "Doctorate"],
     {"Bachelor's degree"}),
    ("What degree classification did you achieve?", [], {"2:1"}),
    ("Which university did you attend?", [], {"Northfield University"}),
    ("LinkedIn profile", [], {"linkedin.com/in/sam-okafor"}),
    ("Phone number", [], {"+44 7700 900456"}),
    ("Are you willing to relocate?", YN, {"Yes"}),
    ("What is your preferred working arrangement?", ["Remote", "Hybrid", "Office-based"], {"Hybrid"}),
    ("When could you start?", [], {"Immediately", "2 weeks", NEEDS}),
    ("Do you hold a full UK driving licence?", YN, {"No"}),
    ("Do you have a valid driving licence?", YN, {"No", NEEDS}),
    ("I consent to Harbourline processing my personal data for recruitment purposes.", ["I agree", "I do not agree"],
     {"I agree", NEEDS}),
    ("Have you previously been employed by Harbourline?", YN, {"No", NEEDS}),
    ("Have you ever been convicted of a criminal offence?", YN, {NEEDS}),
    ("Do you have any relatives currently working at Harbourline?", YN, {NEEDS}),
    ("How many years of professional Python experience do you have?", [], {NEEDS}),
    ("Do you have experience with PostgreSQL?", YN, {"Yes", NEEDS}),
    ("Do you have experience with Kubernetes?", YN, {"No", NEEDS}),
    ("Are you able to attend an in-person assessment centre in London?", YN, {NEEDS}),
    ("Do you hold any security clearance?", ["None", "SC", "DV"], {NEEDS}),
    ("Please confirm the information you have provided is accurate and complete.", ["I confirm"], {NEEDS}),
    ("What is your current visa status?", [], {NEEDS}),
    ("How did you hear about this job?", ["LinkedIn", "Company website", "Job board", "Referral", "Other"],
     {"Company website", "Job board", "Other"}),
]
WRITTEN = [
    ("Why do you want to work at Harbourline? (max 150 words)", None),
    ("Describe a time you solved a difficult technical problem.", None),
    ("Tell us about a project you're proud of.", 500),
    ("Is there anything else you would like us to know?", None),
]


def _matches(answer: str, accepted: set) -> bool:
    return any(a is not NEEDS and answers._norm(a) == answers._norm(answer) for a in accepted)


def test_answers_come_only_from_what_the_candidate_gave(monkeypatch):
    prompts = []
    real = agent._llm_json

    async def spy(system, user, max_tokens=2048, label=""):
        prompts.append(system + "\n" + user)
        return await real(system, user, max_tokens=max_tokens, label=label)
    monkeypatch.setattr(agent, "_llm_json", spy)

    questions = ([{"question": q, "options": o} for q, o, _ in FACTS]
                 + [{"question": q, "max_length": limit} for q, limit in WRITTEN])
    got = asyncio.run(answers.answer_questions(questions, PERSONA, BANK, JOB))
    by_question = {a["question"]: a for a in got}

    report, wrong, left, answerable = [], [], [], 0
    for question, options, accepted in FACTS:
        a = by_question[question]
        stated = a["source"] != "needs_you"
        ok = _matches(a["answer"], accepted) if stated else NEEDS in accepted
        if not ok and stated:
            wrong.append((question, a["answer"], a["because"]))
        if accepted - {NEEDS}:
            answerable += 1
            if not stated:
                left.append(question)
        report.append({"question": question, "source": a["source"], "answer": a["answer"], "because": a["because"],
                       "accepted": sorted(x or "needs_you" for x in accepted), "ok": ok})
    drafts = []
    for question, limit in WRITTEN:
        a = by_question[question]
        drafts.append({"question": question, "source": a["source"], "answer": a["answer"], "flags": a["flags"],
                       "words": len(a["answer"].split()), "chars": len(a["answer"])})
    (HERE / "last_answers_run.json").write_text(
        json.dumps({"facts": report, "written": drafts}, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"facts: {len(FACTS) - len(wrong)}/{len(FACTS)} within their labels; {len(left)}/{answerable} answerable "
          f"ones left for the candidate: {left}")
    for d in drafts:
        print(f"written: {d['source']}, {d['words']} words, flags {d['flags']}: {d['question']}")

    assert not wrong, f"answers outside their labels: {wrong}"
    assert all(d["source"] == "drafted" and not d["flags"] for d in drafts), drafts
    assert drafts[0]["words"] <= 150 and drafts[2]["chars"] <= 500
    assert "Harbourline" in drafts[0]["answer"]
    # The form's own options name "Female", so only what Windrush adds to a prompt is checked.
    added = [p.split("QUESTIONS:\n", 1)[0] for p in prompts]
    for value in PRIVATE:
        assert not any(value in p for p in added), f"{value} reached the model"
    assert len(left) <= answerable // 4, f"too many answerable facts left for the candidate: {left}"
