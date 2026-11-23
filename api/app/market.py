"""
What employers ask for in the roles someone is aiming at, and how their own applications are going: no model is
involved, only counts over the ads whose skills job_skills has read and over the user's tracked applications.

A skill counts as shown when its words appear in what the profile says: the skills list, the projects'
technologies and write-ups, and each job's tech stack and achievements. That's how the roadmap knows not to
suggest what the user can already show, and which asked-for skills nothing in the profile shows yet.
"""
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from . import jobs_db
from .job_skills import words

# Words that set a role's rank, not what the role is: the counts take every ad for the role, and the user's level
# is applied separately.
_RANK_WORDS = {"graduate", "grad", "junior", "senior", "entry", "level", "lead", "principal", "staff", "intern",
               "internship", "trainee", "apprentice", "new", "early", "careers", "programme", "program", "scheme",
               "i", "ii", "iii", "associate", "mid", "experienced"}
_JUNIOR_WORDS = {"graduate", "grad", "junior", "entry", "intern", "internship", "trainee", "apprentice", "new"}

# Names that mean the same skill; the first is the one counted under.
_SAME_SKILL = [
    ("postgresql", "postgres"), ("kubernetes", "k8s"), ("aws", "amazon web services"), ("go", "golang"),
    ("javascript", "js"), ("typescript", "ts"), ("machine learning", "ml"),
    ("google cloud", "gcp", "google cloud platform"), ("react", "reactjs", "react js"),
    ("node js", "nodejs", "node"), ("scikit learn", "sklearn"), ("ci cd", "continuous integration"),
    ("llms", "llm", "large language models", "large language model"), ("nlp", "natural language processing"),
    ("rest apis", "rest api", "restful apis", "restful api"), ("microservices", "microservice"),
    ("docker", "containers", "containerisation", "containerization"), ("c++", "cpp"),
]
_KEY = {form: group[0] for group in _SAME_SKILL for form in group}
_FORMS = {group[0]: group for group in _SAME_SKILL}

_REPLY = {"Responded", "Interview", "Offer"}
_SENT = {"Applied", "Responded", "Interview", "Offer", "Rejected"}
_MIN_ADS_FOR_LEVEL = 30     # below this many ads at the user's level, every level is counted
_MIN_SKILL_ADS = 3
_TOP = 30
_LOOKBACK_DAYS = 365


def skill_key(name: str) -> str:
    w = words(name)
    return _KEY.get(w, w)


def role_title(title: str) -> str:
    """The role without its rank: "Graduate Software Engineer" -> "Software Engineer"."""
    kept = [w for w in re.findall(r"[A-Za-z0-9+#]+", title or "") if w.lower() not in _RANK_WORDS]
    return " ".join(kept)


def _short(name: str) -> str:
    return re.split(r"\s*[:·|]\s*", name or "", maxsplit=1)[0].strip()


def evidence_texts(persona: dict) -> list[tuple[str, str]]:
    """(where, text) for everything the profile says the user has done or knows."""
    out = []
    skills = [s for g in persona.get("skills") or [] for s in g.get("skills") or []]
    if skills:
        out.append(("your skills", " ; ".join(skills)))
    for p in persona.get("projects") or []:
        text = " ; ".join([*(p.get("technologies") or []), p.get("problem_solved") or "", p.get("outcomes") or "",
                           p.get("summary") or ""])
        out.append((_short(p.get("name") or "a project"), text))
    for h in persona.get("history") or []:
        text = " ; ".join([*(h.get("tech_stack") or []), *(h.get("achievements") or []), h.get("summary") or ""])
        out.append((h.get("employer") or "a job", text))
    for c in persona.get("certifications") or []:
        out.append(("certifications", " ".join(str(v) for v in c.values() if isinstance(v, str))))
    return out


def _shown_in(key: str, texts: list[tuple[str, str]]) -> list[str]:
    forms = _FORMS.get(key, (key,))
    where = []
    for place, text in texts:
        blob = f" {words(text)} "
        if any(f" {f} " in blob for f in forms) and place not in where:
            where.append(place)
    return where


def _stage(titles: list[str]) -> str:
    return "junior" if any(w.lower() in _JUNIOR_WORDS for t in titles for w in re.findall(r"[A-Za-z]+", t)) else ""


def demand(persona: dict, applications: list[dict], ads: list[dict] | None = None, waiting: int = 0) -> dict:
    """The skills most asked for in ads for the user's target roles, whether the profile shows each, and how the
    user's applications for those roles have gone."""
    targets = [t for t in dict.fromkeys((persona.get("preferences") or {}).get("target_titles") or []) if t.strip()]
    roles = list(dict.fromkeys(r for r in (role_title(t) for t in targets) if r))
    matchers = {r: jobs_db.title_matcher(r) for r in roles}
    if ads is None:
        since = (datetime.now(timezone.utc) - timedelta(days=_LOOKBACK_DAYS)).isoformat()
        ads = jobs_db.ads_with_skills(since)
    matched = [a for a in ads if any(m(a["title"]) for m in matchers.values())]
    level = _stage(targets)
    at_level = [a for a in matched if a["level"] == level] if level else matched
    counted, level_used = (at_level, level) if level and len(at_level) >= _MIN_ADS_FOR_LEVEL else (matched, "")

    per_ad: Counter = Counter()
    required: Counter = Counter()
    names: dict[str, Counter] = defaultdict(Counter)
    for ad in counted:
        keys_here = set()
        for kind in ("required", "preferred"):
            for name in ad["skills"].get(kind) or []:
                key = skill_key(name)
                if not key or key in keys_here:
                    continue
                keys_here.add(key)
                names[key][name] += 1
                if kind == "required":
                    required[key] += 1
        per_ad.update(keys_here)

    texts = evidence_texts(persona)
    n = len(counted)
    skills = []
    for key, count in sorted(per_ad.items(), key=lambda kv: (-kv[1], kv[0])):
        if count < _MIN_SKILL_ADS or len(skills) >= _TOP:
            break
        where = _shown_in(key, texts)
        skills.append({"name": names[key].most_common(1)[0][0], "key": key, "ads": count,
                       "share": round(count / n, 3) if n else 0, "required": required[key],
                       "shown": bool(where), "where": where[:3]})

    return {"roles": roles, "ads": n, "level": level_used, "matched_ads": len(matched), "read_ads": len(ads),
            "waiting": waiting, "skills": skills, "funnel": funnel(applications, roles, matchers),
            "noted_gaps": noted_gaps(applications)}


def funnel(applications: list[dict], roles: list[str], matchers: dict) -> dict:
    """Applications sent, replies (responded, interview or offer), interviews and rejections, overall and per role."""
    def blank():
        return {"applied": 0, "replies": 0, "interviews": 0, "rejected": 0}
    total, by_role = blank(), {r: blank() for r in [*roles, "Other roles"]}
    for a in applications:
        status = a.get("status") or ""
        if status not in _SENT:
            continue
        role = next((r for r in roles if matchers[r](role_title(a.get("job_title") or ""))), "Other roles")
        for bucket in (total, by_role[role]):
            bucket["applied"] += 1
            bucket["replies"] += status in _REPLY
            bucket["interviews"] += status in ("Interview", "Offer")
            bucket["rejected"] += status == "Rejected"
    return {"total": total, "by_role": [{"role": r, **c} for r, c in by_role.items() if c["applied"]]}


def noted_gaps(applications: list[dict], limit: int = 15) -> list[str]:
    """The gaps the fit check noted on recent applications, newest first, each once."""
    seen, out = set(), []
    for a in sorted(applications, key=lambda a: a.get("created_at") or "", reverse=True):
        for gap in a.get("skill_gaps") or []:
            key = words(gap)
            if isinstance(gap, str) and key and key not in seen:
                seen.add(key)
                out.append(gap.strip())
            if len(out) >= limit:
                return out
    return out


def prompt_block(m: dict) -> str:
    """The market counts as plain lines for the roadmap's prompt."""
    if not m.get("skills"):
        return ""
    lvl = f"{m['level']}-level " if m.get("level") else ""
    lines = [f"What employers ask for: {m['ads']} {lvl}ads for {', '.join(m['roles'])} whose skills were read."]
    for s in m["skills"]:
        shown = f"shown in: {', '.join(s['where'])}" if s["shown"] else "NOT shown anywhere in the profile"
        lines.append(f"- {s['name']}: asked for in {s['ads']} of {m['ads']} ads ({s['required']} as required); {shown}")
    f = m.get("funnel", {}).get("total") or {}
    if f.get("applied"):
        lines.append(f"Their applications: {f['applied']} sent, {f['replies']} replies, {f['interviews']} interviews, "
                     f"{f['rejected']} rejections (rejections don't say why).")
        for r in m["funnel"]["by_role"]:
            lines.append(f"- {r['role']}: {r['applied']} sent, {r['replies']} replies, {r['interviews']} interviews")
    if m.get("noted_gaps"):
        lines.append("Gaps a fit check noted on recent applications: " + "; ".join(m["noted_gaps"]))
    return "\n".join(lines) + "\n"
