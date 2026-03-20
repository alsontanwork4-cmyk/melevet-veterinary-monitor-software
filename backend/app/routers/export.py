import csv
import io
import zipfile
from collections import defaultdict
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import BulkEncounterExportRequest
from ..utils import coerce_utc_naive
from ..services.encounter_service import encounter_day_window, get_encounter
from ..services.chart_service import list_nibp_events, list_upload_measurements


router = APIRouter(tags=["export"])

CORE_NIBP_EXPORT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("bp_systolic_inferred", "nibp_systolic"),
    ("bp_mean_inferred", "nibp_mean"),
    ("bp_diastolic_inferred", "nibp_diastolic"),
)




def _csv_stream(rows: list[list[str]]):
    output = io.StringIO()
    writer = csv.writer(output)
    for row in rows:
        writer.writerow(row)
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)


def _csv_bytes(rows: list[list[str]]) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _build_upload_export_rows(
    *,
    db: Session,
    upload_id: int,
    segment_id: int | None,
    channels: str | None,
    from_ts: datetime | None,
    to_ts: datetime | None,
    include_nibp: bool,
) -> list[list[str]]:
    from_ts = coerce_utc_naive(from_ts)
    to_ts = coerce_utc_naive(to_ts)
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

    header = ["timestamp"] + [channel_names_by_id[channel_id] for channel_id in channel_set]
    if include_nibp:
        header.extend(column_name for _, column_name in CORE_NIBP_EXPORT_COLUMNS)

    rows: list[list[str]] = [header]
    all_timestamps = sorted(set(rows_by_timestamp.keys()) | set(nibp_by_timestamp.keys()))

    for ts in all_timestamps:
        row = [ts.isoformat()]
        values = rows_by_timestamp.get(ts, {})
        row.extend(values.get(channel_id, "") for channel_id in channel_set)
        if include_nibp:
            nibp_values = nibp_by_timestamp.get(ts, {})
            row.extend(nibp_values.get(value_key, "") for value_key, _column_name in CORE_NIBP_EXPORT_COLUMNS)
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
    )
    filename = f"encounter_{encounter_id}.csv"
    return StreamingResponse(
        _csv_stream(rows),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/encounters/export-zip")
def export_bulk_encounter_csv(
    payload: BulkEncounterExportRequest,
    db: Session = Depends(get_db),
):
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for encounter_id in payload.encounter_ids:
            encounter = get_encounter(db, encounter_id)
            if encounter is None:
                raise HTTPException(status_code=404, detail=f"Encounter not found: {encounter_id}")

            from_ts, to_ts = encounter_day_window(encounter.encounter_date_local, encounter.timezone)
            rows = _build_upload_export_rows(
                db=db,
                upload_id=encounter.upload_id,
                segment_id=None,
                channels=None,
                from_ts=from_ts,
                to_ts=to_ts,
                include_nibp=payload.include_nibp,
            )
            archive.writestr(
                f"encounter_{encounter_id}_{encounter.encounter_date_local.isoformat()}.csv",
                _csv_bytes(rows),
            )

    archive_buffer.seek(0)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    filename = f"encounter_exports_{timestamp}.zip"
    return StreamingResponse(
        archive_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
