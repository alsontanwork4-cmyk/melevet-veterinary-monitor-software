from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import RLock, Thread
from typing import Literal
from uuid import uuid4

from .decode_export_service import build_decode_export_archive


DecodeJobStatus = Literal["queued", "processing", "completed", "error"]

JOB_RETENTION = timedelta(minutes=30)


def _utcnow() -> datetime:
    return datetime.now(UTC)


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
    cutoff = _utcnow() - JOB_RETENTION
    expired_ids = [job_id for job_id, job in _jobs.items() if job.updated_at < cutoff]
    for job_id in expired_ids:
        _jobs.pop(job_id, None)


def create_decode_job(*, selected_families: list[str]) -> DecodeJob:
    with _lock:
        _purge_expired_jobs()
        job = DecodeJob(
            id=uuid4().hex,
            status="queued",
            progress_percent=0,
            phase="Queued",
            detail="Waiting to start decode job",
            created_at=_utcnow(),
            updated_at=_utcnow(),
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
        job.updated_at = _utcnow()
        return job


def pop_decode_job_archive(job_id: str) -> tuple[DecodeJob | None, bytes | None]:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return None, None
        return job, job.archive_bytes


def start_decode_job(
    *,
    job_id: str,
    trend_data: bytes | None,
    trend_index: bytes | None,
    nibp_data: bytes | None,
    nibp_index: bytes | None,
    alarm_data: bytes | None,
    alarm_index: bytes | None,
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
                alarm_data=alarm_data,
                alarm_index=alarm_index,
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
