"""Job store for tracking async processing jobs.

This module provides an in-memory job store for local development and a
file-backed store for production (e.g. a Railway persistent volume).

Set the JOB_STORE_PATH environment variable to a directory path to enable
the file-backed store. When unset, falls back to in-memory.

Example (Railway):
    JOB_STORE_PATH=/data/jobs
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from api.schemas import JobDetail, JobStatus


class JobStore(ABC):
    """Abstract interface for job persistence.

    Implement this with Supabase, Redis, or any other backend.
    The API layer only depends on this interface, not the implementation.
    """

    @abstractmethod
    def create(self) -> JobDetail:
        """Create a new job and return it."""
        ...

    @abstractmethod
    def get(self, job_id: str) -> Optional[JobDetail]:
        """Get a job by ID, or None if not found."""
        ...

    @abstractmethod
    def update(self, job_id: str, **kwargs) -> JobDetail:
        """Update fields on an existing job and return it."""
        ...

    @abstractmethod
    def delete(self, job_id: str) -> bool:
        """Delete a job. Returns True if it existed."""
        ...


class InMemoryJobStore(JobStore):
    """In-memory job store for local development.

    Jobs are lost when the server restarts. Replace with a persistent
    implementation (Supabase, Redis, Postgres) for production.

    Thread-safe: all operations are protected by a lock to prevent
    race conditions when background threads update job state while
    the main thread reads it.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, JobDetail] = {}
        self._lock = threading.Lock()

    def create(self) -> JobDetail:
        job_id = uuid.uuid4().hex[:12]
        job = JobDetail(job_id=job_id, status=JobStatus.pending)
        with self._lock:
            self._jobs[job_id] = job
        return job

    def get(self, job_id: str) -> Optional[JobDetail]:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **kwargs) -> JobDetail:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(f"Job {job_id} not found")
            updated = job.model_copy(update=kwargs)
            self._jobs[job_id] = updated
            return updated

    def delete(self, job_id: str) -> bool:
        with self._lock:
            return self._jobs.pop(job_id, None) is not None


class FileJobStore(JobStore):
    """File-backed job store for production deployments.

    Each job is stored as a JSON file under `directory`.  Survives server
    restarts and redeploys as long as the directory is on a persistent volume.

    Thread-safe: a per-job lock prevents torn writes when multiple background
    threads update the same job simultaneously.
    """

    def __init__(self, directory: str | Path) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()  # guards file enumeration / creation

    def _path(self, job_id: str) -> Path:
        return self._dir / f"{job_id}.json"

    def _write(self, job: JobDetail) -> None:
        tmp = self._path(job.job_id).with_suffix(".tmp")
        tmp.write_text(job.model_dump_json(), encoding="utf-8")
        tmp.replace(self._path(job.job_id))  # atomic on POSIX

    def create(self) -> JobDetail:
        job_id = uuid.uuid4().hex[:12]
        job = JobDetail(job_id=job_id, status=JobStatus.pending)
        with self._lock:
            self._write(job)
        return job

    def get(self, job_id: str) -> Optional[JobDetail]:
        path = self._path(job_id)
        try:
            data = path.read_text(encoding="utf-8")
            return JobDetail.model_validate(json.loads(data))
        except FileNotFoundError:
            return None

    def update(self, job_id: str, **kwargs) -> JobDetail:
        path = self._path(job_id)
        with self._lock:
            try:
                data = path.read_text(encoding="utf-8")
            except FileNotFoundError:
                raise KeyError(f"Job {job_id} not found")
            job = JobDetail.model_validate(json.loads(data))
            updated = job.model_copy(update=kwargs)
            self._write(updated)
            return updated

    def delete(self, job_id: str) -> bool:
        try:
            self._path(job_id).unlink()
            return True
        except FileNotFoundError:
            return False


# ---------------------------------------------------------------------------
# Default store instance
# Set JOB_STORE_PATH to a directory (e.g. /data/jobs on a Railway volume)
# to persist jobs across restarts.  Otherwise falls back to in-memory.
# ---------------------------------------------------------------------------
_store_path = os.environ.get("JOB_STORE_PATH", "").strip()
if _store_path:
    job_store: JobStore = FileJobStore(_store_path)
else:
    job_store: JobStore = InMemoryJobStore()
