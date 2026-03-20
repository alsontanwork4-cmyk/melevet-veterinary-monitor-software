from __future__ import annotations

import json
import secrets
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Encounter, Patient, Upload, UploadStatus
from ..utils import coerce_utc, utcnow
from .audit_service import log_audit_event
from .encounter_service import create_or_replace_encounter
from .upload_security import store_upload_file
from .upload_service import (
    DuplicateUploadError,
    build_selected_slice_hashes,
    create_upload_stub_from_slice_hashes,
    filter_parsed_upload_for_day_window,
    parse_monitor_export,
    persist_parsed_upload_for_existing_upload,
    summarize_parsed_upload,
)


STAGE_PHASE_WRITING = "writing_files"
STAGE_PHASE_PARSING = "parsing"
STAGE_PHASE_COMPLETED = "completed"
STAGE_PHASE_ERROR = "error"




def _staging_root() -> Path:
    root = settings.resolved_stage_storage_dir
    root.mkdir(parents=True, exist_ok=True)
    return root


def _stage_dir(stage_id: str) -> Path:
    return _staging_root() / stage_id


def _metadata_path(stage_id: str) -> Path:
    return _stage_dir(stage_id) / "metadata.json"


def _write_metadata(stage_id: str, payload: dict[str, Any]) -> None:
    stage_dir = _stage_dir(stage_id)
    stage_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = _metadata_path(stage_id)
    temp_path = metadata_path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    temp_path.replace(metadata_path)


def _read_metadata(stage_id: str) -> dict[str, Any] | None:
    metadata_path = _metadata_path(stage_id)
    if not metadata_path.exists():
        return None
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def _serialize_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    normalized = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.isoformat().replace("+00:00", "Z")


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _stage_expiry_delta() -> timedelta:
    return timedelta(seconds=max(60, settings.stage_expiry_seconds))


def _touch_metadata(metadata: dict[str, Any]) -> None:
    now = utcnow()
    metadata["updated_at"] = _serialize_dt(now)
    metadata["expires_at"] = _serialize_dt(now + _stage_expiry_delta())


def _is_expired(metadata: dict[str, Any]) -> bool:
    expires_at = _parse_dt(metadata.get("expires_at"))
    return expires_at is not None and utcnow() >= expires_at


def _require_stage_metadata(stage_id: str) -> dict[str, Any]:
    metadata = _read_metadata(stage_id)
    if metadata is None:
        raise HTTPException(status_code=404, detail="Staged upload not found")
    if _is_expired(metadata):
        delete_stage(stage_id)
        raise HTTPException(status_code=404, detail="Staged upload expired")
    return metadata


def _stage_to_api(metadata: dict[str, Any]) -> dict[str, Any]:
    discovery = metadata.get("discovery") or {}
    patient = metadata.get("patient") or {}
    return {
        "stage_id": metadata["id"],
        "status": metadata["status"],
        "phase": metadata["phase"],
        "progress_current": int(metadata.get("progress_current") or 0),
        "progress_total": int(metadata.get("progress_total") or 0),
        "created_at": metadata["created_at"],
        "updated_at": metadata.get("updated_at") or metadata["created_at"],
        "expires_at": metadata["expires_at"],
        "error_message": metadata.get("error_message"),
        "timezone": metadata["timezone"],
        "trend_frames": int(discovery.get("trend_frames") or 0),
        "nibp_frames": int(discovery.get("nibp_frames") or 0),
        "periods": int(discovery.get("periods") or 0),
        "segments": int(discovery.get("segments") or 0),
        "channels": list(discovery.get("channels") or []),
        "detected_local_dates": list(discovery.get("detected_local_dates") or []),
        "patient_id": patient.get("patient_id"),
        "patient_id_code": patient.get("patient_id_code"),
        "patient_name": patient.get("patient_name"),
        "patient_species": patient.get("patient_species"),
    }

async def create_stage(
    *,
    timezone_name: str,
    patient_id: int | None,
    patient_id_code: str | None,
    patient_name: str | None,
    patient_species: str | None,
    trend_data: UploadFile,
    trend_index: UploadFile | None,
    nibp_data: UploadFile | None,
    nibp_index: UploadFile | None,
) -> dict[str, Any]:
    stage_id = secrets.token_hex(12)
    stage_dir = _stage_dir(stage_id)
    stage_dir.mkdir(parents=True, exist_ok=True)

    now = utcnow()
    metadata: dict[str, Any] = {
        "id": stage_id,
        "status": UploadStatus.processing.value,
        "phase": STAGE_PHASE_WRITING,
        "progress_current": 0,
        "progress_total": 2,
        "created_at": _serialize_dt(now),
        "updated_at": _serialize_dt(now),
        "expires_at": _serialize_dt(now + _stage_expiry_delta()),
        "error_message": None,
        "timezone": timezone_name,
        "patient": {
            "patient_id": patient_id,
            "patient_id_code": patient_id_code,
            "patient_name": patient_name,
            "patient_species": patient_species,
        },
        "files": {},
        "discovery": {},
    }
    _write_metadata(stage_id, metadata)

    try:
        total_bytes = 0
        file_specs = [
            ("trend_data", trend_data),
            ("trend_index", trend_index),
            ("nibp_data", nibp_data),
            ("nibp_index", nibp_index),
        ]
        for field_name, upload_file in file_specs:
            if upload_file is None:
                continue
            stored_file, total_bytes = await store_upload_file(
                field_name=field_name,
                upload_file=upload_file,
                destination_dir=stage_dir,
                current_total_bytes=total_bytes,
            )
            if stored_file is not None:
                metadata["files"][field_name] = stored_file.path.name

        metadata["phase"] = STAGE_PHASE_PARSING
        metadata["progress_current"] = 1
        _touch_metadata(metadata)
        _write_metadata(stage_id, metadata)
    except Exception:
        delete_stage(stage_id)
        raise

    return _stage_to_api(metadata)


def get_stage(stage_id: str) -> dict[str, Any]:
    metadata = _require_stage_metadata(stage_id)
    _touch_metadata(metadata)
    _write_metadata(stage_id, metadata)
    return _stage_to_api(metadata)


def _read_stage_file(stage_id: str, metadata: dict[str, Any], field_name: str) -> bytes | None:
    filename = metadata.get("files", {}).get(field_name)
    if not filename:
        return None
    return (_stage_dir(stage_id) / filename).read_bytes()


def process_stage(stage_id: str) -> None:
    metadata = _read_metadata(stage_id)
    if metadata is None or _is_expired(metadata):
        delete_stage(stage_id)
        return

    try:
        parsed_upload = parse_monitor_export(
            trend_data=_read_stage_file(stage_id, metadata, "trend_data") or b"",
            trend_index=_read_stage_file(stage_id, metadata, "trend_index"),
            nibp_data=_read_stage_file(stage_id, metadata, "nibp_data"),
            nibp_index=_read_stage_file(stage_id, metadata, "nibp_index"),
        )
        summary = summarize_parsed_upload(parsed_upload, timezone_name=metadata["timezone"])
        metadata["status"] = UploadStatus.completed.value
        metadata["phase"] = STAGE_PHASE_COMPLETED
        metadata["progress_current"] = 2
        metadata["discovery"] = {
            "trend_frames": summary.trend_frames,
            "nibp_frames": summary.nibp_frames,
            "periods": summary.periods,
            "segments": summary.segments,
            "channels": [
                {
                    "source_type": channel.source_type.value,
                    "channel_index": channel.channel_index,
                    "name": channel.name,
                    "unit": channel.unit,
                    "valid_count": channel.valid_count,
                }
                for channel in summary.channels
            ],
            "detected_local_dates": summary.detected_local_dates,
        }
        _touch_metadata(metadata)
        _write_metadata(stage_id, metadata)
    except Exception as exc:
        metadata["status"] = UploadStatus.error.value
        metadata["phase"] = STAGE_PHASE_ERROR
        metadata["error_message"] = str(exc)
        _touch_metadata(metadata)
        _write_metadata(stage_id, metadata)


def delete_stage(stage_id: str) -> bool:
    stage_dir = _stage_dir(stage_id)
    if not stage_dir.exists():
        return False
    shutil.rmtree(stage_dir, ignore_errors=True)
    return True


def purge_expired_stages() -> int:
    deleted = 0
    for child in _staging_root().iterdir():
        if not child.is_dir():
            continue
        metadata = _read_metadata(child.name)
        if metadata is None or _is_expired(metadata):
            shutil.rmtree(child, ignore_errors=True)
            deleted += 1
    return deleted


def purge_expired_staged_uploads() -> int:
    return purge_expired_stages()


def _resolve_patient_for_stage(db: Session, metadata: dict[str, Any]) -> Patient:
    patient_payload = metadata["patient"]
    patient_id = patient_payload.get("patient_id")
    if patient_id is not None:
        patient = db.get(Patient, int(patient_id))
        if patient is None:
            raise ValueError("Patient not found")
        return patient

    patient_id_code = (patient_payload.get("patient_id_code") or "").strip()
    patient_name = (patient_payload.get("patient_name") or "").strip()
    patient_species = (patient_payload.get("patient_species") or "").strip()
    if not patient_id_code or not patient_name or not patient_species:
        raise ValueError("Staged upload is missing patient information")

    existing = db.scalar(select(Patient).where(Patient.patient_id_code == patient_id_code))
    if existing is not None:
        return existing

    patient = Patient(
        patient_id_code=patient_id_code,
        name=patient_name,
        species=patient_species,
    )
    db.add(patient)
    db.commit()
    db.refresh(patient)
    metadata["patient"]["patient_id"] = patient.id
    _touch_metadata(metadata)
    _write_metadata(metadata["id"], metadata)
    return patient


def save_stage_as_encounter(
    db: Session,
    *,
    stage_id: str,
    encounter_date_local: date,
    timezone_name: str,
    label: str | None,
    notes: str | None,
    actor: str = "system",
):
    metadata = _require_stage_metadata(stage_id)
    if metadata["status"] != UploadStatus.completed.value:
        raise ValueError("Staged upload is not ready to save")

    detected_dates = list((metadata.get("discovery") or {}).get("detected_local_dates") or [])
    if detected_dates and encounter_date_local.isoformat() not in detected_dates:
        raise ValueError("Selected encounter date is not available in this staged upload")

    patient = _resolve_patient_for_stage(db, metadata)
    parsed_upload = parse_monitor_export(
        trend_data=_read_stage_file(stage_id, metadata, "trend_data") or b"",
        trend_index=_read_stage_file(stage_id, metadata, "trend_index"),
        nibp_data=_read_stage_file(stage_id, metadata, "nibp_data"),
        nibp_index=_read_stage_file(stage_id, metadata, "nibp_index"),
    )
    selected_day_upload = filter_parsed_upload_for_day_window(
        parsed_upload,
        encounter_date_local=encounter_date_local,
        timezone_name=timezone_name,
    )
    if not selected_day_upload.trend_frames:
        raise ValueError("Selected encounter date has no trend rows to save")
    slice_hashes = build_selected_slice_hashes(
        selected_day_upload,
        patient_id=patient.id,
        encounter_date_local=encounter_date_local,
        timezone_name=timezone_name,
    )

    existing_encounter = db.scalar(
        select(Encounter)
        .where(Encounter.patient_id == patient.id)
        .where(Encounter.encounter_date_local == encounter_date_local)
    )
    if existing_encounter is not None:
        existing_upload = db.get(Upload, existing_encounter.upload_id)
        if existing_upload is not None and existing_upload.combined_hash == slice_hashes.combined_hash:
            encounter = create_or_replace_encounter(
                db,
                upload=existing_upload,
                patient=patient,
                encounter_date_local=encounter_date_local,
                timezone_name=timezone_name,
                label=label,
                notes=notes,
                actor=actor,
            )
            delete_stage(stage_id)
            return encounter

    created_new_upload = False
    try:
        upload = create_upload_stub_from_slice_hashes(db, patient=patient, slice_hashes=slice_hashes)
        created_new_upload = True
    except DuplicateUploadError as exc:
        upload = exc.upload

    if created_new_upload:
        log_audit_event(
            db,
            action="created",
            entity_type="upload",
            entity_id=upload.id,
            actor=actor,
            details={
                "patient_id": patient.id,
                "combined_hash": upload.combined_hash,
                "source": "staged-save",
            },
            commit=True,
        )
        upload = db.get(Upload, upload.id) or upload

    if upload.status != UploadStatus.completed:
        persist_parsed_upload_for_existing_upload(
            db,
            upload_id=upload.id,
            parsed_upload=selected_day_upload,
            timezone_name=timezone_name,
            slice_hashes=slice_hashes,
        )
    created_encounter = create_or_replace_encounter(
        db,
        upload=db.get(Upload, upload.id) or upload,
        patient=patient,
        encounter_date_local=encounter_date_local,
        timezone_name=timezone_name,
        label=label,
        notes=notes,
        actor=actor,
    )
    delete_stage(stage_id)
    return created_encounter


async def create_staged_upload(
    db: Session,
    *,
    trend_data: UploadFile,
    trend_index: UploadFile | None,
    nibp_data: UploadFile | None,
    nibp_index: UploadFile | None,
    patient_id: int | None,
    patient_id_code: str | None,
    patient_name: str | None,
    patient_species: str | None,
    timezone_name: str,
) -> dict[str, Any]:
    if patient_id is not None and db.get(Patient, patient_id) is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return await create_stage(
        timezone_name=timezone_name,
        patient_id=patient_id,
        patient_id_code=patient_id_code,
        patient_name=patient_name,
        patient_species=patient_species,
        trend_data=trend_data,
        trend_index=trend_index,
        nibp_data=nibp_data,
        nibp_index=nibp_index,
    )


def get_staged_upload(stage_id: str, *, touch: bool = True) -> dict[str, Any]:
    metadata = _read_metadata(stage_id)
    if metadata is None:
        raise FileNotFoundError(stage_id)
    if _is_expired(metadata):
        delete_stage(stage_id)
        raise FileNotFoundError(stage_id)
    if touch:
        _touch_metadata(metadata)
        _write_metadata(stage_id, metadata)
    return _stage_to_api(metadata)


def process_staged_upload(stage_id: str) -> None:
    process_stage(stage_id)


def delete_staged_upload(stage_id: str) -> bool:
    return delete_stage(stage_id)


def save_staged_upload_as_encounter(
    db: Session,
    *,
    stage_id: str,
    encounter_date_local: date,
    timezone_name: str,
    label: str | None,
    notes: str | None,
    actor: str = "system",
):
    metadata = _read_metadata(stage_id)
    if metadata is None or _is_expired(metadata):
        delete_stage(stage_id)
        raise FileNotFoundError(stage_id)
    return save_stage_as_encounter(
        db,
        stage_id=stage_id,
        encounter_date_local=encounter_date_local,
        timezone_name=timezone_name,
        label=label,
        notes=notes,
        actor=actor,
    )


def stage_storage_root() -> Path:
    return _staging_root()
