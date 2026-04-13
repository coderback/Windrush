import asyncio
import json
import os
import time
from typing import AsyncGenerator

from openai import AsyncOpenAI

from .cv_parser import extract_text
from .risk_scorer import lookup_onet, lookup_by_title, ECONOMIC_INDEX
from .job_proxy import search_jobs
from .browser_agent import apply_with_browser
from .guardrails import (
    sanitise_tool_input,
    redact_pii_from_result,
    redact_credentials_from_input,
    GuardrailViolation,
)

# ── LLM backend ───────────────────────────────────────────────────────────────
# Switch between Ollama (local) and Groq (cloud) via LLM_BACKEND env var.
# LLM_BACKEND=ollama  → local Gemma 4 via Ollama
# LLM_BACKEND=groq    → Groq cloud (original)

_BACKEND = os.environ.get("LLM_BACKEND", "ollama").lower()

if _BACKEND == "groq":
    client = AsyncOpenAI(
        api_key=os.environ.get("GROQ_API_KEY", ""),
        base_url="https://api.groq.com/openai/v1",
    )
    AGENT_MODEL = "llama3-groq-70b-8192-tool-use-preview"
    LLM_MODEL   = "llama-3.3-70b-versatile"
else:
    # Ollama — local Gemma 4
    _OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    _OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma4:latest")
    client = AsyncOpenAI(
        api_key="ollama",                        # Ollama ignores the key but requires a value
        base_url=f"{_OLLAMA_HOST}/v1",
    )
    AGENT_MODEL = _OLLAMA_MODEL
    LLM_MODEL   = _OLLAMA_MODEL

SYSTEM_PROMPT = """You are Windrush, an AI career transition advisor helping workers navigate the impact of AI on their careers.

Work through this pipeline in order, passing data between tools explicitly:

1. extract_cv_profile(cv_text) → returns a profile object with name, skills, job_titles, location
2. score_ai_risk(skills=[...all skills and job_titles from step 1...])
3. search_jobs(query=<primary job title from profile>, location=<location from profile>)
4. score_job_fit(jobs=[...the jobs array from step 3's result...], cv_profile={...the full profile object from step 1...})
5. generate_skill_roadmap(skill_risks=[...the skill_risks array from step 2...], cv_profile={...the full profile object from step 1...}, target_job_title=<top ranked job title from step 4>)
6. generate_cover_letter(job={...the top ranked job from step 4...}, cv_profile={...the full profile object from step 1...})

CRITICAL RULES:
- After each tool returns a result, immediately call the next tool in the pipeline. Do NOT write any text, summary, or response to the user between tool calls.
- Always pass the actual data objects from previous tool results into subsequent tool calls. Never call a tool with empty arguments.
- After generate_cover_letter completes, stop. Do NOT call apply_to_job — the user must explicitly approve first."""


_HARDCODED_EXPOSURE: dict[str, float] = {
    # Programming languages
    "python": 0.78, "javascript": 0.71, "typescript": 0.68, "java": 0.69,
    "c++": 0.62, "c#": 0.65, "go": 0.60, "rust": 0.55, "r": 0.76,
    "matlab": 0.72, "scala": 0.63, "kotlin": 0.64, "swift": 0.61,
    # AI / ML
    "machine learning": 0.82, "deep learning": 0.79, "nlp": 0.84,
    "natural language processing": 0.84, "computer vision": 0.81,
    "tensorflow": 0.75, "pytorch": 0.76, "keras": 0.74,
    "large language models": 0.88, "llm": 0.88, "generative ai": 0.86,
    "reinforcement learning": 0.77, "neural networks": 0.80,
    "data science": 0.81, "data analysis": 0.80, "statistics": 0.74,
    # Web / backend
    "react": 0.65, "node.js": 0.67, "django": 0.66, "fastapi": 0.64,
    "rest api": 0.70, "graphql": 0.67, "sql": 0.72, "nosql": 0.68,
    "postgresql": 0.70, "mongodb": 0.67, "redis": 0.63,
    # DevOps / infra
    "docker": 0.58, "kubernetes": 0.52, "aws": 0.61, "azure": 0.60,
    "gcp": 0.59, "terraform": 0.54, "ci/cd": 0.56, "git": 0.55,
    "cloud computing": 0.60, "microservices": 0.58,
    # Lower-exposure / hardware / specialised
    "fpga": 0.32, "embedded systems": 0.40, "hardware design": 0.35,
    "robotics": 0.48, "signal processing": 0.44, "compiler design": 0.38,
    "systems design": 0.38, "distributed systems": 0.42,
    "cryptography": 0.36, "security": 0.41, "networking": 0.43,
    # Soft / domain
    "research": 0.45, "technical leadership": 0.28, "agile": 0.42,
    "project management": 0.50, "communication": 0.30,
    # Job titles
    "software engineer": 0.62, "software developer": 0.65,
    "data engineer": 0.72, "ml engineer": 0.80, "ai engineer": 0.82,
    "graduate software engineer": 0.62, "backend engineer": 0.64,
    "frontend engineer": 0.66, "full stack engineer": 0.65,
    "data scientist": 0.81, "research engineer": 0.58,
    "devops engineer": 0.55, "platform engineer": 0.53,
}

TOOLS = [
    {
        "name": "extract_cv_profile",
        "description": "Parse CV text into structured profile: name, skills, job titles, experience years, location.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cv_text": {"type": "string", "description": "Raw CV text to parse"},
            },
            "required": ["cv_text"],
        },
    },
    {
        "name": "score_ai_risk",
        "description": "Look up AI exposure scores for a list of skills or job titles using the Economic Index.",
        "input_schema": {
            "type": "object",
            "properties": {
                "skills": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of skills or occupation titles to score",
                },
            },
            "required": ["skills"],
        },
    },
    {
        "name": "search_jobs",
        "description": "Search for job listings matching a query in a given location.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Job search query"},
                "location": {"type": "string", "description": "Location e.g. 'London'"},
            },
            "required": ["query", "location"],
        },
    },
    {
        "name": "score_job_fit",
        "description": "Score and rank a list of jobs against a CV profile. Returns jobs sorted by composite score.",
        "input_schema": {
            "type": "object",
            "properties": {
                "jobs": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "List of job objects from search_jobs",
                },
                "cv_profile": {
                    "type": "object",
                    "description": "Structured CV profile from extract_cv_profile",
                },
            },
            "required": ["jobs", "cv_profile"],
        },
    },
    {
        "name": "generate_cover_letter",
        "description": "Generate a personalised cover letter for a specific job, grounded in the CV profile.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job": {"type": "object", "description": "Target job object"},
                "cv_profile": {"type": "object", "description": "Structured CV profile"},
                "tone": {
                    "type": "string",
                    "enum": ["professional", "enthusiastic", "concise"],
                    "description": "Tone of the cover letter",
                },
            },
            "required": ["job", "cv_profile"],
        },
    },
    {
        "name": "apply_to_job",
        "description": "Submit a job application. Only call this after explicit user approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "cover_letter": {"type": "string"},
                "cv_profile": {"type": "object"},
            },
            "required": ["job_id", "cover_letter", "cv_profile"],
        },
    },
    {
        "name": "generate_skill_roadmap",
        "description": "Generate a prioritised skill development roadmap tailored to the candidate's industry and career goals.",
        "input_schema": {
            "type": "object",
            "properties": {
                "skill_risks": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "List of scored skill risks from score_ai_risk",
                },
                "cv_profile": {
                    "type": "object",
                    "description": "Structured CV profile from extract_cv_profile",
                },
                "target_job_title": {
                    "type": "string",
                    "description": "Title of the job the candidate is targeting",
                },
            },
            "required": ["skill_risks"],
        },
    },
    {
        "name": "lookup_economic_index",
        "description": "Look up a specific ONET SOC code in the Economic Index for raw exposure data.",
        "input_schema": {
            "type": "object",
            "properties": {
                "onet_code": {"type": "string", "description": "ONET SOC code e.g. '15-1252.00'"},
            },
            "required": ["onet_code"],
        },
    },
]


GROQ_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        },
    }
    for t in TOOLS
]


async def _llm(system: str, user: str, max_tokens: int = 2048) -> str:
    """Simple single-turn LLM call for internal tool use (CV parsing, cover letter, roadmap)."""
    resp = await client.chat.completions.create(
        model=LLM_MODEL,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return resp.choices[0].message.content or ""


_ARCHETYPE_KEYWORDS: dict[str, list[str]] = {
    "SoftwareEngineer": [
        "backend", "frontend", "full stack", "infrastructure", "distributed",
        "microservices", "api", "platform", "devops", "cloud", "kubernetes",
        "scalability", "reliability", "systems design",
    ],
    "DataML": [
        "machine learning", "deep learning", "model", "pytorch", "tensorflow",
        "data pipeline", "analytics", "nlp", "natural language", "llm",
        "neural network", "training", "inference", "dataset", "feature engineering",
    ],
    "FinanceAnalyst": [
        "financial model", "valuation", "m&a", "equity", "quantitative",
        "trading", "investment", "portfolio", "risk", "derivatives",
        "fixed income", "hedge fund", "private equity", "due diligence",
    ],
}


def _detect_archetype(job_title: str, description: str) -> str:
    text = (job_title + " " + description).lower()
    scores = {arch: sum(1 for kw in kws if kw in text) for arch, kws in _ARCHETYPE_KEYWORDS.items()}
    return max(scores, key=lambda k: scores[k])


def _extract_differentiation_hook(cv_profile: dict, job_description: str) -> str:
    """Find a distinctive item from the candidate's experience not mentioned in the JD."""
    jd_lower = job_description.lower()
    for exp in cv_profile.get("experience", []):
        summary = exp.get("summary", "") + " " + exp.get("employer", "")
        # Look for capitalised proper nouns / specific tech terms not in JD
        tokens = [w.strip(".,();") for w in summary.split() if len(w) > 3 and w[0].isupper()]
        for token in tokens:
            if token.lower() not in jd_lower and len(token) > 4:
                return f"Notable experience with {token} that directly applies to this role."
    return ""


async def execute_tool(name: str, tool_input: dict) -> dict:
    if name == "extract_cv_profile":
        cv_text = tool_input.get("cv_text", "")
        text = await _llm(
            system=(
                "Extract a structured profile from this CV. Return ONLY valid JSON with no markdown fences. "
                "Include: name, email, phone, address (full postal address if present), "
                "location (city/region), linkedin (URL or username), github (URL or username), "
                "skills (array, max 12 most relevant), job_titles (array, max 3), "
                "experience_years (number), summary (1 sentence only), "
                "education (array of {institution, degree, dates}), "
                "experience (array of {employer, title, dates, summary} — max 5 most recent)."
            ),
            user=cv_text[:4000],
        )
        text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            return json.loads(text or "{}")
        except json.JSONDecodeError:
            return {}

    elif name == "score_ai_risk":
        skills = tool_input.get("skills", [])
        results = []
        for skill in skills:
            key = skill.lower().strip()
            if key in _HARDCODED_EXPOSURE:
                exposure = _HARDCODED_EXPOSURE[key]
            else:
                data = lookup_by_title(skill)
                raw = data.get("overall_exposure", 0.0)
                exposure = round(raw, 2) if raw and raw != 0.5 else 0.55
            results.append({
                "skill": skill,
                "exposure": round(exposure, 2),
                "risk": "high" if exposure >= 0.5 else "low",
            })
        return {"skill_risks": results}

    elif name == "search_jobs":
        jobs = await search_jobs(tool_input.get("query", ""), tool_input.get("location", "London"))
        slim_jobs = [
            {k: v for k, v in j.items() if k not in ("salary_min", "salary_max")}
            for j in jobs[:10]
        ]
        return {"jobs": slim_jobs, "count": len(slim_jobs)}

    elif name == "score_job_fit":
        import re as _re
        jobs = tool_input.get("jobs", [])
        cv_profile = tool_input.get("cv_profile", {})
        cv_skills = set(s.lower() for s in cv_profile.get("skills", []))
        cv_years = float(cv_profile.get("experience_years", 0) or 0)

        # Skill vocabulary for gap detection — reuse existing hardcoded keys
        _skill_vocab = set(_HARDCODED_EXPOSURE.keys())

        def _level_match(title: str, desc: str) -> tuple[str, float]:
            """Infer required experience and return (match_label, level_bonus)."""
            required = 0.0
            # Infer from title seniority words
            title_l = title.lower()
            if any(w in title_l for w in ("senior", "sr.")):
                required = 3.0
            elif any(w in title_l for w in ("lead", "principal", "staff")):
                required = 5.0
            elif any(w in title_l for w in ("graduate", "junior", "jr.", "entry")):
                required = 0.0
            # Override with explicit years mention in description
            matches = _re.findall(r"(\d+)\+?\s*(?:years?|yrs?)", desc, _re.I)
            if matches:
                required = max(float(m) for m in matches)
            if cv_years >= required:
                return "strong", 1.0
            elif cv_years >= required - 1:
                return "ok", 0.6
            else:
                return "reach", 0.2

        def _skill_gaps(desc: str) -> list[str]:
            desc_l = desc.lower()
            gaps = [
                skill for skill in _skill_vocab
                if skill in desc_l and skill not in cv_skills
            ]
            return gaps[:6]

        scored = []
        for job in jobs:
            exposure = job.get("exposure_score", 0.5)
            desc = job.get("description", "")
            desc_lower = desc.lower()
            skill_matches = sum(1 for s in cv_skills if s in desc_lower)
            fit_score = min(skill_matches / max(len(cv_skills), 1), 1.0)
            level, level_bonus = _level_match(job.get("title", ""), desc)
            gaps = _skill_gaps(desc)
            composite = (1 - exposure) * 0.35 + fit_score * 0.45 + level_bonus * 0.20
            scored.append({
                "job_id": job.get("job_id"),
                "title": job.get("title"),
                "company": job.get("company"),
                "location": job.get("location"),
                "url": job.get("url"),
                "description": desc,
                "exposure_score": exposure,
                "fit_score": round(fit_score, 2),
                "level_match": level,
                "skill_gaps": gaps,
                "composite_score": round(composite, 2),
            })

        scored.sort(key=lambda j: j["composite_score"], reverse=True)
        return {"ranked_jobs": scored[:4]}

    elif name == "generate_cover_letter":
        job = tool_input.get("job", {})
        cv_profile = tool_input.get("cv_profile", {})
        tone = tool_input.get("tone", "professional")
        archetype = _detect_archetype(job.get("title", ""), job.get("description", ""))
        hook = _extract_differentiation_hook(cv_profile, job.get("description", ""))
        archetype_guidance = {
            "SoftwareEngineer": "Emphasise technical depth, system design decisions, and production reliability.",
            "DataML": "Emphasise model performance, pipeline scale, evaluation rigour, and research grounding.",
            "FinanceAnalyst": "Emphasise quantitative precision, domain-specific modelling, and analytical frameworks.",
        }[archetype]
        system = (
            f"Write a {tone} cover letter. Archetype: {archetype}. {archetype_guidance} "
            "Be specific — reference the candidate's actual experience and the job's requirements. "
            "3 paragraphs. No placeholders like [Your Address] or [Date] — omit address headers entirely "
            "and start directly with 'Dear Hiring Manager,'."
            + (f"\n\nDifferentiation hook to weave in naturally: {hook}" if hook else "")
        )
        letter = await _llm(
            system=system,
            user=(
                f"Candidate: {json.dumps(cv_profile)}\n\n"
                f"Job: {job.get('title')} at {job.get('company')}\n"
                f"Description: {job.get('description', '')}"
            ),
            max_tokens=1024,
        )
        return {
            "status": "ready",
            "job_title": job.get("title", ""),
            "company": job.get("company", ""),
            "candidate_name": cv_profile.get("name", ""),
            "cover_letter": letter,
            "archetype": archetype,
        }

    elif name == "apply_to_job":
        return {
            "status": "submitted",
            "job_id": tool_input.get("job_id"),
            "message": "Application submitted successfully. Good luck!",
        }

    elif name == "generate_skill_roadmap":
        skill_risks = tool_input.get("skill_risks", [])
        cv_profile = tool_input.get("cv_profile", {})
        target_job_title = tool_input.get("target_job_title", "")

        confirmed_high = [s for s in skill_risks if s.get("exposure", 0) > 0.65]
        confirmed_low  = [s for s in skill_risks if 0 < s.get("exposure", 0) <= 0.35]
        all_skills_str = ", ".join(
            f"{s['skill']} ({int(s.get('exposure',0)*100)}%)" for s in skill_risks
        )

        name_str = cv_profile.get("name", "the candidate")
        summary = cv_profile.get("summary", "")
        job_titles = cv_profile.get("job_titles", [])
        edu = cv_profile.get("education", [{}])[0] if cv_profile.get("education") else {}
        edu_str = f"{edu.get('degree','')} at {edu.get('institution','')}" if edu else ""
        exp_list = cv_profile.get("experience", [])
        exp_str = "; ".join(
            f"{e.get('title','')} at {e.get('employer','')}" for e in exp_list[:3]
        )

        text = await _llm(
            system=(
                "You are a career coach specialising in AI-resilient career development. "
                "Given a candidate's background, generate a personalised skill development roadmap. "
                "Return ONLY valid JSON with no markdown fences. "
                "JSON key 'items', an array of exactly 6 objects each with: "
                "skill (string — the skill to develop), "
                "reason (string — one sentence explaining WHY this skill matters for their specific industry/role), "
                "action (string — a concrete task: name a specific course, project, certification or open-source contribution), "
                "timeline (one of: '1 month','2 months','3 months','6 months'), "
                "resource (string — specific course name or platform). "
                "STRICT RULES: "
                "1. Every recommendation must be directly relevant to the candidate's industry and target role. "
                "2. Build ON their existing technical strengths — deepen and extend, do not replace them. "
                "3. For each skill at confirmed high AI risk, suggest a way to apply it at a level AI cannot yet reach "
                "(novel research, production systems, domain-specific expertise, technical leadership). "
                "4. Do NOT recommend generic soft skills (leadership, communication, PM) unless the candidate is "
                "already working in a non-technical or hybrid role. "
                "5. Do NOT recommend skills the candidate already lists. "
                "6. Keep resources real and specific."
            ),
            user=(
                f"Candidate: {name_str}\n"
                f"Background: {summary}\n"
                f"Education: {edu_str}\n"
                f"Experience: {exp_str}\n"
                f"Current job titles: {', '.join(job_titles)}\n"
                f"Target role: {target_job_title or 'not specified'}\n\n"
                f"All skills with AI exposure scores: {all_skills_str}\n"
                + (f"Confirmed high AI-exposure (score > 65%): {', '.join(s['skill'] for s in confirmed_high)}\n" if confirmed_high else "")
                + (f"Confirmed lower AI-exposure (safer foundation): {', '.join(s['skill'] for s in confirmed_low)}\n" if confirmed_low else "")
                + "\nGenerate 6 skill development recommendations that deepen this candidate's technical profile and make them more competitive for their target role."
            ),
            max_tokens=2048,
        )
        text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            data = json.loads(text or "{}")
        except json.JSONDecodeError:
            data = {}
        return {"status": "generated", "items": data.get("items", [])}

    elif name == "lookup_economic_index":
        onet_code = tool_input.get("onet_code", "")
        return lookup_onet(onet_code)

    return {"error": f"Unknown tool: {name}"}


async def _chat(messages: list, tools: list):
    """Call LLM via OpenAI-compatible API (Ollama or Groq)."""
    all_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages
    # Ollama local inference can be slow on large models — use a longer timeout
    timeout = 180.0 if _BACKEND == "ollama" else 90.0
    return await asyncio.wait_for(
        client.chat.completions.create(
            model=AGENT_MODEL,
            max_tokens=4096,
            messages=all_messages,
            tools=tools,
        ),
        timeout=timeout,
    )


def _sse(event_type: str, data: dict) -> str:
    payload = {"type": event_type, "timestamp": time.time(), **data}
    return f"data: {json.dumps(payload)}\n\n"


async def run_pipeline(cv_text: str, location: str = "London") -> AsyncGenerator[str, None]:
    """Yields SSE-formatted strings for each agent step."""
    messages: list[dict] = [
        {
            "role": "user",
            "content": f"Please analyse this CV and find suitable jobs in {location}.\n\nCV:\n{cv_text[:3000]}",
        },
    ]

    yield _sse("start", {"message": "Pipeline started"})

    while True:
        try:
            response = await _chat(messages, GROQ_TOOLS)
        except asyncio.TimeoutError:
            yield _sse("done", {"message": "Request timed out — please try again."})
            return

        message = response.choices[0].message
        finish_reason = response.choices[0].finish_reason

        # Emit any text content
        if message.content and message.content.strip():
            yield _sse("text", {"text": message.content})

        tool_calls = message.tool_calls or []

        # Append assistant turn (must include tool_calls if present)
        assistant_msg: dict = {"role": "assistant", "content": message.content}
        if tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in tool_calls
            ]
        messages.append(assistant_msg)

        for tc in tool_calls:
            tool_name = tc.function.name
            tool_input = json.loads(tc.function.arguments)

            sse_input, _ = redact_credentials_from_input(tool_name, tool_input)
            yield _sse("tool_call", {"tool_name": tool_name, "tool_input": sse_input})

            try:
                safe_input = sanitise_tool_input(tool_name, tool_input)
            except GuardrailViolation as e:
                yield _sse("guardrail", {"check": e.check, "detail": e.detail, "tool_name": tool_name, "fired": True})
                result = {"error": f"Guardrail blocked this tool call: {e.detail}"}
                yield _sse("tool_result", {"tool_name": tool_name, "result": result})
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})
                continue

            result = await execute_tool(tool_name, safe_input)

            sse_result, pii_fired = redact_pii_from_result(tool_name, result)
            if pii_fired:
                yield _sse("guardrail", {"check": "pii_redact", "tool_name": tool_name, "fired": True, "detail": "PII removed from display"})
            yield _sse("tool_result", {"tool_name": tool_name, "result": sse_result})

            messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})

            if tool_name == "generate_cover_letter":
                yield _sse("done", {"message": "Pipeline complete"})
                return

        if finish_reason == "stop" or not tool_calls:
            yield _sse("done", {"message": "Pipeline complete"})
            break


async def run_apply(
    job_id: str,
    job_url: str = "",
    cover_letter: str = "",
    cv_profile: dict | None = None,
    skill_risks: list | None = None,
    session_id: str = "",
    instruction_queue: asyncio.Queue | None = None,
    frame_queue: asyncio.Queue | None = None,
    job_email: str = "",
    job_password: str = "",
    cv_path: str = "",
) -> AsyncGenerator[str, None]:
    """Apply phase: browser automation."""
    cv_profile = cv_profile or {}
    skill_risks = skill_risks or []

    yield _sse("start", {"message": "Starting browser application…", "session_id": session_id})

    if job_url and instruction_queue is not None:
        async for step in apply_with_browser(
            job_url, cv_profile, cover_letter, instruction_queue, frame_queue,
            job_email=job_email, job_password=job_password, cv_path=cv_path,
        ):
            event_type = "browser_blocked" if step.get("blocked") else "browser_action"
            yield _sse(event_type, {
                "action": step.get("action", ""),
                "screenshot": step.get("screenshot"),
                "reason": step.get("reason"),
                "interactive": step.get("interactive", False),
            })
            if step.get("done"):
                break

    yield _sse("done", {"message": "Done"})
