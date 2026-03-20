from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import (
    Channel,
    Encounter,
    Measurement,
    NibpEvent,
    RecordingPeriod,
    Segment,
    SourceType,
    Upload,
    UploadMeasurementLink,
    UploadNibpEventLink,
)
from ..utils import coerce_utc
from .encounter_service import encounter_day_window
from .patient_service import prune_orphaned_canonical_rows
from .write_coordinator import ExclusiveWriteBusyError, exclusive_write


@dataclass(frozen=True)
class UploadTrimMaintenanceResult:
    deleted_orphan_uploads: int
    trimmed_uploads: int
    deleted_segments: int
    deleted_periods: int
    deleted_channels: int
    deleted_orphan_measurements: int
    deleted_orphan_nibp_events: int



def _window_bounds_for_upload(upload_id: int, encounters: list[Encounter]) -> list[tuple[datetime, datetime]]:
    return [
        tuple(bound.replace(tzinfo=UTC) for bound in encounter_day_window(encounter.encounter_date_local, encounter.timezone))
        for encounter in encounters
        if encounter.upload_id == upload_id
    ]


def _timestamp_in_any_window(timestamp: datetime, windows: list[tuple[datetime, datetime]]) -> bool:
    candidate = coerce_utc(timestamp)
    return any(start <= candidate <= end for start, end in windows)


def _recalculate_channel_valid_counts(db: Session, upload: Upload) -> None:
    trend_counts = {
        channel_id: count
        for channel_id, count in db.execute(
            select(UploadMeasurementLink.channel_id, func.count(UploadMeasurementLink.id))
            .where(UploadMeasurementLink.upload_id == upload.id)
            .group_by(UploadMeasurementLink.channel_id)
        ).all()
    }
    nibp_events = db.scalars(
        select(NibpEvent)
        .join(UploadNibpEventLink, UploadNibpEventLink.nibp_event_id == NibpEvent.id)
        .where(UploadNibpEventLink.upload_id == upload.id)
    ).all()
    nibp_counts: dict[int, int] = {}
    for channel in upload.channels:
        if channel.source_type != SourceType.nibp:
            continue
        fallback_name = channel.name
        nibp_counts[channel.id] = sum(1 for event in nibp_events if event.channel_values.get(fallback_name) is not None)

    for channel in list(upload.channels):
        if channel.source_type == SourceType.trend:
            channel.valid_count = int(trend_counts.get(channel.id, 0))
        else:
            channel.valid_count = int(nibp_counts.get(channel.id, 0))
        db.add(channel)

    db.flush()
    db.execute(
        delete(Channel)
        .where(Channel.upload_id == upload.id)
        .where(Channel.valid_count <= 0)
    )


def _detach_orphaned_canonical_rows(db: Session) -> None:
    db.execute(
        update(Measurement)
        .where(~Measurement.upload_links.any())
        .values(upload_id=None, segment_id=None, channel_id=None)
    )
    db.execute(
        update(NibpEvent)
        .where(~NibpEvent.upload_links.any())
        .values(upload_id=None, segment_id=None)
    )


def trim_uploads_to_saved_encounter_windows(db: Session) -> UploadTrimMaintenanceResult:
    uploads = db.scalars(
        select(Upload)
        .order_by(Upload.id.asc())
    ).all()

    deleted_orphan_uploads = 0
    trimmed_uploads = 0
    deleted_segments = 0
    deleted_periods = 0
    deleted_channels = 0

    for upload in uploads:
        encounters = db.scalars(
            select(Encounter)
            .where(Encounter.upload_id == upload.id)
            .order_by(Encounter.encounter_date_local.asc(), Encounter.id.asc())
        ).all()
        if not encounters:
            db.delete(upload)
            deleted_orphan_uploads += 1
            continue

        windows = _window_bounds_for_upload(upload.id, encounters)
        if not windows:
            continue

        removable_measurement_link_ids = [
            row_id
            for row_id, timestamp in db.execute(
                select(UploadMeasurementLink.id, UploadMeasurementLink.timestamp).where(
                    UploadMeasurementLink.upload_id == upload.id
                )
            ).all()
            if not _timestamp_in_any_window(timestamp, windows)
        ]
        removable_nibp_link_ids = [
            row_id
            for row_id, timestamp in db.execute(
                select(UploadNibpEventLink.id, UploadNibpEventLink.timestamp).where(
                    UploadNibpEventLink.upload_id == upload.id
                )
            ).all()
            if not _timestamp_in_any_window(timestamp, windows)
        ]
        if removable_measurement_link_ids:
            db.execute(delete(UploadMeasurementLink).where(UploadMeasurementLink.id.in_(removable_measurement_link_ids)))
        if removable_nibp_link_ids:
            db.execute(delete(UploadNibpEventLink).where(UploadNibpEventLink.id.in_(removable_nibp_link_ids)))

        kept_segment_ids = set(
            db.scalars(select(Segment.id).where(Segment.upload_id == upload.id)).all()
        )
        if kept_segment_ids:
            segment_ids_with_rows = set(
                db.scalars(select(UploadMeasurementLink.segment_id).where(UploadMeasurementLink.upload_id == upload.id)).all()
            )
            segment_ids_with_rows.update(
                db.scalars(select(UploadNibpEventLink.segment_id).where(UploadNibpEventLink.upload_id == upload.id)).all()
            )
            removable_segment_ids = kept_segment_ids - segment_ids_with_rows
            if removable_segment_ids:
                deleted_segments += int(
                    db.execute(delete(Segment).where(Segment.id.in_(removable_segment_ids))).rowcount or 0
                )

        removable_period_ids = [
            period_id
            for period_id in db.scalars(
                select(RecordingPeriod.id).where(RecordingPeriod.upload_id == upload.id)
            ).all()
            if not db.scalar(select(func.count(Segment.id)).where(Segment.period_id == period_id))
        ]
        if removable_period_ids:
            deleted_periods += int(
                db.execute(delete(RecordingPeriod).where(RecordingPeriod.id.in_(removable_period_ids))).rowcount or 0
            )

        upload.periods = db.scalars(
            select(RecordingPeriod).where(RecordingPeriod.upload_id == upload.id).order_by(RecordingPeriod.period_index.asc())
        ).all()
        upload.detected_local_dates = sorted({encounter.encounter_date_local.isoformat() for encounter in encounters})
        upload.trend_frames = int(
            db.scalar(
                select(func.count(func.distinct(UploadMeasurementLink.timestamp))).where(
                    UploadMeasurementLink.upload_id == upload.id
                )
            )
            or 0
        )
        upload.nibp_frames = int(
            db.scalar(select(func.count(UploadNibpEventLink.id)).where(UploadNibpEventLink.upload_id == upload.id))
            or 0
        )
        db.add(upload)
        channels_before = len(upload.channels)
        _recalculate_channel_valid_counts(db, upload)
        refreshed_channels = db.scalars(select(Channel).where(Channel.upload_id == upload.id)).all()
        deleted_channels += max(0, channels_before - len(refreshed_channels))
        trimmed_uploads += 1

    db.flush()
    _detach_orphaned_canonical_rows(db)
    deleted_orphan_measurements, deleted_orphan_nibp_events = prune_orphaned_canonical_rows(db)
    db.commit()

    return UploadTrimMaintenanceResult(
        deleted_orphan_uploads=deleted_orphan_uploads,
        trimmed_uploads=trimmed_uploads,
        deleted_segments=deleted_segments,
        deleted_periods=deleted_periods,
        deleted_channels=deleted_channels,
        deleted_orphan_measurements=deleted_orphan_measurements,
        deleted_orphan_nibp_events=deleted_orphan_nibp_events,
    )


def vacuum_sqlite_database(db: Session) -> None:
    bind = db.get_bind()
    db.commit()
    with bind.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.exec_driver_sql("VACUUM")


def run_opportunistic_maintenance(*, bind=None) -> None:
    from .upload_service import purge_duplicate_orphan_uploads, purge_stale_orphan_uploads

    db = Session(bind=bind) if bind is not None else SessionLocal()
    try:
        try:
            with exclusive_write("opportunistic maintenance", wait=False, busy_detail=""):
                purge_duplicate_orphan_uploads(db, commit=False)
                purge_stale_orphan_uploads(db, commit=False)
                prune_orphaned_canonical_rows(db)
                db.commit()
        except ExclusiveWriteBusyError:
            db.rollback()
    finally:
        db.close()
