from __future__ import annotations

from datetime import datetime
import logging
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import SourceType
from ..schemas import (
    ChannelOut,
    MeasurementPoint,
    MeasurementsResponse,
    RecordingPeriodOut,
    SegmentOut,
    UploadMeasurementsResponse,
)
from ..services.chart_service import (
    list_periods,
    list_segment_channels,
    list_segments,
    list_upload_channels,
    query_measurements,
    query_upload_measurements,
)


router = APIRouter(tags=["sessions"])
logger = logging.getLogger(__name__)


@router.get("/uploads/{upload_id}/periods", response_model=list[RecordingPeriodOut])
def get_upload_periods(upload_id: int, db: Session = Depends(get_db)):
    return list_periods(db, upload_id)


@router.get("/periods/{period_id}/segments", response_model=list[SegmentOut])
def get_period_segments(period_id: int, db: Session = Depends(get_db)):
    return list_segments(db, period_id)


@router.get("/segments/{segment_id}/channels", response_model=list[ChannelOut])
def get_segment_channels(
    segment_id: int,
    source_type: str = Query(default="all"),
    db: Session = Depends(get_db),
):
    st = None
    if source_type != "all":
        try:
            st = SourceType(source_type)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid source_type") from exc

    return list_segment_channels(db, segment_id=segment_id, source_type=st)


@router.get("/segments/{segment_id}/measurements", response_model=MeasurementsResponse)
def get_segment_measurements(
    segment_id: int,
    channels: str | None = Query(default=None),
    from_ts: datetime | None = Query(default=None),
    to_ts: datetime | None = Query(default=None),
    max_points: int | None = Query(default=None, ge=10, le=50000),
    source_type: SourceType = Query(default=SourceType.trend),
    db: Session = Depends(get_db),
):
    started_at = perf_counter()
    channel_ids: list[int] | None = None
    if channels:
        channel_ids = [int(token) for token in channels.split(",") if token.strip()]

    result = query_measurements(
        db,
        segment_id=segment_id,
        channel_ids=channel_ids,
        from_ts=from_ts,
        to_ts=to_ts,
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
        "measurement route=get_segment_measurements segment_id=%s source_type=%s matched_rows=%s returned_rows=%s max_points=%s elapsed_ms=%.2f",
        segment_id,
        source_type.value,
        result.matched_row_count,
        result.returned_row_count,
        max_points,
        (perf_counter() - started_at) * 1000,
    )

    return MeasurementsResponse(segment_id=segment_id, points=points)


@router.get("/uploads/{upload_id}/channels", response_model=list[ChannelOut])
def get_upload_channels(
    upload_id: int,
    source_type: str = Query(default="all"),
    db: Session = Depends(get_db),
):
    st = None
    if source_type != "all":
        try:
            st = SourceType(source_type)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid source_type") from exc

    return list_upload_channels(db, upload_id=upload_id, source_type=st)


@router.get("/uploads/{upload_id}/measurements", response_model=UploadMeasurementsResponse)
def get_upload_measurements(
    upload_id: int,
    channels: str | None = Query(default=None),
    from_ts: datetime | None = Query(default=None),
    to_ts: datetime | None = Query(default=None),
    max_points: int | None = Query(default=None, ge=10, le=50000),
    source_type: SourceType = Query(default=SourceType.trend),
    db: Session = Depends(get_db),
):
    started_at = perf_counter()
    channel_ids: list[int] | None = None
    if channels:
        channel_ids = [int(token) for token in channels.split(",") if token.strip()]

    result = query_upload_measurements(
        db,
        upload_id=upload_id,
        channel_ids=channel_ids,
        from_ts=from_ts,
        to_ts=to_ts,
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
        "measurement route=get_upload_measurements upload_id=%s source_type=%s matched_rows=%s returned_rows=%s max_points=%s elapsed_ms=%.2f",
        upload_id,
        source_type.value,
        result.matched_row_count,
        result.returned_row_count,
        max_points,
        (perf_counter() - started_at) * 1000,
    )

    return UploadMeasurementsResponse(upload_id=upload_id, points=points)
