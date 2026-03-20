from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..constants import CORE_NIBP_CHANNELS, CORE_TREND_CHANNELS
from ..database import (
    SessionLocal,
    build_measurement_dedup_key,
    build_nibp_dedup_key,
)
from ..models import (
    Channel,
    Encounter,
    Patient,
    Measurement,
    NibpEvent,
    RecordingPeriod,
    Segment,
    SourceType,
    UploadMeasurementLink,
    UploadNibpEventLink,
    Upload,
    UploadStatus,
)
from ..parsers.channel_stats import compute_stats_for_matrix
from ..parsers.index_parser import parse_index_bytes
from ..parsers.nibp_parser import NibpFrame, infer_nibp_measurement, nibp_channel_name, parse_nibp_frames
from ..parsers.segmenter import split_periods_and_segments
from ..parsers.trend_parser import TrendFrame, parse_trend_frames
from ..utils import coerce_utc, resolve_core_channel_metadata, trim_nibp_channel_values, utcnow
from .audit_service import log_audit_event
from .encounter_service import detected_local_dates_for_ranges, encounter_day_window
from .patient_service import prune_orphaned_canonical_rows
from .upload_security import cleanup_upload_dir, read_optional_upload_bytes
from .write_coordinator import exclusive_write


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
class ParsedMonitorData:
    trend_frames: list[TrendFrame]
    nibp_frames: list[NibpFrame]


@dataclass(frozen=True)
class UploadComponentHashes:
    trend_sha256: str
    trend_index_sha256: str
    nibp_sha256: str
    nibp_index_sha256: str


@dataclass(frozen=True)
class ParsedUploadData:
    trend_frames: list[TrendFrame]
    nibp_frames: list[NibpFrame]


@dataclass(frozen=True)
class DiscoveredChannelSummary:
    source_type: SourceType
    channel_index: int
    name: str
    unit: str | None
    valid_count: int


@dataclass(frozen=True)
class UploadDiscoverySummary:
    trend_frames: int
    nibp_frames: int
    periods: int
    segments: int
    channels: list[DiscoveredChannelSummary]
    detected_local_dates: list[str]


@dataclass(frozen=True)
class SliceComponentHashes:
    trend_sha256: str
    trend_index_sha256: str
    nibp_sha256: str
    nibp_index_sha256: str
    combined_hash: str


@dataclass(frozen=True)
class PaginatedUploadHistoryResult:
    items: list[Upload]
    total: int


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
) -> str:
    checksum_input = "|".join(
        [
            _sha256(trend_data),
            _sha256(trend_index) if trend_index is not None else _sha256(b""),
            _sha256(nibp_data) if nibp_data is not None else _sha256(b""),
            _sha256(nibp_index) if nibp_index is not None else _sha256(b""),
        ]
    )
    return _sha256(checksum_input.encode("utf-8"))


def build_combined_hash_from_component_hashes(component_hashes: UploadComponentHashes) -> str:
    return _sha256(
        "|".join(
            [
                component_hashes.trend_sha256,
                component_hashes.trend_index_sha256,
                component_hashes.nibp_sha256,
                component_hashes.nibp_index_sha256,
            ]
        ).encode("utf-8")
    )


EMPTY_SHA256 = _sha256(b"")

PHASE_READING = "reading"
PHASE_PARSING = "parsing"
PHASE_SEGMENTING = "segmenting"
PHASE_WRITING_MEASUREMENTS = "writing_measurements"
PHASE_WRITING_EVENTS = "writing_events"
PHASE_FINALIZING = "finalizing"
PHASE_COMPLETED = "completed"
PHASE_ERROR = "error"

CORE_NIBP_VALUE_KEYS = tuple(name for name, _ in CORE_NIBP_CHANNELS.values())


def _coerce_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return coerce_utc(dt)








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

    now = utcnow()
    if upload.started_at is None:
        upload.started_at = now
    upload.heartbeat_at = now

    if upload.progress_total and upload.progress_current > upload.progress_total:
        upload.progress_current = upload.progress_total

    db.add(upload)
    if commit:
        db.commit()


def _set_upload_failed(db: Session, upload: Upload, message: str) -> None:
    now = utcnow()
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
    now = utcnow()
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


def purge_stale_orphan_uploads(db: Session, *, commit: bool = True) -> int:
    cutoff = utcnow() - timedelta(days=max(1, settings.orphan_upload_retention_days))
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
    if deleted and commit:
        db.commit()
    return deleted


def purge_duplicate_orphan_uploads(db: Session, *, commit: bool = True) -> int:
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

    if deleted and commit:
        db.commit()
    return deleted


def list_patient_upload_history_page(
    db: Session,
    *,
    patient_id: int,
    limit: int,
    offset: int,
) -> PaginatedUploadHistoryResult:
    total = int(db.scalar(select(func.count(Upload.id)).where(Upload.patient_id == patient_id)) or 0)
    uploads = db.scalars(
        select(Upload)
        .where(Upload.patient_id == patient_id)
        .order_by(Upload.upload_time.desc(), Upload.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    for upload in uploads:
        fail_stale_upload_if_needed(db, upload)
    return PaginatedUploadHistoryResult(items=list(uploads), total=total)


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
        if not any(frame.values[channel_index] is not None for channel_index in trend_channel_id_by_index):
            continue
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
        trimmed_channel_values, has_measurement = trim_nibp_channel_values(frame.channel_values)
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


def parse_monitor_export(
    *,
    trend_data: bytes,
    trend_index: bytes | None,
    nibp_data: bytes | None,
    nibp_index: bytes | None,
) -> ParsedUploadData:
    invalid_u16_values = settings.invalid_u16_set

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

    if parsed_trend_index is not None:
        _log_index_rollbacks("trend", parsed_trend_index.rollback_indices)
    if parsed_nibp_index is not None:
        _log_index_rollbacks("nibp", parsed_nibp_index.rollback_indices)

    trend_frames = parse_trend_frames(trend_data, parsed_trend_index, invalid_u16_values)
    nibp_frames = (
        parse_nibp_frames(nibp_data, parsed_nibp_index, invalid_u16_values)
        if nibp_data is not None and parsed_nibp_index is not None
        else []
    )
    if not trend_frames:
        raise ValueError("Trend file has no frames to build sessions")

    return ParsedUploadData(
        trend_frames=trend_frames,
        nibp_frames=nibp_frames,
    )


def summarize_parsed_upload(parsed_upload: ParsedUploadData, *, timezone_name: str) -> UploadDiscoverySummary:
    timestamps = [frame.timestamp for frame in parsed_upload.trend_frames]
    period_windows = split_periods_and_segments(
        timestamps=timestamps,
        period_gap_seconds=settings.recording_period_gap_seconds,
        segment_gap_seconds=settings.segment_gap_seconds,
    )

    trend_matrix = [frame.values for frame in parsed_upload.trend_frames]
    trend_stats = compute_stats_for_matrix(trend_matrix)

    channels: list[DiscoveredChannelSummary] = []
    for idx, stats in enumerate(trend_stats):
        core_metadata = CORE_TREND_CHANNELS.get(idx)
        if core_metadata is None or stats.valid_count <= 0:
            continue
        channel_name, unit = resolve_core_channel_metadata(
            source_type=SourceType.trend,
            channel_index=idx,
            fallback_name=core_metadata[0],
            fallback_unit=core_metadata[1],
        )
        channels.append(
            DiscoveredChannelSummary(
                source_type=SourceType.trend,
                channel_index=idx,
                name=channel_name,
                unit=unit,
                valid_count=stats.valid_count,
            )
        )

    for idx, (fallback_name, fallback_unit) in CORE_NIBP_CHANNELS.items():
        valid_count = sum(
            1 for frame in parsed_upload.nibp_frames if frame.channel_values.get(fallback_name) is not None
        )
        if valid_count <= 0:
            continue
        channel_name, unit = resolve_core_channel_metadata(
            source_type=SourceType.nibp,
            channel_index=idx,
            fallback_name=fallback_name,
            fallback_unit=fallback_unit,
        )
        channels.append(
            DiscoveredChannelSummary(
                source_type=SourceType.nibp,
                channel_index=idx,
                name=channel_name,
                unit=unit,
                valid_count=valid_count,
            )
        )

    return UploadDiscoverySummary(
        trend_frames=len(parsed_upload.trend_frames),
        nibp_frames=len(parsed_upload.nibp_frames),
        periods=len(period_windows),
        segments=sum(len(period_window.segments) for period_window in period_windows),
        channels=channels,
        detected_local_dates=detected_local_dates_for_ranges(
            [(period.start_time, period.end_time) for period in period_windows],
            timezone_name,
        ),
    )


def filter_parsed_upload_for_day_window(
    parsed_upload: ParsedUploadData,
    *,
    encounter_date_local: date,
    timezone_name: str,
) -> ParsedUploadData:
    window_start_naive, window_end_naive = encounter_day_window(encounter_date_local, timezone_name)
    window_start = window_start_naive.replace(tzinfo=UTC)
    window_end = window_end_naive.replace(tzinfo=UTC)

    def _in_window(timestamp: datetime) -> bool:
        candidate = timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=UTC)
        return window_start <= candidate <= window_end

    filtered_trend_frames = [
        TrendFrame(frame_index=index, timestamp=frame.timestamp, values=list(frame.values))
        for index, frame in enumerate(frame for frame in parsed_upload.trend_frames if _in_window(frame.timestamp))
    ]

    return ParsedUploadData(
        trend_frames=filtered_trend_frames,
        nibp_frames=[frame for frame in parsed_upload.nibp_frames if _in_window(frame.timestamp)],
    )


def _stable_hash(payload: object) -> str:
    return _sha256(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def build_selected_slice_hashes(
    parsed_upload: ParsedUploadData,
    *,
    patient_id: int,
    encounter_date_local: date,
    timezone_name: str,
) -> SliceComponentHashes:
    trend_rows = [
        {
            "timestamp": _coerce_utc(frame.timestamp).isoformat().replace("+00:00", "Z"),
            "spo2_be_u16": frame.values[14] if len(frame.values) > 14 else None,
            "heart_rate_be_u16": frame.values[16] if len(frame.values) > 16 else None,
        }
        for frame in parsed_upload.trend_frames
    ]
    trend_index_rows = [row["timestamp"] for row in trend_rows]

    nibp_rows = [
        {
            "timestamp": _coerce_utc(frame.timestamp).isoformat().replace("+00:00", "Z"),
            "channel_values": trim_nibp_channel_values(frame.channel_values)[0],
        }
        for frame in parsed_upload.nibp_frames
    ]
    nibp_index_rows = [row["timestamp"] for row in nibp_rows]

    trend_sha256 = _stable_hash(trend_rows) if trend_rows else EMPTY_SHA256
    trend_index_sha256 = _stable_hash(trend_index_rows) if trend_index_rows else EMPTY_SHA256
    nibp_sha256 = _stable_hash(nibp_rows) if nibp_rows else EMPTY_SHA256
    nibp_index_sha256 = _stable_hash(nibp_index_rows) if nibp_index_rows else EMPTY_SHA256

    combined_hash = _sha256(
        "|".join(
            [
                str(patient_id),
                encounter_date_local.isoformat(),
                timezone_name,
                trend_sha256,
                trend_index_sha256,
                nibp_sha256,
                nibp_index_sha256,
            ]
        ).encode("utf-8")
    )

    return SliceComponentHashes(
        trend_sha256=trend_sha256,
        trend_index_sha256=trend_index_sha256,
        nibp_sha256=nibp_sha256,
        nibp_index_sha256=nibp_index_sha256,
        combined_hash=combined_hash,
    )


def persist_parsed_upload_for_existing_upload(
    db: Session,
    *,
    upload_id: int,
    parsed_upload: ParsedUploadData,
    timezone_name: str,
    slice_hashes: SliceComponentHashes | None = None,
) -> UploadParseResult:
    upload = db.get(Upload, upload_id)
    if upload is None:
        raise ValueError(f"Upload not found: {upload_id}")

    try:
        trend_frames = parsed_upload.trend_frames
        nibp_frames = parsed_upload.nibp_frames
        if not trend_frames:
            raise ValueError("Selected encounter day has no trend frames to save")

        retained_trend_channel_count = sum(
            1 for channel_index in CORE_TREND_CHANNELS if channel_index < len(trend_frames[0].values)
        )
        measurement_total = len(trend_frames) * retained_trend_channel_count
        event_total = len(nibp_frames)
        progress_total = max(5, measurement_total + event_total + 5)

        upload.status = UploadStatus.processing
        upload.phase = PHASE_PARSING
        upload.error_message = None
        upload.completed_at = None
        upload.trend_frames = len(trend_frames)
        upload.nibp_frames = len(nibp_frames)
        if slice_hashes is not None:
            upload.trend_sha256 = slice_hashes.trend_sha256
            upload.trend_index_sha256 = slice_hashes.trend_index_sha256
            upload.nibp_sha256 = slice_hashes.nibp_sha256
            upload.nibp_index_sha256 = slice_hashes.nibp_index_sha256
            upload.combined_hash = slice_hashes.combined_hash
        upload.measurements_new = 0
        upload.measurements_reused = 0
        upload.nibp_new = 0
        upload.nibp_reused = 0
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

        trend_matrix = [frame.values for frame in trend_frames]
        trend_stats = compute_stats_for_matrix(trend_matrix)
        trend_channels: list[Channel] = []
        for idx, stats in enumerate(trend_stats):
            core_metadata = CORE_TREND_CHANNELS.get(idx)
            if core_metadata is None or stats.valid_count <= 0:
                continue
            channel_name, unit = resolve_core_channel_metadata(
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

        nibp_channels: list[Channel] = []
        for idx, (fallback_name, fallback_unit) in CORE_NIBP_CHANNELS.items():
            valid_count = sum(1 for frame in nibp_frames if frame.channel_values.get(fallback_name) is not None)
            if valid_count <= 0:
                continue
            channel_name, unit = resolve_core_channel_metadata(
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
        upload.completed_at = utcnow()
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


def create_upload_stub(
    db: Session,
    *,
    patient: Patient,
    trend_data: bytes,
    trend_index: bytes | None,
    nibp_data: bytes | None,
    nibp_index: bytes | None,
    combined_hash: str | None = None,
) -> Upload:
    now = utcnow()
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
        trend_sha256=_sha256(trend_data),
        trend_index_sha256=_sha256(trend_index) if trend_index is not None else EMPTY_SHA256,
        nibp_sha256=_sha256(nibp_data) if nibp_data is not None else EMPTY_SHA256,
        nibp_index_sha256=_sha256(nibp_index) if nibp_index is not None else EMPTY_SHA256,
        combined_hash=combined_hash
        or build_combined_hash(
            trend_data=trend_data,
            trend_index=trend_index,
            nibp_data=nibp_data,
            nibp_index=nibp_index,
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
            ),
        )
        if existing is None:
            raise
        raise DuplicateUploadError(existing) from exc
    db.refresh(upload)
    return upload


def create_upload_stub_from_component_hashes(
    db: Session,
    *,
    patient: Patient,
    component_hashes: UploadComponentHashes,
) -> Upload:
    combined_hash = build_combined_hash_from_component_hashes(component_hashes)
    now = utcnow()
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
        trend_sha256=component_hashes.trend_sha256,
        trend_index_sha256=component_hashes.trend_index_sha256,
        nibp_sha256=component_hashes.nibp_sha256,
        nibp_index_sha256=component_hashes.nibp_index_sha256,
        combined_hash=combined_hash,
        detected_local_dates=[],
    )
    db.add(upload)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = find_reusable_upload(db, combined_hash=combined_hash)
        if existing is None:
            raise
        raise DuplicateUploadError(existing) from exc
    db.refresh(upload)
    return upload


def create_upload_record_from_component_hashes(
    db: Session,
    *,
    patient: Patient,
    component_hashes: UploadComponentHashes,
    actor: str,
) -> Upload:
    upload = create_upload_stub_from_component_hashes(
        db,
        patient=patient,
        component_hashes=component_hashes,
    )
    log_audit_event(
        db,
        action="created",
        entity_type="upload",
        entity_id=upload.id,
        actor=actor,
        details={
            "patient_id": patient.id,
            "combined_hash": upload.combined_hash,
            "exact_duplicate": False,
        },
        commit=True,
    )
    db.refresh(upload)
    return upload


def create_upload_stub_from_slice_hashes(
    db: Session,
    *,
    patient: Patient,
    slice_hashes: SliceComponentHashes,
) -> Upload:
    now = utcnow()
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
        trend_sha256=slice_hashes.trend_sha256,
        trend_index_sha256=slice_hashes.trend_index_sha256,
        nibp_sha256=slice_hashes.nibp_sha256,
        nibp_index_sha256=slice_hashes.nibp_index_sha256,
        combined_hash=slice_hashes.combined_hash,
        detected_local_dates=[],
    )
    db.add(upload)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = find_reusable_upload(db, combined_hash=slice_hashes.combined_hash)
        if existing is None:
            raise
        raise DuplicateUploadError(existing) from exc
    db.refresh(upload)
    return upload


def delete_upload_record(db: Session, upload: Upload, *, actor: str) -> None:
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
        },
    )
    db.delete(upload)
    db.flush()
    prune_orphaned_canonical_rows(db)
    db.commit()


def process_upload(
    db: Session,
    *,
    patient: Patient,
    trend_data: bytes,
    trend_index: bytes | None,
    nibp_data: bytes | None,
    nibp_index: bytes | None,
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
        combined_hash=combined_hash,
    )
    return process_upload_for_existing_upload(
        db,
        upload_id=upload.id,
        trend_data=trend_data,
        trend_index=trend_index,
        nibp_data=nibp_data,
        nibp_index=nibp_index,
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
    combined_hash: str | None = None,
    timezone_name: str = "UTC",
) -> UploadParseResult:
    with exclusive_write(
        "upload persistence",
        wait=True,
        busy_detail="Upload persistence is already in progress.",
    ):
        upload = db.get(Upload, upload_id)
        if upload is None:
            raise ValueError(f"Upload not found: {upload_id}")

        try:
            _update_upload_progress(
                db,
                upload,
                phase=PHASE_PARSING,
                progress_current=1,
                progress_total=5,
                commit=True,
            )
            parsed_upload = parse_monitor_export(
                trend_data=trend_data,
                trend_index=trend_index,
                nibp_data=nibp_data,
                nibp_index=nibp_index,
            )

            upload.trend_sha256 = _sha256(trend_data)
            upload.trend_index_sha256 = _sha256(trend_index) if trend_index is not None else EMPTY_SHA256
            upload.nibp_sha256 = _sha256(nibp_data) if nibp_data is not None else EMPTY_SHA256
            upload.nibp_index_sha256 = _sha256(nibp_index) if nibp_index is not None else EMPTY_SHA256
            upload.combined_hash = combined_hash or build_combined_hash(
                trend_data=trend_data,
                trend_index=trend_index,
                nibp_data=nibp_data,
                nibp_index=nibp_index,
            )
            db.add(upload)
            db.commit()

            return persist_parsed_upload_for_existing_upload(
                db,
                upload_id=upload_id,
                parsed_upload=parsed_upload,
                timezone_name=timezone_name,
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
            combined_hash=combined_hash,
            timezone_name=timezone_name,
        )
        from .upload_maintenance_service import run_opportunistic_maintenance

        run_opportunistic_maintenance()
    except Exception:
        logger.exception("Upload parse failed for upload_id=%s", upload_id)
    finally:
        db.close()


def process_upload_background_from_spool(
    *,
    upload_id: int,
    spool_dir: str,
    timezone_name: str,
) -> None:
    db = SessionLocal()
    spool_path = Path(spool_dir)
    try:
        process_upload_for_existing_upload(
            db,
            upload_id=upload_id,
            trend_data=read_optional_upload_bytes(spool_path / "TrendChartRecord.data") or b"",
            trend_index=read_optional_upload_bytes(spool_path / "TrendChartRecord.Index"),
            nibp_data=read_optional_upload_bytes(spool_path / "NibpRecord.data"),
            nibp_index=read_optional_upload_bytes(spool_path / "NibpRecord.Index"),
            timezone_name=timezone_name,
        )
        from .upload_maintenance_service import run_opportunistic_maintenance

        run_opportunistic_maintenance()
    except Exception:
        logger.exception("Upload parse failed for upload_id=%s", upload_id)
    finally:
        cleanup_upload_dir(spool_path)
        db.close()
