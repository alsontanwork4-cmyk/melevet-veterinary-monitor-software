from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from ..database import run_with_sqlite_retry
from ..models import Encounter, Measurement, NibpEvent, Patient, Upload
from .audit_service import log_audit_event


@dataclass(frozen=True)
class PatientDeleteStats:
    patient_id: int
    deleted_upload_count: int
    deleted_encounter_count: int

    @property
    def upload_count(self) -> int:
        return self.deleted_upload_count

    @property
    def encounter_count_before(self) -> int:
        return self.deleted_encounter_count


def prune_orphaned_canonical_rows(db: Session) -> tuple[int, int]:
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
    return deleted_measurements, deleted_nibp


def create_patient_record(db: Session, payload: dict[str, Any], *, actor: str) -> Patient:
    patient = Patient(**payload)
    db.add(patient)
    db.commit()
    db.refresh(patient)
    log_audit_event(
        db,
        action="created",
        entity_type="patient",
        entity_id=patient.id,
        actor=actor,
        details={
            "patient_id_code": patient.patient_id_code,
            "name": patient.name,
            "species": patient.species,
        },
        commit=True,
    )
    db.refresh(patient)
    return patient


def update_patient_record(db: Session, patient: Patient, changes: dict[str, Any], *, actor: str) -> Patient:
    previous_values = {key: getattr(patient, key) for key in changes}
    for key, value in changes.items():
        setattr(patient, key, value)

    db.add(patient)
    db.commit()
    db.refresh(patient)
    log_audit_event(
        db,
        action="updated",
        entity_type="patient",
        entity_id=patient.id,
        actor=actor,
        details={
            "changes": changes,
            "previous_values": previous_values,
        },
        commit=True,
    )
    db.refresh(patient)
    return patient


def delete_patient_hard(db: Session, patient_id: int, *, actor: str = "system") -> PatientDeleteStats:
    existing_patient_id = db.scalar(select(Patient.id).where(Patient.id == patient_id))
    if existing_patient_id is None:
        raise ValueError("Patient not found")

    deleted_upload_count = 0
    deleted_encounter_count = 0
    patient_snapshot = db.get(Patient, patient_id)
    encounter_snapshots = list(db.scalars(select(Encounter).where(Encounter.patient_id == patient_id)))
    upload_snapshots = list(db.scalars(select(Upload).where(Upload.patient_id == patient_id)))

    def _delete_operation() -> None:
        nonlocal deleted_upload_count, deleted_encounter_count
        db.execute(update(Patient).where(Patient.id == patient_id).values(preferred_encounter_id=None))

        for encounter in encounter_snapshots:
            log_audit_event(
                db,
                action="deleted",
                entity_type="encounter",
                entity_id=encounter.id,
                actor=actor,
                details={
                    "patient_id": encounter.patient_id,
                    "upload_id": encounter.upload_id,
                    "encounter_date_local": encounter.encounter_date_local.isoformat(),
                    "reason": "patient-delete",
                },
            )

        for upload in upload_snapshots:
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
                    "reason": "patient-delete",
                },
            )

        deleted_encounter_count = int(
            db.execute(delete(Encounter).where(Encounter.patient_id == patient_id)).rowcount or 0
        )
        deleted_upload_count = int(
            db.execute(delete(Upload).where(Upload.patient_id == patient_id)).rowcount or 0
        )

        patient_delete_result = db.execute(delete(Patient).where(Patient.id == patient_id))
        if int(patient_delete_result.rowcount or 0) != 1:
            raise RuntimeError(f"Patient delete affected {patient_delete_result.rowcount or 0} rows")

        prune_orphaned_canonical_rows(db)
        log_audit_event(
            db,
            action="deleted",
            entity_type="patient",
            entity_id=patient_id,
            actor=actor,
            details={
                "patient_id_code": patient_snapshot.patient_id_code if patient_snapshot is not None else None,
                "name": patient_snapshot.name if patient_snapshot is not None else None,
                "deleted_upload_count": deleted_upload_count,
                "deleted_encounter_count": deleted_encounter_count,
            },
        )
        db.commit()

    run_with_sqlite_retry(db, _delete_operation, operation_name=f"patient delete {patient_id}")

    return PatientDeleteStats(
        patient_id=patient_id,
        deleted_upload_count=deleted_upload_count,
        deleted_encounter_count=deleted_encounter_count,
    )
