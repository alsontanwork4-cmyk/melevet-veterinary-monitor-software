from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.database import Base
from app.models import Measurement, Patient, Upload, UploadStatus
from app.services.chart_service import list_upload_measurements
from app.services.upload_service import (
    DuplicateUploadError,
    create_upload_stub,
    fail_stale_upload_if_needed,
    find_reusable_upload,
    process_upload_for_existing_upload,
)


def _make_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
    return session_factory()


def _build_trend_data(frame_count: int = 1) -> bytes:
    frame = bytearray(124)
    for channel_index in range(61):
        value = channel_index + 1
        offset = channel_index * 2
        frame[offset : offset + 2] = value.to_bytes(2, "big")
    return bytes(frame) * frame_count


def _build_trend_data_with_timestamps(
    frame_count: int,
    *,
    start_unix_seconds: int,
) -> bytes:
    payload = bytearray()
    for frame_index in range(frame_count):
        frame = bytearray(124)
        frame[2:6] = (start_unix_seconds + frame_index).to_bytes(4, "little")
        for channel_index in range(61):
            value = channel_index + 1 + frame_index
            offset = channel_index * 2
            frame[offset : offset + 2] = value.to_bytes(2, "big")
        payload.extend(frame)
    return bytes(payload)


def _build_index(frame_count: int = 1, start_unix_seconds: int = 1_700_000_000) -> bytes:
    header = (
        (1).to_bytes(4, "little")
        + (124).to_bytes(4, "little")
        + (122).to_bytes(4, "little")
        + (0).to_bytes(4, "little")
    )

    entries = bytearray()
    for frame_index in range(frame_count):
        unix_seconds = start_unix_seconds + frame_index
        ts_hi = (unix_seconds >> 16) & 0xFFFF
        ts_lo = (unix_seconds & 0xFFFF) << 16
        entries.extend((0).to_bytes(4, "little"))  # flags
        entries.extend((0).to_bytes(4, "little"))  # ptr
        entries.extend(ts_lo.to_bytes(4, "little"))
        entries.extend(ts_hi.to_bytes(4, "little"))

    trailer = b"\x00" * 6
    return header + bytes(entries) + trailer


def _create_patient(db: Session, suffix: str = "a") -> Patient:
    patient = Patient(
        patient_id_code=f"P-{suffix}",
        name=f"Patient {suffix}",
        species="Cat",
    )
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient


def test_create_upload_stub_initializes_progress_fields() -> None:
    with _make_session() as db:
        patient = _create_patient(db, "stub")
        upload = create_upload_stub(
            db,
            patient=patient,
            trend_data=b"trend",
            trend_index=b"index",
            nibp_data=None,
            nibp_index=None,
            alarm_data=None,
            alarm_index=None,
        )

        assert upload.status == UploadStatus.processing
        assert upload.phase == "reading"
        assert upload.progress_current == 0
        assert upload.progress_total == 0
        assert upload.started_at is not None
        assert upload.heartbeat_at is not None
        assert upload.completed_at is None


def test_process_upload_marks_completed_with_final_progress() -> None:
    trend_data = _build_trend_data(frame_count=1)
    trend_index = _build_index(frame_count=1)

    with _make_session() as db:
        patient = _create_patient(db, "complete")
        upload = create_upload_stub(
            db,
            patient=patient,
            trend_data=trend_data,
            trend_index=trend_index,
            nibp_data=None,
            nibp_index=None,
            alarm_data=None,
            alarm_index=None,
        )

        result = process_upload_for_existing_upload(
            db,
            upload_id=upload.id,
            trend_data=trend_data,
            trend_index=trend_index,
            nibp_data=None,
            nibp_index=None,
            alarm_data=None,
            alarm_index=None,
        )

        refreshed = db.get(Upload, result.upload_id)
        assert refreshed is not None
        assert refreshed.status == UploadStatus.completed
        assert refreshed.phase == "completed"
        assert refreshed.completed_at is not None
        assert refreshed.progress_total > 0
        assert refreshed.progress_current == refreshed.progress_total


def test_stale_processing_upload_is_marked_error() -> None:
    with _make_session() as db:
        patient = _create_patient(db, "stale")
        upload = create_upload_stub(
            db,
            patient=patient,
            trend_data=b"trend",
            trend_index=b"index",
            nibp_data=None,
            nibp_index=None,
            alarm_data=None,
            alarm_index=None,
        )

        upload.heartbeat_at = datetime.now(UTC) - timedelta(seconds=settings.upload_timeout_seconds + 5)
        db.add(upload)
        db.commit()

        assert fail_stale_upload_if_needed(db, upload) is True

        db.refresh(upload)
        assert upload.status == UploadStatus.error
        assert upload.phase == "error"
        assert upload.error_message is not None
        assert "interrupted" in upload.error_message.lower()


def test_find_reusable_upload_is_global_by_hash() -> None:
    with _make_session() as db:
        first_patient = _create_patient(db, "reuse-a")
        upload = create_upload_stub(
            db,
            patient=first_patient,
            trend_data=b"trend",
            trend_index=b"index",
            nibp_data=None,
            nibp_index=None,
            alarm_data=None,
            alarm_index=None,
            combined_hash="same-hash",
        )
        upload.status = UploadStatus.completed
        upload.phase = "completed"
        db.add(upload)
        db.commit()

        reused_upload = find_reusable_upload(db, combined_hash="same-hash")

        assert reused_upload is not None
        assert reused_upload.id == upload.id


def test_create_upload_stub_raises_for_exact_duplicate_hash() -> None:
    with _make_session() as db:
        patient = _create_patient(db, "duplicate")

        create_upload_stub(
            db,
            patient=patient,
            trend_data=b"trend-a",
            trend_index=b"index-a",
            nibp_data=None,
            nibp_index=None,
            alarm_data=None,
            alarm_index=None,
            combined_hash="shared-hash",
        )

        with pytest.raises(DuplicateUploadError):
            create_upload_stub(
                db,
                patient=patient,
                trend_data=b"trend-b",
                trend_index=b"index-b",
                nibp_data=None,
                nibp_index=None,
                alarm_data=None,
                alarm_index=None,
                combined_hash="shared-hash",
            )


def test_partial_overlap_upload_reuses_existing_measurements_and_keeps_full_view() -> None:
    with _make_session() as db:
        patient = _create_patient(db, "overlap")
        start_unix = 1_700_100_000

        first_trend_data = _build_trend_data_with_timestamps(10, start_unix_seconds=start_unix)
        first_trend_index = _build_index(frame_count=10, start_unix_seconds=start_unix)
        first_upload = create_upload_stub(
            db,
            patient=patient,
            trend_data=first_trend_data,
            trend_index=first_trend_index,
            nibp_data=None,
            nibp_index=None,
            alarm_data=None,
            alarm_index=None,
        )
        process_upload_for_existing_upload(
            db,
            upload_id=first_upload.id,
            trend_data=first_trend_data,
            trend_index=first_trend_index,
            nibp_data=None,
            nibp_index=None,
            alarm_data=None,
            alarm_index=None,
        )

        second_trend_data = _build_trend_data_with_timestamps(15, start_unix_seconds=start_unix)
        second_trend_index = _build_index(frame_count=15, start_unix_seconds=start_unix)
        second_upload = create_upload_stub(
            db,
            patient=patient,
            trend_data=second_trend_data,
            trend_index=second_trend_index,
            nibp_data=None,
            nibp_index=None,
            alarm_data=None,
            alarm_index=None,
        )
        process_upload_for_existing_upload(
            db,
            upload_id=second_upload.id,
            trend_data=second_trend_data,
            trend_index=second_trend_index,
            nibp_data=None,
            nibp_index=None,
            alarm_data=None,
            alarm_index=None,
        )

        db.refresh(second_upload)
        canonical_measurement_count = db.scalar(select(func.count(Measurement.id)))
        upload_rows = list_upload_measurements(
            db,
            upload_id=second_upload.id,
            channel_ids=None,
            from_ts=None,
            to_ts=None,
            max_points=None,
        )

        assert second_upload.measurements_new == 10
        assert second_upload.measurements_reused == 20
        assert len(upload_rows) == 30
        assert db.scalar(select(func.count(Upload.id))) == 2
        assert canonical_measurement_count == 30
