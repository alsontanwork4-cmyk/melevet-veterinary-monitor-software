import csv
import io
from collections import defaultdict
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..services.encounter_service import encounter_day_window, get_encounter
from ..services.chart_service import list_alarms, list_nibp_events, list_upload_measurements


router = APIRouter(tags=["export"])

CORE_NIBP_EXPORT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("bp_systolic_inferred", "nibp_systolic"),
    ("bp_mean_inferred", "nibp_mean"),
    ("bp_diastolic_inferred", "nibp_diastolic"),
)


def _normalize_utc_naive(timestamp: datetime | None) -> datetime | None:
    if timestamp is None:
        return None
    if timestamp.tzinfo is None:
        return timestamp
    return timestamp.astimezone(UTC).replace(tzinfo=None)


def _csv_stream(rows: list[list[str]]):
    output = io.StringIO()
    writer = csv.writer(output)
    for row in rows:
        writer.writerow(row)
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)


def _build_upload_export_rows(
    *,
    db: Session,
    upload_id: int,
    segment_id: int | None,
    channels: str | None,
    from_ts: datetime | None,
    to_ts: datetime | None,
    include_nibp: bool,
    include_alarms: bool,
) -> list[list[str]]:
    from_ts = _normalize_utc_naive(from_ts)
    to_ts = _normalize_utc_naive(to_ts)
    channel_ids = [int(token) for token in channels.split(",") if token.strip()] if channels else []

    measurement_rows = list_upload_measurements(
        db,
        upload_id=upload_id,
        channel_ids=channel_ids or None,
        from_ts=from_ts,
        to_ts=to_ts,
        max_points=None,
    )

    channel_names_by_id: dict[int, str] = {}
    rows_by_timestamp: dict[datetime, dict[int, str]] = defaultdict(dict)
    for measurement, channel_name in measurement_rows:
        channel_names_by_id[measurement.channel_id] = channel_name
        rows_by_timestamp[measurement.timestamp][measurement.channel_id] = (
            "" if measurement.value is None else f"{measurement.value:g}"
        )

    channel_set = sorted(channel_names_by_id)

    nibp_by_timestamp: dict[datetime, dict[str, str]] = defaultdict(dict)
    if include_nibp:
        nibp_events = list_nibp_events(
            db,
            upload_id=upload_id,
            segment_id=segment_id,
            measurements_only=False,
            from_ts=from_ts,
            to_ts=to_ts,
        )
        for event in nibp_events:
            values: dict[str, str] = {}
            for value_key, _column_name in CORE_NIBP_EXPORT_COLUMNS:
                value = event.channel_values.get(value_key)
                if isinstance(value, (int, float)):
                    values[value_key] = f"{value:g}"
            nibp_by_timestamp[event.timestamp] = values

    alarms_by_timestamp: dict[datetime, str] = defaultdict(str)
    if include_alarms:
        alarms = list_alarms(
            db,
            upload_id=upload_id,
            segment_id=segment_id,
            category=None,
            from_ts=from_ts,
            to_ts=to_ts,
        )
        for alarm in alarms:
            existing = alarms_by_timestamp[alarm.timestamp]
            alarms_by_timestamp[alarm.timestamp] = (
                f"{existing} | {alarm.message}" if existing else alarm.message
            )

    header = ["timestamp"] + [channel_names_by_id[channel_id] for channel_id in channel_set]
    if include_nibp:
        header.extend(column_name for _, column_name in CORE_NIBP_EXPORT_COLUMNS)
    if include_alarms:
        header.append("alarms")

    rows: list[list[str]] = [header]
    all_timestamps = sorted(set(rows_by_timestamp.keys()) | set(nibp_by_timestamp.keys()) | set(alarms_by_timestamp.keys()))

    for ts in all_timestamps:
        row = [ts.isoformat()]
        values = rows_by_timestamp.get(ts, {})
        row.extend(values.get(channel_id, "") for channel_id in channel_set)
        if include_nibp:
            nibp_values = nibp_by_timestamp.get(ts, {})
            row.extend(nibp_values.get(value_key, "") for value_key, _column_name in CORE_NIBP_EXPORT_COLUMNS)
        if include_alarms:
            row.append(alarms_by_timestamp.get(ts, ""))
        rows.append(row)

    return rows


@router.get("/uploads/{upload_id}/export")
def export_csv(
    upload_id: int,
    segment_id: int | None = Query(default=None),
    channels: str | None = Query(default=None),
    from_ts: datetime | None = Query(default=None),
    to_ts: datetime | None = Query(default=None),
    include_nibp: bool = Query(default=True),
    include_alarms: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    rows = _build_upload_export_rows(
        db=db,
        upload_id=upload_id,
        segment_id=segment_id,
        channels=channels,
        from_ts=from_ts,
        to_ts=to_ts,
        include_nibp=include_nibp,
        include_alarms=include_alarms,
    )
    filename = f"upload_{upload_id}.csv"
    return StreamingResponse(
        _csv_stream(rows),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/encounters/{encounter_id}/export")
def export_encounter_csv(
    encounter_id: int,
    channels: str | None = Query(default=None),
    include_nibp: bool = Query(default=True),
    include_alarms: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    encounter = get_encounter(db, encounter_id)
    if encounter is None:
        raise HTTPException(status_code=404, detail="Encounter not found")

    from_ts, to_ts = encounter_day_window(encounter.encounter_date_local, encounter.timezone)
    rows = _build_upload_export_rows(
        db=db,
        upload_id=encounter.upload_id,
        segment_id=None,
        channels=channels,
        from_ts=from_ts,
        to_ts=to_ts,
        include_nibp=include_nibp,
        include_alarms=include_alarms,
    )
    filename = f"encounter_{encounter_id}.csv"
    return StreamingResponse(
        _csv_stream(rows),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
