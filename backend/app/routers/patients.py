from __future__ import annotations

import logging
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from ..database import get_db
from ..models import Encounter, Patient, Upload
from ..schemas import (
    PatientAvailableReportDate,
    PatientCreate,
    PatientDeleteResponse,
    PatientEncounterHistoryItem,
    PatientOut,
    PatientUpdate,
    PatientUploadHistoryItem,
    PatientWithUploadCount,
)
from ..services.encounter_service import list_patient_available_report_dates, list_patient_encounters
from ..services.patient_service import delete_patient_hard
from ..services.upload_service import fail_stale_upload_if_needed


router = APIRouter(tags=["patients"])
logger = logging.getLogger(__name__)


@router.get("/patients", response_model=list[PatientWithUploadCount])
def list_patients(
    q: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    preferred_encounter = aliased(Encounter)
    upload_stats = (
        select(
            Upload.patient_id.label("patient_id"),
            func.count(Upload.id).label("upload_count"),
            func.max(Upload.upload_time).label("last_upload_time"),
        )
        .group_by(Upload.patient_id)
        .subquery()
    )
    encounter_stats = (
        select(
            Encounter.patient_id.label("patient_id"),
            func.max(Encounter.encounter_date_local).label("latest_report_date"),
        )
        .group_by(Encounter.patient_id)
        .subquery()
    )
    stmt = (
        select(
            Patient.id,
            Patient.patient_id_code,
            Patient.name,
            Patient.species,
            Patient.age,
            Patient.owner_name,
            Patient.notes,
            Patient.preferred_encounter_id,
            Patient.created_at,
            upload_stats.c.upload_count,
            upload_stats.c.last_upload_time,
            encounter_stats.c.latest_report_date,
            func.coalesce(
                preferred_encounter.encounter_date_local,
                encounter_stats.c.latest_report_date,
            ).label("report_date"),
        )
        .select_from(Patient)
        .outerjoin(upload_stats, upload_stats.c.patient_id == Patient.id)
        .outerjoin(encounter_stats, encounter_stats.c.patient_id == Patient.id)
        .outerjoin(
            preferred_encounter,
            (preferred_encounter.id == Patient.preferred_encounter_id) & (preferred_encounter.patient_id == Patient.id),
        )
        .order_by(Patient.created_at.desc())
        .offset(offset)
        .limit(limit)
    )

    if q:
        like = f"%{q}%"
        stmt = stmt.where((Patient.name.ilike(like)) | (Patient.patient_id_code.ilike(like)))

    rows = db.execute(stmt).all()

    return [
        PatientWithUploadCount(
            id=row.id,
            patient_id_code=row.patient_id_code,
            name=row.name,
            species=row.species,
            age=row.age,
            owner_name=row.owner_name,
            notes=row.notes,
            preferred_encounter_id=row.preferred_encounter_id,
            created_at=row.created_at,
            upload_count=int(row.upload_count or 0),
            last_upload_time=row.last_upload_time,
            latest_report_date=row.latest_report_date,
            report_date=row.report_date,
        )
        for row in rows
    ]


@router.get("/patients/{patient_id}", response_model=PatientOut)
def get_patient(patient_id: int, db: Session = Depends(get_db)):
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient


@router.get("/patients/search", response_model=list[PatientOut])
def search_patients(
    q: str = Query(min_length=1),
    db: Session = Depends(get_db),
):
    like = f"%{q}%"
    patients = db.scalars(
        select(Patient)
        .where((Patient.name.ilike(like)) | (Patient.patient_id_code.ilike(like)))
        .order_by(Patient.name.asc())
        .limit(10)
    ).all()
    return list(patients)


@router.post("/patients", response_model=PatientOut, status_code=status.HTTP_201_CREATED)
def create_patient(payload: PatientCreate, db: Session = Depends(get_db)):
    existing = db.scalar(select(Patient).where(Patient.patient_id_code == payload.patient_id_code))
    if existing is not None:
        raise HTTPException(status_code=409, detail="patient_id_code already exists")

    patient = Patient(**payload.model_dump())
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient


@router.patch("/patients/{patient_id}", response_model=PatientOut)
def update_patient(patient_id: int, payload: PatientUpdate, db: Session = Depends(get_db)):
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    changes = payload.model_dump(exclude_unset=True)
    next_patient_id_code = changes.get("patient_id_code")
    if next_patient_id_code is not None and next_patient_id_code != patient.patient_id_code:
        existing = db.scalar(select(Patient).where(Patient.patient_id_code == next_patient_id_code))
        if existing is not None and existing.id != patient_id:
            raise HTTPException(status_code=409, detail="patient_id_code already exists")

    if "preferred_encounter_id" in changes:
        next_preferred_encounter_id = changes["preferred_encounter_id"]
        if next_preferred_encounter_id is not None:
            preferred_encounter = db.get(Encounter, next_preferred_encounter_id)
            if preferred_encounter is None or preferred_encounter.patient_id != patient_id:
                raise HTTPException(
                    status_code=409,
                    detail="preferred_encounter_id must reference an encounter for this patient",
                )

    for key, value in changes.items():
        setattr(patient, key, value)

    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient


@router.delete("/patients/{patient_id}", response_model=PatientDeleteResponse)
def delete_patient(patient_id: int, db: Session = Depends(get_db)):
    started_at = perf_counter()
    try:
        stats = delete_patient_hard(db, patient_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Patient not found") from exc
    except Exception:
        logger.exception("Patient delete failed patient_id=%s", patient_id)
        raise

    logger.info(
        "Patient delete completed patient_id=%s upload_count=%s deleted_upload_count=%s encounter_count_before=%s deleted_remaining_encounters=%s measurement_count=%s nibp_event_count=%s alarm_count=%s segment_count=%s recording_period_count=%s channel_count=%s elapsed_ms=%.2f",
        stats.patient_id,
        stats.upload_count,
        stats.deleted_upload_count,
        stats.encounter_count_before,
        stats.deleted_remaining_encounters,
        stats.measurement_count,
        stats.nibp_event_count,
        stats.alarm_count,
        stats.segment_count,
        stats.recording_period_count,
        stats.channel_count,
        (perf_counter() - started_at) * 1000,
    )
    return PatientDeleteResponse(deleted=True, patient_id=patient_id)


@router.get("/patients/{patient_id}/uploads", response_model=list[PatientUploadHistoryItem])
def list_patient_uploads(patient_id: int, db: Session = Depends(get_db)):
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    uploads = db.scalars(
        select(Upload).where(Upload.patient_id == patient_id).order_by(Upload.upload_time.desc())
    ).all()
    for upload in uploads:
        fail_stale_upload_if_needed(db, upload)
    return list(uploads)


@router.get("/patients/{patient_id}/encounters", response_model=list[PatientEncounterHistoryItem])
def get_patient_encounters(patient_id: int, db: Session = Depends(get_db)):
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    encounters = list_patient_encounters(db, patient_id)
    return list(encounters)


@router.get("/patients/{patient_id}/available-report-dates", response_model=list[PatientAvailableReportDate])
def get_patient_available_report_dates(patient_id: int, db: Session = Depends(get_db)):
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    available_dates = list_patient_available_report_dates(db, patient_id)
    return [
        PatientAvailableReportDate(
            encounter_date_local=item["encounter_date_local"],
            upload_id=int(item["upload_id"]),
            encounter_id=int(item["encounter_id"]) if item["encounter_id"] is not None else None,
            is_saved=bool(item["is_saved"]),
        )
        for item in available_dates
    ]
