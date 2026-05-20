import asyncio
import json
import pathlib
import tempfile
import uuid
from contextlib import asynccontextmanager
from typing import Optional, Annotated

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordRequestForm

from .cv_parser import extract_text
from .agent import run_pipeline, run_apply, execute_tool
from .guardrails import check_cv_for_injection, get_audit_log, GuardrailViolation
from .job_proxy import search_jobs
from . import tracker
from . import auth
from . import pdf_generator
from . import jobs_db
from .models import Persona


@asynccontextmanager
async def lifespan(app: FastAPI):
    import os
    data_dir = os.environ.get("APP_DATA_PATH", "/tmp")
    tracker.init_db()
    jobs_db.init_db()
    pdf_generator.init_pdf_dir(data_dir)
    yield


app = FastAPI(title="Windrush API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Session registries (now also keyed by user_id for better isolation)
_browser_queues: dict[str, asyncio.Queue] = {}   # session_id → instruction queue
_browser_frames: dict[str, asyncio.Queue] = {}   # session_id → CDP screencast frame queue
_cv_files: dict[str, str] = {}                   # cv_session_id → temp file path
_cv_texts: dict[str, str] = {}                   # cv_session_id → extracted text


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

@app.get("/persona", response_model=Persona)
async def get_persona(current_user: Annotated[auth.User, Depends(auth.get_current_user)]):
    data = tracker.get_user_persona(current_user.id)
    return Persona(**data)


@app.put("/persona")
async def update_persona(
    persona: Persona,
    current_user: Annotated[auth.User, Depends(auth.get_current_user)],
):
    ok = tracker.update_user_persona(current_user.id, persona.model_dump())
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update persona")
    return {"message": "Persona updated"}


# ── Protected Endpoints ───────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/guardrails/audit")
async def guardrails_audit(current_user: Annotated[auth.User, Depends(auth.get_current_user)]):
    return get_audit_log()


@app.post("/upload")
async def upload_cv(
    file: UploadFile = File(...),
    current_user: Annotated[auth.User, Depends(auth.get_current_user)] = None,
):
    """Parse CV, merge into Persona, and return a cv_session_id for the pipeline."""
    pdf_bytes = await file.read()
    try:
        cv_text = extract_text(pdf_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        check_cv_for_injection(cv_text)
    except GuardrailViolation as e:
        raise HTTPException(status_code=422, detail=f"GUARDRAIL: {e.detail}")

    # Extract structured data from CV
    from .agent import execute_tool
    cv_data = await execute_tool("extract_cv_profile", {"cv_text": cv_text})

    # Merge into existing Persona
    existing_persona_data = tracker.get_user_persona(current_user.id)
    persona = Persona(**existing_persona_data)
    
    # Granular merge logic
    if cv_data.get("name"):
        parts = cv_data["name"].split()
        if len(parts) >= 2:
            if not persona.core_info.first_name: persona.core_info.first_name = parts[0]
            if not persona.core_info.last_name: persona.core_info.last_name = " ".join(parts[1:])
        elif not persona.core_info.first_name:
            persona.core_info.first_name = cv_data["name"]

    if cv_data.get("email") and not persona.core_info.email:
        persona.core_info.email = cv_data["email"]
    if cv_data.get("phone") and not persona.core_info.phone:
        persona.core_info.phone = cv_data["phone"]
    
    # Location/Address mapping
    if cv_data.get("address") and not persona.core_info.address_line_1:
        persona.core_info.address_line_1 = cv_data["address"]
    if cv_data.get("location") and not persona.core_info.city:
        persona.core_info.city = cv_data["location"]

    # Skill Categorization Logic (Merging categorized skills)
    # cv_data['skills'] is now expected to be List[dict] with {category, skills}
    extracted_categories = cv_data.get("skills", [])
    if extracted_categories and isinstance(extracted_categories[0], dict):
        # Already categorized by the LLM
        for ext_cat in extracted_categories:
            cat_name = ext_cat.get("category", "Uncategorized")
            new_skills = ext_cat.get("skills", [])
            # Find matching category in persona
            found = False
            for p_cat in persona.skills:
                if p_cat.category.lower() == cat_name.lower():
                    p_cat.skills = list(set(p_cat.skills + new_skills))
                    found = True
                    break
            if not found:
                from .models import SkillCategory
                persona.skills.append(SkillCategory(category=cat_name, skills=new_skills))
    else:
        # Fallback for old/flat list if any
        flat_skills = cv_data.get("skills", [])
        if flat_skills:
            from .models import SkillCategory
            found = False
            for p_cat in persona.skills:
                if p_cat.category == "Uncategorized":
                    p_cat.skills = list(set(p_cat.skills + flat_skills))
                    found = True
                    break
            if not found:
                persona.skills.append(SkillCategory(category="Uncategorized", skills=flat_skills))

    persona.summary = cv_data.get("summary") or persona.summary

    # Update history and education if empty
    from .models import WorkExperience, Education
    if not persona.history and cv_data.get("experience"):
        new_history = []
        for exp in cv_data["experience"]:
            # Map old 'summary' to achievements/summary as needed
            new_history.append(WorkExperience(
                employer=exp.get("employer", ""),
                title=exp.get("title", ""),
                start_date=exp.get("dates", "").split("-")[0].strip() if "-" in exp.get("dates", "") else "",
                end_date=exp.get("dates", "").split("-")[1].strip() if "-" in exp.get("dates", "") else "",
                is_current="present" in exp.get("dates", "").lower(),
                summary=exp.get("summary", ""),
            ))
        persona.history = new_history

    if not persona.education and cv_data.get("education"):
        new_edu = []
        for edu in cv_data["education"]:
            new_edu.append(Education(
                institution=edu.get("institution", ""),
                degree=edu.get("degree", ""),
                start_date="", end_date="", grade="",
                is_currently_enrolled=False
            ))
        persona.education = new_edu

    tracker.update_user_persona(current_user.id, persona.model_dump())

    cv_session_id = uuid.uuid4().hex
    cv_path = pathlib.Path(tempfile.gettempdir()) / f"cv_{cv_session_id}.pdf"
    cv_path.write_bytes(pdf_bytes)
    _cv_files[cv_session_id] = str(cv_path)
    _cv_texts[cv_session_id] = cv_text

    return {"cv_session_id": cv_session_id, "persona": persona}


@app.post("/stream")
async def pipeline_stream(
    cv_session_id: str = Form(...),
    location: str = Form(default="London"),
    current_user: Annotated[auth.User, Depends(auth.get_current_user)] = None,
):
    cv_text = _cv_texts.get(cv_session_id)
    if not cv_text:
        raise HTTPException(status_code=404, detail="CV session not found or expired — please re-upload")

    cv_path_str = _cv_files.get(cv_session_id, "")

    async def pipeline_with_cv_session():
        import time
        try:
            yield f"data: {json.dumps({'type': 'cv_session', 'cv_session_id': cv_session_id, 'timestamp': time.time()})}\n\n"
            async for chunk in run_pipeline(current_user.id, cv_text, location):
                yield chunk
        finally:
            if cv_path_str:
                pathlib.Path(cv_path_str).unlink(missing_ok=True)
            _cv_files.pop(cv_session_id, None)
            _cv_texts.pop(cv_session_id, None)

    return StreamingResponse(
        pipeline_with_cv_session(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/apply")
async def apply(
    job_id: str = Form(...),
    job_url: str = Form(default=""),
    cover_letter: str = Form(default=""),
    cv_profile: str = Form(default="{}"),
    skill_risks: str = Form(default="[]"),
    job_email: str = Form(default=""),
    job_password: str = Form(default=""),
    cv_session_id: str = Form(default=""),
    tailored_cv: str = Form(default=""),
    cv_doc_id: str = Form(default=""),
    job_title: str = Form(default=""),
    company: str = Form(default=""),
    location: str = Form(default=""),
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

    # Fall back to persona credentials if not provided in form
    persona = tracker.get_user_persona(current_user.id)
    core = persona.get("core_info", {})
    effective_email = job_email or core.get("job_email", "")
    effective_password = job_password or core.get("job_password", "")

    # Tailored CV PDF takes precedence over original upload if the user chose it
    if cv_doc_id:
        tailored_path = pdf_generator.get_pdf_path(cv_doc_id)
        import os as _os2
        cv_path = tailored_path if _os2.path.exists(tailored_path) else _cv_files.get(cv_session_id, "")
    else:
        cv_path = _cv_files.get(cv_session_id, "")
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
    )

    q: asyncio.Queue = asyncio.Queue()
    fq: asyncio.Queue = asyncio.Queue(maxsize=8)
    _browser_queues[session_id] = q
    _browser_frames[session_id] = fq

    async def cleanup_gen():
        user_confirmed = False
        try:
            async for chunk in run_apply(
                current_user.id, job_id, job_url, cover_letter, risks, session_id, q, fq,
                job_email=effective_email, job_password=effective_password, cv_path=cv_path,
            ):
                try:
                    payload = json.loads(chunk.removeprefix("data: ").strip())
                    if payload.get("type") == "done":
                        user_confirmed = True
                except Exception:
                    pass
                yield chunk
        finally:
            _browser_queues.pop(session_id, None)
            _browser_frames.pop(session_id, None)
            if app_id and user_confirmed:
                tracker.update_status(app_id, "Applied")

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
    ok = tracker.update_status(app_id, status, notes)
    if not ok:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status!r}")
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

@app.get("/jobs")
async def get_jobs(
    query: str = Query(default=""),
    location: str = Query(default=""),
    level: str = Query(default=""),
    category: str = Query(default=""),
    remote: bool = Query(default=False),
    tags: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: Annotated[auth.User, Depends(auth.get_current_user)] = None,
):
    """Return job listings for the job feed with pagination and filtering."""
    tag_list = [t.strip() for t in tags.split(",")] if tags else []

    # Always pull the persona to get preferences and for semantic search
    persona_data = tracker.get_user_persona(current_user.id)
    
    effective_query = query
    effective_location = location

    if not effective_query:
        prefs = persona_data.get("preferences", {})
        titles = prefs.get("target_titles", [])
        # Join multiple target titles for a broader default search
        effective_query = " ".join(titles) if titles else ""
        
        locs = prefs.get("preferred_locations", [])
        if not effective_location:
            effective_location = locs[0] if locs else ""

    # Generate semantic vector that combines Persona + current search query/tags
    # This "Interest-Weighted" vector ensures the AI prioritizes both who you are AND what you want.
    persona_text = semantic.vectorize_persona(persona_data)
    
    # Merge explicit keywords and tags into a single semantic intent block
    intent_parts = []
    if query: intent_parts.append(query)
    if tag_list: intent_parts.extend(tag_list)
    
    if intent_parts:
        intent_str = ", ".join(intent_parts)
        # Boost the query by repeating it in the text
        persona_text = f"Current user interest: {intent_str}. Specific focus: {intent_str}. {persona_text}"
    
    persona_vector = await semantic.get_embedding(persona_text)

    # ── Clean Feed Logic ──
    # Fetch user's active pipeline statuses to filter/badge the feed
    status_map = tracker.get_user_application_statuses(current_user.id)
    # Statuses that trigger hiding from the feed
    HIDE_STATUSES = {"Applied", "Responded", "Interview", "Offer", "Rejected", "Discarded"}

    def process_clean_feed(raw_jobs: list[dict]) -> list[dict]:
        clean = []
        for job in raw_jobs:
            key = (job.get("company", "").lower(), job.get("title", "").lower())
            status = status_map.get(key)
            
            if status in HIDE_STATUSES:
                continue
            
            if status == "Saved":
                job["tracker_status"] = "Saved"
            elif status:
                # Catch-all for other statuses (e.g. Evaluated, Pending Review)
                job["tracker_status"] = status
                
            clean.append(job)
        return clean

    offset = (page - 1) * limit

    # Query the local jobs database first
    raw_jobs = jobs_db.get_jobs(
        query=effective_query,
        location=effective_location,
        level=level,
        category=category,
        remote=remote,
        tags=tag_list,
        persona_vector=persona_vector,
        limit=limit,
        offset=offset,
    )
    jobs = process_clean_feed(raw_jobs)

    # Proactive Infinite Discovery: If we don't have enough local matches for this 
    # specific location/query, trigger a live discovery across external APIs.
    if (not jobs or len(jobs) < 5):
        # Use only the first title or the specific user query for live search
        live_query = query if query else (titles[0] if persona_data.get("preferences", {}).get("target_titles") else "software engineer")
        
        # Don't trigger if the query is just a single character (e.g. typing)
        if len(live_query) > 2:
            live_jobs = await search_jobs(live_query, effective_location or "London")
            if live_jobs:
                # Persist them for future queries
                for j in live_jobs:
                    j["source"] = j.get("source", "live")
                    j["level"] = _infer_level(j.get("title", ""))
                jobs_db.add_jobs(live_jobs)
                
                # Re-query and re-filter
                refreshed_raw = jobs_db.get_jobs(
                    query=effective_query,
                    location=effective_location,
                    level=level,
                    category=category,
                    remote=remote,
                    tags=tag_list,
                    persona_vector=persona_vector,
                    limit=limit,
                    offset=offset,
                )
                jobs = process_clean_feed(refreshed_raw)

    return {
        "jobs": jobs,
        "query": effective_query,
        "location": effective_location,
        "page": page,
        "limit": limit,
        "has_more": len(jobs) == limit,
    }


def _infer_level(title: str) -> str:
    t = title.lower()
    if any(w in t for w in ["junior", "graduate", "entry", "associate", "intern"]):
        return "junior"
    elif any(w in t for w in ["senior", "lead", "principal", "staff", "manager", "head", "director"]):
        return "senior"
    return "mid"


# ── Per-job agent endpoints (SSE) ─────────────────────────────────────────────

def _sse_json(event_type: str, data: dict) -> str:
    import time
    payload = {"type": event_type, "timestamp": time.time(), **data}
    return f"data: {json.dumps(payload)}\n\n"


@app.post("/jobs/analyze")
async def analyze_job(
    body: dict,
    current_user: Annotated[auth.User, Depends(auth.get_current_user)],
):
    """SSE: score fit + AI risk for a single job against the user's persona."""
    job = body.get("job", {})
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
    job = body.get("job", {})
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
    job = body.get("job", {})
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
    """Generate a PDF from CV or cover-letter Markdown text."""
    doc_type = body.get("type", "cv")
    text = body.get("text", "")
    metadata = body.get("metadata", {})
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    try:
        doc_id = pdf_generator.generate_pdf(doc_type, text, metadata)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"doc_id": doc_id, "download_url": f"/api/documents/{doc_id}/download"}


from fastapi.responses import FileResponse  # noqa: E402


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
