import asyncio
import base64
import json
import os
from typing import AsyncGenerator

from playwright.async_api import Page

_BACKEND = os.environ.get("LLM_BACKEND", "ollama").lower()
_OLLAMA_HOST  = os.environ.get("OLLAMA_HOST",  "http://localhost:11434")
_OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma4:latest")

try:
    from browser_use import Agent, BrowserSession, BrowserProfile

    if _BACKEND == "groq":
        from langchain_groq import ChatGroq as _BaseChatGroq
        from typing import ClassVar

        class _BrowserLLM(_BaseChatGroq):
            """ChatGroq with provider attribute required by browser-use."""
            provider: ClassVar[str] = "groq"

        def _make_browser_llm():
            return _BrowserLLM(
                model="llama-3.3-70b-versatile",
                groq_api_key=os.environ.get("GROQ_API_KEY", ""),
            )
    else:
        from langchain_ollama import ChatOllama as _ChatOllama

        def _make_browser_llm():
            return _ChatOllama(
                model=_OLLAMA_MODEL,
                base_url=_OLLAMA_HOST,
            )

    BROWSER_USE_AVAILABLE = True
except ImportError:
    BROWSER_USE_AVAILABLE = False

    def _make_browser_llm():  # noqa: F811
        return None


async def _screenshot_b64(page: Page) -> str:
    try:
        jpeg = await page.screenshot(full_page=False, type="jpeg", quality=60)
        return base64.b64encode(jpeg).decode()
    except Exception:
        return ""


def _push_frame(frame_queue: asyncio.Queue, frame_b64: str):
    """Drop oldest frame if full, then push newest."""
    if frame_queue.full():
        try:
            frame_queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
    try:
        frame_queue.put_nowait(frame_b64)
    except asyncio.QueueFull:
        pass


async def _cdp_screenshotter(browser_session, frame_queue: asyncio.Queue):
    """
    Attach a CDP Page.startScreencast session to the active Playwright page.
    Chrome pushes JPEG frames at up to ~30fps without us having to poll.
    Re-attaches automatically when the agent navigates to a new tab.
    """
    active: dict = {}  # {"page": Page, "client": CDPSession}

    async def _attach(page):
        # Tear down previous session
        old_client = active.get("client")
        if old_client:
            try:
                await old_client.send("Page.stopScreencast")
            except Exception:
                pass
            try:
                await old_client.detach()
            except Exception:
                pass
        active.clear()

        try:
            client = await page.context.new_cdp_session(page)
        except Exception:
            return

        active["page"] = page
        active["client"] = client

        async def on_frame(data):
            frame_b64 = data.get("data", "")
            if frame_b64:
                _push_frame(frame_queue, frame_b64)
            # Ack is required — Chrome stops sending frames without it
            try:
                await client.send("Page.screencastFrameAck", {"sessionId": data["sessionId"]})
            except Exception:
                pass

        client.on("Page.screencastFrame", on_frame)
        try:
            await client.send("Page.startScreencast", {
                "format": "jpeg",
                "quality": 60,
                "maxWidth": 1280,
                "maxHeight": 800,
                "everyNthFrame": 1,
            })
        except Exception:
            pass

    last_page = None
    while True:
        try:
            context = getattr(browser_session, "context", None)
            if context and context.pages:
                page = context.pages[-1]
                if page is not last_page:
                    last_page = page
                    await _attach(page)
        except Exception:
            pass
        await asyncio.sleep(0.3)  # Only need to poll for page-change events


DONE_COMMANDS = {"submit", "done", "skip", "cancel", "abort"}


async def _interactive_session(page: Page, instruction_queue: asyncio.Queue, context=None) -> AsyncGenerator[dict, None]:
    """
    Hand control to the user. Loops processing commands from instruction_queue.
    Automatically follows new tabs opened by clicks.
    """
    screenshot = await _screenshot_b64(page)
    yield {
        "action": "You have control — click the screenshot or type below",
        "screenshot": screenshot or None,
        "blocked": True,
        "reason": "Click anywhere on the screenshot to interact, type in the box, or type 'submit' / 'skip'.",
        "done": False,
        "interactive": True,
    }

    while True:
        try:
            raw = await asyncio.wait_for(instruction_queue.get(), timeout=120)
        except asyncio.TimeoutError:
            yield {"action": "Session timed out", "screenshot": None, "blocked": False, "reason": None, "done": True}
            return

        cmd: dict | None = None
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and "type" in parsed:
                cmd = parsed
        except (json.JSONDecodeError, TypeError):
            pass

        if cmd:
            kind = cmd.get("type", "")
            if kind == "click":
                pages_before = list(context.pages) if context else []
                await page.mouse.click(float(cmd["x"]), float(cmd["y"]))
                await page.wait_for_timeout(800)
                if context and len(context.pages) > len(pages_before):
                    new_page = context.pages[-1]
                    try:
                        await new_page.wait_for_load_state("domcontentloaded", timeout=10000)
                        page = new_page
                    except Exception:
                        pass
            elif kind == "type":
                await page.keyboard.type(str(cmd.get("text", "")))
                await page.wait_for_timeout(200)
            elif kind == "key":
                await page.keyboard.press(str(cmd.get("key", "Enter")))
                await page.wait_for_timeout(400)
            elif kind == "scroll":
                await page.mouse.wheel(0, float(cmd.get("delta", 300)))
                await page.wait_for_timeout(300)
            elif kind in DONE_COMMANDS or cmd.get("type") in DONE_COMMANDS:
                yield {"action": f"User ended session: {kind}", "screenshot": None, "blocked": False, "reason": None, "done": True}
                return

            screenshot = await _screenshot_b64(page)
            yield {
                "action": f"Executed: {kind}",
                "screenshot": screenshot or None,
                "blocked": True,
                "reason": "Click the screenshot or type below. Type 'submit' when done.",
                "done": False,
                "interactive": True,
            }

        else:
            text = str(raw).strip().lower()
            if text in DONE_COMMANDS:
                if text in ("skip", "cancel", "abort"):
                    yield {"action": "Cancelled by user", "screenshot": None, "blocked": False, "reason": None, "done": True}
                else:
                    yield {"action": "User confirmed — proceeding", "screenshot": None, "blocked": False, "reason": None, "done": True}
                return
            await page.keyboard.type(str(raw))
            await page.wait_for_timeout(200)
            screenshot = await _screenshot_b64(page)
            yield {
                "action": f"Typed: {raw[:40]}",
                "screenshot": screenshot or None,
                "blocked": True,
                "reason": "Click the screenshot or type below. Type 'submit' when done.",
                "done": False,
                "interactive": True,
            }


def _build_task(job_url: str, persona: dict, cover_letter: str,
                job_email: str, job_password: str, cv_path: str) -> str:
    lines = []
    if job_email:
        lines.append(f"If asked to log in, use: email={job_email}, password={job_password}")
    if cv_path:
        lines.append(f"If asked to upload a CV/resume, upload the file at: {cv_path}")

    core = persona.get("core_info", {})
    prefs = persona.get("preferences", {})
    
    profile_lines = []
    full_name = f"{core.get('first_name', '')} {core.get('last_name', '')}".strip()
    if full_name: profile_lines.append(f"Full name: {full_name}")
    if core.get("preferred_name"): profile_lines.append(f"Preferred name: {core['preferred_name']}")
    if core.get("dob"): profile_lines.append(f"Date of Birth: {core['dob']}")
    if core.get("email") or job_email: profile_lines.append(f"Email: {core.get('email') or job_email}")
    if core.get("phone"): profile_lines.append(f"Phone: {core['phone']}")
    
    address = ", ".join(filter(None, [
        core.get("address_line_1"), core.get("city"), core.get("postcode"), core.get("country")
    ]))
    if address: profile_lines.append(f"Address: {address}")
    
    if core.get("linkedin"): profile_lines.append(f"LinkedIn: {core['linkedin']}")
    if core.get("github"): profile_lines.append(f"GitHub: {core['github']}")
    if core.get("twitter"): profile_lines.append(f"Twitter/X: {core['twitter']}")
    if core.get("portfolio"): profile_lines.append(f"Portfolio/Website: {core['portfolio']}")
    if core.get("visa_status"): profile_lines.append(f"Visa Status: {core['visa_status']}")
    if core.get("visa_type"): profile_lines.append(f"Visa Type: {core['visa_type']}")
    if core.get("security_clearance"): profile_lines.append(f"Security Clearance: {core['security_clearance']}")

    # Certifications
    for cert in persona.get("certifications", []):
        profile_lines.append(
            f"Certification: {cert.get('name', '')} from {cert.get('issuing_organization', '')}. "
            f"Credential ID: {cert.get('credential_id', '')}. URL: {cert.get('credential_url', '')}"
        )

    # Categorized Skills
    skills_lines = []
    for cat in persona.get("skills", []):
        skills_lines.append(f"{cat.get('category', 'Uncategorized')}: {', '.join(cat.get('skills', []))}")
    if skills_lines:
        profile_lines.append("Skills - " + " | ".join(skills_lines))

    # All education entries
    for edu in persona.get("education", []):
        status = "Ongoing" if edu.get("is_currently_enrolled") else edu.get("end_date", "Present")
        profile_lines.append(
            f"Education: {edu.get('degree', '')} at {edu.get('institution', '')} "
            f"({edu.get('start_date', '')} to {status}). Grade: {edu.get('grade', '')}"
        )
    # Experience
    for exp in persona.get("history", [])[:5]:
        status = "Present" if exp.get("is_current") else exp.get("end_date", "")
        profile_lines.append(
            f"Experience: {exp.get('title', '')} at {exp.get('employer', '')} "
            f"({exp.get('start_date', '')} to {status}). "
            f"Achievements: {', '.join(exp.get('achievements', []))}. Metrics: {exp.get('metrics', '')}"
        )
    
    # Projects
    for proj in persona.get("projects", []):
        status = "Ongoing" if proj.get("is_ongoing") else "Completed"
        profile_lines.append(
            f"Project: {proj.get('name', '')} ({status}). Problem: {proj.get('problem_solved', '')}. "
            f"Outcomes: {proj.get('outcomes', '')}. URL: {proj.get('url', '')}"
        )

    # Story Bank for behavioral questions
    stories_block = ""
    if persona.get("story_bank"):
        stories_block = "\n\nUse these stories to answer behavioral questions. ALWAYS use the STAR method (Situation, Task, Action, Result) in your answers:\n"
        for story in persona["story_bank"]:
            stories_block += f"- {story['title']}: {story['scenario']} -> {story['action']} -> {story['result']}\n"

    # Screening Vault
    screening = persona.get("screening", {})
    screening_block = ""
    if any(screening.values()):
        screening_block = "\n\nUse these pre-written answers for screening questions:\n"
        for k, v in screening.items():
            if v: screening_block += f"- {k.replace('_', ' ').title()}: {v}\n"

    # Diversity & Inclusion
    diversity = persona.get("diversity", {})
    
    creds_block = "\n".join(lines)
    profile_block = "\n".join(profile_lines)
    task = f"Apply for the job at: {job_url}"
    if creds_block:
        task += f"\n\n{creds_block}"
    if profile_block:
        task += f"\n\nApplicant details:\n{profile_block}"
    if screening_block:
        task += screening_block
    if stories_block:
        task += stories_block

    rtw_uk = "Yes" if core.get("right_to_work_uk", True) else "No"
    sponsorship = "Yes" if core.get("require_sponsorship", False) else "No"
    salary = screening.get("salary_canonical") or f"{prefs.get('min_salary', 'Negotiable')}"
    hourly = f"{prefs.get('expected_hourly_rate', 'Negotiable')}"
    remote = prefs.get("remote_preference", "remote")
    relocate = "Yes" if prefs.get("relocation_willingness", False) else "No"
    pref_locs = ", ".join(prefs.get("preferred_locations", []))
    in_person = "Yes" if prefs.get("can_work_in_person", True) else "No"
    immediate = "Yes" if prefs.get("can_start_immediately", False) else "No"
    transport = "Yes" if prefs.get("has_reliable_transportation", True) else "No"
    accommodations = "Yes" if prefs.get("needs_accommodations", False) else "No"
    gov_ties = "Yes" if core.get("has_government_ties", False) else "No"

    # Diversity defaults
    gender = diversity.get("gender") or "Prefer not to say"
    disability = diversity.get("disability_status") or "No"
    ethnicity = diversity.get("ethnicity") or "Prefer not to say"

    task += (
        f"\n\nFor dropdown / multiple-choice questions use these answers:"
        f"\n- Right to work / work authorisation in the UK: {rtw_uk}"
        f"\n- Require visa sponsorship: {sponsorship}"
        f"\n- Gender: {gender}"
        f"\n- Ethnicity / diversity questions: {ethnicity}"
        f"\n- Disability: {disability}"
        f"\n- Salary expectations (Annual): {salary}"
        f"\n- Salary expectations (Hourly): {hourly}"
        f"\n- Remote/Hybrid preference: {remote}"
        f"\n- Willing to relocate: {relocate}"
        f"\n- Preferred work locations: {pref_locs}"
        f"\n- Can work in-person: {in_person}"
        f"\n- Can start immediately: {immediate}"
        f"\n- Has reliable transportation: {transport}"
        f"\n- Needs accommodations: {accommodations}"
        f"\n- Has government ties: {gov_ties}"
        f"\n- How did you hear about us: Website / Internet search"
        f"\n- Are you currently employed: Yes if experience list is non-empty, else No"
    )

    if persona.get("custom_directives"):
        task += f"\n\nCustom Directives to follow: {persona['custom_directives']}"

    task += f"\n\nFull cover letter to paste into any cover letter field:\n{cover_letter}"
    task += "\n\nComplete and submit the application. Fill every required field. If a field is optional and you don't have the answer, leave it blank."
    return task


async def apply_with_browser(
    job_url: str,
    cv_profile: dict,
    cover_letter: str,
    instruction_queue: asyncio.Queue,
    frame_queue: asyncio.Queue | None = None,
    job_email: str = "",
    job_password: str = "",
    cv_path: str = "",
) -> AsyncGenerator[dict, None]:
    """
    Async generator — uses browser-use LLM agent to autonomously complete a job application.
    Falls back to interactive session if the agent fails.
    Yields dicts: { action, screenshot (base64|None), blocked (bool), reason (str|None), done (bool) }
    """
    if not BROWSER_USE_AVAILABLE:
        yield {
            "action": "browser-use not installed — please rebuild the Docker image",
            "screenshot": None, "blocked": False, "reason": None, "done": True,
        }
        return

    task = _build_task(job_url, cv_profile, cover_letter, job_email, job_password, cv_path)

    yield {"action": "Browser agent starting…", "screenshot": None, "blocked": False, "reason": None, "done": False}

    browser_profile = BrowserProfile(
        headless=True,
        disable_security=True,
        enable_default_extensions=False,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--window-size=1280,800",
            "--disable-extensions",
            # Hardware / performance
            "--disable-gpu",
            "--js-flags=--max-old-space-size=512",
        ],
    )
    browser_session = BrowserSession(browser_profile=browser_profile)

    step_queue: asyncio.Queue = asyncio.Queue()

    async def on_step(browser_state, agent_output, step_number):
        screenshot = browser_state.screenshot  # already base64 JPEG
        if frame_queue is not None and screenshot:
            try:
                frame_queue.put_nowait(screenshot)
            except asyncio.QueueFull:
                pass
        goal = getattr(agent_output, "next_goal", "") or ""
        actions = getattr(agent_output, "action", None) or []
        action_str = str(goal or (actions[0] if actions else agent_output))[:120]
        await step_queue.put({
            "action": f"Step {step_number}: {action_str}",
            "screenshot": screenshot,
            "blocked": False,
            "reason": None,
            "done": False,
        })

    llm = _make_browser_llm()

    agent = Agent(
        task=task,
        llm=llm,
        browser_session=browser_session,
        register_new_step_callback=on_step,
        use_vision=False,
        available_file_paths=[cv_path] if cv_path else [],
    )
    agent_task = asyncio.create_task(agent.run())
    screenshotter_task = (
        asyncio.create_task(_cdp_screenshotter(browser_session, frame_queue))
        if frame_queue is not None else None
    )

    # Stream step events while agent runs
    while not agent_task.done():
        try:
            event = await asyncio.wait_for(step_queue.get(), timeout=1.0)
            yield event
        except asyncio.TimeoutError:
            pass

    # Stop continuous screenshotter
    if screenshotter_task:
        screenshotter_task.cancel()
        try:
            await screenshotter_task
        except asyncio.CancelledError:
            pass

    # Drain any remaining buffered events
    while not step_queue.empty():
        yield await step_queue.get()

    # Check agent result
    agent_error = None
    try:
        result = agent_task.result()
        result_str = str(result)[:200] if result else "Done"
        yield {"action": f"Agent finished: {result_str}", "screenshot": None, "blocked": False, "reason": None, "done": False}
    except Exception as e:
        agent_error = e

    # Get current Playwright page via browser_session.context
    page = None
    pw_context = None
    try:
        pw_context = getattr(browser_session, "context", None)
        if pw_context and pw_context.pages:
            page = pw_context.pages[-1]
    except Exception:
        pass

    if agent_error and page:
        screenshot = await _screenshot_b64(page)
        yield {
            "action": f"Agent encountered an issue — handing control to you ({agent_error})",
            "screenshot": screenshot or None,
            "blocked": True,
            "reason": "Take over to complete the application, then type 'submit'.",
            "done": False,
            "interactive": True,
        }
        async for step in _interactive_session(page, instruction_queue, pw_context):
            yield step
            if step.get("done"):
                try:
                    await browser_session.close()
                except Exception:
                    pass
                return
    elif agent_error:
        yield {"action": f"Browser error: {agent_error}", "screenshot": None, "blocked": False, "reason": None, "done": True}
        try:
            await browser_session.close()
        except Exception:
            pass
        return

    # Final interactive review before submit
    if page:
        screenshot = await _screenshot_b64(page)
        yield {
            "action": "Review the filled form — type 'submit' to submit or 'skip' to skip",
            "screenshot": screenshot or None,
            "blocked": True,
            "reason": "Check the form looks correct before submitting.",
            "done": False,
            "interactive": True,
        }
        async for step in _interactive_session(page, instruction_queue, pw_context):
            yield step
            if step.get("done"):
                break
    else:
        yield {"action": "Application complete", "screenshot": None, "blocked": False, "reason": None, "done": True}

    try:
        await browser_session.close()
    except Exception:
        pass
