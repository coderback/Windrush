"""
Does the critique-and-revise pass make tailored CVs and cover letters better?

For each advert below, the graduate profile from tests/test_documents.py is tailored with the real
model and the critique off (the draft). The critique then runs on the draft as it does in
production, including the guard that drops a rewrite with an unsupported claim or that runs long.
Where it changed something, a judge sees the draft and the revision blind, in both orders (a version
wins only when both agree) and says which better serves the advert. Every run writes evals/last_doc_run.json.

The bar: no kept revision may carry a claim the document check flags that the draft didn't, and for
cover letters (which get the critique by default) the revision must win more often than it loses.
CVs are measured only: across the first three runs they were mixed (draft 3-1, then revision 4-0 and
2-0), so the CV critique is off by default.
"""
import asyncio
import json
import pathlib

import pytest

from app import agent, doc_check
from test_documents import GRADUATE

HERE = pathlib.Path(__file__).parent

ADS = [
    {"title": "Graduate Backend Engineer", "company": "Harbourline", "location": "London",
     "description": "Harbourline builds the booking platform behind 400 ferry routes. As a graduate backend engineer "
                    "you will design and ship Python services (FastAPI) backed by PostgreSQL, write tests with "
                    "pytest, and run them in Docker on AWS. You will own features end to end, from API design to "
                    "monitoring in production. We look for: a degree in a STEM subject or equivalent experience; "
                    "solid Python; SQL; an understanding of REST API design; curiosity about distributed systems."},
    {"title": "Junior Data Engineer", "company": "Meridian Health Analytics", "location": "Bristol",
     "description": "Join a small team turning hospital operations data into dashboards that clinicians use daily. "
                    "You will build ETL pipelines in Python and SQL, model data in PostgreSQL, schedule jobs with "
                    "Airflow and keep data quality high with automated tests. Nice to have: pandas, dbt, AWS. "
                    "You care about getting numbers right and explaining them to non-technical colleagues."},
    {"title": "Graduate Machine Learning Engineer", "company": "Signalbox Rail", "location": "Manchester",
     "description": "Signalbox predicts disruption on UK rail networks. You will train and evaluate forecasting "
                    "models in Python with PyTorch and scikit-learn, build data pipelines for live feeds, and help "
                    "deploy models behind APIs. We value rigorous evaluation, clear write-ups and pragmatic "
                    "engineering. Requirements: Python, machine learning fundamentals, SQL, Git."},
    {"title": "Graduate Frontend Developer", "company": "Larder", "location": "Remote, UK",
     "description": "Larder helps households waste less food. You will build features in React and Next.js with "
                    "TypeScript, write component and end-to-end tests (Jest, Playwright), and work closely with "
                    "design. You will ship to thousands of users weekly. We want: TypeScript, React, attention to "
                    "accessibility and performance, and a portfolio of things you have built."},
    {"title": "Graduate Software Engineer, Trading Systems", "company": "Quayside Capital", "location": "London",
     "description": "Write low-latency, well-tested software for our trading platform in Java and Python. You will "
                    "work on market data services, use data structures and algorithms to make them fast, and pair "
                    "with traders to understand requirements. Strong programming fundamentals, a quantitative "
                    "mindset and a 2:1 or above in Computer Science, Maths or Physics."},
    {"title": "Graduate DevOps Engineer", "company": "Cloudrail", "location": "Leeds",
     "description": "Help our platform team automate everything. You will build CI/CD pipelines with GitHub "
                    "Actions, containerise services with Docker, manage AWS infrastructure and write Python "
                    "tooling. Kubernetes and Terraform experience is a bonus. You enjoy making other engineers "
                    "faster and systems more reliable."},
]

JUDGE = (
    "You are an experienced UK graduate recruiter. You see one job advert and two versions (A and B) of the same "
    "candidate's {kind}, written from the same facts. Decide which version better serves THIS advert: it answers "
    "the advert's main requirements visibly and in the advert's terms, proves claims with concrete specifics and "
    "results, reads as written by a person (no clichés, filler or hedging), and is concise. Ignore formatting. "
    'If they are equally good, say tie. Return ONLY JSON: {{"better": "A" | "B" | "tie", "reason": str}}.'
)


def _candidate(job):
    base = agent._persona_to_cvdoc(GRADUATE)
    return {**base, "contact": {}, "projects": agent._rank_projects_by_relevance(job, agent._persona_projects_for_llm(GRADUATE))}


async def _judge_once(kind: str, job: dict, draft, revised, revised_first: bool) -> tuple[str, str]:
    a, b = (revised, draft) if revised_first else (draft, revised)
    verdict = await agent._llm_json(
        system=JUDGE.format(kind=kind),
        user=f"ADVERT: {job['title']} at {job['company']}\n{job['description']}\n\n"
             f"VERSION A:\n{json.dumps(a, ensure_ascii=False)}\n\nVERSION B:\n{json.dumps(b, ensure_ascii=False)}",
        max_tokens=600, label="eval_judge")
    pick, reason = (verdict or {}).get("better", "tie"), str((verdict or {}).get("reason", ""))
    if pick == "tie" or pick not in ("A", "B"):
        return "tie", reason
    return ("revised" if (pick == "A") == revised_first else "draft"), reason


async def _judge(kind: str, job: dict, draft, revised) -> tuple[str, list[str]]:
    """Judged in both orders; a version wins only when both say so (position bias cancels out)."""
    (first, r1), (second, r2) = await asyncio.gather(_judge_once(kind, job, draft, revised, True),
                                                     _judge_once(kind, job, draft, revised, False))
    return (first if first == second else "tie"), [r1, r2]


async def _one(i: int, job: dict) -> dict:
    out = {"job": f"{job['title']} @ {job['company']}"}
    cv = (await agent.execute_tool("generate_tailored_cv", {"job": job, "persona": GRADUATE}))["cv"]
    letter = (await agent.execute_tool("generate_cover_letter", {"job": job, "persona": GRADUATE}))["letter"]

    revised_cv, cv_issues = await agent._critique_cv_text(cv, _candidate(job), job)
    cv_kept = revised_cv is not None and agent._critique_holds("cv", cv, revised_cv, GRADUATE, job)
    revised_letter, letter_issues = await agent._critique_letter_text(letter, GRADUATE, job, "")
    letter_kept = revised_letter is not None and agent._critique_holds("cover_letter", letter, revised_letter, GRADUATE, job)

    for kind, draft, revised, issues, kept, text in (
        ("CV", cv, revised_cv, cv_issues, cv_kept, agent._cv_text),
        ("cover letter", letter, revised_letter, letter_issues, letter_kept, lambda d: d.get("paragraphs")),
    ):
        key = "cv" if kind == "CV" else "letter"
        new_flags = []
        if revised is not None:
            before = doc_check.check_facts("cv" if key == "cv" else "cover_letter", draft, GRADUATE, job)
            after = doc_check.check_facts("cv" if key == "cv" else "cover_letter", revised, GRADUATE, job)
            new_flags = sorted(agent._finding_keys(after) - agent._finding_keys(before))
        result = {"issues": issues, "rewrote": revised is not None, "kept": kept, "new_flags": [list(f) for f in new_flags],
                  "draft": text(draft), "revised": text(revised) if revised is not None else None}
        if kept:
            result["verdict"], result["reasons"] = await _judge(kind, job, text(draft), text(revised))
        out[key] = result
    return out


@pytest.fixture
def no_research(monkeypatch):
    async def none(*args, **kwargs):
        return ""
    monkeypatch.setattr(agent, "_research_company", none)
    monkeypatch.setattr(agent, "_DOC_CRITIQUE", set())   # drafts without the critique; it runs separately


def test_critique_improves_documents(no_research):
    async def run():
        sem = asyncio.Semaphore(3)

        async def guarded(i, job):
            async with sem:
                return await _one(i, job)
        return await asyncio.gather(*(guarded(i, j) for i, j in enumerate(ADS)))

    results = asyncio.run(run())
    (HERE / "last_doc_run.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")

    score = {}
    for key in ("cv", "letter"):
        verdicts = [r[key]["verdict"] for r in results if "verdict" in r[key]]
        score[key] = (verdicts.count("revised"), verdicts.count("draft"))
        print(f"{key}: issues found {sum(bool(r[key]['issues']) for r in results)}/{len(results)}, "
              f"rewrites kept {sum(r[key]['kept'] for r in results)}, revised won {score[key][0]}, "
              f"lost {score[key][1]}, tied {verdicts.count('tie')}")
        # The guard must have dropped any rewrite with a new unsupported claim.
        assert not any(r[key]["kept"] and r[key]["new_flags"] for r in results)
    # Letters get the critique by default (agent._DOC_CRITIQUE), so they must gain from it; CVs are measured
    # so a change to the CV critique can be judged before it's turned on.
    wins, losses = score["letter"]
    assert wins > losses, f"letters: the critique didn't beat its drafts ({wins} wins, {losses} losses)"
