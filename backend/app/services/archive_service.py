from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import APP_VERSION, settings
from ..models import (
    Encounter,
    Measurement,
    NibpEvent,
    Upload,
    UploadMeasurementLink,
    UploadNibpEventLink,
    UploadStatus,
)
from ..schemas import ArchiveOut
from ..utils import coerce_utc, utcnow
from .audit_service import log_audit_event
from .patient_service import prune_orphaned_canonical_rows


ARCHIVE_SCHEMA_VERSION = 1


def _archive_timestamp() -> datetime:
    return utcnow().astimezone(UTC)


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    normalized = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.isoformat().replace("+00:00", "Z")


def archive_file_path(archive_id: str) -> Path:
    normalized = Path(archive_id).name
    path = settings.archive_dir_path / normalized
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(archive_id)
    return path


def _eligible_uploads(db: Session) -> list[Upload]:
    retention_days = settings.archive_retention_days
    if retention_days is None:
        return []

    cutoff = coerce_utc(utcnow()) - timedelta(days=max(1, retention_days))
    uploads = db.scalars(
        select(Upload)
        .where(Upload.status == UploadStatus.completed)
        .where(Upload.archived_at.is_(None))
        .order_by(Upload.completed_at.asc(), Upload.upload_time.asc(), Upload.id.asc())
    ).all()
    return [
        upload
        for upload in uploads
        if coerce_utc(upload.completed_at or upload.upload_time or utcnow()) <= cutoff
    ]


def _measurement_rows(db: Session, upload_id: int) -> list[dict[str, object | None]]:
    rows = db.execute(
        select(UploadMeasurementLink, Measurement)
        .join(Measurement, Measurement.id == UploadMeasurementLink.measurement_id)
        .where(UploadMeasurementLink.upload_id == upload_id)
        .order_by(UploadMeasurementLink.timestamp.asc(), UploadMeasurementLink.id.asc())
    ).all()
    return [
        {
            "measurement_id": measurement.id,
            "timestamp": _serialize_datetime(measurement.timestamp),
            "segment_id": link.segment_id,
            "channel_id": link.channel_id,
            "value": measurement.value,
            "dedup_key": measurement.dedup_key,
        }
        for link, measurement in rows
    ]


def _nibp_rows(db: Session, upload_id: int) -> list[dict[str, object | None]]:
    rows = db.execute(
        select(UploadNibpEventLink, NibpEvent)
        .join(NibpEvent, NibpEvent.id == UploadNibpEventLink.nibp_event_id)
        .where(UploadNibpEventLink.upload_id == upload_id)
        .order_by(UploadNibpEventLink.timestamp.asc(), UploadNibpEventLink.id.asc())
    ).all()
    return [
        {
            "nibp_event_id": nibp_event.id,
            "timestamp": _serialize_datetime(nibp_event.timestamp),
            "segment_id": link.segment_id,
            "channel_values": json.dumps(nibp_event.channel_values, sort_keys=True),
            "has_measurement": nibp_event.has_measurement,
            "dedup_key": nibp_event.dedup_key,
        }
        for link, nibp_event in rows
    ]


def _csv_bytes(rows: list[dict[str, object | None]]) -> bytes:
    buffer = io.StringIO()
    fieldnames = list(rows[0].keys()) if rows else []
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    if fieldnames:
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return buffer.getvalue().encode("utf-8")


def _archive_manifest(
    upload: Upload,
    *,
    archive_id: str,
    archived_at: datetime,
    encounter_ids: list[int],
    measurement_count: int,
    nibp_event_count: int,
) -> dict[str, object]:
    return {
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "app_version": APP_VERSION,
        "archive_id": archive_id,
        "archived_at": _serialize_datetime(archived_at),
        "upload_id": upload.id,
        "patient_id": upload.patient_id,
        "encounter_ids": encounter_ids,
        "measurement_count": measurement_count,
        "nibp_event_count": nibp_event_count,
    }


def _detach_canonical_rows_for_upload(db: Session, upload_id: int) -> None:
    measurements = db.scalars(
        select(Measurement).where(Measurement.upload_id == upload_id).where(~Measurement.upload_links.any())
    ).all()
    for row in measurements:
        row.upload_id = None
        db.add(row)

    nibp_events = db.scalars(
        select(NibpEvent).where(NibpEvent.upload_id == upload_id).where(~NibpEvent.upload_links.any())
    ).all()
    for row in nibp_events:
        row.upload_id = None
        db.add(row)


def _archive_upload(db: Session, upload: Upload, *, actor: str) -> ArchiveOut:
    archived_at = _archive_timestamp()
    archive_id = f"archive-{archived_at.strftime('%Y%m%d-%H%M%S')}-{upload.id}.zip"
    archive_path = settings.archive_dir_path / archive_id

    measurement_rows = _measurement_rows(db, upload.id)
    nibp_rows = _nibp_rows(db, upload.id)
    encounter_ids = list(db.scalars(select(Encounter.id).where(Encounter.upload_id == upload.id).order_by(Encounter.id.asc())))
    manifest = _archive_manifest(
        upload,
        archive_id=archive_id,
        archived_at=archived_at,
        encounter_ids=encounter_ids,
        measurement_count=len(measurement_rows),
        nibp_event_count=len(nibp_rows),
    )

    with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
        archive.writestr("measurements.csv", _csv_bytes(measurement_rows))
        archive.writestr("nibp_events.csv", _csv_bytes(nibp_rows))

    db.execute(delete(UploadMeasurementLink).where(UploadMeasurementLink.upload_id == upload.id))
    db.execute(delete(UploadNibpEventLink).where(UploadNibpEventLink.upload_id == upload.id))
    _detach_canonical_rows_for_upload(db, upload.id)
    prune_orphaned_canonical_rows(db)

    upload.archived_at = archived_at
    upload.archive_id = archive_id
    db.add(upload)
    log_audit_event(
        db,
        action="archived",
        entity_type="upload",
        entity_id=upload.id,
        actor=actor,
        details={
            "archive_id": archive_id,
            "measurement_count": len(measurement_rows),
            "nibp_event_count": len(nibp_rows),
        },
    )
    db.commit()
    db.refresh(upload)

    stat = archive_path.stat()
    return ArchiveOut(
        id=archive_id,
        filename=archive_id,
        size_bytes=stat.st_size,
        created_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
        upload_id=upload.id,
        patient_id=upload.patient_id,
        encounter_ids=encounter_ids,
        measurement_count=len(measurement_rows),
        nibp_event_count=len(nibp_rows),
    )


def run_archival(db: Session, *, actor: str = "system") -> list[ArchiveOut]:
    archives: list[ArchiveOut] = []
    for upload in _eligible_uploads(db):
        archives.append(_archive_upload(db, upload, actor=actor))
    return archives


def list_archives() -> list[ArchiveOut]:
    items: list[ArchiveOut] = []
    for path in sorted(settings.archive_dir_path.glob("archive-*.zip"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            with zipfile.ZipFile(path, mode="r") as archive:
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        except Exception:
            manifest = {}
        stat = path.stat()
        items.append(
            ArchiveOut(
                id=path.name,
                filename=path.name,
                size_bytes=stat.st_size,
                created_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                upload_id=int(manifest.get("upload_id") or 0),
                patient_id=int(manifest["patient_id"]) if manifest.get("patient_id") is not None else None,
                encounter_ids=[int(item) for item in manifest.get("encounter_ids", []) if isinstance(item, int) or str(item).isdigit()],
                measurement_count=int(manifest.get("measurement_count") or 0),
                nibp_event_count=int(manifest.get("nibp_event_count") or 0),
            )
        )
    return items
