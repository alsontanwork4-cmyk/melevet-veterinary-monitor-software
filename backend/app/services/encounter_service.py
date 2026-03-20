from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..config import settings
from ..models import Encounter, Patient, RecordingPeriod, Upload, UploadStatus
from ..utils import coerce_utc, coerce_utc_naive, utcnow
from .audit_service import log_audit_event
from .patient_service import prune_orphaned_canonical_rows


@dataclass(frozen=True)
class PaginatedEncounterHistoryResult:
    items: list[Encounter]
    total: int


def resolve_timezone(timezone_name: str) -> tzinfo:
    normalized = timezone_name.strip()
    if normalized.upper() == "UTC":
        return timezone.utc
    try:
        return ZoneInfo(normalized)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(
            f"Unknown timezone: {timezone_name}. "
            "The timezone name may be valid, but this server is missing IANA timezone data."
        ) from exc


def encounter_day_window(encounter_date_local: date, timezone_name: str) -> tuple[datetime, datetime]:
    tz = resolve_timezone(timezone_name)
    local_start = datetime.combine(encounter_date_local, time.min, tzinfo=tz)
    local_end = local_start + timedelta(days=1) - timedelta(microseconds=1)
    return coerce_utc_naive(local_start), coerce_utc_naive(local_end)



def _expand_dates_between(start_date: date, end_date: date) -> list[str]:
    day_count = (end_date - start_date).days
    return [(start_date + timedelta(days=offset)).isoformat() for offset in range(day_count + 1)]


def detected_local_dates_for_ranges(
    ranges: list[tuple[datetime, datetime]],
    timezone_name: str,
) -> list[str]:
    if not ranges:
        return []

    tz = resolve_timezone(timezone_name)
    local_dates: set[str] = set()
    for start_time, end_time in ranges:
        local_start = coerce_utc(start_time).astimezone(tz).date()
        local_end = coerce_utc(end_time).astimezone(tz).date()
        local_dates.update(_expand_dates_between(local_start, local_end))
    return sorted(local_dates)


def detected_local_dates_for_periods(periods: list[RecordingPeriod], timezone_name: str) -> list[str]:
    ranges = [(period.start_time, period.end_time) for period in periods]
    return detected_local_dates_for_ranges(ranges, timezone_name)


def list_patient_encounters(db: Session, patient_id: int) -> list[Encounter]:
    return list(
        db.scalars(
            select(Encounter)
            .options(selectinload(Encounter.upload))
            .where(Encounter.patient_id == patient_id)
            .order_by(Encounter.encounter_date_local.desc(), Encounter.updated_at.desc(), Encounter.id.desc())
        )
    )


def list_patient_encounters_page(
    db: Session,
    *,
    patient_id: int,
    limit: int,
    offset: int,
) -> PaginatedEncounterHistoryResult:
    total = int(db.scalar(select(func.count(Encounter.id)).where(Encounter.patient_id == patient_id)) or 0)
    items = db.scalars(
        select(Encounter)
        .options(selectinload(Encounter.upload))
        .where(Encounter.patient_id == patient_id)
        .order_by(Encounter.encounter_date_local.desc(), Encounter.updated_at.desc(), Encounter.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return PaginatedEncounterHistoryResult(items=list(items), total=total)


def list_patient_available_report_dates(
    db: Session,
    patient_id: int,
) -> list[dict[str, int | str | bool | None]]:
    uploads = db.scalars(
        select(Upload)
        .where(Upload.patient_id == patient_id)
        .where(Upload.status == UploadStatus.completed)
        .order_by(Upload.upload_time.desc(), Upload.id.desc())
    ).all()
    encounters = list_patient_encounters(db, patient_id)

    report_dates: dict[str, dict[str, int | str | bool | None]] = {}
    for upload in uploads:
        for raw_date in upload.detected_local_dates or []:
            if raw_date in report_dates:
                continue
            report_dates[raw_date] = {
                "encounter_date_local": raw_date,
                "upload_id": upload.id,
                "encounter_id": None,
                "is_saved": False,
            }

    for encounter in encounters:
        raw_date = encounter.encounter_date_local.isoformat()
        report_dates[raw_date] = {
            "encounter_date_local": raw_date,
            "upload_id": encounter.upload_id,
            "encounter_id": encounter.id,
            "is_saved": True,
        }

    return sorted(
        report_dates.values(),
        key=lambda item: str(item["encounter_date_local"]),
        reverse=True,
    )


def get_encounter(db: Session, encounter_id: int) -> Encounter | None:
    return db.scalar(
        select(Encounter)
        .options(selectinload(Encounter.upload))
        .where(Encounter.id == encounter_id)
    )


def refresh_upload_detected_local_dates(
    db: Session,
    upload: Upload,
    *,
    timezone_name: str,
    commit: bool = True,
) -> list[str]:
    periods = db.scalars(
        select(RecordingPeriod)
        .where(RecordingPeriod.upload_id == upload.id)
        .order_by(RecordingPeriod.start_time.asc())
    ).all()
    upload.detected_local_dates = detected_local_dates_for_periods(periods, timezone_name)
    db.add(upload)
    if commit:
        db.commit()
        db.refresh(upload)
    return list(upload.detected_local_dates)


def _default_encounter_label(encounter_date_local: date) -> str:
    return f"Encounter {encounter_date_local.isoformat()}"


def _set_upload_superseded(db: Session, upload_id: int) -> None:
    upload = db.get(Upload, upload_id)
    if upload is None:
        return
    upload.superseded_at = utcnow()
    db.add(upload)
    db.commit()


def delete_upload_if_orphaned(
    db: Session,
    upload_id: int,
    *,
    immediate: bool = False,
    actor: str = "system",
) -> bool:
    upload = db.get(Upload, upload_id)
    if upload is None:
        return False

    encounter_count = db.scalar(select(func.count(Encounter.id)).where(Encounter.upload_id == upload_id)) or 0
    if encounter_count > 0:
        return False

    if not immediate:
        reference_time = upload.completed_at or upload.upload_time
        if reference_time is None:
            return False
        if coerce_utc(utcnow()) - coerce_utc(reference_time) < timedelta(
            days=max(1, settings.orphan_upload_retention_days)
        ):
            return False

    log_audit_event(
        db,
        action="deleted",
        entity_type="upload",
        entity_id=upload.id,
        actor=actor,
        details={
            "patient_id": upload.patient_id,
            "combined_hash": upload.combined_hash,
            "status": upload.status.value,
            "reason": "orphaned-upload-cleanup",
        },
    )
    db.delete(upload)
    db.flush()
    prune_orphaned_canonical_rows(db)
    db.commit()
    return True


def purge_stale_orphan_uploads(db: Session) -> int:
    uploads = db.scalars(select(Upload).options(selectinload(Upload.encounters))).all()
    deleted = 0
    for upload in uploads:
        if upload.encounters:
            continue
        if delete_upload_if_orphaned(db, upload.id, immediate=False, actor="system"):
            deleted += 1
    return deleted


def create_or_replace_encounter(
    db: Session,
    *,
    upload: Upload,
    patient: Patient,
    encounter_date_local: date,
    timezone_name: str,
    label: str | None,
    notes: str | None,
    actor: str = "system",
) -> Encounter:
    if upload.status != UploadStatus.completed:
        raise ValueError("Upload must be completed before creating an encounter")

    detected_dates = upload.detected_local_dates or []
    if detected_dates and encounter_date_local.isoformat() not in detected_dates:
        raise ValueError("Selected encounter date is not available in this upload")

    existing = db.scalar(
        select(Encounter)
        .options(selectinload(Encounter.upload))
        .where(Encounter.patient_id == patient.id)
        .where(Encounter.encounter_date_local == encounter_date_local)
    )

    if existing is None:
        encounter = Encounter(
            patient_id=patient.id,
            upload_id=upload.id,
            encounter_date_local=encounter_date_local,
            timezone=timezone_name,
            label=label.strip() if label and label.strip() else _default_encounter_label(encounter_date_local),
            notes=notes,
        )
        db.add(encounter)
        db.commit()
        db.refresh(encounter)
        log_audit_event(
            db,
            action="created",
            entity_type="encounter",
            entity_id=encounter.id,
            actor=actor,
            details={
                "patient_id": patient.id,
                "upload_id": upload.id,
                "encounter_date_local": encounter.encounter_date_local.isoformat(),
                "timezone": encounter.timezone,
            },
            commit=True,
        )
        db.refresh(encounter)
        return encounter

    previous_upload_id = existing.upload_id
    existing.upload_id = upload.id
    existing.timezone = timezone_name
    existing.label = label.strip() if label and label.strip() else existing.label or _default_encounter_label(encounter_date_local)
    existing.notes = notes
    db.add(existing)
    db.commit()
    db.refresh(existing)
    log_audit_event(
        db,
        action="updated",
        entity_type="encounter",
        entity_id=existing.id,
        actor=actor,
        details={
            "patient_id": patient.id,
            "previous_upload_id": previous_upload_id,
            "upload_id": upload.id,
            "encounter_date_local": existing.encounter_date_local.isoformat(),
            "timezone": existing.timezone,
        },
        commit=True,
    )
    db.refresh(existing)

    if previous_upload_id != upload.id:
        _set_upload_superseded(db, previous_upload_id)
        delete_upload_if_orphaned(db, previous_upload_id, immediate=True, actor=actor)
        from .upload_maintenance_service import run_opportunistic_maintenance

        run_opportunistic_maintenance(bind=db.get_bind())

    return existing


def update_encounter(
    db: Session,
    *,
    encounter: Encounter,
    encounter_date_local: date | None,
    timezone_name: str | None,
    label: str | None,
    notes: str | None,
    actor: str = "system",
) -> Encounter:
    previous_values = {
        "encounter_date_local": encounter.encounter_date_local.isoformat(),
        "timezone": encounter.timezone,
        "label": encounter.label,
        "notes": encounter.notes,
    }
    next_date = encounter_date_local or encounter.encounter_date_local
    if next_date != encounter.encounter_date_local:
        detected_dates = encounter.upload.detected_local_dates if encounter.upload is not None else []
        if detected_dates and next_date.isoformat() not in detected_dates:
            raise ValueError("Selected encounter date is not available in this upload")

        conflicting = db.scalar(
            select(Encounter)
            .where(Encounter.patient_id == encounter.patient_id)
            .where(Encounter.encounter_date_local == next_date)
            .where(Encounter.id != encounter.id)
        )
        if conflicting is not None:
            raise ValueError("Patient already has an encounter for that date")

    encounter.encounter_date_local = next_date
    if timezone_name is not None:
        encounter.timezone = timezone_name
    if label is not None:
        trimmed = label.strip()
        encounter.label = trimmed or _default_encounter_label(encounter.encounter_date_local)
    if notes is not None:
        encounter.notes = notes

    db.add(encounter)
    db.commit()
    db.refresh(encounter)
    log_audit_event(
        db,
        action="updated",
        entity_type="encounter",
        entity_id=encounter.id,
        actor=actor,
        details={
            "previous_values": previous_values,
            "encounter_date_local": encounter.encounter_date_local.isoformat(),
            "timezone": encounter.timezone,
            "label": encounter.label,
        },
        commit=True,
    )
    db.refresh(encounter)
    return encounter


def delete_encounter(db: Session, encounter: Encounter, *, actor: str = "system") -> None:
    upload_id = encounter.upload_id
    encounter_details = {
        "patient_id": encounter.patient_id,
        "upload_id": encounter.upload_id,
        "encounter_date_local": encounter.encounter_date_local.isoformat(),
        "timezone": encounter.timezone,
        "label": encounter.label,
    }
    patient = db.get(Patient, encounter.patient_id)
    if patient is not None and patient.preferred_encounter_id == encounter.id:
        patient.preferred_encounter_id = None
        db.add(patient)
    db.delete(encounter)
    log_audit_event(
        db,
        action="deleted",
        entity_type="encounter",
        entity_id=encounter.id,
        actor=actor,
        details=encounter_details,
    )
    db.commit()
    delete_upload_if_orphaned(db, upload_id, immediate=True, actor=actor)
    from .upload_maintenance_service import run_opportunistic_maintenance

    run_opportunistic_maintenance(bind=db.get_bind())
