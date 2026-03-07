from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..database import (
    SessionLocal,
    build_alarm_dedup_key,
    build_measurement_dedup_key,
    build_nibp_dedup_key,
)
from ..models import (
    Alarm,
    Channel,
    Encounter,
    Patient,
    Measurement,
    NibpEvent,
    RecordingPeriod,
    Segment,
    SourceType,
    UploadAlarmLink,
    UploadMeasurementLink,
    UploadNibpEventLink,
    Upload,
    UploadStatus,
)
from ..parsers.alarm_parser import parse_alarm_frames
from ..parsers.channel_stats import compute_stats_for_matrix
from ..parsers.index_parser import parse_index_bytes
from ..parsers.nibp_parser import infer_nibp_measurement, nibp_channel_name, parse_nibp_frames
from ..parsers.segmenter import split_periods_and_segments
from ..parsers.trend_parser import parse_trend_frames
from .channel_mapping import resolve_channel_metadata
from .encounter_service import detected_local_dates_for_ranges


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UploadParseResult:
    upload_id: int
    period_count: int
    segment_count: int
    channel_count: int


@dataclass(frozen=True)
class SegmentWindowRef:
    id: int
    start_time: datetime
    end_time: datetime


@dataclass(frozen=True)
class DuplicateUploadError(Exception):
    upload: Upload


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_combined_hash(
    *,
    trend_data: bytes,
    trend_index: bytes | None,
    nibp_data: bytes | None,
    nibp_index: bytes | None,
    alarm_data: bytes | None,
    alarm_index: bytes | None,
) -> str:
    checksum_input = "|".join(
        [
            _sha256(trend_data),
            _sha256(trend_index) if trend_index is not None else _sha256(b""),
            _sha256(nibp_data) if nibp_data is not None else _sha256(b""),
            _sha256(nibp_index) if nibp_index is not None else _sha256(b""),
            _sha256(alarm_data) if alarm_data is not None else _sha256(b""),
            _sha256(alarm_index) if alarm_index is not None else _sha256(b""),
        ]
    )
    return _sha256(checksum_input.encode("utf-8"))


EMPTY_SHA256 = _sha256(b"")

PHASE_READING = "reading"
PHASE_PARSING = "parsing"
PHASE_SEGMENTING = "segmenting"
PHASE_WRITING_MEASUREMENTS = "writing_measurements"
PHASE_WRITING_EVENTS = "writing_events"
PHASE_FINALIZING = "finalizing"
PHASE_COMPLETED = "completed"
PHASE_ERROR = "error"

CORE_TREND_CHANNELS: dict[int, tuple[str, str | None]] = {
    14: ("spo2_be_u16", "%"),
    16: ("heart_rate_be_u16", "bpm"),
}
CORE_NIBP_CHANNELS: dict[int, tuple[str, str | None]] = {
    14: ("bp_systolic_inferred", "mmHg"),
    15: ("bp_mean_inferred", "mmHg"),
    16: ("bp_diastolic_inferred", "mmHg"),
}
CORE_NIBP_VALUE_KEYS = tuple(name for name, _ in CORE_NIBP_CHANNELS.values())


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _coerce_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _resolve_core_channel_metadata(
    *,
    source_type: SourceType,
    channel_index: int,
    fallback_name: str,
    fallback_unit: str | None,
) -> tuple[str, str | None]:
    return resolve_channel_metadata(
        source_type=source_type.value,
        channel_index=channel_index,
        default_name=fallback_name,
        default_unit=fallback_unit,
    )


def _trim_nibp_channel_values(channel_values: dict[str, int | None]) -> tuple[dict[str, int | None], bool]:
    inferred_values = infer_nibp_measurement(channel_values)
    trimmed: dict[str, int | None] = {}

    for channel_index, (key, _fallback_unit) in CORE_NIBP_CHANNELS.items():
        value = inferred_values.get(key)
        if value is None:
            value = channel_values.get(key)
        if value is None:
            value = channel_values.get(nibp_channel_name(channel_index))
        trimmed[key] = value if isinstance(value, int) and value > 0 else None

    has_measurement = any(value is not None for value in trimmed.values())
    return trimmed, has_measurement


def _progress_safe_total(total: int | None) -> int:
    if total is None:
        return 0
    return max(0, total)


def _update_upload_progress(
    db: Session,
    upload: Upload,
    *,
    phase: str | None = None,
    progress_current: int | None = None,
    progress_total: int | None = None,
    progress_increment: int = 0,
    commit: bool = False,
) -> None:
    if phase is not None:
        upload.phase = phase
    if progress_total is not None:
        upload.progress_total = _progress_safe_total(progress_total)
    if progress_current is not None:
        upload.progress_current = max(0, progress_current)
    elif progress_increment:
        upload.progress_current = max(0, (upload.progress_current or 0) + progress_increment)

    now = _utcnow()
    if upload.started_at is None:
        upload.started_at = now
    upload.heartbeat_at = now

    if upload.progress_total and upload.progress_current > upload.progress_total:
        upload.progress_current = upload.progress_total

    db.add(upload)
    if commit:
        db.commit()


def _set_upload_failed(db: Session, upload: Upload, message: str) -> None:
    now = _utcnow()
    upload.status = UploadStatus.error
    upload.phase = PHASE_ERROR
    upload.error_message = message[:4000]
    upload.heartbeat_at = now
    upload.completed_at = None
    db.add(upload)
    db.commit()


def fail_stale_upload_if_needed(db: Session, upload: Upload) -> bool:
    if upload.status != UploadStatus.processing:
        return False

    timeout_seconds = max(1, settings.upload_timeout_seconds)
    now = _utcnow()
    reference = _coerce_utc(upload.heartbeat_at) or _coerce_utc(upload.started_at) or _coerce_utc(upload.upload_time)
    if reference is None:
        return False
    if (now - reference) <= timedelta(seconds=timeout_seconds):
        return False

    _set_upload_failed(db, upload, "Upload worker interrupted; please retry.")
    return True


def fail_stale_processing_uploads(db: Session) -> int:
    uploads = db.scalars(select(Upload).where(Upload.status == UploadStatus.processing)).all()
    stale_count = 0
    for upload in uploads:
        if fail_stale_upload_if_needed(db, upload):
            stale_count += 1
    return stale_count


def purge_stale_orphan_uploads(db: Session) -> int:
    cutoff = _utcnow() - timedelta(days=max(1, settings.orphan_upload_retention_days))
    uploads = db.scalars(
        select(Upload)
        .outerjoin(Upload.encounters)
        .group_by(Upload.id)
        .having(func.count(Encounter.id) == 0)
        .where(func.coalesce(Upload.completed_at, Upload.upload_time) < cutoff)
    ).all()

    deleted = 0
    for upload in uploads:
        db.delete(upload)
        deleted += 1
    if deleted:
        db.commit()
    return deleted


def purge_duplicate_orphan_uploads(db: Session) -> int:
    rows = db.execute(
        select(Upload, func.count(Encounter.id).label("encounter_count"))
        .outerjoin(Upload.encounters)
        .group_by(Upload.id)
        .where(Upload.combined_hash != "")
        .order_by(
            Upload.combined_hash.asc(),
            func.count(Encounter.id).desc(),
            func.coalesce(Upload.completed_at, Upload.upload_time).desc(),
            Upload.id.desc(),
        )
    ).all()

    kept_hashes: set[str] = set()
    deleted = 0

    for upload, encounter_count in rows:
        if upload.combined_hash not in kept_hashes:
            kept_hashes.add(upload.combined_hash)
            continue
        if encounter_count > 0:
            continue

        db.delete(upload)
        deleted += 1

    if deleted:
        db.commit()
    return deleted


def find_reusable_upload(db: Session, *, combined_hash: str) -> Upload | None:
    completed = db.scalar(
        select(Upload)
        .where(Upload.combined_hash == combined_hash)
        .where(Upload.status == UploadStatus.completed)
        .order_by(Upload.upload_time.desc())
    )
    if completed is not None:
        return completed

    return db.scalar(
        select(Upload)
        .where(Upload.combined_hash == combined_hash)
        .where(Upload.status == UploadStatus.processing)
        .order_by(Upload.upload_time.desc())
    )


def _batched(items: Iterable[object], batch_size: int):
    batch: list[object] = []
    for item in items:
        batch.append(item)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def _log_index_rollbacks(source_name: str, rollback_indices: list[int]) -> None:
    if not rollback_indices:
        return

    preview_count = 5
    preview = ", ".join(str(idx) for idx in rollback_indices[:preview_count])
    if len(rollback_indices) > preview_count:
        preview = f"{preview}, ..."

    logger.warning(
        "Detected %d timestamp rollback points in %s index (first entries: %s)",
        len(rollback_indices),
        source_name,
        preview,
    )


def _resolve_segment_for_timestamp(timestamp: datetime, windows: list[SegmentWindowRef]) -> int:
    if not windows:
        raise ValueError("No segments available for timestamp resolution")

    for window in windows:
        if window.start_time <= timestamp <= window.end_time:
            return window.id

    earliest_window = min(windows, key=lambda window: window.start_time)
    latest_window = max(windows, key=lambda window: window.end_time)
    if timestamp < earliest_window.start_time:
        return earliest_window.id
    if timestamp > latest_window.end_time:
        return latest_window.id

    # fallback nearest edge
    nearest = min(
        windows,
        key=lambda window: min(
            abs((timestamp - window.start_time).total_seconds()),
            abs((timestamp - window.end_time).total_seconds()),
        ),
    )
    return nearest.id


def _fetch_existing_measurements_by_key(db: Session, dedup_keys: set[str]) -> dict[str, Measurement]:
    existing: dict[str, Measurement] = {}
    for batch in _batched(sorted(dedup_keys), 1000):
        rows = db.scalars(select(Measurement).where(Measurement.dedup_key.in_(batch))).all()
        existing.update({row.dedup_key: row for row in rows})
    return existing


def _fetch_existing_nibp_events_by_key(db: Session, dedup_keys: set[str]) -> dict[str, NibpEvent]:
    existing: dict[str, NibpEvent] = {}
    for batch in _batched(sorted(dedup_keys), 1000):
        rows = db.scalars(select(NibpEvent).where(NibpEvent.dedup_key.in_(batch))).all()
        existing.update({row.dedup_key: row for row in rows})
    return existing


def _fetch_existing_alarms_by_key(db: Session, dedup_keys: set[str]) -> dict[str, Alarm]:
    existing: dict[str, Alarm] = {}
    for batch in _batched(sorted(dedup_keys), 1000):
        rows = db.scalars(select(Alarm).where(Alarm.dedup_key.in_(batch))).all()
        existing.update({row.dedup_key: row for row in rows})
    return existing


def _persist_measurement_links(
    db: Session,
    *,
    upload: Upload,
    trend_frames,
    trend_channel_id_by_index: dict[int, int],
    trend_frame_to_segment: list[int],
) -> tuple[int, int]:
    specs: dict[tuple[int, int, str], dict[str, object]] = {}
    dedup_keys: set[str] = set()
    for frame in trend_frames:
        segment_id = trend_frame_to_segment[frame.frame_index]
        for channel_index, channel_id in trend_channel_id_by_index.items():
            dedup_key = build_measurement_dedup_key(
                timestamp=frame.timestamp,
                source_type=SourceType.trend.value,
                channel_index=channel_index,
            )
            dedup_keys.add(dedup_key)
            specs[(segment_id, channel_id, dedup_key)] = {
                "segment_id": segment_id,
                "channel_id": channel_id,
                "timestamp": frame.timestamp,
                "value": float(frame.values[channel_index]) if frame.values[channel_index] is not None else None,
                "dedup_key": dedup_key,
            }

    existing = _fetch_existing_measurements_by_key(db, dedup_keys)
    new_rows: list[Measurement] = []
    for spec in specs.values():
        dedup_key = str(spec["dedup_key"])
        if dedup_key in existing:
            continue
        measurement = Measurement(
            upload_id=upload.id,
            segment_id=int(spec["segment_id"]),
            channel_id=int(spec["channel_id"]),
            timestamp=spec["timestamp"],
            value=spec["value"],
            dedup_key=dedup_key,
        )
        new_rows.append(measurement)
        existing[dedup_key] = measurement

    if new_rows:
        db.add_all(new_rows)
        db.flush()

    link_rows = [
        UploadMeasurementLink(
            upload_id=upload.id,
            segment_id=int(spec["segment_id"]),
            channel_id=int(spec["channel_id"]),
            measurement_id=existing[str(spec["dedup_key"])].id,
            timestamp=spec["timestamp"],
        )
        for spec in specs.values()
    ]
    if link_rows:
        db.add_all(link_rows)
        db.flush()

    return len(new_rows), max(0, len(specs) - len(new_rows))


def _persist_nibp_event_links(
    db: Session,
    *,
    upload: Upload,
    nibp_frames,
    segment_windows: list[SegmentWindowRef],
) -> tuple[int, int]:
    specs: dict[tuple[int, str], dict[str, object]] = {}
    dedup_keys: set[str] = set()
    for frame in nibp_frames:
        segment_id = _resolve_segment_for_timestamp(frame.timestamp, segment_windows)
        trimmed_channel_values, has_measurement = _trim_nibp_channel_values(frame.channel_values)
        dedup_key = build_nibp_dedup_key(timestamp=frame.timestamp)
        dedup_keys.add(dedup_key)
        specs[(segment_id, dedup_key)] = {
            "segment_id": segment_id,
            "timestamp": frame.timestamp,
            "channel_values": trimmed_channel_values,
            "has_measurement": has_measurement,
            "dedup_key": dedup_key,
        }

    existing = _fetch_existing_nibp_events_by_key(db, dedup_keys)
    new_rows: list[NibpEvent] = []
    for spec in specs.values():
        dedup_key = str(spec["dedup_key"])
        if dedup_key in existing:
            continue
        nibp_event = NibpEvent(
            upload_id=upload.id,
            segment_id=int(spec["segment_id"]),
            timestamp=spec["timestamp"],
            channel_values=spec["channel_values"],
            has_measurement=bool(spec["has_measurement"]),
            dedup_key=dedup_key,
        )
        new_rows.append(nibp_event)
        existing[dedup_key] = nibp_event

    if new_rows:
        db.add_all(new_rows)
        db.flush()

    link_rows = [
        UploadNibpEventLink(
            upload_id=upload.id,
            segment_id=int(spec["segment_id"]),
            nibp_event_id=existing[str(spec["dedup_key"])].id,
            timestamp=spec["timestamp"],
        )
        for spec in specs.values()
    ]
    if link_rows:
        db.add_all(link_rows)
        db.flush()

    return len(new_rows), max(0, len(specs) - len(new_rows))


def _persist_alarm_links(
    db: Session,
    *,
    upload: Upload,
    alarm_frames,
    segment_windows: list[SegmentWindowRef],
) -> tuple[int, int]:
    specs: dict[tuple[int, str], dict[str, object]] = {}
    dedup_keys: set[str] = set()
    for alarm in alarm_frames:
        segment_id = _resolve_segment_for_timestamp(alarm.timestamp, segment_windows)
        dedup_key = build_alarm_dedup_key(
            timestamp=alarm.timestamp,
            alarm_category=alarm.category.value,
            flag_hi=alarm.flag_hi,
            flag_lo=alarm.flag_lo,
            message=alarm.message,
        )
        dedup_keys.add(dedup_key)
        specs[(segment_id, dedup_key)] = {
            "segment_id": segment_id,
            "timestamp": alarm.timestamp,
            "flag_hi": alarm.flag_hi,
            "flag_lo": alarm.flag_lo,
            "alarm_category": alarm.category,
            "message": alarm.message,
            "dedup_key": dedup_key,
        }

    existing = _fetch_existing_alarms_by_key(db, dedup_keys)
    new_rows: list[Alarm] = []
    for spec in specs.values():
        dedup_key = str(spec["dedup_key"])
        if dedup_key in existing:
            continue
        alarm = Alarm(
            upload_id=upload.id,
            segment_id=int(spec["segment_id"]),
            timestamp=spec["timestamp"],
            flag_hi=int(spec["flag_hi"]),
            flag_lo=int(spec["flag_lo"]),
            alarm_category=spec["alarm_category"],
            message=str(spec["message"]),
            dedup_key=dedup_key,
        )
        new_rows.append(alarm)
        existing[dedup_key] = alarm

    if new_rows:
        db.add_all(new_rows)
        db.flush()

    link_rows = [
        UploadAlarmLink(
            upload_id=upload.id,
            segment_id=int(spec["segment_id"]),
            alarm_id=existing[str(spec["dedup_key"])].id,
            timestamp=spec["timestamp"],
        )
        for spec in specs.values()
    ]
    if link_rows:
        db.add_all(link_rows)
        db.flush()

    return len(new_rows), max(0, len(specs) - len(new_rows))


def create_upload_stub(
    db: Session,
    *,
    patient: Patient,
    trend_data: bytes,
    trend_index: bytes | None,
    nibp_data: bytes | None,
    nibp_index: bytes | None,
    alarm_data: bytes | None,
    alarm_index: bytes | None,
    combined_hash: str | None = None,
) -> Upload:
    now = _utcnow()
    upload = Upload(
        patient_id=patient.id,
        status=UploadStatus.processing,
        phase=PHASE_READING,
        progress_current=0,
        progress_total=0,
        started_at=now,
        heartbeat_at=now,
        completed_at=None,
        trend_frames=0,
        nibp_frames=0,
        alarm_frames=0,
        trend_sha256=_sha256(trend_data),
        trend_index_sha256=_sha256(trend_index) if trend_index is not None else EMPTY_SHA256,
        nibp_sha256=_sha256(nibp_data) if nibp_data is not None else EMPTY_SHA256,
        nibp_index_sha256=_sha256(nibp_index) if nibp_index is not None else EMPTY_SHA256,
        alarm_sha256=_sha256(alarm_data) if alarm_data is not None else EMPTY_SHA256,
        alarm_index_sha256=_sha256(alarm_index) if alarm_index is not None else EMPTY_SHA256,
        combined_hash=combined_hash
        or build_combined_hash(
            trend_data=trend_data,
            trend_index=trend_index,
            nibp_data=nibp_data,
            nibp_index=nibp_index,
            alarm_data=alarm_data,
            alarm_index=alarm_index,
        ),
        detected_local_dates=[],
    )
    db.add(upload)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = find_reusable_upload(
            db,
            combined_hash=combined_hash
            or build_combined_hash(
                trend_data=trend_data,
                trend_index=trend_index,
                nibp_data=nibp_data,
                nibp_index=nibp_index,
                alarm_data=alarm_data,
                alarm_index=alarm_index,
            ),
        )
        if existing is None:
            raise
        raise DuplicateUploadError(existing) from exc
    db.refresh(upload)
    return upload


def process_upload(
    db: Session,
    *,
    patient: Patient,
    trend_data: bytes,
    trend_index: bytes | None,
    nibp_data: bytes | None,
    nibp_index: bytes | None,
    alarm_data: bytes | None,
    alarm_index: bytes | None,
    combined_hash: str,
    timezone_name: str,
) -> UploadParseResult:
    upload = create_upload_stub(
        db,
        patient=patient,
        trend_data=trend_data,
        trend_index=trend_index,
        nibp_data=nibp_data,
        nibp_index=nibp_index,
        alarm_data=alarm_data,
        alarm_index=alarm_index,
        combined_hash=combined_hash,
    )
    return process_upload_for_existing_upload(
        db,
        upload_id=upload.id,
        trend_data=trend_data,
        trend_index=trend_index,
        nibp_data=nibp_data,
        nibp_index=nibp_index,
        alarm_data=alarm_data,
        alarm_index=alarm_index,
        combined_hash=combined_hash,
        timezone_name=timezone_name,
    )


def process_upload_for_existing_upload(
    db: Session,
    *,
    upload_id: int,
    trend_data: bytes,
    trend_index: bytes | None,
    nibp_data: bytes | None,
    nibp_index: bytes | None,
    alarm_data: bytes | None,
    alarm_index: bytes | None,
    combined_hash: str | None = None,
    timezone_name: str = "UTC",
) -> UploadParseResult:
    upload = db.get(Upload, upload_id)
    if upload is None:
        raise ValueError(f"Upload not found: {upload_id}")

    try:
        invalid_u16_values = settings.invalid_u16_set
        _update_upload_progress(
            db,
            upload,
            phase=PHASE_PARSING,
            progress_current=1,
            progress_total=5,
            commit=True,
        )

        parsed_trend_index = (
            parse_index_bytes(trend_index, trend_data, require_monotonic=False)
            if trend_index is not None
            else None
        )
        parsed_nibp_index = (
            parse_index_bytes(nibp_index, nibp_data, require_monotonic=False)
            if nibp_data is not None and nibp_index is not None
            else None
        )
        parsed_alarm_index = (
            parse_index_bytes(alarm_index, alarm_data, require_monotonic=False)
            if alarm_data is not None and alarm_index is not None
            else None
        )
        if parsed_trend_index is not None:
            _log_index_rollbacks("trend", parsed_trend_index.rollback_indices)
        if parsed_nibp_index is not None:
            _log_index_rollbacks("nibp", parsed_nibp_index.rollback_indices)
        if parsed_alarm_index is not None:
            _log_index_rollbacks("alarm", parsed_alarm_index.rollback_indices)

        trend_frames = parse_trend_frames(trend_data, parsed_trend_index, invalid_u16_values)
        nibp_frames = (
            parse_nibp_frames(nibp_data, parsed_nibp_index, invalid_u16_values)
            if nibp_data is not None and parsed_nibp_index is not None
            else []
        )
        alarm_frames = (
            parse_alarm_frames(alarm_data, parsed_alarm_index)
            if alarm_data is not None and parsed_alarm_index is not None
            else []
        )
        if not trend_frames:
            raise ValueError("Trend file has no frames to build sessions")

        retained_trend_channel_count = sum(
            1 for channel_index in CORE_TREND_CHANNELS if channel_index < len(trend_frames[0].values)
        )
        measurement_total = len(trend_frames) * retained_trend_channel_count
        event_total = len(nibp_frames) + len(alarm_frames)
        progress_total = max(5, measurement_total + event_total + 5)

        upload.status = UploadStatus.processing
        upload.phase = PHASE_PARSING
        upload.error_message = None
        upload.completed_at = None
        upload.trend_frames = len(trend_frames)
        upload.nibp_frames = len(nibp_frames)
        upload.alarm_frames = len(alarm_frames)
        upload.trend_sha256 = _sha256(trend_data)
        upload.trend_index_sha256 = _sha256(trend_index) if trend_index is not None else EMPTY_SHA256
        upload.nibp_sha256 = _sha256(nibp_data) if nibp_data is not None else EMPTY_SHA256
        upload.nibp_index_sha256 = _sha256(nibp_index) if nibp_index is not None else EMPTY_SHA256
        upload.alarm_sha256 = _sha256(alarm_data) if alarm_data is not None else EMPTY_SHA256
        upload.alarm_index_sha256 = _sha256(alarm_index) if alarm_index is not None else EMPTY_SHA256
        upload.measurements_new = 0
        upload.measurements_reused = 0
        upload.nibp_new = 0
        upload.nibp_reused = 0
        upload.alarms_new = 0
        upload.alarms_reused = 0
        upload.combined_hash = combined_hash or build_combined_hash(
            trend_data=trend_data,
            trend_index=trend_index,
            nibp_data=nibp_data,
            nibp_index=nibp_index,
            alarm_data=alarm_data,
            alarm_index=alarm_index,
        )
        _update_upload_progress(
            db,
            upload,
            progress_current=2,
            progress_total=progress_total,
            commit=True,
        )

        timestamps = [frame.timestamp for frame in trend_frames]
        _update_upload_progress(db, upload, phase=PHASE_SEGMENTING, progress_current=3)
        period_windows = split_periods_and_segments(
            timestamps=timestamps,
            period_gap_seconds=settings.recording_period_gap_seconds,
            segment_gap_seconds=settings.segment_gap_seconds,
        )

        upload.detected_local_dates = detected_local_dates_for_ranges(
            [(period.start_time, period.end_time) for period in period_windows],
            timezone_name,
        )

        trend_frame_to_segment: list[int] = [0 for _ in trend_frames]
        segment_windows: list[SegmentWindowRef] = []

        global_segment_counter = 0
        for period_window in period_windows:
            period = RecordingPeriod(
                upload_id=upload.id,
                period_index=period_window.period_index,
                start_time=period_window.start_time,
                end_time=period_window.end_time,
                frame_count=period_window.frame_count,
                label=f"Period {period_window.period_index + 1}",
            )
            db.add(period)
            db.flush()

            for segment_window in period_window.segments:
                segment = Segment(
                    period_id=period.id,
                    upload_id=upload.id,
                    segment_index=segment_window.segment_index,
                    start_time=segment_window.start_time,
                    end_time=segment_window.end_time,
                    frame_count=segment_window.frame_count,
                    duration_seconds=segment_window.duration_seconds,
                )
                db.add(segment)
                db.flush()

                segment_windows.append(
                    SegmentWindowRef(id=segment.id, start_time=segment.start_time, end_time=segment.end_time)
                )

                for frame_idx in range(segment_window.start_idx, segment_window.end_idx + 1):
                    trend_frame_to_segment[frame_idx] = segment.id

                global_segment_counter += 1

        # Trend channels
        trend_matrix = [frame.values for frame in trend_frames]
        trend_stats = compute_stats_for_matrix(trend_matrix)
        trend_channels: list[Channel] = []
        for idx, stats in enumerate(trend_stats):
            core_metadata = CORE_TREND_CHANNELS.get(idx)
            if core_metadata is None or stats.valid_count <= 0:
                continue
            channel_name, unit = _resolve_core_channel_metadata(
                source_type=SourceType.trend,
                channel_index=idx,
                fallback_name=core_metadata[0],
                fallback_unit=core_metadata[1],
            )
            trend_channels.append(
                Channel(
                    upload_id=upload.id,
                    source_type=SourceType.trend,
                    channel_index=idx,
                    name=channel_name,
                    unit=unit,
                    valid_count=stats.valid_count,
                )
            )
        if trend_channels:
            db.add_all(trend_channels)
            db.flush()

        trend_channel_id_by_index = {channel.channel_index: channel.id for channel in trend_channels}

        # NIBP channels
        nibp_channels: list[Channel] = []
        for idx, (fallback_name, fallback_unit) in CORE_NIBP_CHANNELS.items():
            valid_count = sum(1 for frame in nibp_frames if frame.channel_values.get(fallback_name) is not None)
            if valid_count <= 0:
                continue
            channel_name, unit = _resolve_core_channel_metadata(
                source_type=SourceType.nibp,
                channel_index=idx,
                fallback_name=fallback_name,
                fallback_unit=fallback_unit,
            )
            nibp_channels.append(
                Channel(
                    upload_id=upload.id,
                    source_type=SourceType.nibp,
                    channel_index=idx,
                    name=channel_name,
                    unit=unit,
                    valid_count=valid_count,
                )
            )
        if nibp_channels:
            db.add_all(nibp_channels)
            db.flush()

        _update_upload_progress(db, upload, phase=PHASE_SEGMENTING, progress_current=4, commit=True)

        # Trend measurements
        _update_upload_progress(db, upload, phase=PHASE_WRITING_MEASUREMENTS, progress_current=5, commit=True)
        measurements_new, measurements_reused = _persist_measurement_links(
            db,
            upload=upload,
            trend_frames=trend_frames,
            trend_channel_id_by_index=trend_channel_id_by_index,
            trend_frame_to_segment=trend_frame_to_segment,
        )
        upload.measurements_new = measurements_new
        upload.measurements_reused = measurements_reused
        _update_upload_progress(
            db,
            upload,
            phase=PHASE_WRITING_MEASUREMENTS,
            progress_increment=measurements_new + measurements_reused,
            commit=True,
        )

        # NIBP events
        _update_upload_progress(db, upload, phase=PHASE_WRITING_EVENTS, commit=True)
        nibp_new, nibp_reused = _persist_nibp_event_links(
            db,
            upload=upload,
            nibp_frames=nibp_frames,
            segment_windows=segment_windows,
        )
        upload.nibp_new = nibp_new
        upload.nibp_reused = nibp_reused
        _update_upload_progress(
            db,
            upload,
            phase=PHASE_WRITING_EVENTS,
            progress_increment=nibp_new + nibp_reused,
            commit=True,
        )

        # Alarms
        alarms_new, alarms_reused = _persist_alarm_links(
            db,
            upload=upload,
            alarm_frames=alarm_frames,
            segment_windows=segment_windows,
        )
        upload.alarms_new = alarms_new
        upload.alarms_reused = alarms_reused
        _update_upload_progress(
            db,
            upload,
            phase=PHASE_WRITING_EVENTS,
            progress_increment=alarms_new + alarms_reused,
            commit=True,
        )

        _update_upload_progress(
            db,
            upload,
            phase=PHASE_FINALIZING,
            progress_current=max(upload.progress_current, max(0, upload.progress_total - 1)),
            commit=True,
        )
        upload.status = UploadStatus.completed
        upload.phase = PHASE_COMPLETED
        upload.error_message = None
        upload.completed_at = _utcnow()
        upload.heartbeat_at = upload.completed_at
        upload.progress_current = upload.progress_total
        db.add(upload)
        db.commit()

        channel_count = db.scalar(select(func.count(Channel.id)).where(Channel.upload_id == upload.id))
        if channel_count is None:
            channel_count = len(trend_channels) + len(nibp_channels)

        return UploadParseResult(
            upload_id=upload.id,
            period_count=len(period_windows),
            segment_count=global_segment_counter,
            channel_count=channel_count,
        )
    except Exception as exc:
        db.rollback()
        failed = db.get(Upload, upload_id)
        if failed is not None:
            _set_upload_failed(db, failed, str(exc))
        raise


def process_upload_background(
    *,
    upload_id: int,
    trend_data: bytes,
    trend_index: bytes | None,
    nibp_data: bytes | None,
    nibp_index: bytes | None,
    alarm_data: bytes | None,
    alarm_index: bytes | None,
    combined_hash: str,
    timezone_name: str,
) -> None:
    db = SessionLocal()
    try:
        process_upload_for_existing_upload(
            db,
            upload_id=upload_id,
            trend_data=trend_data,
            trend_index=trend_index,
            nibp_data=nibp_data,
            nibp_index=nibp_index,
            alarm_data=alarm_data,
            alarm_index=alarm_index,
            combined_hash=combined_hash,
            timezone_name=timezone_name,
        )
    except Exception:
        logger.exception("Upload parse failed for upload_id=%s", upload_id)
    finally:
        db.close()
