"""The career plan: the model's answer is checked before it's kept (unknown values reset, a project it builds on must
be the user's own, ad counts looked up), the newest plan is the user's, and its items can be ticked off by its owner
only."""
import json

from app import career_plan, main, tracker

PERSONA = {"preferences": {"target_titles": ["ML Engineer"]},
           "projects": [{"name": "Cambium: graph ML core", "technologies": ["PyTorch"]}]}
DEMAND = {"ads": 40, "skills": [{"key": "kubernetes", "name": "Kubernetes", "ads": 18, "shown": False}]}

RAW = {
    "diagnosis": "Strong ML research, little production infrastructure.",
    "strengths": ["Reproducible GPU training (Cambium)", "", 7],
    "goals": [{"goal": "Ship a model service", "measure": "Deployed with CI", "by": "60 days"},
              {"goal": "Interview at 3 ML roles", "measure": "3 first rounds", "by": "next year"},
              {"measure": "no goal"}],
    "tracks": [
        {"skill": "Kubernetes", "why": "18 of 40 ads ask for it.", "study": ["Pods and deployments", "Helm", ""],
         "resources": ["Kubernetes Up & Running"],
         "project": {"title": "Serve Cambium on k8s", "brief": "Package the scorer.", "builds_on": "cambium",
                     "done_when": "A rolling deploy passes"},
         "proof": {"kind": "certification", "target": "CKAD", "why": "Checkable."}, "timeline": "2 months"},
        {"skill": "MLOps", "study": "not a list", "project": {"title": "Feature store", "builds_on": "Someone else's"},
         "proof": {"kind": "badge", "target": "A merged PR to Feast"}, "timeline": "forever"},
        {"why": "no skill"},
    ],
    "applications": ["Apply to ML platform roles, where replies came from."],
}


def test_the_models_plan_is_checked_and_its_items_get_ids():
    plan = career_plan.validate(RAW, PERSONA, DEMAND)
    assert plan["strengths"] == ["Reproducible GPU training (Cambium)"]
    assert [(g["id"], g["by"]) for g in plan["goals"]] == [("g1", "60 days"), ("g2", "90 days")]
    k8s, mlops = plan["tracks"]
    assert k8s["market"] == {"ads": 18, "of": 40, "shown": False} and mlops["market"] is None
    assert [s["id"] for s in k8s["study"]] == ["t1.s1", "t1.s2"] and mlops["study"] == []
    assert k8s["project"]["builds_on"] == "Cambium" and mlops["project"]["builds_on"] == ""
    assert k8s["resources"] == [{"name": "Kubernetes Up & Running", "url": "", "checked": False}]
    assert (k8s["proof"]["kind"], mlops["proof"]["kind"]) == ("certification", "portfolio")
    assert (k8s["timeline"], mlops["timeline"]) == ("2 months", "3 months")
    assert career_plan.item_ids(plan) == {"g1", "g2", "t1.s1", "t1.s2", "t1.p", "t1.r", "t2.p", "t2.r"}


def test_a_plan_without_a_track_is_no_plan():
    assert career_plan.validate({"goals": RAW["goals"]}, PERSONA, DEMAND) is None
    assert career_plan.validate(None, PERSONA, DEMAND) is None


def test_the_prompt_names_the_users_projects_and_targets():
    text = career_plan.prompt(PERSONA, {})
    assert "Target roles: ML Engineer" in text and "- Cambium: PyTorch" in text
    assert "email" not in text.lower()


def _generate(client, monkeypatch, raw):
    async def tool(name, tool_input):
        return {"plan": career_plan.validate(raw, tool_input["persona"], tool_input["market"])}
    monkeypatch.setattr(main, "execute_tool", tool)
    events = [json.loads(line[6:]) for line in client.post("/careers/plan").text.splitlines() if line.startswith("data: ")]
    return {e["type"]: e for e in events}


def test_a_generated_plan_is_kept_and_its_items_ticked_off(client, user, monkeypatch):
    tracker.update_user_persona(user, PERSONA)
    assert client.get("/careers/plan").json() == {"plan": None}
    saved = _generate(client, monkeypatch, RAW)["plan"]
    assert saved["target"] == "ML Engineer" and saved["done"] == [] and saved["plan"]["tracks"][0]["skill"] == "Kubernetes"
    body = {"plan_id": saved["id"], "item_id": "t1.s2", "done": True}
    assert client.put("/careers/plan/items", json=body).json() == {"done": ["t1.s2"]}
    assert client.put("/careers/plan/items", json={**body, "item_id": "t9.s1"}).status_code == 404
    assert client.get("/careers/plan").json()["done"] == ["t1.s2"]
    assert client.put("/careers/plan/items", json={**body, "done": False}).json() == {"done": []}


def test_a_new_plan_replaces_the_old_and_another_user_cant_touch_it(client, client_for, make_user, user, monkeypatch):
    tracker.update_user_persona(user, PERSONA)
    first = _generate(client, monkeypatch, RAW)["plan"]
    second = _generate(client, monkeypatch, {**RAW, "diagnosis": "Newer."})["plan"]
    assert second["id"] != first["id"] and client.get("/careers/plan").json()["plan"]["diagnosis"] == "Newer."
    other = client_for(make_user("other@example.com"))
    assert other.get("/careers/plan").json() == {"plan": None}
    assert other.put("/careers/plan/items", json={"plan_id": second["id"], "item_id": "g1", "done": True}).status_code == 404


def test_an_empty_answer_is_an_error_not_a_saved_plan(client, user, monkeypatch):
    events = _generate(client, monkeypatch, {"tracks": []})
    assert events["error"]["message"] == "The plan came back empty. Try again." and "plan" not in events
    assert client.get("/careers/plan").json() == {"plan": None}
