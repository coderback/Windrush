"""
Autopilot: applies to jobs from the user's feed on its own, inside the guardrails the user set.

Each run works down the feed, best match first:
  1. only forms on Greenhouse, Lever, Ashby and Workable, and each job once. LinkedIn and Indeed forbid
     automated applying, and sites that want an account per employer (Workday) are left to the user;
  2. the fit score must reach the user's threshold, and a stretch in seniority ('reach') is skipped;
  3. the tailored CV and cover letter are written and fact-checked, as on the job page;
  4. a browser nobody watches fills the form, and it is sent only if nothing needs the user: every answer
     came from the answer bank or the profile (none drafted, none left blank), no required field is empty,
     neither document claims something the profile doesn't back, and fewer than the daily limit went out
     in the last 24 hours. In practice mode nothing is sent at all.
Whatever is held back goes to the queue with its reasons; the user's answers there are saved, so the next
form that asks is clean. A sent form keeps two screenshots: the filled form, and the page after sending.
"""
import asyncio
import base64
import io
import json
import logging
import os
import re
import zipfile
from contextlib import aclosing
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from . import agent, answers, browser_agent, doc_check, doc_render, jobs_db, pdf_generator, semantic, tracker

logger = logging.getLogger("windrush.autopilot")

DEFAULTS = {"enabled": False, "live": False, "min_fit": 75, "daily_cap": 3}
MIN_FIT = (50, 100)
DAILY_CAP = (1, 10)

# Applicant tracking systems whose forms take an application without an account: host (and its subdomains).
ATS_HOSTS = {"greenhouse.io": "Greenhouse", "lever.co": "Lever", "ashbyhq.com": "Ashby", "workable.com": "Workable"}

_FEED_DEPTH = 60        # feed jobs looked at per run, best match first
_SCORE_PER_RUN = 15     # fit-scored per run (one model call per 5)
_SCORE_BATCH = 5        # what score_job_fit takes at once
_EXTRA_FILLS = 2        # forms filled per run: the daily limit plus this many, for ones that get held back
_MAX_FILLS = 8
_EVERY = timedelta(hours=6)         # scheduled runs, while autopilot is on
_TICK_S = 15 * 60
_DESCRIPTION_CHARS = 1500           # of each ad, for scoring


# ── Settings ──────────────────────────────────────────────────────────────────────────────────

def settings(user_id: str) -> dict:
    return {**DEFAULTS, **clean_settings(tracker.get_autopilot_settings(user_id), strict=False)}


def clean_settings(raw: dict, strict: bool = True) -> dict:
    """The known settings in `raw`, checked. strict: a bad value raises ValueError, else it is dropped."""
    out: dict = {}
    for name in ("enabled", "live"):
        if name in raw:
            if isinstance(raw[name], bool):
                out[name] = raw[name]
            elif strict:
                raise ValueError(f"{name} must be true or false")
    for name, (low, high) in (("min_fit", MIN_FIT), ("daily_cap", DAILY_CAP)):
        if name in raw:
            value = raw[name]
            if isinstance(value, int) and not isinstance(value, bool) and low <= value <= high:
                out[name] = value
            elif strict:
                raise ValueError(f"{name} must be a whole number from {low} to {high}")
    return out


def save_settings(user_id: str, changes: dict) -> dict:
    """Apply `changes` (validated) to the user's settings and return them all."""
    merged = {**settings(user_id), **clean_settings(changes)}
    tracker.save_autopilot_settings(user_id, merged)
    return merged


# ── Which jobs, and whether to send ───────────────────────────────────────────────────────────

def ats_of(url: str) -> str:
    """The applicant tracking system a job's form is on ('Greenhouse'…), or '' if autopilot doesn't apply there."""
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        return ""
    return next((name for domain, name in ATS_HOSTS.items() if host == domain or host.endswith("." + domain)), "")


def _listed(items: list[str], limit: int = 4) -> str:
    shown = "; ".join(f"“{item}”" for item in items[:limit])
    return shown + (f" and {len(items) - limit} more" if len(items) > limit else "")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


# A follow-up a form shows whatever was answered just before it: "If yes, ..." after a No, "If other, ..." when Other
# wasn't chosen, "If applicable, ...". Left blank, it isn't something the user still has to answer; a form that
# requires it anyway lists it among the required fields still empty, which holds the form on its own.
_IF_YES = re.compile(r"^\W*if\s+(?:yes|so)\b", re.I)
_IF_OTHER = re.compile(r"^\W*if\s+(?:other|you\s+(?:selected|chose|answered)\s+['\"“]?other)\b", re.I)
_IF_APPLICABLE = re.compile(r"^\W*if\s+applicable\b", re.I)
_OTHER = re.compile(r"^\W*other\b", re.I)


def _follow_up_applies(questions: list[dict], i: int) -> bool:
    """Whether question i, left blank, still needs the user: False for a follow-up whose condition the question
    asked just before it rules out. Unsure counts as applying."""
    text = questions[i].get("question") or ""
    if _IF_APPLICABLE.match(text):
        return False
    before = (questions[i - 1].get("answer") or "").strip() if i > 0 else None
    if _IF_YES.match(text):
        return before is None or answers._polarity(before) is not False
    if _IF_OTHER.match(text):
        return before is None or bool(_OTHER.match(before))
    return True


def hold_reasons(filled: dict, document_problems: list[str]) -> list[str]:
    """
    Why a filled form must not go out without the user, as sentences for the queue; [] when it can.
    `filled` is what the fill left behind (browser_agent._finish_unattended): {ready, error, questions, empty}.
    """
    reasons = []
    if filled.get("error"):
        reasons.append(f"The agent hit a problem: {filled['error']}"[:300])
    elif not filled.get("ready"):
        reasons.append("The agent couldn't finish the form.")
    questions = filled.get("questions") or []
    unanswered = [(i, q) for i, q in enumerate(questions) if q.get("source") == "needs_you" or not q.get("answer")]
    blank = [q["question"] for i, q in unanswered if _follow_up_applies(questions, i)]
    left_out = [q["question"] for i, q in unanswered if q["question"] not in blank]   # follow-ups that don't apply
    drafted = [q["question"] for q in questions if q["question"] not in blank and q.get("source") == "drafted"]
    # Anything else that isn't the answer bank or the profile isn't the user's own data either.
    other = [q["question"] for q in questions if q["question"] not in blank + drafted + left_out
             and (q.get("source") not in ("saved", "profile") or q.get("flags"))]
    if blank:
        reasons.append(f"{_plural(len(blank), 'question')} only you can answer: {_listed(blank)}")
    if drafted:
        reasons.append(f"{_plural(len(drafted), 'written answer')} drafted for this job that you haven't read: "
                       f"{_listed(drafted)}")
    if other:
        reasons.append(f"{_plural(len(other), 'answer')} that didn't come from your saved answers or profile: "
                       f"{_listed(other)}")
    empty = filled.get("empty") or []
    if empty:
        reasons.append(f"{_plural(len(empty), 'required field')} still empty: {_listed(empty)}")
    self_answered = filled.get("self_answered") or []
    if self_answered:
        reasons.append(f"{_plural(len(self_answered), 'answer')} the agent chose itself, not from your saved "
                       f"answers or persona: {_listed(self_answered)}")
    return reasons + list(document_problems)


def document_problems(cv: dict, letter: dict, persona: dict, job: dict, research: str = "") -> list[str]:
    """Claims in the tailored CV or cover letter that the profile doesn't back (doc_check), as sentences."""
    out = []
    for doc_type, doc, extra, name in (("cv", cv, "", "The tailored CV"),
                                       ("cover_letter", letter, research, "The cover letter")):
        findings = doc_check.check_facts(doc_type, doc, persona, job, extra)
        if findings:
            messages = list(dict.fromkeys(f["message"] for f in findings))
            out.append(f"{name} says something your profile doesn't back: " + "; ".join(messages[:3])
                       + (f" and {len(messages) - 3} more" if len(messages) > 3 else ""))
    return out


def letter_text(letter: dict) -> str:
    """The letter as the form's text box takes it (as DocEditor.tsx letterToText does)."""
    parts = [letter.get("salutation"), *(letter.get("paragraphs") or []), letter.get("signoff"),
             letter.get("candidate_name")]
    return "\n\n".join(str(p) for p in parts if p)


def _since_last_day() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


def sent_last_day(user_id: str) -> int:
    return tracker.autopilot_sent_since(user_id, _since_last_day())


# ── Screenshots ───────────────────────────────────────────────────────────────────────────────

SCREENSHOTS = ("form", "confirm")


def screenshot_path(run: dict, which: str) -> str:
    """Where a run's screenshot is kept: one per job and kind, so a retry replaces the last one."""
    folder = os.path.join(os.environ.get("APP_DATA_PATH", "/tmp"), "autopilot")
    safe = lambda text: re.sub(r"[^A-Za-z0-9_-]", "_", str(text))[:80]
    return os.path.join(folder, f"{safe(run['user_id'])}-{safe(run['job_id'])}-{which}.jpg")


def _keep_screenshot(run: dict, which: str, b64: str) -> None:
    path = screenshot_path(run, which)
    try:
        if b64:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(base64.b64decode(b64))
        elif os.path.exists(path):
            os.remove(path)   # a retry didn't get this far: don't show the last attempt's
    except Exception as exc:
        logger.warning("couldn't keep the %s screenshot: %s", which, exc)


# ── A run ─────────────────────────────────────────────────────────────────────────────────────

@dataclass
class _Run:
    started_at: str
    live: bool
    step: str = "Starting"
    job: str = ""
    tried: int = 0
    counts: dict = field(default_factory=dict)
    task: asyncio.Task | None = None


_runs: dict[str, _Run] = {}           # user id → the run in progress
_last: dict[str, dict] = {}           # user id → how the last run ended
_codes: dict[str, asyncio.Future] = {}   # run id → the code the user types in, while its form waits for one
_CODE_WAIT_S = 10 * 60                # how long a form held open for an emailed code waits for the user's


def give_code(run_id: str, code: str) -> bool:
    """Hand the code the user typed into Windrush to the form waiting for it; False when none is waiting."""
    waiting = _codes.get(run_id)
    if waiting is None or waiting.done():
        return False
    waiting.set_result(code)
    return True


class _Stop(Exception):
    """Ends one job's attempt with a reason for the user."""


def _distinct(items) -> list[str]:
    seen, out = set(), []
    for item in items or []:
        norm = " ".join(str(item or "").lower().split())
        if norm and norm not in seen:
            seen.add(norm)
            out.append(str(item).strip())
    return out


async def _feed(user_id: str, persona: dict, live: bool) -> list[dict]:
    """The feed as the user sees it by default (their locations, sponsorship needs, nothing they've already
    tracked), best match first, cut to jobs autopilot can apply to and hasn't dealt with."""
    prefs = persona.get("preferences") or {}
    core = persona.get("core_info") or {}
    vector = await semantic.get_embedding(semantic.vectorize_persona(persona), timeout=20.0)
    tracked = set(tracker.get_user_application_statuses(user_id))
    needs_sponsorship = core.get("require_sponsorship") is True
    jobs, _ = await asyncio.to_thread(
        jobs_db.get_jobs, location=_distinct(prefs.get("preferred_locations")), persona_vector=vector,
        limit=_FEED_DEPTH, exclude=tracked, sponsorship="possible" if needs_sponsorship else "any",
        marks=tracker.get_job_marks(user_id), career_stage=agent.career_stage(persona),
        needs_sponsorship=needs_sponsorship)
    tried = tracker.autopilot_tried(user_id, count_practice=not live)
    return [j for j in jobs if ats_of(j.get("url")) and str(j.get("id")) not in tried]


async def _fit_scores(jobs: list[dict], persona: dict) -> dict[str, dict]:
    """job id → score_job_fit's verdict {fit_score, level_match, reasoning…}; jobs it couldn't score are missing."""
    out: dict[str, dict] = {}
    for start in range(0, len(jobs), _SCORE_BATCH):
        batch = [{"job_id": str(j["id"]), "title": j.get("title", ""), "company": j.get("company", ""),
                  "location": j.get("location", ""), "level": j.get("level", ""),
                  "description": (j.get("description") or "")[:_DESCRIPTION_CHARS]}
                 for j in jobs[start:start + _SCORE_BATCH]]
        try:
            result = await agent.execute_tool("score_job_fit", {"jobs": batch, "persona": persona})
        except Exception as exc:
            logger.warning("autopilot: fit scoring failed: %s", exc)
            continue
        for verdict in result.get("ranked_jobs") or []:
            if isinstance(verdict, dict) and isinstance(verdict.get("fit_score"), (int, float)):
                out[str(verdict.get("job_id"))] = verdict
    return out


def _skip_reason(verdict: dict, min_fit: int) -> str:
    if verdict.get("level_match") == "reach":
        return f"A stretch in seniority for you. {verdict.get('reasoning') or ''}".strip()[:300]
    if verdict["fit_score"] < min_fit:
        return f"Fit {round(verdict['fit_score'])} is under your threshold of {min_fit}. {verdict.get('reasoning') or ''}".strip()[:300]
    return ""


def _pdf(doc_id: str) -> str:
    path = pdf_generator.get_pdf_path(doc_id) if re.fullmatch(r"[a-f0-9]{32}", doc_id or "") else ""
    return path if path and os.path.exists(path) else ""


def _earlier_documents(user_id: str, job: dict) -> dict | None:
    """The CV and cover letter the last run for this job wrote, when both PDFs are still there."""
    docs = tracker.autopilot_documents(user_id, str(job.get("id", "")))
    return docs if docs and _pdf(docs["cv_doc_id"]) and _pdf(docs["letter_doc_id"]) else None


async def _write_documents(state: _Run, job: dict, persona: dict) -> dict:
    """A tailored CV and cover letter for the job, rendered: {cv, template_id, letter, research, cv_doc_id,
    letter_doc_id}."""
    state.step = "Writing the tailored CV"
    cv_result = await agent.execute_tool("generate_tailored_cv", {"job": job, "persona": persona})
    cv, template_id = cv_result.get("cv"), cv_result.get("template_id")
    if not cv:
        raise _Stop("Couldn't write the tailored CV.")
    state.step = "Writing the cover letter"
    letter_result = await agent.execute_tool("generate_cover_letter", {"job": job, "persona": persona})
    letter = letter_result.get("letter") or {}
    if not letter.get("paragraphs"):
        raise _Stop("Couldn't write the cover letter.")
    return {"cv": cv, "template_id": template_id, "letter": letter, "research": letter_result.get("research") or "",
            "cv_doc_id": await doc_render.render_pdf("cv", cv, template_id),
            "letter_doc_id": await doc_render.render_pdf("cover_letter", letter, template_id)}


def handover_pack(user_id: str, run: dict, persona: dict) -> tuple[str, bytes]:
    """
    (file name, ZIP) for applying to the run's job yourself: its CV and cover letter under the names autopilot
    uploads them as, and a sheet with the job's link, why it was held, each question the form asked with its
    answer, and the letter as text for a form that wants it pasted. Raises LookupError when the PDFs are gone.
    """
    cv, letter = _pdf(run.get("cv_doc_id") or ""), _pdf(run.get("letter_doc_id") or "")
    if not cv or not letter:
        raise LookupError("This run's CV and cover letter aren't there any more.")
    cv_name = browser_agent.upload_name(persona, "CV")
    letter_name = browser_agent.upload_name(persona, "Cover Letter")
    plain = lambda text: " ".join(re.sub(r"[^A-Za-z0-9 .&-]+", " ", str(text or "")).split())[:60]  # noqa: E731
    company = plain(run.get("company")) or "Job"

    lines = [f"{run.get('job_title') or ''} at {run.get('company') or ''}", run.get("job_url") or "", ""]
    if run.get("reasons"):
        lines += ["Held because:", *[f"- {reason}" for reason in run["reasons"]], ""]
    lines += ["Upload:", f"- CV: {cv_name}", f"- Cover letter: {letter_name}", ""]
    if run.get("questions"):
        lines += ["The form's questions and your answers:", ""]
        for q in run["questions"]:
            lines += [f"Q: {q.get('question') or ''}", f"A: {q.get('answer') or '(left for you to answer)'}", ""]
    written = (tracker.autopilot_documents(user_id, run.get("job_id") or "") or {}).get("letter")
    if written:
        lines += ["The cover letter as text, for a form that wants it pasted:", "", letter_text(written), ""]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as pack:
        pack.write(cv, cv_name)
        pack.write(letter, letter_name)
        pack.writestr(f"{company} - answers.txt", "\n".join(lines))
    return f"Windrush - {company} - {plain(run.get('job_title')) or 'application'}.zip", buf.getvalue()


def _keep_documents(run_id: str, user_id: str, docs: dict) -> None:
    tracker.update_autopilot_run(run_id, user_id=user_id, cv_doc_id=docs["cv_doc_id"],
                                 letter_doc_id=docs["letter_doc_id"],
                                 documents={k: docs.get(k) for k in ("cv", "template_id", "letter", "research")})


async def _apply(state: _Run, user_id: str, job: dict, verdict: dict, cfg: dict, persona: dict) -> str:
    """Try one job: documents, then the form, then send or hold. Returns the run's outcome."""
    live = cfg["live"]
    # A live send uses the CV and cover letter the last run for this job wrote (the practice run the user looked
    # at), so what goes out is what they saw. Read before start_autopilot_run replaces that run; practice always
    # writes them afresh.
    earlier = _earlier_documents(user_id, job) if live else None
    run_id = tracker.start_autopilot_run(user_id, job, practice=not live, fit_score=verdict.get("fit_score"))
    if earlier:
        _keep_documents(run_id, user_id, earlier)   # at once, so a retry after a failure still has them
    run = tracker.get_autopilot_run(user_id, run_id)
    state.job = f"{job.get('title', '')} at {job.get('company', '')}"
    held: list[str] = []
    given: list[str] = []   # codes the user typed in for this form
    final: dict = {}
    questions: list[dict] = []
    try:
        job = await jobs_db.ensure_full_description(job)
        if earlier:
            state.step = "Using the CV and cover letter from the last run"
            docs = earlier
        else:
            docs = await _write_documents(state, job, persona)
            _keep_documents(run_id, user_id, docs)
        cv, letter = docs["cv"], docs["letter"]
        cv_doc_id, letter_doc_id = docs["cv_doc_id"], docs["letter_doc_id"]
        problems = document_problems(cv, letter, persona, job, docs.get("research") or "")

        text = letter_text(letter)
        answer_job = {"title": job.get("title", ""), "company": job.get("company", ""),
                      "location": job.get("location", ""), "description": job.get("description", "")}

        async def answerer(asked: list[dict]) -> list[dict]:
            return await answers.answer_questions(asked, persona, tracker.list_answers(user_id), answer_job, text)

        async def decide(filled: dict) -> bool:
            held[:] = hold_reasons(filled, problems)
            if live and not held and sent_last_day(user_id) >= cfg["daily_cap"]:
                held.append(f"Your limit of {cfg['daily_cap']} a day was reached before this one could go.")
            return live and not held

        async def ask_code(asked: str, attempt: int) -> str | None:
            # The site emailed the user a code to confirm a person is applying: the form waits, open, for them to
            # type it into Windrush (give_code). It never comes from anywhere else (see browser_agent.CodeAsker).
            again = " The last code didn't work: check it's the newest one." if attempt > 1 else ""
            tracker.update_autopilot_run(run_id, user_id=user_id, outcome="awaiting_code", reasons=[
                f"The job site emailed you a code: “{asked}”{again} Type it in here within {_CODE_WAIT_S // 60} "
                f"minutes and Windrush will enter it and send the application."[:600]])
            waiting = asyncio.get_running_loop().create_future()
            _codes[run_id] = waiting
            try:
                code = await asyncio.wait_for(waiting, _CODE_WAIT_S)
            except asyncio.TimeoutError:
                return None
            finally:
                _codes.pop(run_id, None)
            given.append(code)
            tracker.update_autopilot_run(run_id, user_id=user_id, outcome="running", reasons=[])
            return code

        state.step = "Filling in the form"
        core = persona.get("core_info") or {}
        async with aclosing(browser_agent.apply_with_browser(
            job["url"], persona, text, asyncio.Queue(), None,
            job_email=core.get("job_email", ""), job_password=tracker.get_job_password(user_id),
            cv_path=_pdf(cv_doc_id), cover_letter_path=_pdf(letter_doc_id), answerer=answerer, decide=decide,
            ask_code=ask_code if live else None,
        )) as steps:
            async for step in steps:
                if step.get("done"):
                    final = step
                    break
                state.step = str(step.get("action") or state.step)[:160]
        if "form_screenshot" not in final:
            raise _Stop(str(final.get("action") or "The browser stopped before the form was filled."))
    except _Stop as stop:
        tracker.update_autopilot_run(run_id, user_id=user_id, outcome="failed", reasons=[str(stop)[:300]])
        return "failed"
    except Exception as exc:
        logger.exception("autopilot: %s failed", state.job)
        tracker.update_autopilot_run(run_id, user_id=user_id, outcome="failed",
                                     reasons=[f"Something went wrong: {type(exc).__name__}: {exc}"[:300]])
        return "failed"

    questions = final.get("questions") or []
    _keep_screenshot(run, "form", final.get("form_screenshot") or "")
    _keep_screenshot(run, "confirm", final.get("confirm_screenshot") or "")
    if final.get("submitted"):
        outcome, reasons = "submitted", []
    elif final.get("code_asked"):
        # The site emailed the candidate a code to prove a person is applying (Catapult, on Greenhouse: "enter the
        # 8-character code to confirm you're a human"), and no code they gave got it through: nothing went.
        why = ("the code you typed in didn't take" if given else
               f"no code was typed in within {_CODE_WAIT_S // 60} minutes")
        outcome, reasons = "needs_you", [f"The job site emailed you a code to confirm a person is applying, and "
                                         f"{why}, so this wasn't sent. It says: “{final['code_asked']}” Apply on the "
                                         f"job's page with this run's handover pack."[:600]]
    elif final.get("submit_attempted"):
        detail = final.get("submit_detail") or "no confirmation shown"
        outcome, reasons = "unconfirmed", [f"The submit button was clicked, but the page didn't confirm it ({detail}). "
                                           f"Check whether it went through before applying again."[:400]]
    elif held:
        outcome, reasons = "needs_you", held
    else:
        outcome, reasons = "ready", []   # practice mode: it would have gone

    app_id = None
    if live:
        status = "Applied" if outcome == "submitted" else "Pending Review"
        tracked = {"job_id": job.get("id"), "title": job.get("title", ""), "company": job.get("company", ""),
                   "location": job.get("location", ""), "url": job.get("url", "")}
        app_id = (tracker.add_application(user_id, tracked, {}, text, {"fit_score": verdict.get("fit_score"),
                                                                       "level_match": verdict.get("level_match", "ok"),
                                                                       "skill_gaps": verdict.get("skill_gaps") or []},
                                          tailored_cv=json.dumps(cv), status=status)
                  or tracker.find_application_id(user_id, job.get("company", ""), job.get("title", "")))
        if app_id:
            note = {"submitted": "Sent by autopilot.", "unconfirmed": "Autopilot clicked submit but saw no confirmation.",
                    "needs_you": "Autopilot filled this in and held it for you."}[outcome]
            if final.get("code_asked"):
                note = "Autopilot filled this in, but the job site asked for a code it emailed you: apply on its page."
            tracker.update_status(app_id, status, note, user_id=user_id)
            tracker.set_application_questions(app_id, questions, user_id=user_id)
    reused = (f"Used the CV and cover letter from the {'practice ' if earlier['practice'] else ''}run of "
              f"{earlier['updated_at'][:10]}. " if earlier else "")
    if given and outcome == "submitted":
        reused += "Sent after you typed in the code the job site emailed you. "
    tracker.update_autopilot_run(run_id, user_id=user_id, outcome=outcome, reasons=reasons, questions=questions,
                                 notes=(reused + str(final.get("notes") or ""))[:2000], application_id=app_id)
    logger.info("autopilot: %s -> %s (%d reasons)", state.job, outcome, len(reasons))
    return outcome


async def run(user_id: str, job_id: str = "") -> dict:
    """One autopilot run for the user (or for one job, when `job_id` is given). Returns what it did."""
    cfg = settings(user_id)
    state = _runs.get(user_id) or _Run(started_at=datetime.now(timezone.utc).isoformat(), live=cfg["live"])
    tracker.mark_autopilot_run(user_id)
    persona = tracker.get_user_persona(user_id)
    counts: dict[str, int] = {}
    note = ""
    try:
        if cfg["live"] and sent_last_day(user_id) >= cfg["daily_cap"]:
            note = f"Your limit of {cfg['daily_cap']} a day is reached; nothing was tried."
            return {"note": note, "counts": counts}
        state.step = "Looking through your feed"
        if job_id:
            job = jobs_db.get_job(job_id)
            if not job or not ats_of(job.get("url")):
                note = "Autopilot can't apply to that job: its form isn't on Greenhouse, Lever, Ashby or Workable."
                return {"note": note, "counts": counts}
            if tracker.get_user_application_statuses(user_id).get(
                    ((job.get("company") or "").lower(), (job.get("title") or "").lower())) == "Applied":
                note = "You've already applied to that job."
                return {"note": note, "counts": counts}
            candidates = [job]
        else:
            candidates = (await _feed(user_id, persona, cfg["live"]))[:_SCORE_PER_RUN]
        if not candidates:
            note = "No new jobs in your feed that autopilot can apply to."
            return {"note": note, "counts": counts}

        state.step = f"Scoring the fit of {_plural(len(candidates), 'job')}"
        verdicts = await _fit_scores(candidates, persona)
        to_try = []
        for job in candidates:
            verdict = verdicts.get(str(job["id"]))
            if verdict is None:
                continue   # couldn't score it: try again next run
            # A job the user picked (a retry from the queue) is theirs to judge: only the feed's are screened.
            reason = "" if job_id else _skip_reason(verdict, cfg["min_fit"])
            if reason:
                tracker.start_autopilot_run(user_id, job, "skipped", fit_score=verdict["fit_score"], reasons=[reason])
                counts["skipped"] = counts.get("skipped", 0) + 1
            else:
                to_try.append((job, verdict))
        to_try.sort(key=lambda pair: pair[1]["fit_score"], reverse=True)

        for job, verdict in to_try[:min(cfg["daily_cap"] + _EXTRA_FILLS, _MAX_FILLS)]:
            if cfg["live"] and sent_last_day(user_id) >= cfg["daily_cap"]:
                note = f"Stopped at your limit of {cfg['daily_cap']} a day."
                break
            outcome = await _apply(state, user_id, job, verdict, cfg, persona)
            counts[outcome] = counts.get(outcome, 0) + 1
            state.tried += 1
        return {"note": note, "counts": counts}
    finally:
        _last[user_id] = {"finished_at": datetime.now(timezone.utc).isoformat(), "live": cfg["live"],
                          "counts": counts, "note": note}


def start(user_id: str, job_id: str = "") -> bool:
    """Start a run in the background; False if one is already going for this user."""
    if user_id in _runs:
        return False
    state = _Run(started_at=datetime.now(timezone.utc).isoformat(), live=settings(user_id)["live"])
    _runs[user_id] = state

    async def go():
        try:
            await run(user_id, job_id)
        except Exception:
            logger.exception("autopilot run failed")
        finally:
            _runs.pop(user_id, None)

    state.task = asyncio.create_task(go())
    return True


def status(user_id: str) -> dict:
    cfg = settings(user_id)
    state = _runs.get(user_id)
    last_run_at = next((last for uid, _, last in tracker.autopilot_schedules() if uid == user_id), None)
    next_run_at = None
    if cfg["enabled"] and not state:
        last = _parse(last_run_at)
        next_run_at = (last + _EVERY).isoformat() if last else datetime.now(timezone.utc).isoformat()
    return {
        "settings": cfg,
        "running": bool(state),
        "step": state.step if state else "",
        "job": state.job if state else "",
        "started_at": state.started_at if state else None,
        "sent_last_day": sent_last_day(user_id),
        "last_run_at": last_run_at,
        "next_run_at": next_run_at,
        "last": _last.get(user_id),
    }


def _parse(stamp: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(stamp) if stamp else None
    except ValueError:
        return None


async def keep_running() -> None:
    """Scheduled runs: every user with autopilot on gets a run every few hours."""
    tracker.finish_stale_autopilot_runs()
    while True:
        await asyncio.sleep(_TICK_S)
        try:
            now = datetime.now(timezone.utc)
            for user_id, raw, last_run_at in tracker.autopilot_schedules():
                if not {**DEFAULTS, **clean_settings(raw, strict=False)}["enabled"]:
                    continue
                last = _parse(last_run_at)
                if last is None or now - last >= _EVERY:
                    start(user_id)
        except Exception:
            logger.exception("autopilot scheduler tick failed")
