import asyncio
import json
import os
import re
import time
from typing import AsyncGenerator

from openai import AsyncOpenAI, BadRequestError

from .cv_parser import extract_text
from .risk_scorer import lookup_onet, lookup_by_title, ECONOMIC_INDEX
from .job_proxy import search_jobs, FIXTURE as JOBS_FIXTURE
from .browser_agent import apply_with_browser
from .guardrails import (
    sanitise_tool_input,
    redact_pii_from_result,
    redact_credentials_from_input,
    GuardrailViolation,
)

client = AsyncOpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=os.environ.get("GROQ_API_KEY", ""),
)

MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = """You are Windrush, an AI career transition advisor helping workers navigate the impact of AI on their careers.

IMPORTANT: You MUST use the structured tool_calls mechanism to call tools. Never write tool calls as plain text like <function=name> or ```json. Always use the API's tool_calls field.


Work through this pipeline in order, passing data between tools explicitly:

1. extract_cv_profile(cv_text) → returns a profile object with name, skills, job_titles, location
2. score_ai_risk(skills=[...all skills and job_titles from step 1...])
3. search_jobs(query=<primary job title from profile>, location=<location from profile>)
4. score_job_fit(jobs=[...the jobs array from step 3's result...], cv_profile={...the full profile object from step 1...})
5. generate_cover_letter(job={...the top ranked job from step 4...}, cv_profile={...the full profile object from step 1...})

CRITICAL: Always pass the actual data objects from previous tool results into subsequent tool calls. Never call a tool with empty arguments.

After generate_cover_letter completes, stop. Do NOT call apply_to_job — the user must explicitly approve first."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "extract_cv_profile",
            "description": "Parse CV text into structured profile: name, skills, job titles, experience years, location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cv_text": {"type": "string", "description": "Raw CV text to parse"},
                },
                "required": ["cv_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "score_ai_risk",
            "description": "Look up AI exposure scores for a list of skills or job titles using the Economic Index.",
            "parameters": {
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
    },
    {
        "type": "function",
        "function": {
            "name": "search_jobs",
            "description": "Search for job listings matching a query in a given location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Job search query"},
                    "location": {"type": "string", "description": "Location e.g. 'London'"},
                },
                "required": ["query", "location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "score_job_fit",
            "description": "Score and rank a list of jobs against a CV profile. Returns jobs sorted by composite score.",
            "parameters": {
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
    },
    {
        "type": "function",
        "function": {
            "name": "generate_cover_letter",
            "description": "Generate a personalised cover letter for a specific job, grounded in the CV profile.",
            "parameters": {
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
    },
    {
        "type": "function",
        "function": {
            "name": "apply_to_job",
            "description": "Submit a job application. Only call this after explicit user approval.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string"},
                    "cover_letter": {"type": "string"},
                    "cv_profile": {"type": "object"},
                },
                "required": ["job_id", "cover_letter", "cv_profile"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_skill_roadmap",
            "description": "Generate a prioritised skill development roadmap tailored to the candidate's industry and career goals.",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_risks": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "List of scored skill risks from score_ai_risk",
                    },
                    "cv_profile": {
                        "type": "object",
                        "description": "Structured CV profile from extract_cv_profile — used to tailor roadmap to the candidate's industry and background",
                    },
                    "target_job_title": {
                        "type": "string",
                        "description": "Title of the job the candidate is targeting",
                    },
                },
                "required": ["skill_risks"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_economic_index",
            "description": "Look up a specific ONET SOC code in the Economic Index for raw exposure data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "onet_code": {"type": "string", "description": "ONET SOC code e.g. '15-1252.00'"},
                },
                "required": ["onet_code"],
            },
        },
    },
]


async def execute_tool(name: str, tool_input: dict) -> dict:
    if name == "extract_cv_profile":
        cv_text = tool_input.get("cv_text", "")
        resp = await client.chat.completions.create(
            model=MODEL,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract a structured profile from this CV. Return compact JSON with: "
                        "name, email, phone, address (full postal address if present), "
                        "location (city/region), linkedin (URL or username), github (URL or username), "
                        "skills (array, max 12 most relevant), job_titles (array, max 3), "
                        "experience_years (number), summary (1 sentence only), "
                        "education (array of {institution, degree, dates}), "
                        "experience (array of {employer, title, dates, summary} — max 5 most recent)."
                    ),
                },
                {"role": "user", "content": cv_text[:4000]},
            ],
        )
        return json.loads(resp.choices[0].message.content)

    elif name == "score_ai_risk":
        skills = tool_input.get("skills", [])
        results = []
        for skill in skills:
            data = lookup_by_title(skill)
            exposure = round(data.get("overall_exposure", 0.5), 2)
            results.append({
                "skill": skill,
                "exposure": exposure,
                "risk": "high" if exposure >= 0.5 else "low",
            })
        return {"skill_risks": results}

    elif name == "search_jobs":
        jobs = await search_jobs(tool_input.get("query", ""), tool_input.get("location", "London"))
        # Strip descriptions and cap at 5 — model must echo these back in score_job_fit args
        slim_jobs = [
            {k: v for k, v in j.items() if k not in ("description", "salary_min", "salary_max")}
            for j in jobs[:5]
        ]
        return {"jobs": slim_jobs, "count": len(slim_jobs)}

    elif name == "score_job_fit":
        jobs = tool_input.get("jobs", [])
        cv_profile = tool_input.get("cv_profile", {})
        cv_skills = set(s.lower() for s in cv_profile.get("skills", []))

        # Re-inject descriptions from fixture for scoring, then strip them from the result
        fixture_by_id = {j["job_id"]: j for j in JOBS_FIXTURE}

        scored = []
        for job in jobs:
            full_job = {**fixture_by_id.get(job.get("job_id", ""), {}), **job}
            exposure = full_job.get("exposure_score", 0.5)
            desc_lower = full_job.get("description", "").lower()
            skill_matches = sum(1 for s in cv_skills if s in desc_lower)
            fit_score = min(skill_matches / max(len(cv_skills), 1), 1.0)
            composite = (1 - exposure) * 0.5 + fit_score * 0.5
            scored.append({
                "job_id": full_job.get("job_id"),
                "title": full_job.get("title"),
                "company": full_job.get("company"),
                "location": full_job.get("location"),
                "url": full_job.get("url"),
                "exposure_score": exposure,
                "fit_score": round(fit_score, 2),
                "composite_score": round(composite, 2),
            })

        scored.sort(key=lambda j: j["composite_score"], reverse=True)
        return {"ranked_jobs": scored[:4]}

    elif name == "generate_cover_letter":
        job = tool_input.get("job", {})
        cv_profile = tool_input.get("cv_profile", {})
        tone = tool_input.get("tone", "professional")
        # Re-inject full description from fixture if not present (stripped from score_job_fit result)
        fixture_by_id = {j["job_id"]: j for j in JOBS_FIXTURE}
        full_job = {**fixture_by_id.get(job.get("job_id", ""), {}), **job}
        resp = await client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": f"Write a {tone} cover letter. Be specific — reference the candidate's actual experience and the job's requirements. 3 paragraphs. No placeholders like [Your Address] or [Date] — omit address headers entirely and start directly with 'Dear Hiring Manager,'.",
                },
                {
                    "role": "user",
                    "content": (
                        f"Candidate: {json.dumps(cv_profile)}\n\n"
                        f"Job: {full_job.get('title')} at {full_job.get('company')}\n"
                        f"Description: {full_job.get('description', '')}"
                    ),
                },
            ],
        )
        letter = resp.choices[0].message.content or ""
        return {
            "status": "ready",
            "job_title": full_job.get("title", ""),
            "company": full_job.get("company", ""),
            "candidate_name": cv_profile.get("name", ""),
            "cover_letter": letter,
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

        # Only flag skills with a confirmed high score — 0.5 is the no-data default,
        # not a genuine "high risk" signal, so we use a higher threshold.
        confirmed_high = [s for s in skill_risks if s.get("exposure", 0) > 0.65]
        confirmed_low  = [s for s in skill_risks if 0 < s.get("exposure", 0) <= 0.35]
        # Skills at exactly 0.5 (no ONET data) are omitted from risk labels
        all_skills_str = ", ".join(
            f"{s['skill']} ({int(s.get('exposure',0)*100)}%)" for s in skill_risks
        )

        # Build a concise candidate context for the prompt
        name_str = cv_profile.get("name", "the candidate")
        summary = cv_profile.get("summary", "")
        job_titles = cv_profile.get("job_titles", [])
        edu = cv_profile.get("education", [{}])[0] if cv_profile.get("education") else {}
        edu_str = f"{edu.get('degree','')} at {edu.get('institution','')}" if edu else ""
        exp_list = cv_profile.get("experience", [])
        exp_str = "; ".join(
            f"{e.get('title','')} at {e.get('employer','')}" for e in exp_list[:3]
        )

        resp = await client.chat.completions.create(
            model=MODEL,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a career coach specialising in AI-resilient career development. "
                        "Given a candidate's background, generate a personalised skill development roadmap. "
                        "Return JSON with key 'items', an array of exactly 6 objects each with: "
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
                },
                {
                    "role": "user",
                    "content": (
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
                },
            ],
        )
        data = json.loads(resp.choices[0].message.content)
        return {"status": "generated", "items": data.get("items", [])}

    elif name == "lookup_economic_index":
        onet_code = tool_input.get("onet_code", "")
        return lookup_onet(onet_code)

    return {"error": f"Unknown tool: {name}"}


def _parse_llama_tool_call(error: BadRequestError) -> tuple[str, dict] | None:
    """
    Llama 3.x sometimes generates <function=NAME=JSON></function> instead of
    proper tool_calls. Extract name + args from the error's failed_generation field.
    """
    try:
        body = error.response.json()
        text = body.get("error", {}).get("failed_generation", "")
    except Exception:
        return None
    match = re.search(r"<function=([^=]+)=(\{.*?\})\s*>", text, re.DOTALL)
    if not match:
        return None
    name = match.group(1).strip()
    try:
        args = json.loads(match.group(2))
    except json.JSONDecodeError:
        return None
    return name, args


async def _chat(messages: list, tools: list) -> object:
    """
    Wrapper around client.chat.completions.create that recovers from the
    Llama <function=name=args> format bug by returning a synthetic response.
    """
    try:
        return await client.chat.completions.create(model=MODEL, tools=tools, messages=messages)
    except BadRequestError as e:
        parsed = _parse_llama_tool_call(e)
        if parsed is None:
            raise
        name, args = parsed

        class _FakeFunction:
            def __init__(self):
                self.name = name
                self.arguments = json.dumps(args)

        class _FakeToolCall:
            def __init__(self):
                self.id = "fallback-0"
                self.function = _FakeFunction()
            def model_dump(self):
                return {"id": self.id, "type": "function",
                        "function": {"name": name, "arguments": json.dumps(args)}}

        class _FakeMessage:
            def __init__(self):
                self.content = None
                self.tool_calls = [_FakeToolCall()]

        class _FakeChoice:
            def __init__(self):
                self.message = _FakeMessage()
                self.finish_reason = "tool_calls"

        class _FakeResponse:
            def __init__(self):
                self.choices = [_FakeChoice()]

        return _FakeResponse()


def _sse(event_type: str, data: dict) -> str:
    payload = {"type": event_type, "timestamp": time.time(), **data}
    return f"data: {json.dumps(payload)}\n\n"


async def run_pipeline(cv_text: str, location: str = "London") -> AsyncGenerator[str, None]:
    """Yields SSE-formatted strings for each agent step."""
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Please analyse this CV and find suitable jobs in {location}.\n\nCV:\n{cv_text[:4000]}",
        },
    ]

    yield _sse("start", {"message": "Pipeline started"})

    while True:
        response = await _chat(messages, TOOLS)

        message = response.choices[0].message
        finish_reason = response.choices[0].finish_reason

        if message.content and message.content.strip():
            yield _sse("text", {"text": message.content})

        tool_results = []
        if message.tool_calls:
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                tool_input = json.loads(tool_call.function.arguments)

                # Mask credentials before streaming the tool_call event
                sse_input, _ = redact_credentials_from_input(tool_name, tool_input)
                yield _sse("tool_call", {"tool_name": tool_name, "tool_input": sse_input})

                # Validate / sanitise input — may raise GuardrailViolation
                try:
                    safe_input = sanitise_tool_input(tool_name, tool_input)
                except GuardrailViolation as e:
                    yield _sse("guardrail", {"check": e.check, "detail": e.detail, "tool_name": tool_name, "fired": True})
                    result = {"error": f"Guardrail blocked this tool call: {e.detail}"}
                    yield _sse("tool_result", {"tool_name": tool_name, "result": result})
                    tool_results.append({"role": "tool", "tool_call_id": tool_call.id, "content": json.dumps(result)})
                    continue

                # Execute with sanitised input
                result = await execute_tool(tool_name, safe_input)

                # PII-redacted copy for SSE only; LLM gets unredacted result
                sse_result, pii_fired = redact_pii_from_result(tool_name, result)
                if pii_fired:
                    yield _sse("guardrail", {"check": "pii_redact", "tool_name": tool_name, "fired": True, "detail": "PII removed from display"})
                yield _sse("tool_result", {"tool_name": tool_name, "result": sse_result})

                # Internal message uses UNREDACTED result so the LLM has real contact details
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result),
                })

                # Stop immediately after cover letter — avoids another LLM call with bloated context
                if tool_name == "generate_cover_letter":
                    yield _sse("done", {"message": "Pipeline complete"})
                    return

        if finish_reason == "stop" or not message.tool_calls:
            yield _sse("done", {"message": "Pipeline complete"})
            break

        messages.append({
            "role": "assistant",
            "content": message.content,
            "tool_calls": [tc.model_dump() for tc in message.tool_calls],
        })
        messages.extend(tool_results)


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
    """Apply phase: browser automation first, then skill roadmap generation."""
    cv_profile = cv_profile or {}
    skill_risks = skill_risks or []

    yield _sse("start", {"message": "Starting browser application…", "session_id": session_id})

    # --- Browser phase ---
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

    # --- Roadmap phase ---
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"The browser has submitted the application for job '{job_id}'. "
                f"Now call generate_skill_roadmap with: skill_risks (below), "
                f"cv_profile (below), and target_job_title='{job_id}'.\n\n"
                f"CV Profile summary: name={cv_profile.get('name','')}, "
                f"summary={cv_profile.get('summary','')[:120]}, "
                f"job_titles={cv_profile.get('job_titles',[])}\n\n"
                f"Skill risks:\n{json.dumps(skill_risks)}"
            ),
        },
    ]

    async def execute_tool_with_context(name: str, tool_input: dict) -> dict:
        if name == "generate_skill_roadmap":
            if not tool_input.get("skill_risks"):
                tool_input = {**tool_input, "skill_risks": skill_risks}
            if not tool_input.get("cv_profile") and cv_profile:
                tool_input = {**tool_input, "cv_profile": cv_profile}
        return await execute_tool(name, tool_input)

    while True:
        response = await _chat(messages, TOOLS)

        message = response.choices[0].message
        finish_reason = response.choices[0].finish_reason

        if message.content and message.content.strip():
            yield _sse("text", {"text": message.content})

        tool_results = []
        roadmap_done = False
        if message.tool_calls:
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                tool_input = json.loads(tool_call.function.arguments)

                sse_input, _ = redact_credentials_from_input(tool_name, tool_input)
                yield _sse("tool_call", {"tool_name": tool_name, "tool_input": sse_input})

                try:
                    safe_input = sanitise_tool_input(tool_name, tool_input)
                except GuardrailViolation as e:
                    yield _sse("guardrail", {"check": e.check, "detail": e.detail, "tool_name": tool_name, "fired": True})
                    result = {"error": f"Guardrail blocked this tool call: {e.detail}"}
                    yield _sse("tool_result", {"tool_name": tool_name, "result": result})
                    tool_results.append({"role": "tool", "tool_call_id": tool_call.id, "content": json.dumps(result)})
                    continue

                result = await execute_tool_with_context(tool_name, safe_input)

                sse_result, pii_fired = redact_pii_from_result(tool_name, result)
                if pii_fired:
                    yield _sse("guardrail", {"check": "pii_redact", "tool_name": tool_name, "fired": True, "detail": "PII removed from display"})
                yield _sse("tool_result", {"tool_name": tool_name, "result": sse_result})

                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result),
                })
                if tool_name == "generate_skill_roadmap":
                    roadmap_done = True

        if roadmap_done or finish_reason == "stop" or not message.tool_calls:
            yield _sse("done", {"message": "Done"})
            break

        messages.append({
            "role": "assistant",
            "content": message.content,
            "tool_calls": [tc.model_dump() for tc in message.tool_calls],
        })
        messages.extend(tool_results)
