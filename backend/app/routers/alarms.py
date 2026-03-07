from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AlarmCategory
from ..schemas import AlarmOut, NibpEventOut
from ..services.chart_service import (
    list_alarms,
    list_encounter_nibp_events,
    list_nibp_events,
)


router = APIRouter(tags=["alarms"])


@router.get("/uploads/{upload_id}/alarms", response_model=list[AlarmOut])
def get_upload_alarms(
    upload_id: int,
    segment_id: int | None = Query(default=None),
    category: AlarmCategory | None = Query(default=None),
    from_ts: datetime | None = Query(default=None),
    to_ts: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return list_alarms(
        db,
        upload_id=upload_id,
        segment_id=segment_id,
        category=category,
        from_ts=from_ts,
        to_ts=to_ts,
    )


@router.get("/uploads/{upload_id}/nibp-events", response_model=list[NibpEventOut])
def get_upload_nibp_events(
    upload_id: int,
    segment_id: int | None = Query(default=None),
    measurements_only: bool = Query(default=False),
    from_ts: datetime | None = Query(default=None),
    to_ts: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return list_nibp_events(
        db,
        upload_id=upload_id,
        segment_id=segment_id,
        measurements_only=measurements_only,
        from_ts=from_ts,
        to_ts=to_ts,
    )

@router.get("/encounters/{encounter_id}/nibp-events", response_model=list[NibpEventOut])
def get_encounter_nibp_events(
    encounter_id: int,
    measurements_only: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    return list_encounter_nibp_events(
        db,
        encounter_id=encounter_id,
        measurements_only=measurements_only,
    )
