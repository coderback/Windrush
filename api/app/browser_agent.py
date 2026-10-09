"""
Autonomous job-application filling with browser-use (pinned to 0.11.x — see requirements.txt).

Flow: the agent fills the form and STOPS before the final submit → the user reviews it in the
live view (and can take over with clicks / typing) → 'submit' has a short follow-up agent click
the final button, 'done' means the user submitted it themselves, 'skip' abandons it.

browser-use 0.11 is CDP-native (no Playwright, no LangChain): LLMs must be its own
`browser_use` Chat* wrappers, and everything here talks to Chrome through the session's CDP client.
"""
import asyncio
import base64
import json
import logging
import os
from typing import AsyncGenerator, Awaitable, Callable

logger = logging.getLogger("windrush.browser_agent")

_BACKEND = os.environ.get("LLM_BACKEND", "ollama").lower()
_OLLAMA_HOST  = os.environ.get("OLLAMA_HOST",  "http://ollama:11434")
_OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3.5:4b")

# Viewport the agent browses at. BrowserView.tsx maps clicks on the live frame onto these
# exact dimensions (BROWSER_W / BROWSER_H) — keep the two in sync.
VIEWPORT = {"width": 1280, "height": 800}

# browser-use defaults to 500 steps; cap the LLM spend per application.
_MAX_FILL_STEPS = 40
_MAX_SUBMIT_STEPS = 4

# Navigation the agent's browser must never reach: it runs inside the api container, next to
# the internal services. Raw-IP URLs are blocked separately (BrowserProfile.block_ip_addresses).
# 'http*://' because browser-use patterns without a scheme only match https.
_BLOCK_IP_ADDRESSES = True
_PROHIBITED_HOSTS = [
    f"http*://{h}" for h in (
        "localhost", "*.localhost", "host.docker.internal", "metadata.google.internal",
        # docker-compose service names (see docker-compose.yml)
        "api", "frontend", "nginx", "ollama",
    )
]

# How long the review / takeover phase waits for the user's next command. Must stay under
# nginx's proxy_read_timeout (600s) for /api/apply, which sees no bytes while we wait.
_INPUT_TIMEOUT_S = 300

try:
    from browser_use import Agent, BrowserProfile, BrowserSession
    from browser_use.actor.page import Page as _ActorPage

    BROWSER_USE_AVAILABLE = True
except ImportError:
    BROWSER_USE_AVAILABLE = False


def _make_browser_llm():
    """The browser-use chat model for the configured backend (its own wrappers, not LangChain)."""
    if _BACKEND == "groq":
        from browser_use import ChatGroq
        # Same model as the main agent. browser-use drives Groq via json_schema output, so this
        # must be a model listed in browser_use.llm.groq.chat.JsonSchemaModels (llama-4-scout is).
        return ChatGroq(
            model=os.environ.get("GROQ_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct"),
            api_key=os.environ.get("GROQ_API_KEY", ""),
        )
    if _BACKEND == "claude":
        from browser_use import ChatAnthropic
        return ChatAnthropic(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
            api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            max_tokens=4096,
            timeout=120.0,
        )
    from browser_use import ChatOllama
    return ChatOllama(model=_OLLAMA_MODEL, host=_OLLAMA_HOST)


async def _screenshot_b64(browser_session) -> str:
    """JPEG of the agent-focused tab, base64-encoded ('' if the browser isn't available)."""
    try:
        jpeg = await browser_session.take_screenshot(format="jpeg", quality=60)
        return base64.b64encode(jpeg).decode()
    except Exception:
        return ""


def _has_page(browser_session) -> bool:
    return bool(getattr(browser_session, "agent_focus_target_id", None))


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


async def _cdp_screencaster(browser_session, frame_queue: asyncio.Queue):
    """
    Stream CDP Page.screencast frames from whichever tab currently has agent focus.
    Chrome pushes JPEGs (no screenshot polling); we only poll cached session state to
    notice focus changes and move the screencast to the new tab. Mirrors browser-use's own
    RecordingWatchdog, which is inactive here because we don't enable video recording.
    """
    current: dict = {"session_id": None}
    registered = False
    ack_tasks: set[asyncio.Task] = set()

    async def _ack(frame_session_id: int, session_id: str | None):
        try:
            await browser_session.cdp_client.send.Page.screencastFrameAck(
                params={"sessionId": frame_session_id}, session_id=session_id,
            )
        except Exception:
            pass

    def on_frame(event, session_id):
        # Synchronous: the CDP reader awaits handlers inline, so the ack runs as its own task.
        if session_id == current["session_id"] and event.get("data"):
            _push_frame(frame_queue, event["data"])
        task = asyncio.create_task(_ack(event["sessionId"], session_id))
        ack_tasks.add(task)
        task.add_done_callback(ack_tasks.discard)

    try:
        while True:
            try:
                if _has_page(browser_session):
                    if not registered:
                        browser_session.cdp_client.register.Page.screencastFrame(on_frame)
                        registered = True
                    cdp_session = await browser_session.get_or_create_cdp_session(focus=False)
                    if cdp_session.session_id != current["session_id"]:
                        old = current["session_id"]
                        current["session_id"] = cdp_session.session_id
                        if old:
                            try:
                                await browser_session.cdp_client.send.Page.stopScreencast(session_id=old)
                            except Exception:
                                pass  # the old tab may already be gone
                        await cdp_session.cdp_client.send.Page.startScreencast(
                            params={"format": "jpeg", "quality": 60,
                                    "maxWidth": VIEWPORT["width"], "maxHeight": VIEWPORT["height"],
                                    "everyNthFrame": 1},
                            session_id=cdp_session.session_id,
                        )
            except Exception as exc:
                logger.debug("screencast attach failed: %s", exc)
                current["session_id"] = None  # retry on the next tick
            await asyncio.sleep(0.5)
    finally:
        if current["session_id"]:
            try:
                await browser_session.cdp_client.send.Page.stopScreencast(session_id=current["session_id"])
            except Exception:
                pass


DONE_COMMANDS = {"submit", "done", "skip", "cancel", "abort"}
# Subset of DONE_COMMANDS that mean "the application went in" (vs. abandoned).
SUBMIT_COMMANDS = {"submit", "done"}


async def _focused_page(browser_session):
    """Actor Page for the agent-focused tab, reusing its existing CDP session."""
    cdp_session = await browser_session.get_or_create_cdp_session(focus=False)
    return _ActorPage(browser_session, cdp_session.target_id, session_id=cdp_session.session_id), cdp_session


async def _run_user_command(browser_session, cmd: dict) -> None:
    """Replay one takeover input (from BrowserView.tsx) onto the focused tab via CDP."""
    page, cdp_session = await _focused_page(browser_session)
    kind = cmd.get("type", "")
    if kind == "click":
        tabs_before = len(browser_session.get_page_targets())
        await (await page.mouse).click(int(float(cmd["x"])), int(float(cmd["y"])))
        await asyncio.sleep(0.8)
        # Follow a tab the click opened (e.g. "Apply on company site").
        if len(browser_session.get_page_targets()) > tabs_before:
            new_tab = await browser_session.get_most_recently_opened_target_id()
            await browser_session.get_or_create_cdp_session(new_tab, focus=True)
    elif kind == "type":
        await _insert_text(browser_session, cdp_session, str(cmd.get("text", "")))
    elif kind == "key":
        await page.press(str(cmd.get("key", "Enter")))
        await asyncio.sleep(0.4)
    elif kind == "scroll":
        await (await page.mouse).scroll(delta_y=int(float(cmd.get("delta", 300))))
        await asyncio.sleep(0.3)


async def _insert_text(browser_session, cdp_session, text: str) -> None:
    await browser_session.cdp_client.send.Input.insertText(params={"text": text}, session_id=cdp_session.session_id)
    await asyncio.sleep(0.2)


async def _interactive_session(
    browser_session,
    instruction_queue: asyncio.Queue,
    intro_action: str,
    intro_reason: str,
    on_submit: Callable[[], Awaitable[tuple[bool, str]]],
) -> AsyncGenerator[dict, None]:
    """
    Hand control to the user until they finish. Commands (from BrowserView.tsx):
      JSON {type: click|type|key|scroll} → replayed onto the page via CDP
      'submit' → a short agent clicks the final submit button (submitted if it confirms)
      'done'   → the user submitted it themselves
      'skip' / 'cancel' / 'abort' → abandon (not submitted)
      any other text → typed into the focused field
    """
    def interactive(action: str, reason: str, screenshot: str) -> dict:
        return {"action": action, "screenshot": screenshot or None, "blocked": True,
                "reason": reason, "done": False, "interactive": True}

    yield interactive(intro_action, intro_reason, await _screenshot_b64(browser_session))
    again = "Click the screenshot or type below. 'submit' sends it, 'done' if you submitted it yourself, 'skip' cancels."

    while True:
        try:
            raw = await asyncio.wait_for(instruction_queue.get(), timeout=_INPUT_TIMEOUT_S)
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
        word = (cmd.get("type", "") if cmd else str(raw)).strip().lower()

        if word == "submit":
            yield {"action": "Submitting the application…", "screenshot": None, "blocked": False,
                   "reason": None, "done": False}
            ok, detail = await on_submit()
            if ok:
                yield {"action": f"Application submitted{': ' + detail if detail else ''}",
                       "screenshot": await _screenshot_b64(browser_session) or None,
                       "blocked": False, "reason": None, "done": True, "submitted": True}
                return
            yield interactive(
                f"Couldn't confirm the submission{': ' + detail if detail else ''}",
                "Click the submit button on the screenshot yourself, then type 'done' — or 'skip' to cancel.",
                await _screenshot_b64(browser_session),
            )
            continue

        if word in DONE_COMMANDS:
            if word in SUBMIT_COMMANDS:
                yield {"action": "Marked as submitted by you", "screenshot": None, "blocked": False,
                       "reason": None, "done": True, "submitted": True}
            else:
                yield {"action": "Cancelled by user", "screenshot": None, "blocked": False, "reason": None, "done": True}
            return

        try:
            if cmd:
                await _run_user_command(browser_session, cmd)
                label = f"Executed: {word}"
            else:
                _, cdp_session = await _focused_page(browser_session)
                await _insert_text(browser_session, cdp_session, str(raw))
                label = f"Typed: {str(raw)[:40]}"
        except Exception as exc:
            logger.warning("takeover command %r failed: %s", word, exc)
            label = f"That didn't work ({exc}) — try again"
        yield interactive(label, again, await _screenshot_b64(browser_session))


def _build_task(job_url: str, persona: dict, cover_letter: str,
                job_email: str, job_password: str, cv_path: str) -> str:
    lines = []
    if job_email:
        # The real password is never in the prompt: browser-use substitutes the placeholder at
        # input time (Agent sensitive_data, scoped to the job site — see _credential_scope).
        password_hint = " password=<secret>job_password</secret>" if job_password else ""
        lines.append(f"If asked to log in, use: email={job_email}{password_hint}")
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
    task += (
        "\n\nFill in the application completely: every required field, plus optional ones you have an answer for "
        "(leave optional fields blank if you don't). Logging in, creating an account, uploading the CV and moving "
        "between steps of a multi-page form with 'Next'/'Continue' are all fine."
        "\n\nIMPORTANT — DO NOT SUBMIT. Never click the FINAL button that sends the application "
        "(e.g. 'Submit', 'Submit application', 'Apply', 'Send application', 'Finish'). The candidate reviews the "
        "filled form and submits it themselves. As soon as the only thing left is that final submission, stop and "
        "call done with success=true, summarising what you filled and anything you were unsure about. If you cannot "
        "fill the form (blocked, missing information, page errors), call done with success=false and say why."
    )
    return task


_SUBMIT_TASK = (
    "The job application form on the current page has already been filled in and the candidate has reviewed "
    "and approved it. Click the button that submits the application (e.g. 'Submit', 'Submit application', "
    "'Apply', 'Send'). Do NOT change any field and do NOT navigate elsewhere. After clicking, check the page: "
    "call done with success=true only if it confirms the application was received/submitted; otherwise call done "
    "with success=false and quote any error or validation message shown."
)


def _browser_profile() -> "BrowserProfile":
    return BrowserProfile(
        headless=True,
        keep_alive=True,  # keep the browser after agent.run() for review / takeover / submit
        viewport=VIEWPORT,
        device_scale_factor=1,
        block_ip_addresses=_BLOCK_IP_ADDRESSES,
        prohibited_domains=_PROHIBITED_HOSTS,
        enable_default_extensions=False,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--disable-extensions",
            # Hardware / performance
            "--disable-gpu",
            "--js-flags=--max-old-space-size=512",
        ],
    )


def _credential_scope(job_url: str) -> str | None:
    """
    browser-use domain pattern the job-site password may be typed into: the job URL's host and
    its subdomains, HTTPS only. A login on a different domain (e.g. an external ATS) won't get
    the secret — the agent hands over and the user types it — which is the point: a
    prompt-injected page elsewhere can't get it typed into an attacker's form.
    """
    from urllib.parse import urlparse
    host = (urlparse(job_url).hostname or "").lower()
    host = host.removeprefix("www.")
    return f"https://*.{host}" if host else None


async def _submit_with_agent(llm, browser_session) -> tuple[bool, str]:
    """Run a tiny follow-up agent on the same (kept-alive) browser to click the final submit."""
    try:
        agent = Agent(
            task=_SUBMIT_TASK, llm=llm, browser_session=browser_session,
            use_vision=False, use_judge=False, directly_open_url=False,
        )
        history = await agent.run(max_steps=_MAX_SUBMIT_STEPS)
        return bool(history.is_successful()), (history.final_result() or "")[:200]
    except Exception as exc:
        logger.warning("submit agent failed: %s", exc)
        return False, str(exc)[:200]


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
    Async generator: the browser-use agent fills the application, then the user reviews it and
    decides whether to submit (see module docstring). Yields dicts:
      { action, screenshot (base64|None), blocked (bool), reason (str|None), done (bool),
        interactive (bool, optional), submitted (bool, only on the final done event) }
    The browser is always killed on exit — including when the client disconnects mid-run.
    """
    if not BROWSER_USE_AVAILABLE:
        yield {
            "action": "browser-use not installed — please rebuild the Docker image",
            "screenshot": None, "blocked": False, "reason": None, "done": True,
        }
        return

    task = _build_task(job_url, cv_profile, cover_letter, job_email, job_password, cv_path)

    yield {"action": "Browser agent starting…", "screenshot": None, "blocked": False, "reason": None, "done": False}

    llm = _make_browser_llm()
    browser_session = BrowserSession(browser_profile=_browser_profile())

    step_queue: asyncio.Queue = asyncio.Queue()

    async def on_step(browser_state, agent_output, step_number):
        screenshot = getattr(browser_state, "screenshot", None)  # base64; None when use_vision=False
        if frame_queue is not None and screenshot:
            _push_frame(frame_queue, screenshot)
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

    scope = _credential_scope(job_url)
    sensitive_data = {scope: {"job_password": job_password}} if (job_password and scope) else None

    agent_task: asyncio.Task | None = None
    screencast_task: asyncio.Task | None = None
    try:
        agent = Agent(
            task=task,
            llm=llm,
            browser_session=browser_session,
            register_new_step_callback=on_step,
            use_vision=False,
            available_file_paths=[cv_path] if cv_path else [],
            sensitive_data=sensitive_data,
            # The judge LLM call grades the run from the RAW step history, which browser-use does not
            # redact — e.g. an evaluate() that reads the form back carries the typed password. We
            # rely on the agent's own is_successful(), so the judge only costs a call and leaks.
            use_judge=False,
            # Open the job page before step 1. browser-use's own directly_open_url guesses the URL
            # from the task text and gives up when it sees more than one URL-like string — which a
            # persona's LinkedIn/GitHub links or a cover letter mentioning "ASP.NET" always trigger.
            initial_actions=[{"navigate": {"url": job_url, "new_tab": False}}],
        )
        agent_task = asyncio.create_task(agent.run(max_steps=_MAX_FILL_STEPS))
        if frame_queue is not None:
            screencast_task = asyncio.create_task(_cdp_screencaster(browser_session, frame_queue))

        # Stream step events while the agent fills the form
        while not agent_task.done():
            try:
                yield await asyncio.wait_for(step_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                pass
        while not step_queue.empty():
            yield step_queue.get_nowait()

        agent_error: Exception | None = None
        ready = False
        summary = ""
        try:
            history = agent_task.result()
            ready = bool(history.is_successful())  # agent's own verdict: "form filled, ready to submit"
            summary = (history.final_result() or "")[:300]
        except Exception as exc:
            agent_error = exc
            logger.warning("browser agent failed: %s", exc)

        if not _has_page(browser_session):
            yield {"action": f"Browser error: {agent_error or 'no page was opened'}", "screenshot": None,
                   "blocked": False, "reason": None, "done": True}
            return

        if agent_error:
            intro = f"The agent hit a problem — handing control to you ({agent_error})"
            reason = "Finish the form yourself, then type 'submit' (or 'done' if you submitted it), or 'skip'."
        elif ready:
            intro = "Form filled — review it before anything is sent" + (f". Agent notes: {summary}" if summary else "")
            reason = "Type 'submit' to send it, click/type to fix anything first, or 'skip' to cancel."
        else:
            intro = "The agent couldn't finish the form" + (f": {summary}" if summary else "")
            reason = "Take over by clicking/typing, then 'submit' (or 'done' if you submitted it), or 'skip'."

        async for step in _interactive_session(
            browser_session, instruction_queue, intro, reason,
            on_submit=lambda: _submit_with_agent(llm, browser_session),
        ):
            yield step
            if step.get("done"):
                return
    finally:
        # Runs on normal completion AND when the client disconnects (generator closed):
        # stop background work and kill Chromium so no browser process is leaked.
        for t in (agent_task, screencast_task):
            if t and not t.done():
                t.cancel()
                try:
                    await t
                except BaseException:
                    pass
        try:
            await browser_session.kill()
        except Exception as exc:
            logger.debug("browser kill failed: %s", exc)
