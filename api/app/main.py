import asyncio
import json
import pathlib
import tempfile
import uuid

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .cv_parser import extract_text
from .agent import run_pipeline, run_apply
from .guardrails import check_cv_for_injection, get_audit_log, GuardrailViolation

app = FastAPI(title="Windrush API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Session registries
_browser_queues: dict[str, asyncio.Queue] = {}   # instruction queues
_browser_frames: dict[str, asyncio.Queue] = {}   # CDP screencast frame queues
_cv_files: dict[str, str] = {}                   # cv_session_id → temp file path


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/guardrails/audit")
async def guardrails_audit():
    return get_audit_log()


@app.post("/stream")
async def pipeline_stream(
    file: UploadFile = File(...),
    location: str = Form(default="London"),
):
    pdf_bytes = await file.read()
    cv_text = extract_text(pdf_bytes)

    # Guardrail: reject CV text containing prompt injection before it reaches the LLM
    try:
        check_cv_for_injection(cv_text)
    except GuardrailViolation as e:
        import time as _time

        async def _blocked_stream():
            yield f"data: {json.dumps({'type': 'guardrail', 'check': e.check, 'detail': e.detail, 'fired': True, 'timestamp': _time.time()})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'message': 'Upload rejected by guardrails — possible prompt injection detected'})}\n\n"

        return StreamingResponse(
            _blocked_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
        )

    # Save CV to disk so browser agent can upload it during applications
    cv_session_id = uuid.uuid4().hex
    cv_path = pathlib.Path(tempfile.gettempdir()) / f"cv_{cv_session_id}.pdf"
    cv_path.write_bytes(pdf_bytes)
    _cv_files[cv_session_id] = str(cv_path)

    async def pipeline_with_cv_session():
        import json, time
        yield f"data: {json.dumps({'type': 'cv_session', 'cv_session_id': cv_session_id, 'timestamp': time.time()})}\n\n"
        async for chunk in run_pipeline(cv_text, location):
            yield chunk

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
    cover_letter: str = Form(...),
    cv_profile: str = Form(default="{}"),
    skill_risks: str = Form(default="[]"),
    job_email: str = Form(default=""),
    job_password: str = Form(default=""),
    cv_session_id: str = Form(default=""),
):
    profile = json.loads(cv_profile)
    risks = json.loads(skill_risks)
    cv_path = _cv_files.get(cv_session_id, "")
    session_id = str(uuid.uuid4())

    q: asyncio.Queue = asyncio.Queue()
    fq: asyncio.Queue = asyncio.Queue(maxsize=8)
    _browser_queues[session_id] = q
    _browser_frames[session_id] = fq

    async def cleanup_gen():
        try:
            async for chunk in run_apply(
                job_id, job_url, cover_letter, profile, risks, session_id, q, fq,
                job_email=job_email, job_password=job_password, cv_path=cv_path,
            ):
                yield chunk
        finally:
            _browser_queues.pop(session_id, None)
            _browser_frames.pop(session_id, None)

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
async def browser_input(session_id: str, body: dict):
    """Relay a user instruction into the running browser session."""
    q = _browser_queues.get(session_id)
    if q is None:
        raise HTTPException(status_code=404, detail="Session not found or already complete")
    await q.put(body.get("instruction", ""))
    return {"queued": True}


@app.get("/browser-stream/{session_id}")
async def browser_stream(session_id: str):
    """SSE stream of live CDP screencast JPEG frames."""
    async def gen():
        while True:
            fq = _browser_frames.get(session_id)
            if fq is None:
                # Session ended — send close event and stop
                yield f"data: {json.dumps({'type': 'close'})}\n\n"
                return
            try:
                frame = await asyncio.wait_for(fq.get(), timeout=5.0)
                yield f"data: {json.dumps({'frame': frame})}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"  # SSE comment — keeps connection alive

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
