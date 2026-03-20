from __future__ import annotations

import logging
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Patient, SourceType, Upload
from ..schemas import (
    ChannelOut,
    EncounterCreate,
    EncounterDeleteResponse,
    EncounterMeasurementsResponse,
    PaginatedNibpEventList,
    EncounterOut,
    EncounterUpdate,
    MeasurementPoint,
)
from ..services.chart_service import (
    list_encounter_channels,
    list_encounter_nibp_events_page,
    query_encounter_measurements,
)
from ..services.audit_service import resolve_actor_from_request
from ..services.encounter_service import create_or_replace_encounter, delete_encounter, get_encounter, update_encounter


router = APIRouter(tags=["encounters"])
logger = logging.getLogger(__name__)


@router.post("/uploads/{upload_id}/encounters", response_model=EncounterOut)
def create_upload_encounter(
    upload_id: int,
    payload: EncounterCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    upload = db.get(Upload, upload_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="Upload not found")

    patient = db.get(Patient, payload.patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    if upload.patient_id != patient.id:
        raise HTTPException(
            status_code=409,
            detail="upload_id must reference a snapshot for this patient",
        )

    try:
        return create_or_replace_encounter(
            db,
            upload=upload,
            patient=patient,
            encounter_date_local=payload.encounter_date_local,
            timezone_name=payload.timezone,
            label=payload.label,
            notes=payload.notes,
            actor=resolve_actor_from_request(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/encounters/{encounter_id}", response_model=EncounterOut)
def get_encounter_by_id(encounter_id: int, db: Session = Depends(get_db)):
    encounter = get_encounter(db, encounter_id)
    if encounter is None:
        raise HTTPException(status_code=404, detail="Encounter not found")
    return encounter


@router.patch("/encounters/{encounter_id}", response_model=EncounterOut)
def patch_encounter(encounter_id: int, payload: EncounterUpdate, request: Request, db: Session = Depends(get_db)):
    encounter = get_encounter(db, encounter_id)
    if encounter is None:
        raise HTTPException(status_code=404, detail="Encounter not found")

    try:
        return update_encounter(
            db,
            encounter=encounter,
            encounter_date_local=payload.encounter_date_local,
            timezone_name=payload.timezone,
            label=payload.label,
            notes=payload.notes,
            actor=resolve_actor_from_request(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/encounters/{encounter_id}", response_model=EncounterDeleteResponse)
def remove_encounter(encounter_id: int, request: Request, db: Session = Depends(get_db)):
    encounter = get_encounter(db, encounter_id)
    if encounter is None:
        raise HTTPException(status_code=404, detail="Encounter not found")

    delete_encounter(db, encounter, actor=resolve_actor_from_request(request))
    return EncounterDeleteResponse(deleted=True, encounter_id=encounter_id)


@router.get("/encounters/{encounter_id}/channels", response_model=list[ChannelOut])
def get_encounter_channels(
    encounter_id: int,
    source_type: str = Query(default="all"),
    db: Session = Depends(get_db),
):
    st = None
    if source_type != "all":
        try:
            st = SourceType(source_type)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid source_type") from exc

    return list_encounter_channels(db, encounter_id=encounter_id, source_type=st)


@router.get("/encounters/{encounter_id}/measurements", response_model=EncounterMeasurementsResponse)
def get_encounter_measurements(
    encounter_id: int,
    channels: str | None = Query(default=None),
    max_points: int | None = Query(default=None, ge=10, le=50000),
    source_type: SourceType = Query(default=SourceType.trend),
    db: Session = Depends(get_db),
):
    started_at = perf_counter()
    channel_ids: list[int] | None = None
    if channels:
        channel_ids = [int(token) for token in channels.split(",") if token.strip()]

    result = query_encounter_measurements(
        db,
        encounter_id=encounter_id,
        channel_ids=channel_ids,
        max_points=max_points,
        source_type=source_type,
    )

    points = [
        MeasurementPoint(
            timestamp=measurement.timestamp,
            channel_id=measurement.channel_id,
            channel_name=channel_name,
            value=measurement.value,
        )
        for measurement, channel_name in result.rows
    ]

    logger.info(
        "measurement route=get_encounter_measurements encounter_id=%s source_type=%s matched_rows=%s returned_rows=%s max_points=%s elapsed_ms=%.2f",
        encounter_id,
        source_type.value,
        result.matched_row_count,
        result.returned_row_count,
        max_points,
        (perf_counter() - started_at) * 1000,
    )
    return EncounterMeasurementsResponse(encounter_id=encounter_id, points=points)


@router.get("/encounters/{encounter_id}/nibp-events", response_model=PaginatedNibpEventList)
def get_encounter_nibp_events(
    encounter_id: int,
    measurements_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    result = list_encounter_nibp_events_page(
        db,
        encounter_id=encounter_id,
        measurements_only=measurements_only,
        limit=limit,
        offset=offset,
    )
    return PaginatedNibpEventList(items=result.items, total=result.total, limit=limit, offset=offset)
