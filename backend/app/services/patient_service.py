from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from ..models import (
    Alarm,
    Channel,
    Encounter,
    Measurement,
    NibpEvent,
    Patient,
    RecordingPeriod,
    Segment,
    Upload,
    UploadAlarmLink,
    UploadMeasurementLink,
    UploadNibpEventLink,
)


@dataclass(frozen=True)
class PatientDeleteStats:
    patient_id: int
    upload_count: int
    deleted_upload_count: int
    encounter_count_before: int
    deleted_remaining_encounters: int
    measurement_count: int
    nibp_event_count: int
    alarm_count: int
    segment_count: int
    recording_period_count: int
    channel_count: int


def prune_orphaned_canonical_rows(db: Session) -> tuple[int, int, int]:
    deleted_measurements = int(
        db.execute(
            delete(Measurement).where(~Measurement.upload_links.any()).where(Measurement.upload_id.is_(None))
        ).rowcount
        or 0
    )
    deleted_nibp = int(
        db.execute(
            delete(NibpEvent).where(~NibpEvent.upload_links.any()).where(NibpEvent.upload_id.is_(None))
        ).rowcount
        or 0
    )
    deleted_alarms = int(
        db.execute(delete(Alarm).where(~Alarm.upload_links.any()).where(Alarm.upload_id.is_(None))).rowcount or 0
    )
    return deleted_measurements, deleted_nibp, deleted_alarms


def _count_related_rows(db: Session, model, *, upload_ids: list[int]) -> int:
    if not upload_ids:
        return 0
    if model is Measurement:
        linked_count = int(
            db.scalar(select(func.count(UploadMeasurementLink.id)).where(UploadMeasurementLink.upload_id.in_(upload_ids)))
            or 0
        )
        if linked_count > 0:
            return linked_count
        return int(db.scalar(select(func.count(Measurement.id)).where(Measurement.upload_id.in_(upload_ids))) or 0)
    if model is NibpEvent:
        linked_count = int(
            db.scalar(select(func.count(UploadNibpEventLink.id)).where(UploadNibpEventLink.upload_id.in_(upload_ids)))
            or 0
        )
        if linked_count > 0:
            return linked_count
        return int(db.scalar(select(func.count(NibpEvent.id)).where(NibpEvent.upload_id.in_(upload_ids))) or 0)
    if model is Alarm:
        linked_count = int(
            db.scalar(select(func.count(UploadAlarmLink.id)).where(UploadAlarmLink.upload_id.in_(upload_ids))) or 0
        )
        if linked_count > 0:
            return linked_count
        return int(db.scalar(select(func.count(Alarm.id)).where(Alarm.upload_id.in_(upload_ids))) or 0)
    return int(
        db.scalar(select(func.count(model.id)).where(model.upload_id.in_(upload_ids)))  # type: ignore[attr-defined]
        or 0
    )


def delete_patient_hard(db: Session, patient_id: int) -> PatientDeleteStats:
    existing_patient_id = db.scalar(select(Patient.id).where(Patient.id == patient_id))
    if existing_patient_id is None:
        raise ValueError("Patient not found")

    upload_ids = list(db.scalars(select(Upload.id).where(Upload.patient_id == patient_id)).all())
    encounter_count_before = int(
        db.scalar(select(func.count(Encounter.id)).where(Encounter.patient_id == patient_id)) or 0
    )

    stats = PatientDeleteStats(
        patient_id=patient_id,
        upload_count=len(upload_ids),
        deleted_upload_count=0,
        encounter_count_before=encounter_count_before,
        deleted_remaining_encounters=0,
        measurement_count=_count_related_rows(db, Measurement, upload_ids=upload_ids),
        nibp_event_count=_count_related_rows(db, NibpEvent, upload_ids=upload_ids),
        alarm_count=_count_related_rows(db, Alarm, upload_ids=upload_ids),
        segment_count=_count_related_rows(db, Segment, upload_ids=upload_ids),
        recording_period_count=_count_related_rows(db, RecordingPeriod, upload_ids=upload_ids),
        channel_count=_count_related_rows(db, Channel, upload_ids=upload_ids),
    )

    try:
        db.execute(
            update(Patient)
            .where(Patient.id == patient_id)
            .values(preferred_encounter_id=None)
        )

        deleted_upload_count = 0
        if upload_ids:
            upload_delete_result = db.execute(delete(Upload).where(Upload.id.in_(upload_ids)))
            deleted_upload_count = int(upload_delete_result.rowcount or 0)

        remaining_encounter_count = int(
            db.scalar(select(func.count(Encounter.id)).where(Encounter.patient_id == patient_id)) or 0
        )
        deleted_remaining_encounters = 0
        if remaining_encounter_count > 0:
            encounter_delete_result = db.execute(delete(Encounter).where(Encounter.patient_id == patient_id))
            deleted_remaining_encounters = int(encounter_delete_result.rowcount or remaining_encounter_count)

        patient_delete_result = db.execute(delete(Patient).where(Patient.id == patient_id))
        if int(patient_delete_result.rowcount or 0) != 1:
            raise RuntimeError(f"Patient delete affected {patient_delete_result.rowcount or 0} rows")

        prune_orphaned_canonical_rows(db)
        db.commit()
    except Exception:
        db.rollback()
        raise

    return PatientDeleteStats(
        patient_id=stats.patient_id,
        upload_count=stats.upload_count,
        deleted_upload_count=deleted_upload_count,
        encounter_count_before=stats.encounter_count_before,
        deleted_remaining_encounters=deleted_remaining_encounters,
        measurement_count=stats.measurement_count,
        nibp_event_count=stats.nibp_event_count,
        alarm_count=stats.alarm_count,
        segment_count=stats.segment_count,
        recording_period_count=stats.recording_period_count,
        channel_count=stats.channel_count,
    )
