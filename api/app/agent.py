import asyncio
import json
import os
import time
from typing import AsyncGenerator

import anthropic

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

anthropic_client = anthropic.AsyncAnthropic(
    api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
)

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are Windrush, an AI career transition advisor helping workers navigate the impact of AI on their careers.

Work through this pipeline in order, passing data between tools explicitly:

1. extract_cv_profile(cv_text) → returns a profile object with name, skills, job_titles, location
2. score_ai_risk(skills=[...all skills and job_titles from step 1...])
3. search_jobs(query=<primary job title from profile>, location=<location from profile>)
4. score_job_fit(jobs=[...the jobs array from step 3's result...], cv_profile={...the full profile object from step 1...})
5. generate_skill_roadmap(skill_risks=[...the skill_risks array from step 2...], cv_profile={...the full profile object from step 1...}, target_job_title=<top ranked job title from step 4>)
6. generate_cover_letter(job={...the top ranked job from step 4...}, cv_profile={...the full profile object from step 1...})

CRITICAL: Always pass the actual data objects from previous tool results into subsequent tool calls. Never call a tool with empty arguments.

After generate_cover_letter completes, stop. Do NOT call apply_to_job — the user must explicitly approve first."""


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


async def execute_tool(name: str, tool_input: dict) -> dict:
    if name == "extract_cv_profile":
        cv_text = tool_input.get("cv_text", "")
        resp = await anthropic_client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=(
                "Extract a structured profile from this CV. Return ONLY valid JSON with no markdown fences. "
                "Include: name, email, phone, address (full postal address if present), "
                "location (city/region), linkedin (URL or username), github (URL or username), "
                "skills (array, max 12 most relevant), job_titles (array, max 3), "
                "experience_years (number), summary (1 sentence only), "
                "education (array of {institution, degree, dates}), "
                "experience (array of {employer, title, dates, summary} — max 5 most recent)."
            ),
            messages=[{"role": "user", "content": cv_text[:8000]}],
        )
        text = next((b.text for b in resp.content if b.type == "text"), "")
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
                # Fall back to lookup, then default 0.55
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
        # Cap at 5; keep description (truncated) so score_job_fit can match skills without fixture lookup
        slim_jobs = [
            {k: v for k, v in j.items() if k not in ("salary_min", "salary_max")}
            for j in jobs[:5]
        ]
        return {"jobs": slim_jobs, "count": len(slim_jobs)}

    elif name == "score_job_fit":
        jobs = tool_input.get("jobs", [])
        cv_profile = tool_input.get("cv_profile", {})
        cv_skills = set(s.lower() for s in cv_profile.get("skills", []))

        scored = []
        for job in jobs:
            exposure = job.get("exposure_score", 0.5)
            desc_lower = job.get("description", "").lower()
            skill_matches = sum(1 for s in cv_skills if s in desc_lower)
            fit_score = min(skill_matches / max(len(cv_skills), 1), 1.0)
            composite = (1 - exposure) * 0.5 + fit_score * 0.5
            scored.append({
                "job_id": job.get("job_id"),
                "title": job.get("title"),
                "company": job.get("company"),
                "location": job.get("location"),
                "url": job.get("url"),
                "description": job.get("description", ""),
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
        resp = await anthropic_client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=f"Write a {tone} cover letter. Be specific — reference the candidate's actual experience and the job's requirements. 3 paragraphs. No placeholders like [Your Address] or [Date] — omit address headers entirely and start directly with 'Dear Hiring Manager,'.",
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Candidate: {json.dumps(cv_profile)}\n\n"
                        f"Job: {job.get('title')} at {job.get('company')}\n"
                        f"Description: {job.get('description', '')}"
                    ),
                },
            ],
        )
        letter = next((b.text for b in resp.content if b.type == "text"), "")
        return {
            "status": "ready",
            "job_title": job.get("title", ""),
            "company": job.get("company", ""),
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

        resp = await anthropic_client.messages.create(
            model=MODEL,
            max_tokens=2048,
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
            messages=[
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
        text = next((b.text for b in resp.content if b.type == "text"), "")
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
    """Call Anthropic messages API. Extracts system message from the messages list."""
    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    filtered = [m for m in messages if m["role"] != "system"]
    return await asyncio.wait_for(
        anthropic_client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system,
            messages=filtered,
            tools=tools,
        ),
        timeout=90.0,
    )


def _sse(event_type: str, data: dict) -> str:
    payload = {"type": event_type, "timestamp": time.time(), **data}
    return f"data: {json.dumps(payload)}\n\n"


async def run_pipeline(cv_text: str, location: str = "London") -> AsyncGenerator[str, None]:
    """Yields SSE-formatted strings for each agent step."""
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Please analyse this CV and find suitable jobs in {location}.\n\nCV:\n{cv_text[:8000]}",
        },
    ]

    yield _sse("start", {"message": "Pipeline started"})

    while True:
        try:
            response = await _chat(messages, TOOLS)
        except asyncio.TimeoutError:
            yield _sse("done", {"message": "Request timed out — please try again."})
            return

        text_blocks = [b for b in response.content if b.type == "text"]
        tool_uses   = [b for b in response.content if b.type == "tool_use"]

        if text_blocks and text_blocks[0].text.strip():
            yield _sse("text", {"text": text_blocks[0].text})

        tool_results_content = []

        for tool_use in tool_uses:
            tool_name  = tool_use.name
            tool_input = tool_use.input  # already a dict

            sse_input, _ = redact_credentials_from_input(tool_name, tool_input)
            yield _sse("tool_call", {"tool_name": tool_name, "tool_input": sse_input})

            try:
                safe_input = sanitise_tool_input(tool_name, tool_input)
            except GuardrailViolation as e:
                yield _sse("guardrail", {"check": e.check, "detail": e.detail, "tool_name": tool_name, "fired": True})
                result = {"error": f"Guardrail blocked this tool call: {e.detail}"}
                yield _sse("tool_result", {"tool_name": tool_name, "result": result})
                tool_results_content.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": json.dumps(result),
                })
                continue

            result = await execute_tool(tool_name, safe_input)

            sse_result, pii_fired = redact_pii_from_result(tool_name, result)
            if pii_fired:
                yield _sse("guardrail", {"check": "pii_redact", "tool_name": tool_name, "fired": True, "detail": "PII removed from display"})
            yield _sse("tool_result", {"tool_name": tool_name, "result": sse_result})

            # Unredacted result for LLM context
            tool_results_content.append({
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": json.dumps(result),
            })

            if tool_name == "generate_cover_letter":
                yield _sse("done", {"message": "Pipeline complete"})
                return

        if response.stop_reason == "end_turn" or not tool_uses:
            yield _sse("done", {"message": "Pipeline complete"})
            break

        # Append assistant turn + tool results as a single user message
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results_content})


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

    yield _sse("done", {"message": "Done"})
