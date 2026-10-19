import asyncio
import json
import logging
import os
import pathlib
import re
import uuid
from contextlib import aclosing, asynccontextmanager
from typing import Optional, Annotated

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.security import OAuth2PasswordRequestForm

from .cv_parser import extract_text, extract_links, profile_links
from .agent import run_apply, execute_tool, career_stage
from .guardrails import check_cv_for_injection, GuardrailViolation
from . import tracker
from . import answers
from . import autopilot
from . import gmail
from . import enrich
from . import auth
from . import pdf_generator
from . import doc_render
from . import doc_check
from . import jobs_db
from . import net_guard
from . import seniority
from . import sponsor_register
from . import job_attributes
from .models import Persona
from .profile_merge import merge_cv as _merge_cv, _split_cv_dates  # noqa: F401  (tests use _split_cv_dates)

logger = logging.getLogger("windrush.main")


class _HideOAuthCode(logging.Filter):
    """Google's redirect back to /gmail/callback carries a one-time code (and the state): keep them out of the
    access log."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and any(isinstance(a, str) and "/gmail/callback" in a for a in record.args):
            record.args = tuple(re.sub(r"\b(code|state)=[^&\s]+", r"\1=<hidden>", a) if isinstance(a, str) else a
                                for a in record.args)
        return True


logging.getLogger("uvicorn.access").addFilter(_HideOAuthCode())


@asynccontextmanager
async def lifespan(app: FastAPI):
    import os
    # Ensure app-level INFO/WARNING logs reach container stdout. Uvicorn configures
    # its own loggers but leaves the root logger without a handler, so without this
    # our "windrush.*" diagnostics would be filtered out (lastResort = WARNING-only).
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    data_dir = os.environ.get("APP_DATA_PATH", "/tmp")
    tracker.init_db()
    jobs_db.init_db()
    pdf_generator.init_pdf_dir(data_dir)
    from . import discovery
    background = [asyncio.create_task(sponsor_register.keep_fresh()),
                  asyncio.create_task(job_attributes.keep_extracting()),
                  asyncio.create_task(discovery.keep_collecting()),
                  asyncio.create_task(autopilot.keep_running()),
                  asyncio.create_task(gmail.keep_syncing())]
    yield
    for task in background:
        task.cancel()
    discovery.shutdown()


app = FastAPI(title="Windrush API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Live browser-apply sessions
_browser_queues: dict[str, asyncio.Queue] = {}   # session_id → instruction queue
_browser_frames: dict[str, asyncio.Queue] = {}   # session_id → CDP screencast frame queue


def _original_cv_path(user_id: str) -> pathlib.Path:
    """The user's most recently uploaded CV — one file per user, overwritten on re-upload."""
    return pathlib.Path(os.environ.get("APP_DATA_PATH", "/tmp")) / "cvs" / f"{user_id}.pdf"


def _stored_pdf(doc_id: str) -> str:
    """Path of a stored PDF document, or "" for an id that isn't one (ids are 32 hex characters)."""
    path = pdf_generator.get_pdf_path(doc_id) if re.fullmatch(r"[a-f0-9]{32}", doc_id or "") else ""
    return path if path and os.path.exists(path) else ""


async def _cover_letter_pdf(text: str, doc_json: str, doc_id: str, template_id: str, metadata: dict) -> str:
    """
    A PDF of the cover letter, for forms that take it as a file: the one the user saved, else the
    letter document rendered now, else its plain text. "" when there's no letter or it can't be
    rendered; the agent can still paste the text into a box.
    """
    if saved := _stored_pdf(doc_id):
        return saved
    try:
        doc = json.loads(doc_json) if doc_json else None
        if isinstance(doc, dict) and doc.get("paragraphs"):
            new_id = await doc_render.render_pdf("cover_letter", doc, template_id or None)
        elif text.strip():
            new_id = await asyncio.to_thread(pdf_generator.generate_pdf, "cover_letter", text, metadata)
        else:
            return ""
        return _stored_pdf(new_id)
    except Exception as exc:
        logger.warning("cover letter PDF for /apply failed: %s", exc)
        return ""


# ── Auth Endpoints ────────────────────────────────────────────────────────────

@app.post("/signup")
async def signup(email: str = Form(...), password: str = Form(...)):
    existing = tracker.get_user_by_email(email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed = auth.get_password_hash(password)
    user_id = tracker.create_user(email, hashed)
    return {"message": "User created", "user_id": user_id}


@app.post("/login", response_model=auth.Token)
async def login(form_data: Annotated[OAuth2PasswordRequestForm, Depends()]):
    user = tracker.get_user_by_email(form_data.username)
    if not user or not auth.verify_password(form_data.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token = auth.create_access_token(
        data={"sub": user["email"], "user_id": user["id"]}
    )
    return {"access_token": access_token, "token_type": "bearer"}


# ── Persona Endpoints ─────────────────────────────────────────────────────────

# The job-site password is stored encrypted outside the persona and never sent back to the
# browser. GET returns this placeholder when one is saved; PUT treats it as "keep as-is",
# '' as "clear", and anything else as a new password.
JOB_PASSWORD_MASK = "••••••••"


@app.get("/persona", response_model=Persona)
async def get_persona(current_user: Annotated[auth.User, Depends(auth.get_current_user)]):
    persona = Persona(**tracker.get_user_persona(current_user.id))
    persona.core_info.job_password = JOB_PASSWORD_MASK if tracker.has_job_password(current_user.id) else ""
    return persona


@app.put("/persona")
async def update_persona(
    persona: Persona,
    current_user: Annotated[auth.User, Depends(auth.get_current_user)],
):
    password = persona.core_info.job_password
    if password != JOB_PASSWORD_MASK:
        tracker.set_job_password(current_user.id, password)
    persona.core_info.job_password = ""
    ok = tracker.update_user_persona(current_user.id, persona.model_dump())
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update persona")
    return {"message": "Persona updated"}


@app.get("/persona/export")
async def export_persona(
    current_user: Annotated[auth.User, Depends(auth.get_current_user)],
    format: str = Query("json", pattern="^(json|md|pdf)$"),
):
    """Download the user's persona twin as JSON, Markdown, or a formatted CV PDF."""
    from fastapi.responses import JSONResponse, Response
    from .persona_export import persona_to_markdown
    from .agent import _persona_to_cvdoc

    persona = tracker.get_user_persona(current_user.id)

    if format == "json":
        return JSONResponse(
            content=persona,
            headers={"Content-Disposition": 'attachment; filename="windrush_persona.json"'},
        )

    if format == "md":
        return Response(
            content=persona_to_markdown(persona),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="windrush_persona.md"'},
        )

    # format == "pdf" — render the persona through the existing CV pipeline.
    cvdoc = _persona_to_cvdoc(persona)
    try:
        doc_id = await doc_render.render_pdf("cv", cvdoc, "classic")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF render failed: {exc}")
    path = pdf_generator.get_pdf_path(doc_id)
    return FileResponse(
        path,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="windrush_persona.pdf"'},
    )


# ── Protected Endpoints ───────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/upload")
async def upload_cv(
    file: UploadFile = File(...),
    current_user: Annotated[auth.User, Depends(auth.get_current_user)] = None,
):
    """Parse a CV PDF, merge what it contains into the Persona, and keep the PDF for applications."""
    pdf_bytes = await file.read()
    try:
        cv_text = extract_text(pdf_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    links = extract_links(pdf_bytes)
    if links:
        # A clickable link's target is in no page text; the model needs it for profile and project URLs.
        cv_text += "\n\nLinks in this CV (anchor text -> URL):\n" + "\n".join(
            f"- {anchor or '(no text)'} -> {url}" for anchor, url in links)

    try:
        check_cv_for_injection(cv_text)
    except GuardrailViolation as e:
        raise HTTPException(status_code=422, detail=f"GUARDRAIL: {e.detail}")

    cv_data = await execute_tool("extract_cv_profile", {"cv_text": cv_text})
    # LinkedIn and GitHub profile addresses are unambiguous: take them from the links themselves.
    cv_data.update(profile_links(links))

    persona = Persona(**tracker.get_user_persona(current_user.id))
    _merge_cv(persona, cv_data)
    tracker.update_user_persona(current_user.id, persona.model_dump())

    # Keep the original PDF so the apply flow can upload it when no tailored CV is chosen.
    cv_file = _original_cv_path(current_user.id)
    cv_file.parent.mkdir(parents=True, exist_ok=True)
    cv_file.write_bytes(pdf_bytes)

    return {"persona": persona}


@app.post("/apply")
async def apply(
    job_id: str = Form(...),
    job_url: str = Form(default=""),
    cover_letter: str = Form(default=""),
    cv_profile: str = Form(default="{}"),
    skill_risks: str = Form(default="[]"),
    job_email: str = Form(default=""),
    job_password: str = Form(default=""),
    tailored_cv: str = Form(default=""),
    cv_doc_id: str = Form(default=""),
    cover_letter_doc: str = Form(default=""),
    letter_doc_id: str = Form(default=""),
    template_id: str = Form(default=""),
    job_title: str = Form(default=""),
    company: str = Form(default=""),
    location: str = Form(default=""),
    job_description: str = Form(default=""),
    composite_score: float = Form(default=0.0),
    exposure_score: float = Form(default=0.5),
    fit_score: float = Form(default=0.0),
    level_match: str = Form(default="ok"),
    skill_gaps: str = Form(default="[]"),
    current_user: Annotated[auth.User, Depends(auth.get_current_user)] = None,
):
    try:
        profile = json.loads(cv_profile)
    except json.JSONDecodeError:
        profile = {}
    try:
        risks = json.loads(skill_risks)
    except json.JSONDecodeError:
        risks = []
    try:
        gaps = json.loads(skill_gaps)
    except json.JSONDecodeError:
        gaps = []

    # The browser agent navigates here from inside our network — refuse internal targets.
    if job_url:
        try:
            await net_guard.assert_public_url(job_url)
        except net_guard.UnsafeURLError as exc:
            raise HTTPException(status_code=400, detail=f"Job URL not allowed: {exc}")

    # Fall back to persona credentials if not provided in form
    persona = tracker.get_user_persona(current_user.id)
    core = persona.get("core_info", {})
    effective_email = job_email or core.get("job_email", "")
    effective_password = job_password or tracker.get_job_password(current_user.id)

    # Tailored CV PDF (if the user chose it) takes precedence over their uploaded original.
    original_cv = _original_cv_path(current_user.id)
    cv_path = _stored_pdf(cv_doc_id) or (str(original_cv) if original_cv.exists() else "")
    letter_path = await _cover_letter_pdf(cover_letter, cover_letter_doc, letter_doc_id, template_id,
                                          {"job_title": job_title, "company": company})
    session_id = str(uuid.uuid4())

    job_dict = {
        "job_id": job_id,
        "title": job_title,
        "company": company,
        "location": location,
        "url": job_url,
    }
    score_data = {
        "composite_score": composite_score,
        "exposure_score": exposure_score,
        "fit_score": fit_score,
        "skill_gaps": gaps,
        "level_match": level_match,
    }
    app_id = tracker.add_application(
        current_user.id, job_dict, profile, cover_letter, score_data, tailored_cv=tailored_cv
    ) or tracker.find_application_id(current_user.id, company, job_title)  # already saved/tracked

    q: asyncio.Queue = asyncio.Queue()
    fq: asyncio.Queue = asyncio.Queue(maxsize=8)
    _browser_queues[session_id] = q
    _browser_frames[session_id] = fq

    # The form's questions are answered from the answer bank as it stands when each page is reached.
    answer_job = {"title": job_title, "company": company, "location": location, "description": job_description}

    async def answerer(questions: list[dict]) -> list[dict]:
        return await answers.answer_questions(questions, persona, tracker.list_answers(current_user.id),
                                              answer_job, cover_letter)

    async def cleanup_gen():
        user_confirmed = False
        try:
            # aclosing: if the client disconnects, close run_apply (and the browser beneath it) now
            async with aclosing(run_apply(
                current_user.id, job_id, job_url, cover_letter, risks, session_id, q, fq,
                job_email=effective_email, job_password=effective_password, cv_path=cv_path,
                cover_letter_path=letter_path, answerer=answerer,
            )) as chunks:
                async for chunk in chunks:
                    try:
                        payload = json.loads(chunk.removeprefix("data: ").strip())
                        if payload.get("type") == "done" and payload.get("submitted") is True:
                            user_confirmed = True
                        if app_id and payload.get("questions"):
                            tracker.set_application_questions(app_id, payload["questions"], user_id=current_user.id)
                    except Exception:
                        pass
                    yield chunk
        finally:
            _browser_queues.pop(session_id, None)
            _browser_frames.pop(session_id, None)
            if app_id and user_confirmed:
                tracker.update_status(app_id, "Applied", user_id=current_user.id)

    return StreamingResponse(
        cleanup_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/browser-input/{session_id}")
async def browser_input(
    session_id: str,
    body: dict,
    current_user: Annotated[auth.User, Depends(auth.get_current_user)],
):
    """Relay a user instruction into the running browser session."""
    q = _browser_queues.get(session_id)
    if q is None:
        raise HTTPException(status_code=404, detail="Session not found or already complete")
    await q.put(body.get("instruction", ""))
    return {"queued": True}


@app.get("/browser-stream/{session_id}")
async def browser_stream(session_id: str):
    """SSE stream of live CDP screencast JPEG frames."""
    # Note: Browser stream is often called by <img> tags or similar which don't easily send auth headers.
    # In a real app we might use a short-lived session token in the URL.
    async def gen():
        while True:
            fq = _browser_frames.get(session_id)
            if fq is None:
                yield f"data: {json.dumps({'type': 'close'})}\n\n"
                return
            try:
                frame = await asyncio.wait_for(fq.get(), timeout=5.0)
                yield f"data: {json.dumps({'frame': frame})}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── Application Tracker endpoints ─────────────────────────────────────────────

@app.get("/applications")
async def list_applications(
    status: Optional[str] = Query(default=None),
    current_user: Annotated[auth.User, Depends(auth.get_current_user)] = None,
):
    return tracker.list_applications(current_user.id, status)


@app.post("/applications")
async def create_application(
    body: dict,
    current_user: Annotated[auth.User, Depends(auth.get_current_user)],
):
    job = body.get("job", {})
    cv_profile = body.get("cv_profile", {})
    cover_letter = body.get("cover_letter", "")
    score_data = body.get("score_data", {})
    app_id = tracker.add_application(current_user.id, job, cv_profile, cover_letter, score_data)
    if app_id:
        return {"id": app_id, "status": "created"}
    return {"status": "duplicate", "message": "An application for this role already exists."}


@app.patch("/applications/{app_id}/status")
async def update_application_status(
    app_id: str,
    body: dict,
    current_user: Annotated[auth.User, Depends(auth.get_current_user)],
):
    status = body.get("status", "")
    notes = body.get("notes")
    if status not in tracker.VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status!r}")
    if not tracker.update_status(app_id, status, notes, user_id=current_user.id):
        # Unknown id, or another user's application — indistinguishable to the caller by design.
        raise HTTPException(status_code=404, detail="Application not found")
    return {"id": app_id, "status": status, "updated": True}


@app.post("/jobs/save")
async def save_job(
    body: dict,
    current_user: Annotated[auth.User, Depends(auth.get_current_user)],
):
    """Bookmark a job for later by adding it to the tracker with 'Saved' status."""
    job = body.get("job", {})
    if not job:
        raise HTTPException(status_code=400, detail="Job data is required")
    
    # We use empty defaults for profile/scores since the job hasn't been analysed yet
    app_id = tracker.add_application(
        user_id=current_user.id,
        job=job,
        cv_profile={},
        cover_letter="",
        score_data={
            "composite_score": 0.0,
            "exposure_score": 0.5,
            "fit_score": 0.0,
            "skill_gaps": [],
            "level_match": "ok"
        },
        status="Saved"
    )
    
    if app_id:
        return {"id": app_id, "status": "Saved"}
    return {"status": "duplicate", "message": "This job is already in your tracker."}


# ── Onboarding ────────────────────────────────────────────────────────────────

@app.get("/onboarding/status")
async def onboarding_status(current_user: Annotated[auth.User, Depends(auth.get_current_user)]):
    return {"complete": tracker.get_onboarding_status(current_user.id)}


@app.post("/onboarding/complete")
async def onboarding_complete(current_user: Annotated[auth.User, Depends(auth.get_current_user)]):
    tracker.set_onboarding_complete(current_user.id)
    return {"complete": True}


# ── Job Feed ──────────────────────────────────────────────────────────────────

from . import semantic
from . import discovery

# Live discovery kicks in (in the background) when page 1 has fewer matches than this.
_THIN_FEED = 5
# It runs once per top target title, each run covering their first few preferred locations;
# capped because each run is a full multi-source search in the worker pool.
_DISCOVERY_TITLES = 3
# Each location is two Adzuna calls per title (plain and in its graduate category; a UK city isn't
# searched when the UK is), made two at a time to stay under Adzuna's ~25 calls/minute.
_DISCOVERY_LOCATIONS = 4
# Request-path embedding budget: past this the feed falls back to recency ranking rather than
# making the user wait on Ollama loading the model (background work still allows 600s).
_FEED_EMBED_TIMEOUT_S = 20.0
# Tracker statuses that hide a job from the feed.
_HIDE_STATUSES = {"Applied", "Responded", "Interview", "Offer", "Rejected", "Discarded"}


def _distinct(items) -> list[str]:
    """Stripped, non-empty items without case/whitespace duplicates (first spelling kept). The
    profile stores raw comma-split text, e.g. "London, london , LONDON"."""
    seen, out = set(), []
    for item in items or []:
        item = (item or "").strip()
        norm = " ".join(item.lower().split())
        if norm and norm not in seen:
            seen.add(norm)
            out.append(item)
    return out


@app.get("/jobs")
async def get_jobs(
    query: str = Query(default=""),
    location: str = Query(default=""),
    level: str = Query(default=""),
    category: str = Query(default=""),
    remote: bool = Query(default=False),
    tags: str = Query(default=""),
    sponsorship: str = Query(default=""),
    max_years: Optional[int] = Query(default=None, ge=0, le=40),
    no_degree: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: Annotated[auth.User, Depends(auth.get_current_user)] = None,
):
    """
    Job feed. Explicit filters (query, tags, category, level, location, remote, sponsorship,
    max_years, no_degree) are applied in SQL; the persona only *ranks* (semantic similarity) and
    supplies a default location and sponsorship filter. If page 1 comes back thin, live discovery
    starts in the background and `discovering` tells the client to re-poll — the request itself
    never waits on scraping or embedding.
    """
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    persona_data = tracker.get_user_persona(current_user.id)
    prefs = persona_data.get("preferences", {}) or {}
    titles = _distinct(prefs.get("target_titles"))
    locs = _distinct(prefs.get("preferred_locations"))
    # An explicit filter wins; otherwise any of the user's preferred locations matches.
    effective_location = location or locs

    # "Interest-weighted" ranking vector: who you are (persona) + what you're searching for now.
    persona_text = semantic.vectorize_persona(persona_data)
    intent_parts = ([query] if query else []) + tag_list
    if intent_parts:
        intent_str = ", ".join(intent_parts)
        persona_text = f"Current user interest: {intent_str}. Specific focus: {intent_str}. {persona_text}"
    persona_vector = await semantic.get_embedding(persona_text, timeout=_FEED_EMBED_TIMEOUT_S)

    status_map = tracker.get_user_application_statuses(current_user.id)
    hidden = {key for key, status in status_map.items() if status in _HIDE_STATUSES}
    # Someone who needs a visa sponsored doesn't see jobs that rule them out unless they ask to.
    needs_sponsorship = (persona_data.get("core_info") or {}).get("require_sponsorship") is True
    if sponsorship not in jobs_db.SPONSORSHIP_FILTERS:
        sponsorship = "possible" if needs_sponsorship else "any"
    marks = tracker.get_job_marks(current_user.id)

    jobs, has_more = await asyncio.to_thread(
        jobs_db.get_jobs,
        query=query, location=effective_location, level=level, category=category, remote=remote,
        tags=tag_list, persona_vector=persona_vector, limit=limit, offset=(page - 1) * limit,
        exclude=hidden, sponsorship=sponsorship, marks=marks, max_years=max_years, no_degree=no_degree,
        career_stage=career_stage(persona_data), needs_sponsorship=needs_sponsorship,
    )
    for job in jobs:
        status = status_map.get(((job.get("company") or "").lower(), (job.get("title") or "").lower()))
        if status:
            job["tracker_status"] = status
        job["sponsorship_mark"] = marks.get(job["id"], "")

    # Page 1 also says how many match, what the sponsorship filter and the jobs already dealt with hide,
    # and when the feed was last refreshed, so a thin feed explains itself.
    summary = {}
    if page == 1:
        filters = dict(query=query, location=effective_location, level=level, category=category, remote=remote,
                       tags=tag_list, marks=marks, max_years=max_years, no_degree=no_degree)
        total = await asyncio.to_thread(jobs_db.count_jobs, exclude=hidden, sponsorship=sponsorship, **filters)
        by_sponsorship = (await asyncio.to_thread(jobs_db.count_jobs, exclude=hidden, sponsorship="any", **filters)
                          if sponsorship != "any" else total)
        with_dealt = await asyncio.to_thread(jobs_db.count_jobs, exclude=None, sponsorship=sponsorship, **filters)
        summary = {
            "total": total,
            "hidden": {"sponsorship": by_sponsorship - total, "dealt_with": with_dealt - total},
            "collection": await asyncio.to_thread(discovery.collection_status),
        }

    discovering = discovery.collecting()
    if page == 1 and len(jobs) < _THIN_FEED:
        free_text = [t for t in tag_list if t.lower() not in jobs_db.ROLE_TAGS | jobs_db.DOMAIN_TAGS]
        live_queries = [query] if query else free_text[:1] or titles[:_DISCOVERY_TITLES] or ["software engineer"]
        live_locations = ([location] if location else
                          [l for l in locs if l.lower() != "remote"][:_DISCOVERY_LOCATIONS] or ["London"])
        # One run per title over its locations not already in flight or in cooldown. ensure() is
        # cheap for those; evaluate every title.
        discovering = any([discovery.ensure(q, live_locations) for q in live_queries
                           if len(q) > 2]) or discovering  # don't fire on a stray character

    return {
        "jobs": jobs,
        "query": query,
        "location": location or ", ".join(locs),
        "page": page,
        "limit": limit,
        "has_more": has_more,
        "discovering": discovering,
        "sponsorship": sponsorship,
        **summary,
    }


@app.post("/jobs/refresh")
async def refresh_jobs(current_user: Annotated[auth.User, Depends(auth.get_current_user)]):
    """The feed's Refresh button: start a collection now (see discovery.refresh_now). 429 when it can't
    start yet, with why."""
    started, detail = await discovery.refresh_now()
    if not started and not discovery.collecting():
        raise HTTPException(status_code=429, detail=detail)
    return {"started": started, "detail": detail,
            "collection": await asyncio.to_thread(discovery.collection_status)}


def _sponsorship_view(job: dict, mark: str) -> dict:
    return {
        "sponsorship": job.get("sponsorship") or "",
        "evidence": job.get("sponsorship_evidence") or "",
        "clearance": job.get("clearance") or "",
        "licensed_sponsor": bool(job.get("licensed_sponsor")),
        "sponsor_name": job.get("sponsor_name") or "",
        "mark": mark,
    }


@app.get("/jobs/{job_db_id}/sponsorship")
async def get_job_sponsorship(
    job_db_id: str,
    current_user: Annotated[auth.User, Depends(auth.get_current_user)],
):
    """What the ad says about sponsorship and clearance, whether the employer is a licensed sponsor,
    and the user's own mark (which wins)."""
    job = await asyncio.to_thread(jobs_db.get_job, job_db_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _sponsorship_view(job, tracker.get_job_marks(current_user.id).get(job_db_id, ""))


@app.put("/jobs/{job_db_id}/sponsorship")
async def mark_job_sponsorship(
    job_db_id: str,
    body: dict,
    current_user: Annotated[auth.User, Depends(auth.get_current_user)],
):
    """Mark a job as sponsoring ("offered") or not ("not_offered"), or clear the mark (null)."""
    mark = body.get("mark")
    if mark not in (*tracker.JOB_MARKS, None, ""):
        raise HTTPException(status_code=422, detail=f"mark must be one of {tracker.JOB_MARKS} or null")
    job = await asyncio.to_thread(jobs_db.get_job, job_db_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    tracker.set_job_mark(current_user.id, job_db_id, mark or None)
    return _sponsorship_view(job, mark or "")


# ── Per-job agent endpoints (SSE) ─────────────────────────────────────────────

def _sse_json(event_type: str, data: dict) -> str:
    import time
    payload = {"type": event_type, "timestamp": time.time(), **data}
    return f"data: {json.dumps(payload)}\n\n"


@app.post("/jobs/from-url")
async def job_from_url(
    body: dict,
    current_user: Annotated[auth.User, Depends(auth.get_current_user)],
):
    """
    Scrape a user-pasted job-posting URL into a full Job object for analysis.

    The job is returned (not persisted) — the frontend keeps it in sessionStorage
    and runs the normal detail-page flow; it only enters the DB if the user Saves.
    """
    from .job_searcher import scrape_job_from_url

    url = (body.get("url") or "").strip()
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Please paste a valid http(s) link.")
    try:
        job = await scrape_job_from_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not fetch that listing: {exc}")

    job["level"] = seniority.infer_level(job.get("title", ""), job.get("description", ""))
    job["tags"] = jobs_db._extract_tags(job)
    return {"job": job}


@app.post("/jobs/analyze")
async def analyze_job(
    body: dict,
    current_user: Annotated[auth.User, Depends(auth.get_current_user)],
):
    """SSE: score fit + AI risk for a single job against the user's persona."""
    job = await jobs_db.ensure_full_description(body.get("job", {}))
    persona = tracker.get_user_persona(current_user.id)

    async def gen():
        yield _sse_json("start", {"message": "Analysing job…"})

        # Score AI risk for persona skills
        all_skills: list[str] = []
        for cat in persona.get("skills", []):
            all_skills.extend(cat.get("skills", []))
        for exp in persona.get("history", []):
            title = exp.get("title", "")
            if title:
                all_skills.append(title)
        if all_skills:
            risk_result = await execute_tool("score_ai_risk", {"skills": list(set(all_skills))})
            yield _sse_json("skill_risks", risk_result)

        # Score job fit
        fit_result = await execute_tool("score_job_fit", {"jobs": [job], "persona": persona})
        yield _sse_json("job_fit", fit_result)
        yield _sse_json("done", {"message": "Analysis complete"})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/jobs/cover-letter")
async def generate_cover_letter_endpoint(
    body: dict,
    current_user: Annotated[auth.User, Depends(auth.get_current_user)],
):
    """SSE: generate a tailored cover letter for a job."""
    job = await jobs_db.ensure_full_description(body.get("job", {}))
    tone = body.get("tone", "professional")
    persona = tracker.get_user_persona(current_user.id)

    async def gen():
        yield _sse_json("start", {"message": "Writing cover letter…"})
        result = await execute_tool("generate_cover_letter", {"job": job, "persona": persona, "tone": tone})
        yield _sse_json("cover_letter", result)
        yield _sse_json("done", {"message": "Cover letter ready"})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/jobs/tailored-cv")
async def generate_tailored_cv_endpoint(
    body: dict,
    current_user: Annotated[auth.User, Depends(auth.get_current_user)],
):
    """SSE: generate a tailored CV (Markdown) for a specific job."""
    job = await jobs_db.ensure_full_description(body.get("job", {}))
    persona = tracker.get_user_persona(current_user.id)

    async def gen():
        yield _sse_json("start", {"message": "Tailoring your CV…"})
        result = await execute_tool("generate_tailored_cv", {"job": job, "persona": persona})
        yield _sse_json("tailored_cv", result)
        yield _sse_json("done", {"message": "CV ready"})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Careers ───────────────────────────────────────────────────────────────────

@app.post("/score-skills")
async def score_skills(
    current_user: Annotated[auth.User, Depends(auth.get_current_user)],
):
    """Non-streaming: score AI risk for all skills in the user's persona."""
    persona = tracker.get_user_persona(current_user.id)
    all_skills: list[str] = []
    for cat in persona.get("skills", []):
        all_skills.extend(cat.get("skills", []))
    for exp in persona.get("history", []):
        title = exp.get("title", "")
        if title:
            all_skills.append(title)
    if not all_skills:
        return {"skill_risks": []}
    result = await execute_tool("score_ai_risk", {"skills": list(set(all_skills))})
    return result


@app.post("/careers/roadmap")
async def careers_roadmap(  # noqa: E302
    current_user: Annotated[auth.User, Depends(auth.get_current_user)],
):
    """SSE: generate a skill development roadmap from the user's persona."""
    persona = tracker.get_user_persona(current_user.id)
    all_skills: list[str] = []
    for cat in persona.get("skills", []):
        all_skills.extend(cat.get("skills", []))

    async def gen():
        yield _sse_json("start", {"message": "Building your skill roadmap…"})
        risk_result = await execute_tool("score_ai_risk", {"skills": list(set(all_skills)) or ["software engineering"]})
        skill_risks = risk_result.get("skill_risks", [])
        result = await execute_tool("generate_skill_roadmap", {"skill_risks": skill_risks, "persona": persona})
        yield _sse_json("roadmap", result)
        yield _sse_json("done", {"message": "Roadmap ready"})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Document / PDF export ─────────────────────────────────────────────────────

@app.post("/documents/pdf")
async def create_pdf(
    body: dict,
    current_user: Annotated[auth.User, Depends(auth.get_current_user)],
):
    """
    Generate a PDF for a document.

    Preferred: a structured ``doc`` (CVDoc/LetterDoc) rendered via the HTML template
    → WeasyPrint. Legacy: raw ``text`` rendered via fpdf2 (kept for back-compat).
    """
    doc_type = body.get("type", "cv")
    doc = body.get("doc")
    template_id = body.get("template_id", "classic")
    metadata = body.get("metadata", {})

    try:
        if doc is not None:
            doc_id = await doc_render.render_pdf(doc_type, doc, template_id)
        else:
            text = body.get("text", "")
            if not text:
                raise HTTPException(status_code=400, detail="doc or text is required")
            doc_id = pdf_generator.generate_pdf(doc_type, text, metadata)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"doc_id": doc_id, "download_url": f"/api/documents/{doc_id}/download"}


@app.post("/documents/preview")
async def preview_document(
    body: dict,
    current_user: Annotated[auth.User, Depends(auth.get_current_user)],
):
    """Render a structured document to HTML for the live in-app preview (iframe)."""
    doc_type = body.get("type", "cv")
    doc = body.get("doc", {})
    template_id = body.get("template_id", "classic")
    try:
        # A worker thread: fitting a CV to its page count lays it out in WeasyPrint.
        html = await asyncio.to_thread(doc_render.render_html, doc_type, doc, template_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"html": html}


@app.post("/documents/check")
async def check_document(
    body: dict,
    current_user: Annotated[auth.User, Depends(auth.get_current_user)],
):
    """
    Check a tailored CV or cover letter before it goes out: the ad's keywords it shows or misses,
    claims your persona doesn't back up, machine-sounding words, and the rendered PDF read back as
    an applicant tracking system reads it. No model calls.
    """
    doc_type = body.get("type", "cv")
    if doc_type not in ("cv", "cover_letter"):
        raise HTTPException(status_code=400, detail="type must be 'cv' or 'cover_letter'")
    doc = body.get("doc") or {}
    job = body.get("job") or {}
    persona = tracker.get_user_persona(current_user.id)
    return await asyncio.to_thread(
        doc_check.check_document, doc_type, doc, persona, job, body.get("template_id"), bool(body.get("ats", True)),
    )


# ── The answer bank: your own answers to application-form questions (answers.py) ──

@app.get("/answers")
async def list_saved_answers(current_user: Annotated[auth.User, Depends(auth.get_current_user)]):
    """Your saved answers, most recently changed first."""
    return tracker.list_answers(current_user.id)


@app.post("/answers")
async def save_answer(body: dict, current_user: Annotated[auth.User, Depends(auth.get_current_user)]):
    """
    Save your answer to a question, replacing any saved for the same question. `kind` is 'fact' or
    'written'; `company` is the job's employer, and the answer is kept for that employer only when the
    question or the answer names it.
    """
    try:
        return answers.save(current_user.id, body.get("question", ""), body.get("answer", ""),
                            body.get("kind", "fact"), body.get("company", ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.put("/answers/{answer_id}")
async def edit_saved_answer(answer_id: str, body: dict,
                            current_user: Annotated[auth.User, Depends(auth.get_current_user)]):
    text = str(body.get("answer") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="An answer is needed; delete it instead.")
    updated = tracker.update_answer(current_user.id, answer_id, text)
    if not updated:
        raise HTTPException(status_code=404, detail="No such saved answer")
    return updated


@app.delete("/answers/{answer_id}")
async def delete_saved_answer(answer_id: str, current_user: Annotated[auth.User, Depends(auth.get_current_user)]):
    if not tracker.delete_answer(current_user.id, answer_id):
        raise HTTPException(status_code=404, detail="No such saved answer")
    return {"deleted": answer_id}


@app.post("/answers/draft")
async def draft_answers(body: dict, current_user: Annotated[auth.User, Depends(auth.get_current_user)]):
    """
    Answers to a job's application questions, as the apply agent gets them: each saved, from your
    profile, drafted (written ones) or needs_you, never guessed. `questions` are strings or
    {question, options?, max_length?}; `job` is {title, company, location, description}. Nothing is saved.
    """
    questions = body.get("questions")
    if not isinstance(questions, list) or not questions:
        raise HTTPException(status_code=400, detail="questions must be a non-empty list")
    job = body.get("job") if isinstance(body.get("job"), dict) else {}
    persona = tracker.get_user_persona(current_user.id)
    return {"answers": await answers.answer_questions(questions, persona, tracker.list_answers(current_user.id),
                                                      job, str(body.get("cover_letter") or ""))}


from fastapi.responses import FileResponse  # noqa: E402


# ── Autopilot ─────────────────────────────────────────────────────────────────

# What the user can still do with a run: retry it (autopilot tries the job again) or clear it from the queue.
_RETRYABLE = {"needs_you", "failed", "skipped", "ready", "dismissed"}
_DISMISSABLE = {"needs_you", "failed", "skipped", "ready", "unconfirmed"}


@app.get("/autopilot")
async def autopilot_status(current_user: Annotated[auth.User, Depends(auth.get_current_user)]):
    """Autopilot's settings, whether a run is going (and what it's doing), and how many went out today."""
    return autopilot.status(current_user.id)


@app.put("/autopilot/settings")
async def autopilot_settings(body: dict, current_user: Annotated[auth.User, Depends(auth.get_current_user)]):
    """Change any of {enabled, live, min_fit, daily_cap}; returns them all."""
    try:
        return autopilot.save_settings(current_user.id, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/autopilot/run", status_code=202)
async def autopilot_run(current_user: Annotated[auth.User, Depends(auth.get_current_user)]):
    """Start a run now, in the background (GET /autopilot follows it)."""
    if not autopilot.start(current_user.id):
        raise HTTPException(status_code=409, detail="Autopilot is already running")
    return {"started": True}


@app.get("/autopilot/runs")
async def autopilot_runs(current_user: Annotated[auth.User, Depends(auth.get_current_user)]):
    """Every job autopilot has dealt with, latest first, with which screenshots it kept."""
    runs = tracker.list_autopilot_runs(current_user.id)
    for run in runs:
        run["screenshots"] = [w for w in autopilot.SCREENSHOTS if os.path.exists(autopilot.screenshot_path(run, w))]
        run.pop("user_id", None)
    return runs


def _own_run(user_id: str, run_id: str) -> dict:
    run = tracker.get_autopilot_run(user_id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="No such autopilot run")
    return run


@app.post("/autopilot/runs/{run_id}/retry", status_code=202)
async def autopilot_retry(run_id: str, current_user: Annotated[auth.User, Depends(auth.get_current_user)]):
    """Have autopilot try this job again now: after you've answered its questions, say."""
    run = _own_run(current_user.id, run_id)
    if run["outcome"] not in _RETRYABLE:
        raise HTTPException(status_code=400, detail=f"A run that is {run['outcome']} can't be retried")
    if not autopilot.start(current_user.id, run["job_id"]):
        raise HTTPException(status_code=409, detail="Autopilot is already running")
    return {"started": True}


@app.post("/autopilot/runs/{run_id}/dismiss")
async def autopilot_dismiss(run_id: str, current_user: Annotated[auth.User, Depends(auth.get_current_user)]):
    """Clear a run from the queue. Autopilot won't try the job again unless you retry it."""
    run = _own_run(current_user.id, run_id)
    if run["outcome"] not in _DISMISSABLE:
        raise HTTPException(status_code=400, detail=f"A run that is {run['outcome']} can't be dismissed")
    tracker.update_autopilot_run(run_id, user_id=current_user.id, outcome="dismissed")
    return {"dismissed": run_id}


@app.get("/autopilot/runs/{run_id}/screenshots/{which}")
async def autopilot_screenshot(run_id: str, which: str,
                               current_user: Annotated[auth.User, Depends(auth.get_current_user)]):
    """A run's screenshot: 'form' (the filled form) or 'confirm' (the page after it was sent)."""
    if which not in autopilot.SCREENSHOTS:
        raise HTTPException(status_code=404, detail="No such screenshot")
    path = autopilot.screenshot_path(_own_run(current_user.id, run_id), which)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="No such screenshot")
    return FileResponse(path, media_type="image/jpeg")


@app.get("/documents/{doc_id}/download")
async def download_pdf(
    doc_id: str,
    current_user: Annotated[auth.User, Depends(auth.get_current_user)],
):
    import re
    import os as _os
    if not re.fullmatch(r"[a-f0-9]{32}", doc_id):
        raise HTTPException(status_code=400, detail="Invalid doc_id")
    path = pdf_generator.get_pdf_path(doc_id)
    if not _os.path.exists(path):
        raise HTTPException(status_code=404, detail="Document not found")
    return FileResponse(path, media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="windrush_{doc_id[:8]}.pdf"'})


# ── Gmail tracking ────────────────────────────────────────────────────────────

@app.get("/gmail")
async def gmail_status(current_user: Annotated[auth.User, Depends(auth.get_current_user)]):
    """Whether Gmail tracking is set up and connected, and how the last sync went."""
    return gmail.status(current_user.id)


@app.get("/gmail/connect")
async def gmail_connect(current_user: Annotated[auth.User, Depends(auth.get_current_user)]):
    """The Google consent page to send the user to (read-only Gmail access)."""
    if not gmail.configured():
        raise HTTPException(status_code=400, detail="Gmail tracking isn't set up: GOOGLE_CLIENT_ID and "
                                                    "GOOGLE_CLIENT_SECRET aren't in .env")
    return {"url": gmail.auth_url(current_user.id)}


@app.get("/gmail/callback")
async def gmail_callback(state: str = "", code: str = "", error: str = ""):
    """Where Google sends the browser back. A plain redirect, so the user is known by the OAuth state."""
    from urllib.parse import quote
    if error or not code:
        reason = "You didn't allow access." if error == "access_denied" else (error or "Google sent no code.")
        return RedirectResponse(f"/inbox?gmail=error&reason={quote(reason)}", status_code=303)
    try:
        user_id = await gmail.finish(state, code)
    except gmail.GmailError as exc:
        return RedirectResponse(f"/inbox?gmail=error&reason={quote(str(exc))}", status_code=303)
    except Exception:
        logger.exception("gmail connect failed")
        return RedirectResponse(f"/inbox?gmail=error&reason={quote('Connecting failed. Try again.')}", status_code=303)
    gmail.start_sync(user_id)
    return RedirectResponse("/inbox?gmail=connected", status_code=303)


@app.post("/gmail/sync", status_code=202)
async def gmail_sync(current_user: Annotated[auth.User, Depends(auth.get_current_user)]):
    account = tracker.get_gmail_account(current_user.id)
    if not account:
        raise HTTPException(status_code=400, detail="Gmail isn't connected")
    if account.get("problem"):
        raise HTTPException(status_code=400, detail=account["problem"])
    if not gmail.start_sync(current_user.id):
        raise HTTPException(status_code=409, detail="A sync is already running")
    return {"started": True}


@app.delete("/gmail")
async def gmail_disconnect(current_user: Annotated[auth.User, Depends(auth.get_current_user)]):
    """Revoke Windrush's Gmail access and forget the account."""
    await gmail.disconnect(current_user.id)
    return {"connected": False}


@app.get("/gmail/events")
async def gmail_events(current_user: Annotated[auth.User, Depends(auth.get_current_user)]):
    """Emails read as being about an application, latest first, with what Windrush did about each."""
    return tracker.list_email_events(current_user.id)


def _email_action(fn, *args):
    try:
        return fn(*args)
    except LookupError:
        raise HTTPException(status_code=404, detail="No such email")
    except gmail.GmailError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/gmail/events/{event_id}/confirm")
async def gmail_confirm(event_id: str, body: dict, current_user: Annotated[auth.User, Depends(auth.get_current_user)]):
    """Make the change an email points to; {application_id} links an email Windrush couldn't match."""
    application_id = body.get("application_id") if isinstance(body.get("application_id"), str) else None
    return _email_action(gmail.confirm, current_user.id, event_id, application_id)


@app.post("/gmail/events/track-all")
async def gmail_track_all(current_user: Annotated[auth.User, Depends(auth.get_current_user)]):
    """Add every application the unmatched emails are about, one per company and role, at its latest status."""
    return gmail.track_all(current_user.id)


@app.post("/gmail/events/{event_id}/track")
async def gmail_track(event_id: str, body: dict, current_user: Annotated[auth.User, Depends(auth.get_current_user)]):
    """Add the application an unmatched email is about: {company, role}, at the status the email points to."""
    return _email_action(gmail.track, current_user.id, event_id, body.get("company"), body.get("role"))


@app.post("/gmail/events/{event_id}/dismiss")
async def gmail_dismiss(event_id: str, current_user: Annotated[auth.User, Depends(auth.get_current_user)]):
    _email_action(gmail.dismiss, current_user.id, event_id)
    return {"dismissed": event_id}


@app.post("/gmail/events/{event_id}/undo")
async def gmail_undo(event_id: str, current_user: Annotated[auth.User, Depends(auth.get_current_user)]):
    """Put the application back to where it was before this email changed it."""
    return _email_action(gmail.undo, current_user.id, event_id)


# ── Profile suggestions (see enrich.py) ───────────────────────────────────────

_LINKEDIN_ZIP_LIMIT = 50_000_000


def _ids(body: dict) -> list[str]:
    ids = body.get("ids")
    return [i for i in ids if isinstance(i, str)][:500] if isinstance(ids, list) else []


@app.get("/profile/suggestions")
async def profile_suggestions(current_user: Annotated[auth.User, Depends(auth.get_current_user)]):
    """What GitHub, the website and a LinkedIn export suggest adding to the persona, and how each read went."""
    persona = Persona(**tracker.get_user_persona(current_user.id))
    return {"suggestions": enrich.pending(current_user.id), **enrich.status(current_user.id, persona)}


@app.post("/profile/suggestions/read", status_code=202)
async def profile_suggestions_read(body: dict, current_user: Annotated[auth.User, Depends(auth.get_current_user)]):
    """Read {source: github | website} in the background; GET /profile/suggestions shows when it's done."""
    source = body.get("source")
    if source not in ("github", "website"):
        raise HTTPException(status_code=400, detail="source must be github or website")
    if not enrich.start(current_user.id, source):
        raise HTTPException(status_code=409, detail="Already reading a source")
    return {"started": True}


@app.post("/profile/suggestions/linkedin")
async def profile_suggestions_linkedin(file: UploadFile = File(...),
                                       current_user: Annotated[auth.User, Depends(auth.get_current_user)] = None):
    """Read a LinkedIn data export (the zip LinkedIn emails) into suggestions."""
    data = await file.read(_LINKEDIN_ZIP_LIMIT + 1)
    if len(data) > _LINKEDIN_ZIP_LIMIT:
        raise HTTPException(status_code=413, detail="That file is too big for a LinkedIn export")
    try:
        added = await enrich.read(current_user.id, "linkedin", data)
    except enrich.SourceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"added": added}


@app.post("/profile/suggestions/accept")
async def profile_suggestions_accept(body: dict, current_user: Annotated[auth.User, Depends(auth.get_current_user)]):
    """Add {ids} to the persona. Each only adds an entry or fills an empty field; ones the persona has caught
    up with are counted as outdated and change nothing."""
    result = enrich.accept(current_user.id, _ids(body))
    persona = result["persona"]
    persona.core_info.job_password = JOB_PASSWORD_MASK if tracker.has_job_password(current_user.id) else ""
    return result


@app.post("/profile/suggestions/dismiss")
async def profile_suggestions_dismiss(body: dict, current_user: Annotated[auth.User, Depends(auth.get_current_user)]):
    """Say no to {ids}: they aren't offered again when the source is read again."""
    return {"dismissed": enrich.dismiss(current_user.id, _ids(body))}
