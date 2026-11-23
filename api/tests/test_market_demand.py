"""What employers ask for: each ad's skills are read once and kept only where the ad says them; the counts over
the ads for the user's target roles say which skills their profile shows; and the roadmap gets the counts, with
the figures shown beside each item looked up rather than taken from the model."""
import asyncio
import json

from app import agent, job_skills, jobs_db, main, market, tracker
from tests.conftest import make_job

AD = ("We need a Python engineer who knows Kubernetes and PostgreSQL, writes C++ for the hot path and runs CI/CD. "
      "Nice to have: Rust. ") * 8


# ── Reading one ad ────────────────────────────────────────────────────────────

def test_only_skills_the_ad_says_are_kept():
    raw = {"required": ["Python", "Kubernetes", "C++", "Python", "Terraform", "CI/CD", 42, ""],
           "preferred": ["Rust", "postgresql", "AWS"]}
    assert job_skills.parse(raw, "Engineer", AD) == {"required": ["Python", "Kubernetes", "C++", "CI/CD"],
                                                     "preferred": ["Rust", "postgresql"]}


def test_an_answer_with_nothing_in_the_ad_is_no_reading():
    assert job_skills.parse({"required": ["Terraform"], "preferred": []}, "Engineer", AD) is None
    assert job_skills.parse(None, "Engineer", AD) is None


def test_only_ads_with_enough_text_are_queued_and_a_new_ad_is_read_again(db):
    jobs_db.add_jobs([make_job(1, description=AD), make_job(2, description="Python role.")])
    queued = jobs_db.jobs_needing_skills(10, job_skills.SKILLS_VERSION)
    assert [r["title"] for r in queued] == ["Job"] and len(queued) == 1
    jobs_db.store_skills(queued[0]["id"], {"required": ["Python"], "preferred": []}, job_skills.SKILLS_VERSION)
    assert jobs_db.jobs_needing_skills(10, job_skills.SKILLS_VERSION) == []
    assert jobs_db.ads_with_skills()[0]["skills"] == {"required": ["Python"], "preferred": []}
    jobs_db.update_description(queued[0]["id"], AD + " Now with Go.")
    assert len(jobs_db.jobs_needing_skills(10, job_skills.SKILLS_VERSION)) == 1


def test_reading_pending_ads_stores_each_reading(db, monkeypatch):
    jobs_db.add_jobs([make_job(1, description=AD)])
    monkeypatch.setattr(tracker, "feed_locations", lambda: None)

    async def fake(system, user, max_tokens=900, label=""):
        return {"required": ["Python", "Haskell"], "preferred": ["Rust"]}
    monkeypatch.setattr(agent, "_llm_json", fake)
    assert asyncio.run(job_skills.read_pending()) == (1, 1)
    assert jobs_db.ads_with_skills()[0]["skills"] == {"required": ["Python"], "preferred": ["Rust"]}


# ── Counting across ads ──────────────────────────────────────────────────────

def _ad(i, title, required, preferred=(), level="junior"):
    return {"id": str(i), "title": title, "company": f"Co{i}", "level": level,
            "skills": {"required": list(required), "preferred": list(preferred)}}


PERSONA = {
    "preferences": {"target_titles": ["Graduate Software Engineer", "ML Engineer"]},
    "skills": [{"category": "Languages", "skills": ["Python"]}],
    "projects": [{"name": "RootLayer: compliance", "technologies": ["Postgres", "Docker"], "outcomes": "Ran CI/CD."}],
    "history": [{"employer": "Acme", "tech_stack": ["Kubernetes"], "achievements": []}],
}


def test_counts_say_which_asked_for_skills_the_profile_shows():
    ads = [_ad(1, "Software Engineer", ["Python", "PostgreSQL", "Rust"], ["Python"]),
           _ad(2, "Junior Software Engineer", ["Rust", "Kubernetes"]),
           _ad(3, "Machine Learning Engineer", ["Rust", "PyTorch", "CI/CD"]),
           _ad(4, "Software Engineer", ["Rust", "postgres"]),
           _ad(5, "Data Analyst", ["Rust", "Excel"])]   # not a target role
    m = market.demand(PERSONA, [], ads)
    assert m["roles"] == ["Software Engineer", "ML Engineer"] and m["ads"] == 4 and m["level"] == ""
    by = {s["key"]: s for s in m["skills"]}
    assert by["rust"]["ads"] == 4 and not by["rust"]["shown"]
    assert set(by) == {"rust"}           # the others are in fewer than 3 ads
    small = market.demand(PERSONA, [], ads * 3)
    by = {s["key"]: s for s in small["skills"]}
    assert by["postgresql"]["shown"] and by["postgresql"]["where"] == ["RootLayer"]
    assert by["kubernetes"]["where"] == ["Acme"] and by["ci cd"]["where"] == ["RootLayer"]
    assert by["python"]["ads"] == 3 and by["python"]["where"] == ["your skills"]   # once per ad


def test_the_users_level_is_counted_when_there_are_enough_ads():
    ads = [_ad(i, "Software Engineer", ["Rust"], level="junior") for i in range(30)]
    ads += [_ad(100 + i, "Senior Software Engineer", ["Leadership"], level="senior") for i in range(40)]
    m = market.demand(PERSONA, [], ads)
    assert m["level"] == "junior" and m["ads"] == 30 and [s["key"] for s in m["skills"]] == ["rust"]
    assert market.demand(PERSONA, [], ads[:29] + ads[30:])["level"] == ""    # too few junior ads: every level


def test_the_funnel_counts_sent_applications_per_role():
    apps = [{"job_title": "Junior Software Engineer", "status": "Rejected"},
            {"job_title": "Software Engineer", "status": "Interview"},
            {"job_title": "Machine Learning Engineer", "status": "Responded"},
            {"job_title": "Chef", "status": "Applied"},
            {"job_title": "Software Engineer", "status": "Saved"}]       # never sent
    f = market.demand(PERSONA, apps, [])["funnel"]
    assert f["total"] == {"applied": 4, "replies": 2, "interviews": 1, "rejected": 1}
    assert {r["role"]: r["applied"] for r in f["by_role"]} == {"Software Engineer": 2, "ML Engineer": 1, "Other roles": 1}


def test_gaps_the_fit_check_noted_are_listed_once_newest_first():
    apps = [{"created_at": "2026-01-01", "skill_gaps": ["Kubernetes", "Go"]},
            {"created_at": "2026-02-01", "skill_gaps": ["kubernetes", "Rust"]}]
    assert market.noted_gaps(apps) == ["kubernetes", "Rust", "Go"]


def test_the_market_endpoint_counts_the_users_own_profile_and_applications(client, user, monkeypatch):
    tracker.update_user_persona(user, PERSONA)
    jobs_db.add_jobs([make_job(i, title="Software Engineer", description=AD, level="junior") for i in range(4)])
    for row in jobs_db.jobs_needing_skills(10, job_skills.SKILLS_VERSION):
        jobs_db.store_skills(row["id"], {"required": ["Rust", "Python"], "preferred": []}, job_skills.SKILLS_VERSION)
    tracker.add_application(user, {"job_id": "x", "title": "Software Engineer", "company": "Acme"}, {}, "",
                            {"skill_gaps": ["Rust"]}, status="Applied")
    m = client.get("/careers/market").json()
    assert m["ads"] == 4 and m["waiting"] == 0
    assert [(s["name"], s["shown"]) for s in m["skills"]] == [("Python", True), ("Rust", False)]
    assert m["funnel"]["total"]["applied"] == 1 and m["noted_gaps"] == ["Rust"]


# ── The roadmap ───────────────────────────────────────────────────────────────

def test_the_roadmap_sees_the_projects_and_the_counts_and_its_figures_are_looked_up(monkeypatch):
    seen = {}

    async def fake_llm(system, user, max_tokens=2048):
        seen.update(system=system, user=user)
        return json.dumps({"items": [{"skill": "Rust", "reason": "Asked for in 999 ads."}, {"skill": "Haskell"}]})
    monkeypatch.setattr(agent, "_llm", fake_llm)
    ads = [_ad(i, "Software Engineer", ["Rust", "Python"]) for i in range(5)]
    m = market.demand(PERSONA, [{"job_title": "Software Engineer", "status": "Rejected"}], ads)
    out = asyncio.run(agent.execute_tool("generate_skill_roadmap", {"persona": PERSONA, "market": m}))
    assert "- RootLayer: Postgres, Docker" in seen["user"] and "Acme (Kubernetes)" in seen["user"]
    assert "- Rust: asked for in 5 of 5 ads (5 as required); NOT shown anywhere in the profile" in seen["user"]
    assert "- Python: asked for in 5 of 5 ads (5 as required); shown in: your skills" in seen["user"]
    assert "1 sent, 0 replies, 0 interviews, 1 rejections" in seen["user"]
    assert "never invent one" in seen["system"]
    assert [i["market"] for i in out["items"]] == [{"ads": 5, "of": 5, "shown": False}, None]


def test_the_prompt_block_is_empty_without_counts():
    assert market.prompt_block({}) == "" and market.prompt_block(market.demand(PERSONA, [], [])) == ""


def test_main_passes_the_market_to_the_roadmap(client, user, monkeypatch):
    got = {}

    async def tool(name, tool_input):
        got.update(name=name, keys=set(tool_input))
        return {"status": "generated", "items": []}
    monkeypatch.setattr(main, "execute_tool", tool)
    client.post("/careers/roadmap").text
    assert got == {"name": "generate_skill_roadmap", "keys": {"persona", "market"}}
