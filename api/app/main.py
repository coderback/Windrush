from fastapi import FastAPI, UploadFile, File, Form
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
    cover_letter: str = Form(...),
    cv_profile: str = Form(default="{}"),
):
    import json
    profile = json.loads(cv_profile)
    return StreamingResponse(
        run_apply(job_id, cover_letter, profile),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
