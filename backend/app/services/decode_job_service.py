from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import RLock, Thread
from typing import Literal
from uuid import uuid4

from ..utils import utcnow
from .decode_export_service import build_decode_export_archive


DecodeJobStatus = Literal["queued", "processing", "completed", "error"]
DecodeArchiveState = Literal["available", "not_found", "not_ready", "consumed", "expired", "error"]

JOB_RETENTION = timedelta(minutes=5)
MAX_RETAINED_JOBS = 20
MAX_RETAINED_ARCHIVE_BYTES = 200 * 1024 * 1024




@dataclass
class DecodeJob:
    id: str
    status: DecodeJobStatus
    progress_percent: int
    phase: str
    detail: str | None
    created_at: datetime
    updated_at: datetime
    filename: str = "decoded-records.zip"
    error_message: str | None = None
    archive_bytes: bytes | None = None
    archive_consumed_at: datetime | None = None
    selected_families: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "status": self.status,
            "progress_percent": self.progress_percent,
            "phase": self.phase,
            "detail": self.detail,
            "filename": self.filename,
            "error_message": self.error_message,
            "selected_families": list(self.selected_families),
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "updated_at": self.updated_at.isoformat().replace("+00:00", "Z"),
        }


_jobs: dict[str, DecodeJob] = {}
_lock = RLock()


def _purge_expired_jobs() -> None:
    cutoff = utcnow() - JOB_RETENTION
    expired_ids = [job_id for job_id, job in _jobs.items() if job.updated_at < cutoff]
    for job_id in expired_ids:
        _jobs.pop(job_id, None)

    terminal_jobs = [job for job in _jobs.values() if job.status in {"completed", "error"}]
    removable_jobs = sorted(terminal_jobs, key=lambda job: (job.updated_at, job.created_at))
    while len(_jobs) > MAX_RETAINED_JOBS and removable_jobs:
        removable = removable_jobs.pop(0)
        _jobs.pop(removable.id, None)

    archive_holders = [
        job for job in _jobs.values() if job.status == "completed" and job.archive_bytes is not None
    ]
    total_archive_bytes = sum(len(job.archive_bytes or b"") for job in archive_holders)
    for job in sorted(archive_holders, key=lambda candidate: (candidate.updated_at, candidate.created_at)):
        if total_archive_bytes <= MAX_RETAINED_ARCHIVE_BYTES:
            break
        if job.archive_bytes is None:
            continue
        total_archive_bytes -= len(job.archive_bytes)
        job.archive_bytes = None


def create_decode_job(*, selected_families: list[str]) -> DecodeJob:
    with _lock:
        _purge_expired_jobs()
        job = DecodeJob(
            id=uuid4().hex,
            status="queued",
            progress_percent=0,
            phase="Queued",
            detail="Waiting to start decode job",
            created_at=utcnow(),
            updated_at=utcnow(),
            selected_families=selected_families,
        )
        _jobs[job.id] = job
        return job


def get_decode_job(job_id: str) -> DecodeJob | None:
    with _lock:
        _purge_expired_jobs()
        return _jobs.get(job_id)


def update_decode_job(
    job_id: str,
    *,
    status: DecodeJobStatus | None = None,
    progress_percent: int | None = None,
    phase: str | None = None,
    detail: str | None = None,
    error_message: str | None = None,
    archive_bytes: bytes | None = None,
) -> DecodeJob | None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return None

        if status is not None:
            job.status = status
        if progress_percent is not None:
            job.progress_percent = max(0, min(100, progress_percent))
        if phase is not None:
            job.phase = phase
        job.detail = detail
        if error_message is not None:
            job.error_message = error_message
        if archive_bytes is not None:
            job.archive_bytes = archive_bytes
        job.updated_at = utcnow()
        return job


def consume_decode_job_archive(job_id: str) -> tuple[DecodeJob | None, bytes | None, DecodeArchiveState]:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return None, None, "not_found"

        if job.updated_at < (utcnow() - JOB_RETENTION):
            _jobs.pop(job_id, None)
            if job.status == "completed":
                return job, None, "expired"
            return None, None, "not_found"

        if job.status == "error":
            return job, None, "error"

        if job.status != "completed":
            return job, None, "not_ready"

        if job.archive_consumed_at is not None:
            return job, None, "consumed"

        if job.archive_bytes is None:
            return job, None, "expired"

        archive_bytes = job.archive_bytes
        job.archive_bytes = None
        job.archive_consumed_at = utcnow()
        job.phase = "Downloaded"
        job.detail = "Decode archive already downloaded"
        job.updated_at = utcnow()
        return job, archive_bytes, "available"


def start_decode_job(
    *,
    job_id: str,
    trend_data: bytes | None,
    trend_index: bytes | None,
    nibp_data: bytes | None,
    nibp_index: bytes | None,
    timezone_name: str,
) -> None:
    def run() -> None:
        try:
            update_decode_job(
                job_id,
                status="processing",
                progress_percent=2,
                phase="Starting decode",
                detail="Preparing selected record families",
            )
            archive_bytes = build_decode_export_archive(
                trend_data=trend_data,
                trend_index=trend_index,
                nibp_data=nibp_data,
                nibp_index=nibp_index,
                timezone_name=timezone_name,
                progress_callback=lambda percent, phase, detail: update_decode_job(
                    job_id,
                    status="processing",
                    progress_percent=percent,
                    phase=phase,
                    detail=detail,
                ),
            )
            update_decode_job(
                job_id,
                status="completed",
                progress_percent=100,
                phase="Ready to download",
                detail="Decoded workbooks are ready",
                archive_bytes=archive_bytes,
            )
        except Exception as exc:
            update_decode_job(
                job_id,
                status="error",
                progress_percent=100,
                phase="Decode failed",
                detail="Unable to finish workbook export",
                error_message=str(exc),
            )

    Thread(target=run, daemon=True).start()
