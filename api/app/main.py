import asyncio
import json
import uuid

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .cv_parser import extract_text
from .agent import run_pipeline, run_apply

app = FastAPI(title="Windrush API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Session registry: session_id → asyncio.Queue for browser instruction passing
_browser_queues: dict[str, asyncio.Queue] = {}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/stream")
async def pipeline_stream(
    file: UploadFile = File(...),
    location: str = Form(default="London"),
):
    pdf_bytes = await file.read()
    cv_text = extract_text(pdf_bytes)
    return StreamingResponse(
        run_pipeline(cv_text, location),
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
):
    profile = json.loads(cv_profile)
    risks = json.loads(skill_risks)
    session_id = str(uuid.uuid4())
    q: asyncio.Queue = asyncio.Queue()
    _browser_queues[session_id] = q

    async def cleanup_gen():
        try:
            async for chunk in run_apply(job_id, job_url, cover_letter, profile, risks, session_id, q):
                yield chunk
        finally:
            _browser_queues.pop(session_id, None)

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
