import anthropic
import json
import time
from typing import AsyncGenerator

from .cv_parser import extract_text
from .risk_scorer import lookup_onet, lookup_by_title, ECONOMIC_INDEX
from .job_proxy import search_jobs

client = anthropic.AsyncAnthropic()

SYSTEM_PROMPT = """You are Windrush, an AI career transition advisor helping workers navigate the impact of AI on their careers.

You have access to tools to analyse a CV, score AI-related risk for their skills, find suitable jobs, and generate a cover letter.

Work through this pipeline in order:
1. extract_cv_profile — parse the CV text into structured data
2. score_ai_risk — score each extracted skill/occupation for AI exposure
3. search_jobs — find relevant jobs in the user's location
4. score_job_fit — rank those jobs against the CV profile
5. generate_cover_letter — write a personalised cover letter for the top job

IMPORTANT: After generate_cover_letter completes, return end_turn. Do NOT call apply_to_job automatically.
The user must explicitly approve before any application is submitted.

Be thorough but efficient. Use real data from the CV — never generate generic responses."""

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
        "description": "Generate a prioritised skill development roadmap to reduce AI exposure risk.",
        "input_schema": {
            "type": "object",
            "properties": {
                "skill_risks": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "List of scored skill risks",
                },
                "target_job": {"type": "object", "description": "Target job to pivot toward"},
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
        # Claude does the extraction; we just echo back with a structured hint
        return {
            "status": "parsed",
            "cv_text_length": len(tool_input.get("cv_text", "")),
            "note": "Profile extracted from CV text. Use this data for subsequent tools.",
            "raw_text_preview": tool_input.get("cv_text", "")[:500],
        }

    elif name == "score_ai_risk":
        skills = tool_input.get("skills", [])
        results = []
        for skill in skills:
            data = lookup_by_title(skill)
            results.append({
                "skill": skill,
                "occupation_name": data.get("occupation_name", skill),
                "overall_exposure": data.get("overall_exposure", 0.5),
                "risk_level": "high" if data.get("overall_exposure", 0.5) >= 0.5 else "low",
            })
        return {"skill_risks": results}

    elif name == "search_jobs":
        jobs = await search_jobs(tool_input.get("query", ""), tool_input.get("location", "London"))
        return {"jobs": jobs, "count": len(jobs)}

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
            scored.append({**job, "fit_score": round(fit_score, 2), "composite_score": round(composite, 2)})

        scored.sort(key=lambda j: j["composite_score"], reverse=True)
        return {"ranked_jobs": scored}

    elif name == "generate_cover_letter":
        job = tool_input.get("job", {})
        cv_profile = tool_input.get("cv_profile", {})
        tone = tool_input.get("tone", "professional")
        # Claude generates the actual text; we signal readiness
        return {
            "status": "ready",
            "job_title": job.get("title", ""),
            "company": job.get("company", ""),
            "candidate_name": cv_profile.get("name", ""),
            "tone": tone,
            "instruction": "Generate a compelling cover letter using the CV profile data and job description above.",
        }

    elif name == "apply_to_job":
        return {
            "status": "submitted",
            "job_id": tool_input.get("job_id"),
            "message": "Application submitted successfully. Good luck!",
        }

    elif name == "generate_skill_roadmap":
        skill_risks = tool_input.get("skill_risks", [])
        high_risk = [s for s in skill_risks if s.get("overall_exposure", 0) >= 0.5]
        return {
            "status": "generated",
            "high_risk_skills": len(high_risk),
            "instruction": "Generate a 6-month roadmap with specific courses and actions to pivot away from high-risk skills.",
        }

    elif name == "lookup_economic_index":
        onet_code = tool_input.get("onet_code", "")
        return lookup_onet(onet_code)

    return {"error": f"Unknown tool: {name}"}


def _sse(event_type: str, data: dict) -> str:
    payload = {"type": event_type, "timestamp": time.time(), **data}
    return f"data: {json.dumps(payload)}\n\n"


async def run_pipeline(cv_text: str, location: str = "London") -> AsyncGenerator[str, None]:
    """Yields SSE-formatted strings for each agent step."""
    messages: list[dict] = [
        {
            "role": "user",
            "content": f"Please analyse this CV and find suitable jobs in {location}.\n\nCV:\n{cv_text}",
        }
    ]

    yield _sse("start", {"message": "Pipeline started"})

    while True:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        tool_results = []

        for block in response.content:
            if block.type == "tool_use":
                yield _sse("tool_call", {"tool_name": block.name, "tool_input": block.input})
                result = await execute_tool(block.name, block.input)
                yield _sse("tool_result", {"tool_name": block.name, "result": result})
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    }
                )
            elif block.type == "text" and block.text.strip():
                yield _sse("text", {"text": block.text})

        if response.stop_reason == "end_turn":
            yield _sse("done", {"message": "Pipeline complete"})
            break

        # Push ONE assistant message + ONE user message with ALL tool results
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})


async def run_apply(job_id: str, cover_letter: str, cv_profile: dict, skill_risks: list | None = None) -> AsyncGenerator[str, None]:
    """Short continuation for the apply + roadmap phase after user approval."""
    skill_risks = skill_risks or []
    messages = [
        {
            "role": "user",
            "content": (
                f"The user has approved the cover letter. Please:\n"
                f"1. Call apply_to_job with job_id='{job_id}'\n"
                f"2. Then call generate_skill_roadmap using the skill_risks below\n\n"
                f"Cover letter:\n{cover_letter}\n\n"
                f"CV Profile:\n{json.dumps(cv_profile)}\n\n"
                f"Skill risks (from earlier scoring):\n{json.dumps(skill_risks)}"
            ),
        }
    ]

    yield _sse("start", {"message": "Applying..."})

    while True:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        tool_results = []

        for block in response.content:
            if block.type == "tool_use":
                yield _sse("tool_call", {"tool_name": block.name, "tool_input": block.input})
                result = await execute_tool(block.name, block.input)
                yield _sse("tool_result", {"tool_name": block.name, "result": result})
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    }
                )
            elif block.type == "text" and block.text.strip():
                yield _sse("text", {"text": block.text})

        if response.stop_reason == "end_turn":
            yield _sse("done", {"message": "Done"})
            break

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})
