from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time, timedelta
from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from ..database import SQLiteBusyError
from ..database import get_db
from ..models import Encounter, Patient, Upload
from ..schemas import (
    PaginatedPatientList,
    PaginatedPatientEncounterHistory,
    PaginatedPatientUploadHistory,
    PatientAvailableReportDate,
    PatientCreate,
    PatientDeleteResponse,
    PatientOut,
    PatientUpdate,
    PatientWithUploadCount,
)
from ..services.encounter_service import list_patient_available_report_dates, list_patient_encounters_page
from ..services.audit_service import resolve_actor_from_request
from ..services.patient_service import create_patient_record, delete_patient_hard, update_patient_record
from ..services.upload_service import list_patient_upload_history_page
from ..services.write_coordinator import ExclusiveWriteBusyError, exclusive_write


router = APIRouter(tags=["patients"])
logger = logging.getLogger(__name__)
PATIENT_DELETE_BUSY_DETAIL = (
    "Patient delete is temporarily unavailable while upload or cleanup work is in progress. Please retry in a moment."
)


def _created_at_range_start(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=UTC)


def _created_at_range_end(value: date) -> datetime:
    return datetime.combine(value + timedelta(days=1), time.min, tzinfo=UTC)


def _line_prefix_match_conditions(column, field_name: str, field_value: str):
    normalized_notes = func.lower(func.coalesce(column, ""))
    prefix = f"{field_name.lower()}:{field_value.lower()}"
    prefix_with_space = f"{field_name.lower()}: {field_value.lower()}"
    return [
        normalized_notes.like(f"{prefix}%"),
        normalized_notes.like(f"{prefix_with_space}%"),
        normalized_notes.like(f"%\n{prefix}%"),
        normalized_notes.like(f"%\n{prefix_with_space}%"),
    ]


@router.get("/patients", response_model=PaginatedPatientList)
def list_patients(
    q: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    species: Annotated[str | None, Query()] = None,
    owner_name: Annotated[str | None, Query()] = None,
    patient_name: Annotated[str | None, Query()] = None,
    gender: Annotated[str | None, Query()] = None,
    age: Annotated[str | None, Query()] = None,
    created_from: Annotated[date | None, Query()] = None,
    created_to: Annotated[date | None, Query()] = None,
    db: Session = Depends(get_db),
):
    if created_from and created_to and created_from > created_to:
        raise HTTPException(status_code=422, detail="created_from cannot be after created_to")

    conditions = []

    normalized_query = q.strip() if q else None
    if normalized_query:
        like = f"%{normalized_query}%"
        conditions.append((Patient.name.ilike(like)) | (Patient.patient_id_code.ilike(like)))

    normalized_species = species.strip() if species else None
    if normalized_species:
        conditions.append(func.lower(func.trim(Patient.species)) == normalized_species.lower())

    normalized_owner_name = owner_name.strip() if owner_name else None
    if normalized_owner_name:
        conditions.append(Patient.owner_name.ilike(f"%{normalized_owner_name}%"))

    normalized_patient_name = patient_name.strip() if patient_name else None
    if normalized_patient_name:
        conditions.append(Patient.name.ilike(f"%{normalized_patient_name}%"))

    normalized_gender = gender.strip() if gender else None
    if normalized_gender:
        conditions.append(or_(*_line_prefix_match_conditions(Patient.notes, "gender", normalized_gender)))

    normalized_age = age.strip() if age else None
    if normalized_age:
        age_like = f"%{normalized_age}%"
        conditions.append(
            or_(
                Patient.age.ilike(age_like),
                *[
                    condition
                    for condition in _line_prefix_match_conditions(Patient.notes, "age", age_like)
                ],
            )
        )

    if created_from:
        conditions.append(Patient.created_at >= _created_at_range_start(created_from))

    if created_to:
        conditions.append(Patient.created_at < _created_at_range_end(created_to))

    count_stmt = select(func.count(Patient.id)).select_from(Patient)
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total = int(db.scalar(count_stmt) or 0)

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

    if conditions:
        stmt = stmt.where(*conditions)

    rows = db.execute(stmt).all()

    return PaginatedPatientList(
        items=[
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
        ],
        total=total,
    )


@router.get("/patients/search", response_model=list[PatientOut])
def search_patients(
    q: Annotated[str, Query(min_length=1)],
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


@router.get("/patients/species", response_model=list[str])
def list_patient_species(db: Session = Depends(get_db)):
    normalized_species = func.trim(Patient.species)
    species_rows = db.execute(
        select(normalized_species)
        .where(normalized_species != "")
        .distinct()
        .order_by(func.lower(normalized_species).asc())
    ).scalars()
    return list(species_rows)


@router.get("/patients/{patient_id}", response_model=PatientOut)
def get_patient(patient_id: int, db: Session = Depends(get_db)):
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient


@router.post("/patients", response_model=PatientOut, status_code=status.HTTP_201_CREATED)
def create_patient(payload: PatientCreate, request: Request, db: Session = Depends(get_db)):
    existing = db.scalar(select(Patient).where(Patient.patient_id_code == payload.patient_id_code))
    if existing is not None:
        raise HTTPException(status_code=409, detail="patient_id_code already exists")

    return create_patient_record(db, payload.model_dump(), actor=resolve_actor_from_request(request))


@router.patch("/patients/{patient_id}", response_model=PatientOut)
def update_patient(patient_id: int, payload: PatientUpdate, request: Request, db: Session = Depends(get_db)):
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

    return update_patient_record(db, patient, changes, actor=resolve_actor_from_request(request))


@router.delete("/patients/{patient_id}", response_model=PatientDeleteResponse)
def delete_patient(patient_id: int, request: Request, db: Session = Depends(get_db)):
    started_at = perf_counter()
    try:
        with exclusive_write("patient delete", wait=False, busy_detail=PATIENT_DELETE_BUSY_DETAIL):
            stats = delete_patient_hard(db, patient_id, actor=resolve_actor_from_request(request))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Patient not found") from exc
    except (ExclusiveWriteBusyError, SQLiteBusyError):
        raise
    except Exception:
        logger.exception("Patient delete failed patient_id=%s", patient_id)
        raise

    logger.info(
        "Patient delete completed patient_id=%s deleted_upload_count=%s deleted_encounter_count=%s elapsed_ms=%.2f",
        stats.patient_id,
        stats.deleted_upload_count,
        stats.deleted_encounter_count,
        (perf_counter() - started_at) * 1000,
    )
    return PatientDeleteResponse(deleted=True, patient_id=patient_id)


@router.get("/patients/{patient_id}/uploads", response_model=PaginatedPatientUploadHistory)
def list_patient_uploads(
    patient_id: int,
    db: Session = Depends(get_db),
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    result = list_patient_upload_history_page(db, patient_id=patient_id, limit=limit, offset=offset)
    return PaginatedPatientUploadHistory(items=result.items, total=result.total, limit=limit, offset=offset)


@router.get("/patients/{patient_id}/encounters", response_model=PaginatedPatientEncounterHistory)
def get_patient_encounters(
    patient_id: int,
    db: Session = Depends(get_db),
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    result = list_patient_encounters_page(db, patient_id=patient_id, limit=limit, offset=offset)
    return PaginatedPatientEncounterHistory(items=result.items, total=result.total, limit=limit, offset=offset)


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
