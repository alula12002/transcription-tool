"""Pydantic models for API request/response schemas."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class RefinementMode(str, Enum):
    raw_cleanup = "raw_cleanup"
    structured_prose = "structured_prose"
    summary = "summary"


class ExportFormat(str, Enum):
    txt = "txt"
    md = "md"


# --- Upload ---

class UploadResponse(BaseModel):
    job_id: str
    status: JobStatus
    num_files_found: int = 0
    num_chunks: int = 0
    total_duration_seconds: float = 0.0
    estimated_cost: float = 0.0
    skipped_files: list[str] = Field(default_factory=list)


# --- Transcribe ---

class TranscribeRequest(BaseModel):
    job_id: str
    language: str = "en"
    parallel: bool = False


class TranscribeResponse(BaseModel):
    job_id: str
    status: JobStatus
    message: str = ""


# --- Refine ---

class RefineRequest(BaseModel):
    job_id: str
    mode: RefinementMode = RefinementMode.structured_prose
    user_instructions: Optional[str] = None
    parallel: bool = False


class RefineResponse(BaseModel):
    job_id: str
    status: JobStatus
    message: str = ""


# --- Job status ---

class JobDetail(BaseModel):
    job_id: str
    status: JobStatus
    step: str = ""  # "upload", "transcribe", "refine"
    progress: float = 0.0  # 0.0 to 1.0
    error: Optional[str] = None

    # Upload results
    num_files_found: int = 0
    num_chunks: int = 0
    total_duration_seconds: float = 0.0
    upload_cost_estimate: float = 0.0
    skipped_files: list[str] = Field(default_factory=list)
    chunk_paths: list[str] = Field(default_factory=list)

    # Transcription results
    raw_transcript: Optional[str] = None
    transcription_cost: float = 0.0
    processing_time_seconds: float = 0.0

    # Refinement results
    refined_transcript: Optional[str] = None
    refinement_mode: Optional[str] = None
    refinement_cost: float = 0.0
    sections_processed: int = 0


# --- Export ---

class ExportRequest(BaseModel):
    job_id: str
    format: ExportFormat = ExportFormat.txt
    content: str = "refined"  # "raw" or "refined"
    mode: Optional[str] = None  # refinement mode for filename


# --- Cost estimate ---

class CostEstimateResponse(BaseModel):
    estimated_cost: float
    estimated_input_tokens: int
    estimated_output_tokens: int
