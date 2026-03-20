"""FastAPI backend for Transcript Studio.

Run locally:
    python3 -m uvicorn api.main:app --reload

For production, deploy to Railway, Fly.io, Render, etc.
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from api.jobs import job_store
from api.schemas import (
    CostEstimateResponse,
    ExportFormat,
    ExportRequest,
    JobDetail,
    JobStatus,
    RefineRequest,
    RefineResponse,
    RefinementMode,
    TranscribeRequest,
    TranscribeResponse,
    UploadResponse,
)

load_dotenv()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Transcript Studio API",
    version="1.0.0",
    description="Upload audio, transcribe with Whisper, refine with Claude.",
)

# CORS — allow any origin in dev. Lock down for production.
_cors_origins = os.getenv("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=("*" not in _cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_job_or_404(job_id: str) -> JobDetail:
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health_check() -> dict:
    """Health check endpoint for load balancers and uptime monitors."""
    openai_ok = bool(os.getenv("OPENAI_API_KEY", "")) and os.getenv("OPENAI_API_KEY") != "your_key_here"
    anthropic_ok = bool(os.getenv("ANTHROPIC_API_KEY", "")) and os.getenv("ANTHROPIC_API_KEY") != "your_key_here"
    return {
        "status": "ok",
        "openai_key_configured": openai_ok,
        "anthropic_key_configured": anthropic_ok,
    }


# --- Upload ---

@app.post("/upload/zip", response_model=UploadResponse)
async def upload_zip(file: UploadFile = File(...)) -> UploadResponse:
    """Upload a zip file containing audio recordings.

    Extracts audio, converts to mp3, and chunks for transcription.
    Returns job ID and upload summary.
    """
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="File must be a .zip")

    job = job_store.create()

    # Write upload to temp file
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        from core.chunker import process_upload

        result = process_upload(tmp_path, cleanup=False)
        job_store.update(
            job.job_id,
            status=JobStatus.completed,
            step="upload",
            progress=1.0,
            num_files_found=result["num_files_found"],
            num_chunks=result["num_chunks"],
            total_duration_seconds=result["total_duration_seconds"],
            upload_cost_estimate=result["estimated_cost"],
            skipped_files=result["skipped_files"],
            chunk_paths=result["chunk_paths"],
        )

        return UploadResponse(
            job_id=job.job_id,
            status=JobStatus.completed,
            num_files_found=result["num_files_found"],
            num_chunks=result["num_chunks"],
            total_duration_seconds=result["total_duration_seconds"],
            estimated_cost=result["estimated_cost"],
            skipped_files=result["skipped_files"],
        )

    except Exception as e:
        job_store.update(job.job_id, status=JobStatus.failed, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@app.post("/upload/audio", response_model=UploadResponse)
async def upload_audio(files: list[UploadFile] = File(...)) -> UploadResponse:
    """Upload individual audio files for transcription.

    Accepts one or more audio files. Converts and chunks them.
    """
    job = job_store.create()

    staging_dir = os.path.join("temp_audio", "staged", job.job_id)
    os.makedirs(staging_dir, exist_ok=True)

    try:
        staged_paths = []
        for f in files:
            dest = os.path.join(staging_dir, f.filename or "audio.mp3")
            with open(dest, "wb") as out:
                out.write(await f.read())
            staged_paths.append(dest)

        from core.chunker import process_audio_files

        result = process_audio_files(staged_paths, cleanup=False)
        job_store.update(
            job.job_id,
            status=JobStatus.completed,
            step="upload",
            progress=1.0,
            num_files_found=result["num_files_found"],
            num_chunks=result["num_chunks"],
            total_duration_seconds=result["total_duration_seconds"],
            upload_cost_estimate=result["estimated_cost"],
            skipped_files=result["skipped_files"],
            chunk_paths=result["chunk_paths"],
        )

        return UploadResponse(
            job_id=job.job_id,
            status=JobStatus.completed,
            num_files_found=result["num_files_found"],
            num_chunks=result["num_chunks"],
            total_duration_seconds=result["total_duration_seconds"],
            estimated_cost=result["estimated_cost"],
            skipped_files=result["skipped_files"],
        )

    except Exception as e:
        job_store.update(job.job_id, status=JobStatus.failed, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# --- Transcribe ---

@app.post("/transcribe", response_model=TranscribeResponse)
def start_transcription(req: TranscribeRequest) -> TranscribeResponse:
    """Start transcription for a previously uploaded job.

    Runs asynchronously in a background thread. Poll GET /jobs/{job_id}
    for progress.
    """
    job = _get_job_or_404(req.job_id)

    if not job.chunk_paths:
        raise HTTPException(status_code=400, detail="No chunks to transcribe. Upload audio first.")

    job_store.update(req.job_id, status=JobStatus.processing, step="transcribe", progress=0.0)

    def _run_transcription():
        try:
            from core.transcriber import transcribe_all

            total_chunks = len(job.chunk_paths)

            def _progress(current, total):
                job_store.update(req.job_id, progress=current / total)

            result = transcribe_all(
                job.chunk_paths,
                language=req.language,
                parallel=req.parallel,
                progress_callback=_progress,
            )

            from core.chunker import cleanup_temp_dir
            cleanup_temp_dir()

            job_store.update(
                req.job_id,
                status=JobStatus.completed,
                step="transcribe",
                progress=1.0,
                raw_transcript=result["full_text"],
                transcription_cost=result["estimated_cost"],
                processing_time_seconds=result["processing_time_seconds"],
            )

        except Exception as e:
            logger.error(f"Transcription failed for job {req.job_id}: {e}")
            job_store.update(req.job_id, status=JobStatus.failed, error=str(e))

    thread = threading.Thread(target=_run_transcription, daemon=True)
    thread.start()

    return TranscribeResponse(
        job_id=req.job_id,
        status=JobStatus.processing,
        message="Transcription started. Poll GET /jobs/{job_id} for progress.",
    )


# --- Refine ---

@app.post("/refine", response_model=RefineResponse)
def start_refinement(req: RefineRequest) -> RefineResponse:
    """Start refinement for a transcribed job.

    Runs asynchronously in a background thread. Poll GET /jobs/{job_id}
    for progress.
    """
    job = _get_job_or_404(req.job_id)

    if not job.raw_transcript:
        raise HTTPException(status_code=400, detail="No transcript to refine. Transcribe first.")

    job_store.update(req.job_id, status=JobStatus.processing, step="refine", progress=0.0)

    def _run_refinement():
        try:
            from core.refiner import refine_transcript

            def _progress(current, total):
                job_store.update(req.job_id, progress=current / total)

            result = refine_transcript(
                job.raw_transcript,
                mode=req.mode.value,
                user_instructions=req.user_instructions,
                progress_callback=_progress,
            )

            job_store.update(
                req.job_id,
                status=JobStatus.completed,
                step="refine",
                progress=1.0,
                refined_transcript=result["refined_text"],
                refinement_mode=result["mode"],
                refinement_cost=result["actual_cost"],
                sections_processed=result["sections_processed"],
            )

        except Exception as e:
            logger.error(f"Refinement failed for job {req.job_id}: {e}")
            job_store.update(req.job_id, status=JobStatus.failed, error=str(e))

    thread = threading.Thread(target=_run_refinement, daemon=True)
    thread.start()

    return RefineResponse(
        job_id=req.job_id,
        status=JobStatus.processing,
        message="Refinement started. Poll GET /jobs/{job_id} for progress.",
    )


# --- Job status ---

@app.get("/jobs/{job_id}", response_model=JobDetail)
def get_job(job_id: str) -> JobDetail:
    """Get the current status and results of a job.

    Frontend should poll this endpoint during long-running operations.
    """
    return _get_job_or_404(job_id)


@app.delete("/jobs/{job_id}")
def delete_job(job_id: str) -> dict:
    """Delete a job and its associated data."""
    if not job_store.delete(job_id):
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return {"deleted": job_id}


# --- Cost estimate ---

@app.get("/estimate/{job_id}", response_model=CostEstimateResponse)
def estimate_refinement_cost(job_id: str, mode: RefinementMode = RefinementMode.structured_prose) -> CostEstimateResponse:
    """Estimate the cost of refining a transcript before committing."""
    job = _get_job_or_404(job_id)

    if not job.raw_transcript:
        raise HTTPException(status_code=400, detail="No transcript yet. Transcribe first.")

    from core.refiner import estimate_refinement_cost as _estimate

    est = _estimate(job.raw_transcript, mode=mode.value)
    return CostEstimateResponse(**est)


# --- Export ---

@app.post("/export")
def export_to_disk(req: ExportRequest) -> dict:
    """Save a transcript to the output/ directory on the server.

    For local use. In production, the frontend would generate files
    client-side or use a storage service.
    """
    job = _get_job_or_404(req.job_id)

    if req.content == "refined":
        text = job.refined_transcript
        if not text:
            raise HTTPException(status_code=400, detail="No refined transcript. Refine first.")
        mode = req.mode or job.refinement_mode or "refined"
    else:
        text = job.raw_transcript
        if not text:
            raise HTTPException(status_code=400, detail="No raw transcript. Transcribe first.")
        mode = "raw"

    from core.exporter import export_transcript

    path = export_transcript(text, f"job_{req.job_id}", mode, format=req.format.value)
    return {"path": path}


@app.get("/download/{job_id}")
def download_transcript(job_id: str, content: str = "refined", format: str = "txt") -> PlainTextResponse:
    """Download a transcript as a text response.

    Args:
        content: "raw" or "refined"
        format: "txt" or "md"
    """
    job = _get_job_or_404(job_id)

    if content == "refined":
        text = job.refined_transcript
        if not text:
            raise HTTPException(status_code=400, detail="No refined transcript.")
        mode = job.refinement_mode or "refined"
    else:
        text = job.raw_transcript
        if not text:
            raise HTTPException(status_code=400, detail="No raw transcript.")
        mode = "raw"

    if format == "md":
        from config.settings import REFINEMENT_MODES
        base_name = f"job_{job_id}"
        mode_display = REFINEMENT_MODES.get(mode, mode)
        body = f"# Transcript: {base_name} — {mode_display}\n\n"
        sections = text.split("\n\n\n")
        body += "\n\n---\n\n".join(sections)
        media_type = "text/markdown"
    else:
        body = text
        media_type = "text/plain"

    return PlainTextResponse(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="transcript_{job_id}_{mode}.{format}"'},
    )
