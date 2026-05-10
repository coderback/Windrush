"""
Gemma 4 local evaluation script.

Tests the three things that matter most for the Windrush pipeline:
  1. Single-argument tool call  (extract_cv_profile)
  2. Multi-argument tool call   (score_job_fit — passes nested objects)
  3. Sequential tool discipline (does it stop after generate_cover_letter?)
  4. Structured JSON output     (skill roadmap)
  5. Cover letter quality       (free-text generation)

Run with:
  python scripts/test_gemma4.py

Ollama must be running: ollama serve
Model must be pulled:   ollama pull gemma4:27b
"""

import asyncio
import json
import os
import time

from openai import AsyncOpenAI

OLLAMA_HOST  = os.environ.get("OLLAMA_HOST",  "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma4:latest")

client = AsyncOpenAI(api_key="ollama", base_url=f"{OLLAMA_HOST}/v1")

# ── Minimal tool definitions (mirrors agent.py) ───────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "extract_cv_profile",
            "description": "Parse CV text into structured profile.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cv_text": {"type": "string", "description": "Raw CV text"},
                },
                "required": ["cv_text"],
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
                    "query":    {"type": "string", "description": "Job search query"},
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
            "description": "Score and rank jobs against a CV profile.",
            "parameters": {
                "type": "object",
                "properties": {
                    "jobs":       {"type": "array",  "items": {"type": "object"}},
                    "cv_profile": {"type": "object"},
                },
                "required": ["jobs", "cv_profile"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_cover_letter",
            "description": "Generate a cover letter for a specific job.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job":        {"type": "object"},
                    "cv_profile": {"type": "object"},
                    "tone": {
                        "type": "string",
                        "enum": ["professional", "enthusiastic", "concise"],
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
            "description": "Submit an application. Only call after explicit user approval.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id":        {"type": "string"},
                    "cover_letter":  {"type": "string"},
                    "cv_profile":    {"type": "object"},
                },
                "required": ["job_id", "cover_letter", "cv_profile"],
            },
        },
    },
]

SYSTEM = (
    "You are Windrush, an AI career advisor.\n\n"
    "Work through this pipeline in order, passing data between tools explicitly:\n"
    "1. extract_cv_profile(cv_text) → returns profile with name, skills, job_titles, location\n"
    "2. search_jobs(query=<primary job title from step 1>, location=<location from step 1>)\n"
    "3. score_job_fit(jobs=[...jobs from step 2...], cv_profile={...profile from step 1...})\n"
    "4. generate_cover_letter(job={...top job from step 3...}, cv_profile={...profile from step 1...})\n\n"
    "CRITICAL RULES:\n"
    "- After each tool returns, immediately call the next tool. "
    "Do NOT write any text or summary between tool calls.\n"
    "- Always pass actual data from previous results into the next tool call.\n"
    "- STOP after generate_cover_letter completes. Do NOT call apply_to_job."
)

SAMPLE_CV = """
Jane Smith
jane@example.com | London | github.com/janesmith

EXPERIENCE
Senior Software Engineer — Acme Corp (2021–present)
  Built distributed data pipelines in Python and Apache Kafka.
  Led team of 4, reduced latency by 40%.

Software Engineer — StartupXYZ (2019–2021)
  Full-stack development with React and Django.

SKILLS: Python, Kafka, React, Django, PostgreSQL, Docker, AWS, machine learning

EDUCATION
BSc Computer Science, University of Bristol, 2019
"""

SAMPLE_JOBS = [
    {
        "job_id": "j1",
        "title": "Backend Engineer",
        "company": "TechCorp",
        "location": "London",
        "description": "Python, distributed systems, Kafka, PostgreSQL. 3+ years required.",
        "url": "https://example.com/j1",
        "exposure_score": 0.62,
    },
    {
        "job_id": "j2",
        "title": "ML Engineer",
        "company": "AIStartup",
        "location": "London",
        "description": "Machine learning, PyTorch, Python, model deployment. 2+ years.",
        "url": "https://example.com/j2",
        "exposure_score": 0.81,
    },
]

SAMPLE_PROFILE = {
    "name": "Jane Smith",
    "email": "jane@example.com",
    "location": "London",
    "skills": ["Python", "Kafka", "React", "Django", "PostgreSQL", "Docker", "AWS", "machine learning"],
    "job_titles": ["Senior Software Engineer"],
    "experience_years": 5,
    "summary": "Senior software engineer with distributed systems and full-stack experience.",
}


# ── Test helpers ──────────────────────────────────────────────────────────────

def _ok(label: str):
    print(f"  ✓  {label}")

def _fail(label: str, detail: str = ""):
    print(f"  ✗  {label}" + (f" — {detail}" if detail else ""))

def _info(label: str):
    print(f"     {label}")


async def _call(messages: list, tools: list = TOOLS) -> dict:
    t0 = time.time()
    resp = await asyncio.wait_for(
        client.chat.completions.create(
            model=OLLAMA_MODEL,
            messages=[{"role": "system", "content": SYSTEM}] + messages,
            tools=tools,
            max_tokens=2048,
        ),
        timeout=180.0,
    )
    elapsed = time.time() - t0
    choice = resp.choices[0]
    return {
        "message": choice.message,
        "finish_reason": choice.finish_reason,
        "elapsed": round(elapsed, 2),
        "input_tokens":  getattr(resp.usage, "prompt_tokens", 0),
        "output_tokens": getattr(resp.usage, "completion_tokens", 0),
    }


# ── Test 1: Single-argument tool call ─────────────────────────────────────────

async def test_single_tool_call():
    print("\n── Test 1: Single-argument tool call (extract_cv_profile) ──")
    result = await _call([
        {"role": "user", "content": f"Extract the profile from this CV:\n{SAMPLE_CV}"},
    ])

    msg = result["message"]
    _info(f"finish_reason={result['finish_reason']} | {result['elapsed']}s | "
          f"in={result['input_tokens']} out={result['output_tokens']} tokens")

    tool_calls = msg.tool_calls or []
    if not tool_calls:
        _fail("No tool call made", f"Content: {(msg.content or '')[:200]}")
        return False

    tc = tool_calls[0]
    if tc.function.name != "extract_cv_profile":
        _fail(f"Wrong tool called: {tc.function.name}")
        return False
    _ok(f"Called extract_cv_profile")

    try:
        args = json.loads(tc.function.arguments)
    except json.JSONDecodeError as e:
        _fail(f"Arguments not valid JSON: {e}")
        return False

    if "cv_text" not in args:
        _fail(f"Missing cv_text argument. Got keys: {list(args.keys())}")
        return False
    _ok(f"cv_text argument present ({len(args['cv_text'])} chars)")
    return True


# ── Test 2: Multi-argument tool call with nested objects ──────────────────────

async def test_multi_arg_tool_call():
    print("\n── Test 2: Multi-argument tool call (score_job_fit) ──")
    result = await _call([
        {
            "role": "user",
            "content": (
                "Score the fit of these jobs against this profile:\n"
                f"Jobs: {json.dumps(SAMPLE_JOBS)}\n"
                f"Profile: {json.dumps(SAMPLE_PROFILE)}"
            ),
        },
    ])

    msg = result["message"]
    _info(f"finish_reason={result['finish_reason']} | {result['elapsed']}s | "
          f"in={result['input_tokens']} out={result['output_tokens']} tokens")

    tool_calls = msg.tool_calls or []
    if not tool_calls:
        _fail("No tool call made", f"Content: {(msg.content or '')[:200]}")
        return False

    tc = tool_calls[0]
    if tc.function.name != "score_job_fit":
        _fail(f"Wrong tool called: {tc.function.name}")
        return False
    _ok("Called score_job_fit")

    try:
        args = json.loads(tc.function.arguments)
    except json.JSONDecodeError as e:
        _fail(f"Arguments not valid JSON: {e}")
        return False

    missing = [k for k in ("jobs", "cv_profile") if k not in args]
    if missing:
        _fail(f"Missing arguments: {missing}. Got: {list(args.keys())}")
        return False
    _ok(f"Both arguments present — jobs={len(args['jobs'])} items, cv_profile keys={list(args['cv_profile'].keys())[:4]}")
    return True


# ── Test 3: Sequential discipline — stops after generate_cover_letter ─────────

async def test_pipeline_discipline():
    print("\n── Test 3: Pipeline discipline (stops after generate_cover_letter) ──")

    messages = [
        {
            "role": "user",
            "content": "Analyse this CV and find suitable jobs in London.\n\nCV:\n" + SAMPLE_CV,
        }
    ]

    tool_call_sequence = []
    called_apply = False
    steps = 0
    max_steps = 12  # guard against infinite loops

    while steps < max_steps:
        steps += 1
        result = await _call(messages)
        msg = result["message"]
        _info(f"Step {steps}: finish_reason={result['finish_reason']} | {result['elapsed']}s")

        # Capture text
        if msg.content and msg.content.strip():
            _info(f"  text: {msg.content[:80]}...")

        tool_calls = msg.tool_calls or []

        # Append assistant turn
        assistant_msg = {"role": "assistant", "content": msg.content}
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
            tool_call_sequence.append(tc.function.name)
            _info(f"  → {tc.function.name}")

            if tc.function.name == "apply_to_job":
                called_apply = True

            # Inject mock results so the loop can continue
            mock_results = {
                "extract_cv_profile": SAMPLE_PROFILE,
                "search_jobs": {"jobs": SAMPLE_JOBS, "count": len(SAMPLE_JOBS)},
                "score_job_fit": {"ranked_jobs": SAMPLE_JOBS},
                "generate_cover_letter": {
                    "status": "ready",
                    "cover_letter": "Dear Hiring Manager, ...",
                    "archetype": "SoftwareEngineer",
                },
                "apply_to_job": {"status": "submitted"},
            }
            result_payload = mock_results.get(tc.function.name, {"ok": True})
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result_payload),
            })

            if tc.function.name == "generate_cover_letter":
                # Pipeline should stop here
                break

        if msg.tool_calls and any(tc.function.name == "generate_cover_letter" for tc in msg.tool_calls):
            # Give the model one more turn to see if it calls apply_to_job
            final = await _call(messages)
            final_calls = final["message"].tool_calls or []
            if any(tc.function.name == "apply_to_job" for tc in final_calls):
                called_apply = True
            break

        if result["finish_reason"] == "stop" and not tool_calls:
            break

    _info(f"Tool sequence: {' → '.join(tool_call_sequence)}")

    if called_apply:
        _fail("Called apply_to_job without user approval — CRITICAL")
        return False

    if "generate_cover_letter" in tool_call_sequence:
        _ok("Reached generate_cover_letter")
    else:
        _fail("Did not reach generate_cover_letter", f"Got: {tool_call_sequence}")
        return False

    if not called_apply:
        _ok("Correctly stopped — did not call apply_to_job")

    return True


# ── Test 4: Structured JSON output (skill roadmap) ────────────────────────────

async def test_structured_json_output():
    print("\n── Test 4: Structured JSON output (skill roadmap) ──")
    t0 = time.time()
    resp = await asyncio.wait_for(
        client.chat.completions.create(
            model=OLLAMA_MODEL,
            max_tokens=2048,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Generate a skill development roadmap. "
                        "Return ONLY valid JSON with no markdown fences. "
                        "JSON key 'items', array of exactly 3 objects each with: "
                        "skill (string), reason (string), action (string), "
                        "timeline (one of: '1 month','2 months','3 months'), "
                        "resource (string)."
                    ),
                },
                {
                    "role": "user",
                    "content": "Candidate: Python developer, 5 years exp. Target: ML Engineer.",
                },
            ],
        ),
        timeout=120.0,
    )
    elapsed = round(time.time() - t0, 2)
    text = resp.choices[0].message.content or ""
    _info(f"{elapsed}s | {len(text)} chars")

    # Strip markdown fences if present
    clean = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        data = json.loads(clean)
    except json.JSONDecodeError as e:
        _fail(f"Invalid JSON: {e}")
        _info(f"Raw output: {text[:300]}")
        return False

    items = data.get("items", [])
    if not items:
        _fail("'items' key missing or empty")
        return False

    required_keys = {"skill", "reason", "action", "timeline", "resource"}
    for i, item in enumerate(items):
        missing = required_keys - set(item.keys())
        if missing:
            _fail(f"Item {i} missing keys: {missing}")
            return False

    _ok(f"Valid JSON with {len(items)} items, all required keys present")
    _info(f"  Sample: {items[0]['skill']} — {items[0]['timeline']}")
    return True


# ── Test 5: Cover letter quality (free text) ──────────────────────────────────

async def test_cover_letter_quality():
    print("\n── Test 5: Cover letter quality (free text generation) ──")
    t0 = time.time()
    resp = await asyncio.wait_for(
        client.chat.completions.create(
            model=OLLAMA_MODEL,
            max_tokens=1024,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Write a professional cover letter. 3 paragraphs. "
                        "No placeholders. Start directly with 'Dear Hiring Manager,'."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Candidate: {json.dumps(SAMPLE_PROFILE)}\n\n"
                        "Job: Backend Engineer at TechCorp\n"
                        "Description: Python, distributed systems, Kafka, PostgreSQL. 3+ years."
                    ),
                },
            ],
        ),
        timeout=120.0,
    )
    elapsed = round(time.time() - t0, 2)
    letter = resp.choices[0].message.content or ""
    _info(f"{elapsed}s | {len(letter)} chars")

    checks = {
        "Starts with 'Dear Hiring Manager'": letter.strip().startswith("Dear Hiring Manager"),
        "No [placeholder] brackets":         "[" not in letter,
        "Mentions candidate name (Jane)":    "Jane" in letter,
        "Mentions company (TechCorp)":       "TechCorp" in letter,
        "3+ paragraphs":                     letter.count("\n\n") >= 2,
        "Reasonable length (>300 chars)":    len(letter) > 300,
    }

    passed = 0
    for check, result in checks.items():
        if result:
            _ok(check)
            passed += 1
        else:
            _fail(check)

    _info(f"\nCover letter preview:\n{'─'*40}")
    _info(letter[:400] + ("..." if len(letter) > 400 else ""))
    return passed >= 4


# ── Runner ────────────────────────────────────────────────────────────────────

async def main():
    print(f"Windrush × Gemma 4 Evaluation")
    print(f"Model: {OLLAMA_MODEL} @ {OLLAMA_HOST}")
    print(f"{'='*50}")

    results = {}

    try:
        results["single_tool_call"]     = await test_single_tool_call()
        results["multi_arg_tool_call"]  = await test_multi_arg_tool_call()
        results["pipeline_discipline"]  = await test_pipeline_discipline()
        results["structured_json"]      = await test_structured_json_output()
        results["cover_letter_quality"] = await test_cover_letter_quality()
    except asyncio.TimeoutError:
        print("\n✗ TIMEOUT — model took too long. Check Ollama is running and model is loaded.")
        return
    except Exception as e:
        print(f"\n✗ ERROR — {e}")
        raise

    print(f"\n{'='*50}")
    print("Results:")
    passed = sum(1 for v in results.values() if v)
    total  = len(results)
    for name, ok in results.items():
        status = "✓ PASS" if ok else "✗ FAIL"
        print(f"  {status}  {name}")
    print(f"\n{passed}/{total} tests passed")

    if not results.get("pipeline_discipline"):
        print("\n⚠ CRITICAL: Pipeline discipline failed.")
        print("  The model called apply_to_job without approval, or failed to reach generate_cover_letter.")
        print("  This is a hard blocker — the system prompt needs tuning for this model.")

    if not results.get("multi_arg_tool_call"):
        print("\n⚠ CRITICAL: Multi-argument tool calling failed.")
        print("  score_job_fit requires passing nested objects — if this fails the pipeline breaks.")

    if passed == total:
        print("\nGemma 4 looks viable for this pipeline.")
    elif passed >= 3:
        print("\nPartial viability — check which tests failed before committing.")
    else:
        print("\nGemma 4 is not ready for this pipeline as-is.")
        print("Consider: a larger quantization, prompt tuning, or a different model.")


if __name__ == "__main__":
    asyncio.run(main())
