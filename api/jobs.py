"""Job store for tracking async processing jobs.

This module provides an in-memory job store for local development.
For production, swap InMemoryJobStore with a Supabase/Redis implementation
that implements the same interface.
"""

from __future__ import annotations

import threading
import uuid
from abc import ABC, abstractmethod
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


# Default store instance — swap this for production
job_store = InMemoryJobStore()
