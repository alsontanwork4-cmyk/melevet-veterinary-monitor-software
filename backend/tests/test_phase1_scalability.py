from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base, get_db
from app.models import (
    Channel,
    Encounter,
    Measurement,
    NibpEvent,
    Patient,
    RecordingPeriod,
    Segment,
    SourceType,
    Upload,
    UploadMeasurementLink,
    UploadNibpEventLink,
    UploadStatus,
)
from app.routers import patients as patients_router
from app.routers import settings as settings_router
from app.services.upload_maintenance_service import run_opportunistic_maintenance
from app.services.write_coordinator import exclusive_write


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


def _override_get_db(session_factory) -> Generator[Session, None, None]:
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


def _build_client(session_factory) -> TestClient:
    app = FastAPI()

    def override():
        yield from _override_get_db(session_factory)

    app.dependency_overrides[get_db] = override
    app.include_router(patients_router.router, prefix="/api")
    app.include_router(settings_router.router, prefix="/api")
    return TestClient(app)


def _new_upload(patient_id: int, *, upload_time: datetime, combined_hash: str) -> Upload:
    checksum = combined_hash[:64].ljust(64, "0")
    return Upload(
        patient_id=patient_id,
        upload_time=upload_time,
        status=UploadStatus.completed,
        phase="completed",
        progress_current=1,
        progress_total=1,
        trend_frames=1,
        nibp_frames=1,
        trend_sha256=checksum,
        trend_index_sha256=checksum,
        nibp_sha256=checksum,
        nibp_index_sha256=checksum,
        combined_hash=checksum,
        detected_local_dates=["2026-03-05"],
        completed_at=upload_time,
    )


def test_patient_uploads_endpoint_paginates_with_stable_order() -> None:
    session_factory = _session_factory()
    with session_factory() as db:
        patient = Patient(patient_id_code="P-001", name="Patient", species="Dog")
        db.add(patient)
        db.flush()
        db.add_all(
            [
                _new_upload(patient.id, upload_time=datetime(2026, 3, 3, 10, 0, 0), combined_hash="1" * 64),
                _new_upload(patient.id, upload_time=datetime(2026, 3, 2, 10, 0, 0), combined_hash="2" * 64),
                _new_upload(patient.id, upload_time=datetime(2026, 3, 1, 10, 0, 0), combined_hash="3" * 64),
            ]
        )
        db.commit()

    client = _build_client(session_factory)
    response = client.get("/api/patients/1/uploads", params={"limit": 2, "offset": 1})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert payload["limit"] == 2
    assert payload["offset"] == 1
    assert [item["id"] for item in payload["items"]] == [2, 3]


def test_upload_nibp_events_pagination_applies_filters_before_page_slice() -> None:
    session_factory = _session_factory()
    with session_factory() as db:
        patient = Patient(patient_id_code="P-002", name="Patient", species="Dog")
        db.add(patient)
        db.flush()
        upload = _new_upload(patient.id, upload_time=datetime(2026, 3, 3, 10, 0, 0), combined_hash="4" * 64)
        db.add(upload)
        db.flush()
        period = RecordingPeriod(
            upload_id=upload.id,
            period_index=0,
            start_time=datetime(2026, 3, 3, 10, 0, 0),
            end_time=datetime(2026, 3, 3, 10, 5, 0),
            frame_count=3,
            label="Period 1",
        )
        db.add(period)
        db.flush()
        segment = Segment(
            period_id=period.id,
            upload_id=upload.id,
            segment_index=0,
            start_time=period.start_time,
            end_time=period.end_time,
            frame_count=3,
            duration_seconds=300,
        )
        db.add(segment)
        db.flush()
        db.add_all(
            [
                NibpEvent(
                    upload_id=upload.id,
                    segment_id=segment.id,
                    timestamp=datetime(2026, 3, 3, 10, 0, 0),
                    channel_values={"bp_systolic_inferred": 120},
                    has_measurement=False,
                    dedup_key="nibp-0",
                ),
                NibpEvent(
                    upload_id=upload.id,
                    segment_id=segment.id,
                    timestamp=datetime(2026, 3, 3, 10, 1, 0),
                    channel_values={"bp_systolic_inferred": 121},
                    has_measurement=True,
                    dedup_key="nibp-1",
                ),
                NibpEvent(
                    upload_id=upload.id,
                    segment_id=segment.id,
                    timestamp=datetime(2026, 3, 3, 10, 2, 0),
                    channel_values={"bp_systolic_inferred": 122},
                    has_measurement=True,
                    dedup_key="nibp-2",
                ),
            ]
        )
        db.commit()
        upload_id = upload.id

    client = _build_client(session_factory)
    response = client.get(
        f"/api/uploads/{upload_id}/nibp-events",
        params={"measurements_only": True, "limit": 1, "offset": 0},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert len(payload["items"]) == 1
    assert payload["items"][0]["timestamp"] == "2026-03-03T10:01:00Z"


def test_settings_diagnostics_reports_counts_and_threshold_flags() -> None:
    session_factory = _session_factory()
    original_threshold = settings.link_table_warning_threshold
    settings.link_table_warning_threshold = 1
    try:
        with session_factory() as db:
            patient = Patient(patient_id_code="P-003", name="Patient", species="Dog")
            db.add(patient)
            db.flush()
            upload = _new_upload(patient.id, upload_time=datetime(2026, 3, 4, 10, 0, 0), combined_hash="5" * 64)
            db.add(upload)
            db.flush()
            period = RecordingPeriod(
                upload_id=upload.id,
                period_index=0,
                start_time=datetime(2026, 3, 4, 10, 0, 0),
                end_time=datetime(2026, 3, 4, 10, 5, 0),
                frame_count=1,
                label="Period 1",
            )
            db.add(period)
            db.flush()
            segment = Segment(
                period_id=period.id,
                upload_id=upload.id,
                segment_index=0,
                start_time=period.start_time,
                end_time=period.end_time,
                frame_count=1,
                duration_seconds=300,
            )
            db.add(segment)
            db.flush()
            channel = Channel(
                upload_id=upload.id,
                source_type=SourceType.trend,
                channel_index=16,
                name="Heart Rate",
                unit="bpm",
                valid_count=1,
            )
            db.add(channel)
            db.flush()
            measurement = Measurement(
                upload_id=upload.id,
                segment_id=segment.id,
                channel_id=channel.id,
                timestamp=datetime(2026, 3, 4, 10, 1, 0),
                value=88.0,
                dedup_key="measurement-1",
            )
            nibp_event = NibpEvent(
                upload_id=upload.id,
                segment_id=segment.id,
                timestamp=datetime(2026, 3, 4, 10, 2, 0),
                channel_values={"bp_systolic_inferred": 120},
                has_measurement=True,
                dedup_key="nibp-event-1",
            )
            db.add_all([measurement, nibp_event])
            db.flush()
            db.add_all(
                [
                    UploadMeasurementLink(
                        upload_id=upload.id,
                        segment_id=segment.id,
                        channel_id=channel.id,
                        measurement_id=measurement.id,
                        timestamp=measurement.timestamp,
                    ),
                    UploadNibpEventLink(
                        upload_id=upload.id,
                        segment_id=segment.id,
                        nibp_event_id=nibp_event.id,
                        timestamp=nibp_event.timestamp,
                    ),
                ]
            )
            db.commit()

        client = _build_client(session_factory)
        response = client.get("/api/settings/diagnostics")

        assert response.status_code == 200
        payload = response.json()
        assert payload["measurement_count"] == 1
        assert payload["upload_measurement_link_count"] == 1
        assert payload["upload_nibp_event_link_count"] == 1
        assert payload["link_table_warning_threshold"] == 1
        assert payload["upload_measurement_links_over_threshold"] is False
        assert payload["sqlite_file_size_bytes"] is None or payload["sqlite_file_size_bytes"] >= 0
    finally:
        settings.link_table_warning_threshold = original_threshold


def test_opportunistic_maintenance_skips_when_write_lock_is_held() -> None:
    session_factory = _session_factory()
    with session_factory() as db:
        patient = Patient(patient_id_code="P-004", name="Patient", species="Dog")
        db.add(patient)
        db.flush()
        upload = _new_upload(
            patient.id,
            upload_time=datetime.now(UTC) - timedelta(days=10),
            combined_hash="6" * 64,
        )
        db.add(upload)
        db.commit()

        with exclusive_write("held", wait=True, busy_detail="held"):
            run_opportunistic_maintenance(bind=db.get_bind())

        remaining_upload_ids = db.scalars(select(Upload.id).order_by(Upload.id.asc())).all()
        assert remaining_upload_ids == [upload.id]
