"""
The career plan: from the whole profile, the target roles and what their ads ask for (market.py), one LLM call
writes a diagnosis, goals with dates, and a track per gap (study steps, resources, a project brief that builds on
the user's own work where it can, and a proof point to aim for), plus advice on how they apply.

The model's answer is checked before it is kept: unknown values are dropped or reset, a project it "builds on"
must be one of the user's, and the ad counts shown with each track are looked up, never taken from its text.
Every checkable item gets an id so progress can be ticked off.
"""
import re

from . import market
from .risk_scorer import target_evidence

GOAL_BY = ("30 days", "60 days", "90 days")
TIMELINES = ("1 month", "2 months", "3 months", "6 months")
PROOF_KINDS = ("certification", "competition", "publication", "open_source", "portfolio", "talk")

SYSTEM = """You are a career coach for people trying to land a role they are aiming for. From the candidate's whole profile, their target roles, what the ads for those roles ask for and how their applications have gone, write a plan that would genuinely move them forward. Return ONLY a JSON object with exactly these keys:

"diagnosis": 2-4 sentences on where they stand against the target roles: what they already show that the ads ask for, and the biggest gaps.
"strengths": 3-5 short strengths the profile proves, each naming the project or job that proves it.
"goals": 3-5 objects {"goal": an outcome to reach, "measure": how they will know it's reached (checkable), "by": "30 days", "60 days" or "90 days"}.
"tracks": 4-6 objects, one per gap to close, most important first, each with:
  "skill": a short name; when it is one of the counted skills, its exact name,
  "why": 1-2 sentences on why it matters for the target roles,
  "study": 3-6 ordered, concrete study steps,
  "resources": 1-3 specific, real courses, books, official docs or tutorials, by exact name, no links,
  "project": {"title": a name, "brief": 2-3 sentences on what to build and which part exercises the skill, "builds_on": the exact name of one of the candidate's projects it extends, or "" for a new one, "done_when": a checkable finish line},
  "proof": {"kind": "certification", "competition", "publication", "open_source", "portfolio" or "talk", "target": one specific thing to achieve (a named certification, a placing in a named competition, a merged pull request to a named project...), "why": one sentence},
  "timeline": "1 month", "2 months", "3 months" or "6 months".
"applications": 2-4 pieces of advice on how they apply, grounded in their application numbers when given (which roles reply, where to focus, what to change).

RULES:
1. Plan for the TARGET roles across the employers who hire for them. Past employers' industries are background only.
2. Build ON their existing strengths. Never make a track of a skill the profile already lists or shows in a project or job.
3. When counts of what employers ask for are given, they are the strongest evidence: choose gaps many ads ask for that the profile does NOT show. Use given numbers exactly and never invent one.
4. Prefer projects that extend one of their own projects over toy projects, and proof points an employer can check.
5. If usage evidence about AI is given, favour work people hand to AI least; treat it as a hint and never quote its figures or call a skill safe or at risk.
6. No generic soft skills (leadership, communication) unless they already work in a non-technical or hybrid role.
7. Never claim to know why an application was rejected: rejections don't say.
8. Name only resources you are confident exist; never invent a course, book or certification."""


def _short(name: str) -> str:
    return re.split(r"\s*[:·|]\s*", name or "", maxsplit=1)[0].strip()


def prompt(persona: dict, demand: dict) -> str:
    """The user message: the profile (no contact details), the target roles, the counts and the AI-usage hint."""
    targets = (persona.get("preferences") or {}).get("target_titles") or []
    skills = ", ".join(s for g in persona.get("skills") or [] for s in g.get("skills") or [])
    jobs = "".join(
        f"\n- {h.get('title', '')} at {h.get('employer', '')}"
        + (f" ({', '.join(h.get('tech_stack') or [])})" if h.get("tech_stack") else "")
        for h in (persona.get("history") or [])[:6])
    projects = "".join(
        f"\n- {_short(p.get('name') or '')}: {', '.join(p.get('technologies') or [])}"
        for p in persona.get("projects") or [] if p.get("name"))
    education = "; ".join(f"{e.get('degree', '')} at {e.get('institution', '')}" for e in (persona.get("education") or [])[:2])
    certs = ", ".join(c.get("name", "") for c in persona.get("certifications") or [] if c.get("name"))
    evidence = target_evidence(targets)
    out = (f"Target roles: {', '.join(targets) or 'not specified'}\n"
           f"Background: {persona.get('summary', '')}\n"
           f"Education: {education}\n"
           f"Jobs: {jobs}\n"
           f"Skills they list: {skills}\n"
           + (f"Certifications: {certs}\n" if certs else "")
           + (f"Projects and the technologies they used: {projects}\n" if projects else "")
           + (f"\n{market.prompt_block(demand)}" if market.prompt_block(demand) else ""))
    if evidence:
        tasks = lambda key: "; ".join(t["task"] for t in evidence[key])  # noqa: E731
        out += (f"\nUsage evidence for {evidence['occupation']} (Anthropic Economic Index, chat conversations, "
                f"{evidence['month']}):\nHanded to AI most: {tasks('most_handed_to_ai')}\n"
                f"Handed to AI least: {tasks('least_handed_to_ai')}\n")
    return out + "\nWrite the plan."


def _text(value, limit: int = 600) -> str:
    return re.sub(r"\s+", " ", value).strip()[:limit] if isinstance(value, str) else ""


def _texts(values, limit: int, each: int = 300) -> list[str]:
    return [t for t in (_text(v, each) for v in (values if isinstance(values, list) else [])) if t][:limit]


def validate(raw: dict | None, persona: dict, demand: dict) -> dict | None:
    """The plan as kept: well-formed parts only, each checkable item with an id. None without a single track."""
    if not isinstance(raw, dict):
        return None
    own = {_short(p.get("name") or "").lower(): _short(p.get("name") or "") for p in persona.get("projects") or []}
    counted = {s["key"]: s for s in demand.get("skills") or []}

    goals = []
    for g in raw.get("goals") if isinstance(raw.get("goals"), list) else []:
        if isinstance(g, dict) and _text(g.get("goal")):
            goals.append({"id": f"g{len(goals) + 1}", "goal": _text(g.get("goal"), 300),
                          "measure": _text(g.get("measure"), 300),
                          "by": g.get("by") if g.get("by") in GOAL_BY else "90 days"})
    tracks = []
    for t in raw.get("tracks") if isinstance(raw.get("tracks"), list) else []:
        if not isinstance(t, dict) or not _text(t.get("skill"), 80):
            continue
        tid = f"t{len(tracks) + 1}"
        skill = _text(t.get("skill"), 80)
        counts = counted.get(market.skill_key(skill))
        project = t.get("project") if isinstance(t.get("project"), dict) else {}
        builds_on = own.get(_short(_text(project.get("builds_on"), 120)).lower(), "")
        proof = t.get("proof") if isinstance(t.get("proof"), dict) else {}
        track = {
            "id": tid, "skill": skill, "why": _text(t.get("why")),
            "market": ({"ads": counts["ads"], "of": demand.get("ads", 0), "shown": counts["shown"]} if counts else None),
            "study": [{"id": f"{tid}.s{i + 1}", "text": s} for i, s in enumerate(_texts(t.get("study"), 6))],
            "resources": [{"name": r, "url": "", "checked": False} for r in _texts(t.get("resources"), 3, 160)],
            "project": ({"id": f"{tid}.p", "title": _text(project.get("title"), 120), "brief": _text(project.get("brief")),
                         "builds_on": builds_on, "done_when": _text(project.get("done_when"), 300)}
                        if _text(project.get("title")) else None),
            "proof": ({"id": f"{tid}.r", "kind": proof.get("kind") if proof.get("kind") in PROOF_KINDS else "portfolio",
                       "target": _text(proof.get("target"), 300), "why": _text(proof.get("why"), 300)}
                      if _text(proof.get("target")) else None),
            "timeline": t.get("timeline") if t.get("timeline") in TIMELINES else "3 months",
        }
        tracks.append(track)
        if len(tracks) >= 6:
            break
    if not tracks:
        return None
    return {"diagnosis": _text(raw.get("diagnosis"), 1200), "strengths": _texts(raw.get("strengths"), 5),
            "goals": goals[:5], "tracks": tracks, "applications": _texts(raw.get("applications"), 4, 500),
            "venues": []}


def item_ids(plan: dict) -> set[str]:
    """The ids of everything in a plan that can be ticked off."""
    ids = {g["id"] for g in plan.get("goals") or []} | {v["id"] for v in plan.get("venues") or []}
    for t in plan.get("tracks") or []:
        ids |= {s["id"] for s in t.get("study") or []}
        ids |= {x["id"] for x in (t.get("project"), t.get("proof")) if x}
    return ids


async def generate(persona: dict, demand: dict) -> dict | None:
    from .agent import _llm_json  # lazy: agent builds the LLM client at import
    raw = await _llm_json(SYSTEM, prompt(persona, demand), max_tokens=4096, label="career_plan")
    return validate(raw, persona, demand)
