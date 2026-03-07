from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
import time
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import (
    Alarm,
    AlarmCategory,
    Channel,
    Measurement,
    NibpEvent,
    Patient,
    RecordingPeriod,
    Segment,
    SourceType,
    Upload,
    UploadStatus,
)
from app.routers.decode import router as decode_router
from app.services.decode_export_service import (
    ALARM_WORKBOOK_NAME,
    NIBP_WORKBOOK_NAME,
    TREND_WORKBOOK_NAME,
    build_decode_export_archive,
)


app = FastAPI()
app.include_router(decode_router, prefix="/api")
client = TestClient(app)


def _file_bytes(data_dir, relative_path: str) -> bytes:
    return (data_dir / relative_path).read_bytes()


def _zip_names(payload: bytes) -> list[str]:
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        return sorted(archive.namelist())


def _wait_for_job(job_id: str, *, timeout_seconds: float = 30.0) -> dict[str, object]:
    started_at = time.monotonic()
    while time.monotonic() - started_at < timeout_seconds:
        response = client.get(f"/api/decode/jobs/{job_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] in {"completed", "error"}:
            return payload
        time.sleep(0.05)
    raise AssertionError(f"Timed out waiting for decode job {job_id}")


def _build_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
    return session_factory()


def _table_counts(db: Session) -> dict[str, int]:
    return {
        "patients": db.scalar(select(func.count(Patient.id))) or 0,
        "uploads": db.scalar(select(func.count(Upload.id))) or 0,
        "recording_periods": db.scalar(select(func.count(RecordingPeriod.id))) or 0,
        "segments": db.scalar(select(func.count(Segment.id))) or 0,
        "channels": db.scalar(select(func.count(Channel.id))) or 0,
        "measurements": db.scalar(select(func.count(Measurement.id))) or 0,
        "nibp_events": db.scalar(select(func.count(NibpEvent.id))) or 0,
        "alarms": db.scalar(select(func.count(Alarm.id))) or 0,
    }


def _seed_decode_irrelevant_rows(db: Session) -> None:
    checksum = "1" * 64
    patient = Patient(patient_id_code="DECODE-001", name="Decode Patient", species="Dog")
    db.add(patient)
    db.flush()

    upload = Upload(
        patient_id=patient.id,
        status=UploadStatus.completed,
        phase="completed",
        progress_current=1,
        progress_total=1,
        trend_frames=1,
        nibp_frames=1,
        alarm_frames=1,
        trend_sha256=checksum,
        trend_index_sha256=checksum,
        nibp_sha256=checksum,
        nibp_index_sha256=checksum,
        alarm_sha256=checksum,
        alarm_index_sha256=checksum,
        combined_hash=checksum,
        detected_local_dates=["2026-03-07"],
        completed_at=datetime(2026, 3, 7, 0, 0, 0, tzinfo=UTC),
    )
    db.add(upload)
    db.flush()

    period = RecordingPeriod(
        upload_id=upload.id,
        period_index=0,
        start_time=datetime(2026, 3, 7, 0, 0, 0),
        end_time=datetime(2026, 3, 7, 0, 5, 0),
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
        name="heart_rate_be_u16",
        unit="bpm",
        valid_count=1,
    )
    db.add(channel)
    db.flush()

    db.add(
        Measurement(
            upload_id=upload.id,
            segment_id=segment.id,
            channel_id=channel.id,
            timestamp=datetime(2026, 3, 7, 0, 1, 0),
            value=88.0,
            dedup_key="measurement-seed-1",
        )
    )
    db.add(
        NibpEvent(
            upload_id=upload.id,
            segment_id=segment.id,
            timestamp=datetime(2026, 3, 7, 0, 2, 0),
            channel_values={"bp_systolic_inferred": 120, "bp_mean_inferred": 90, "bp_diastolic_inferred": 70},
            has_measurement=True,
            dedup_key="nibp-seed-1",
        )
    )
    db.add(
        Alarm(
            upload_id=upload.id,
            segment_id=segment.id,
            timestamp=datetime(2026, 3, 7, 0, 3, 0),
            flag_hi=4,
            flag_lo=2,
            alarm_category=AlarmCategory.informational,
            message="Existing alarm",
            dedup_key="alarm-seed-1",
        )
    )
    db.commit()


def test_decode_export_rejects_empty_request() -> None:
    response = client.post("/api/decode/export", data={"timezone": "UTC"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Upload at least one complete record pair to decode"


def test_decode_export_rejects_partial_pair(data_dir) -> None:
    response = client.post(
        "/api/decode/export",
        data={"timezone": "UTC"},
        files={
            "trend_data": ("TrendChartRecord.data", _file_bytes(data_dir, "Records/TrendChartRecord.data"), "application/octet-stream"),
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Trend files must be uploaded together: trend_data + trend_index"


def test_decode_export_returns_expected_zip_for_single_pair(data_dir) -> None:
    response = client.post(
        "/api/decode/export",
        data={"timezone": "Asia/Singapore"},
        files={
            "trend_data": ("TrendChartRecord.data", _file_bytes(data_dir, "Records/TrendChartRecord.data"), "application/octet-stream"),
            "trend_index": ("TrendChartRecord.Index", _file_bytes(data_dir, "Records/TrendChartRecord.Index"), "application/octet-stream"),
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "decoded-records.zip" in response.headers["content-disposition"]
    assert _zip_names(response.content) == [TREND_WORKBOOK_NAME]


def test_decode_export_returns_expected_zip_for_all_pairs(data_dir) -> None:
    response = client.post(
        "/api/decode/export",
        data={"timezone": "Asia/Singapore"},
        files={
            "trend_data": ("TrendChartRecord.data", _file_bytes(data_dir, "Records/TrendChartRecord.data"), "application/octet-stream"),
            "trend_index": ("TrendChartRecord.Index", _file_bytes(data_dir, "Records/TrendChartRecord.Index"), "application/octet-stream"),
            "nibp_data": ("NibpRecord.data", _file_bytes(data_dir, "Records/NibpRecord.data"), "application/octet-stream"),
            "nibp_index": ("NibpRecord.Index", _file_bytes(data_dir, "Records/NibpRecord.Index"), "application/octet-stream"),
            "alarm_data": ("AlarmRecord.data", _file_bytes(data_dir, "Records/AlarmRecord.data"), "application/octet-stream"),
            "alarm_index": ("AlarmRecord.Index", _file_bytes(data_dir, "Records/AlarmRecord.Index"), "application/octet-stream"),
        },
    )

    assert response.status_code == 200
    assert _zip_names(response.content) == sorted([TREND_WORKBOOK_NAME, NIBP_WORKBOOK_NAME, ALARM_WORKBOOK_NAME])


def test_decode_job_reports_progress_and_supports_download(data_dir) -> None:
    response = client.post(
        "/api/decode/jobs",
        data={"timezone": "Asia/Singapore"},
        files={
            "trend_data": ("TrendChartRecord.data", _file_bytes(data_dir, "Records/TrendChartRecord.data"), "application/octet-stream"),
            "trend_index": ("TrendChartRecord.Index", _file_bytes(data_dir, "Records/TrendChartRecord.Index"), "application/octet-stream"),
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["id"]
    assert payload["selected_families"] == ["Trend Chart"]
    assert payload["status"] in {"queued", "processing", "completed"}

    final_payload = _wait_for_job(payload["id"])
    assert final_payload["status"] == "completed"
    assert final_payload["progress_percent"] == 100
    assert final_payload["phase"] == "Ready to download"

    download_response = client.get(f"/api/decode/jobs/{payload['id']}/download")
    assert download_response.status_code == 200
    assert download_response.headers["content-type"] == "application/zip"
    assert _zip_names(download_response.content) == [TREND_WORKBOOK_NAME]


def test_build_decode_export_archive_does_not_mutate_database_rows(data_dir) -> None:
    with _build_session() as db:
        _seed_decode_irrelevant_rows(db)
        counts_before = _table_counts(db)

        archive = build_decode_export_archive(
            trend_data=_file_bytes(data_dir, "Records/TrendChartRecord.data"),
            trend_index=_file_bytes(data_dir, "Records/TrendChartRecord.Index"),
            nibp_data=_file_bytes(data_dir, "Records/NibpRecord.data"),
            nibp_index=_file_bytes(data_dir, "Records/NibpRecord.Index"),
            alarm_data=_file_bytes(data_dir, "Records/AlarmRecord.data"),
            alarm_index=_file_bytes(data_dir, "Records/AlarmRecord.Index"),
            timezone_name="Asia/Singapore",
        )

        counts_after = _table_counts(db)

    assert len(archive) > 0
    assert counts_before == counts_after
