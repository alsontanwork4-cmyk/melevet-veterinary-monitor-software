from __future__ import annotations

import asyncio
import importlib
import json
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import FastAPI, UploadFile
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base, get_db
from app.models import Channel, Encounter, Measurement, Patient, SourceType, Upload, UploadMeasurementLink
from app.routers.export import _build_upload_export_rows
from app.routers.staged_uploads import router as staged_uploads_router
from app.services.chart_service import list_encounter_measurements
from app.services.encounter_service import create_or_replace_encounter
from app.services.staged_upload_service import (
    create_staged_upload,
    delete_staged_upload,
    get_staged_upload,
    process_staged_upload,
    purge_expired_staged_uploads,
    save_staged_upload_as_encounter,
)
from app.services.upload_maintenance_service import trim_uploads_to_saved_encounter_windows
from app.services.upload_service import create_upload_stub, process_upload_for_existing_upload


def _make_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
    return session_factory()


def _upload_file(name: str, payload: bytes) -> UploadFile:
    return UploadFile(filename=name, file=BytesIO(payload))


def _build_index(unix_seconds: list[int]) -> bytes:
    header = (
        (1).to_bytes(4, "little")
        + (124).to_bytes(4, "little")
        + (122).to_bytes(4, "little")
        + (0).to_bytes(4, "little")
    )
    entries = bytearray()
    for frame_index, unix_second in enumerate(unix_seconds):
        ts_hi = (unix_second >> 16) & 0xFFFF
        ts_lo = (unix_second & 0xFFFF) << 16
        entries.extend((0).to_bytes(4, "little"))
        entries.extend(frame_index.to_bytes(4, "little"))
        entries.extend(ts_lo.to_bytes(4, "little"))
        entries.extend(ts_hi.to_bytes(4, "little"))
    return header + bytes(entries) + (b"\x00" * 6)


def _build_trend_data(unix_seconds: list[int]) -> bytes:
    payload = bytearray()
    for frame_index, unix_second in enumerate(unix_seconds):
        frame = bytearray(124)
        frame[2:6] = unix_second.to_bytes(4, "little")
        frame[28:30] = (96 + frame_index).to_bytes(2, "big")
        frame[32:34] = (80 + frame_index).to_bytes(2, "big")
        payload.extend(frame)
    return bytes(payload)


def _set_blank_trend_frame(payload: bytes, *, frame_index: int) -> bytes:
    start = frame_index * 124
    frame = bytearray(payload[start : start + 124])
    frame[28:30] = (65535).to_bytes(2, "big")
    frame[32:34] = (65535).to_bytes(2, "big")
    updated = bytearray(payload)
    updated[start : start + 124] = frame
    return bytes(updated)


def _build_nibp_data(values: list[tuple[int, int, int]]) -> bytes:
    payload = bytearray()
    for systolic, mean, diastolic in values:
        frame = bytearray(124)
        frame[28:30] = systolic.to_bytes(2, "big")
        frame[30:32] = mean.to_bytes(2, "big")
        frame[32:34] = diastolic.to_bytes(2, "big")
        payload.extend(frame)
    return bytes(payload)


def _build_alarm_data(messages: list[str]) -> bytes:
    payload = bytearray()
    for message in messages:
        frame = bytearray(124)
        frame[0] = 0x02
        frame[1] = 0x04
        encoded = message.encode("ascii", errors="ignore")[:96]
        frame[26 : 26 + len(encoded)] = encoded
        payload.extend(frame)
    return bytes(payload)


def _stage_metadata_path(stage_root: Path, stage_id: str) -> Path:
    return stage_root / stage_id / "metadata.json"


def _api_form_data(*, patient_id: int | None = None) -> dict[str, str]:
    data = {"timezone": "UTC"}
    if patient_id is not None:
        data["patient_id"] = str(patient_id)
        return data

    data.update(
        {
            "patient_id_code": "API-STAGE-001",
            "patient_name": "API Stage Patient",
            "patient_species": "canine",
        }
    )
    return data


def _api_files(
    *,
    trend_data: bytes,
    trend_index: bytes | None = None,
    nibp_data: bytes | None = None,
    nibp_index: bytes | None = None,
    alarm_data: bytes | None = None,
    alarm_index: bytes | None = None,
) -> list[tuple[str, tuple[str, bytes, str]]]:
    files: list[tuple[str, tuple[str, bytes, str]]] = [
        ("trend_data", ("TrendChartRecord.data", trend_data, "application/octet-stream")),
    ]
    if trend_index is not None:
        files.append(("trend_index", ("TrendChartRecord.Index", trend_index, "application/octet-stream")))
    if nibp_data is not None:
        files.append(("nibp_data", ("NibpRecord.data", nibp_data, "application/octet-stream")))
    if nibp_index is not None:
        files.append(("nibp_index", ("NibpRecord.Index", nibp_index, "application/octet-stream")))
    if alarm_data is not None:
        files.append(("alarm_data", ("AlarmRecord.data", alarm_data, "application/octet-stream")))
    if alarm_index is not None:
        files.append(("alarm_index", ("AlarmRecord.Index", alarm_index, "application/octet-stream")))
    return files


@pytest.fixture
def staged_settings(tmp_path, monkeypatch):
    stage_root = tmp_path / "staged"
    monkeypatch.setattr(settings, "stage_storage_dir", str(stage_root))
    monkeypatch.setattr(settings, "stage_expiry_seconds", 60)
    return stage_root


@pytest.fixture
def staged_api_client(staged_settings: Path):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)

    app = FastAPI()
    app.include_router(staged_uploads_router, prefix="/api")

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as client:
        yield client, session_factory

    app.dependency_overrides.clear()
    engine.dispose()


def test_main_module_imports_with_staged_router_present() -> None:
    module = importlib.import_module("app.main")

    assert module.app is not None
    assert any(route.path == "/api/staged-uploads" for route in module.app.routes)


def test_staged_upload_parses_without_writing_sqlite(staged_settings: Path) -> None:
    unix_seconds = [
        int(datetime(2026, 3, 5, 23, 59, tzinfo=UTC).timestamp()),
        int(datetime(2026, 3, 6, 0, 5, tzinfo=UTC).timestamp()),
    ]
    trend_data = _build_trend_data(unix_seconds)
    trend_index = _build_index(unix_seconds)

    with _make_session() as db:
        staged = asyncio.run(
            create_staged_upload(
                db,
                trend_data=_upload_file("TrendChartRecord.data", trend_data),
                trend_index=_upload_file("TrendChartRecord.Index", trend_index),
                nibp_data=None,
                nibp_index=None,
                patient_id=None,
                patient_id_code="STAGE-001",
                patient_name="Stage Patient",
                patient_species="canine",
                timezone_name="UTC",
            )
        )

        assert db.scalar(select(func.count(Patient.id))) == 0
        assert db.scalar(select(func.count(Upload.id))) == 0

        process_staged_upload(staged["stage_id"])
        completed = get_staged_upload(staged["stage_id"], touch=False)

        assert completed["status"] == "completed"
        assert completed["trend_frames"] == 2
        assert completed["periods"] == 1
        assert completed["segments"] == 1
        assert completed["detected_local_dates"] == ["2026-03-05", "2026-03-06"]
        assert (staged_settings / staged["stage_id"] / "TrendChartRecord.data").exists()

        assert db.scalar(select(func.count(Upload.id))) == 0
        assert db.scalar(select(func.count(Measurement.id))) == 0


def test_staged_upload_delete_and_expiry_remove_files(staged_settings: Path) -> None:
    unix_seconds = [int(datetime(2026, 3, 6, 8, 0, tzinfo=UTC).timestamp())]
    trend_data = _build_trend_data(unix_seconds)
    trend_index = _build_index(unix_seconds)

    with _make_session() as db:
        staged = asyncio.run(
            create_staged_upload(
                db,
                trend_data=_upload_file("TrendChartRecord.data", trend_data),
                trend_index=_upload_file("TrendChartRecord.Index", trend_index),
                nibp_data=None,
                nibp_index=None,
                patient_id=None,
                patient_id_code="STAGE-DELETE",
                patient_name="Delete Patient",
                patient_species="canine",
                timezone_name="UTC",
            )
        )
        stage_path = staged_settings / staged["stage_id"]
        assert stage_path.exists()
        assert delete_staged_upload(staged["stage_id"]) is True
        assert not stage_path.exists()

        staged = asyncio.run(
            create_staged_upload(
                db,
                trend_data=_upload_file("TrendChartRecord.data", trend_data),
                trend_index=_upload_file("TrendChartRecord.Index", trend_index),
                nibp_data=None,
                nibp_index=None,
                patient_id=None,
                patient_id_code="STAGE-EXPIRE",
                patient_name="Expire Patient",
                patient_species="canine",
                timezone_name="UTC",
            )
        )
        metadata_path = _stage_metadata_path(staged_settings, staged["stage_id"])
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["expires_at"] = "2020-01-01T00:00:00Z"
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

        assert purge_expired_staged_uploads() == 1
        with pytest.raises(FileNotFoundError):
            get_staged_upload(staged["stage_id"], touch=False)


def test_save_staged_upload_persists_only_selected_day_slice(staged_settings: Path) -> None:
    unix_seconds = [
        int(datetime(2026, 3, 5, 12, 0, tzinfo=UTC).timestamp()),
        int(datetime(2026, 3, 6, 0, 5, tzinfo=UTC).timestamp()),
        int(datetime(2026, 3, 6, 12, 10, tzinfo=UTC).timestamp()),
    ]
    trend_data = _build_trend_data(unix_seconds)
    trend_index = _build_index(unix_seconds)
    nibp_data = _build_nibp_data([(120, 90, 70), (121, 91, 71), (122, 92, 72)])
    nibp_index = _build_index(unix_seconds)
    with _make_session() as db:
        staged = asyncio.run(
            create_staged_upload(
                db,
                trend_data=_upload_file("TrendChartRecord.data", trend_data),
                trend_index=_upload_file("TrendChartRecord.Index", trend_index),
                nibp_data=_upload_file("NibpRecord.data", nibp_data),
                nibp_index=_upload_file("NibpRecord.Index", nibp_index),
                patient_id=None,
                patient_id_code="SLICE-001",
                patient_name="Slice Patient",
                patient_species="canine",
                timezone_name="UTC",
            )
        )
        process_staged_upload(staged["stage_id"])

        encounter = save_staged_upload_as_encounter(
            db,
            stage_id=staged["stage_id"],
            encounter_date_local=date(2026, 3, 6),
            timezone_name="UTC",
            label=None,
            notes=None,
        )

        upload = db.get(Upload, encounter.upload_id)
        assert upload is not None
        assert upload.detected_local_dates == ["2026-03-06"]
        assert upload.trend_frames == 2
        assert upload.nibp_frames == 2

        persisted_timestamps = db.scalars(
            select(UploadMeasurementLink.timestamp)
            .where(UploadMeasurementLink.upload_id == upload.id)
            .order_by(UploadMeasurementLink.timestamp.asc())
        ).all()
        assert persisted_timestamps
        assert all(timestamp.date() == date(2026, 3, 6) for timestamp in persisted_timestamps)

        trend_channel_ids = db.scalars(
            select(Channel.id)
            .where(Channel.upload_id == upload.id)
            .where(Channel.source_type == SourceType.trend)
            .order_by(Channel.channel_index.asc())
        ).all()
        rows = list_encounter_measurements(
            db,
            encounter_id=encounter.id,
            channel_ids=list(trend_channel_ids),
            max_points=None,
            source_type=SourceType.trend,
        )
        assert {row[0].timestamp.date() for row in rows} == {date(2026, 3, 6)}
        assert db.scalar(select(func.count(Patient.id))) == 1

        with pytest.raises(FileNotFoundError):
            get_staged_upload(staged["stage_id"], touch=False)


def test_saving_identical_selected_day_slice_reuses_saved_upload(staged_settings: Path) -> None:
    unix_seconds = [
        int(datetime(2026, 3, 6, 8, 0, tzinfo=UTC).timestamp()),
        int(datetime(2026, 3, 6, 9, 0, tzinfo=UTC).timestamp()),
    ]
    trend_data = _build_trend_data(unix_seconds)
    trend_index = _build_index(unix_seconds)

    with _make_session() as db:
        first_stage = asyncio.run(
            create_staged_upload(
                db,
                trend_data=_upload_file("TrendChartRecord.data", trend_data),
                trend_index=_upload_file("TrendChartRecord.Index", trend_index),
                nibp_data=None,
                nibp_index=None,
                patient_id=None,
                patient_id_code="REUSE-001",
                patient_name="Reuse Patient",
                patient_species="canine",
                timezone_name="UTC",
            )
        )
        process_staged_upload(first_stage["stage_id"])
        encounter = save_staged_upload_as_encounter(
            db,
            stage_id=first_stage["stage_id"],
            encounter_date_local=date(2026, 3, 6),
            timezone_name="UTC",
            label="Original",
            notes=None,
        )

        patient = db.get(Patient, encounter.patient_id)
        assert patient is not None

        second_stage = asyncio.run(
            create_staged_upload(
                db,
                trend_data=_upload_file("TrendChartRecord.data", trend_data),
                trend_index=_upload_file("TrendChartRecord.Index", trend_index),
                nibp_data=None,
                nibp_index=None,
                patient_id=patient.id,
                patient_id_code=None,
                patient_name=None,
                patient_species=None,
                timezone_name="UTC",
            )
        )
        process_staged_upload(second_stage["stage_id"])
        replacement = save_staged_upload_as_encounter(
            db,
            stage_id=second_stage["stage_id"],
            encounter_date_local=date(2026, 3, 6),
            timezone_name="UTC",
            label="Replacement",
            notes="same slice",
        )

        assert replacement.id == encounter.id
        assert replacement.upload_id == encounter.upload_id
        assert db.scalar(select(func.count(Upload.id))) == 1
        assert db.scalar(select(func.count(Encounter.id))) == 1


def test_save_staged_upload_skips_blank_trend_timestamps_in_export(staged_settings: Path) -> None:
    unix_seconds = [
        int(datetime(2026, 3, 6, 0, 5, tzinfo=UTC).timestamp()),
        int(datetime(2026, 3, 6, 12, 10, tzinfo=UTC).timestamp()),
        int(datetime(2026, 3, 6, 12, 11, tzinfo=UTC).timestamp()),
    ]
    trend_data = _set_blank_trend_frame(_build_trend_data(unix_seconds), frame_index=0)
    trend_index = _build_index(unix_seconds)

    with _make_session() as db:
        staged = asyncio.run(
            create_staged_upload(
                db,
                trend_data=_upload_file("TrendChartRecord.data", trend_data),
                trend_index=_upload_file("TrendChartRecord.Index", trend_index),
                nibp_data=None,
                nibp_index=None,
                patient_id=None,
                patient_id_code="BLANK-ROW-001",
                patient_name="Blank Row Patient",
                patient_species="canine",
                timezone_name="UTC",
            )
        )
        process_staged_upload(staged["stage_id"])

        encounter = save_staged_upload_as_encounter(
            db,
            stage_id=staged["stage_id"],
            encounter_date_local=date(2026, 3, 6),
            timezone_name="UTC",
            label=None,
            notes=None,
        )

        upload = db.get(Upload, encounter.upload_id)
        assert upload is not None

        persisted_timestamps = db.scalars(
            select(UploadMeasurementLink.timestamp)
            .where(UploadMeasurementLink.upload_id == upload.id)
            .order_by(UploadMeasurementLink.timestamp.asc())
        ).all()
        assert persisted_timestamps == [
            datetime(2026, 3, 6, 12, 10),
            datetime(2026, 3, 6, 12, 10),
            datetime(2026, 3, 6, 12, 11),
            datetime(2026, 3, 6, 12, 11),
        ]

        trend_channel_ids = db.scalars(
            select(Channel.id)
            .where(Channel.upload_id == upload.id)
            .where(Channel.source_type == SourceType.trend)
            .order_by(Channel.channel_index.asc())
        ).all()
        rows = list_encounter_measurements(
            db,
            encounter_id=encounter.id,
            channel_ids=list(trend_channel_ids),
            max_points=None,
            source_type=SourceType.trend,
        )
        assert [row[0].timestamp for row in rows] == [
            datetime(2026, 3, 6, 12, 10),
            datetime(2026, 3, 6, 12, 10),
            datetime(2026, 3, 6, 12, 11),
            datetime(2026, 3, 6, 12, 11),
        ]
        assert all(row[0].timestamp != datetime(2026, 3, 6, 0, 5) for row in rows)

        export_rows = _build_upload_export_rows(
            db=db,
            upload_id=upload.id,
            segment_id=None,
            channels=None,
            from_ts=datetime(2026, 3, 6, 0, 0),
            to_ts=datetime(2026, 3, 6, 23, 59, 59),
            include_nibp=False,
        )
        assert export_rows == [
            ["timestamp", "spo2_be_u16", "heart_rate_be_u16"],
            ["2026-03-06T12:10:00", "97", "81"],
            ["2026-03-06T12:11:00", "98", "82"],
        ]


def test_trim_uploads_to_saved_encounter_windows_prunes_old_history(staged_settings: Path) -> None:
    unix_seconds = [
        int(datetime(2026, 3, 5, 12, 0, tzinfo=UTC).timestamp()),
        int(datetime(2026, 3, 6, 8, 0, tzinfo=UTC).timestamp()),
        int(datetime(2026, 3, 6, 9, 0, tzinfo=UTC).timestamp()),
    ]
    trend_data = _build_trend_data(unix_seconds)
    trend_index = _build_index(unix_seconds)

    with _make_session() as db:
        patient = Patient(patient_id_code="TRIM-001", name="Trim Patient", species="canine")
        db.add(patient)
        db.commit()
        db.refresh(patient)

        upload = create_upload_stub(
            db,
            patient=patient,
            trend_data=trend_data,
            trend_index=trend_index,
            nibp_data=None,
            nibp_index=None,
        )
        process_upload_for_existing_upload(
            db,
            upload_id=upload.id,
            trend_data=trend_data,
            trend_index=trend_index,
            nibp_data=None,
            nibp_index=None,
            timezone_name="UTC",
        )

        orphan_upload = create_upload_stub(
            db,
            patient=patient,
            trend_data=_build_trend_data([int(datetime(2026, 3, 7, 10, 0, tzinfo=UTC).timestamp())]),
            trend_index=_build_index([int(datetime(2026, 3, 7, 10, 0, tzinfo=UTC).timestamp())]),
            nibp_data=None,
            nibp_index=None,
        )
        process_upload_for_existing_upload(
            db,
            upload_id=orphan_upload.id,
            trend_data=_build_trend_data([int(datetime(2026, 3, 7, 10, 0, tzinfo=UTC).timestamp())]),
            trend_index=_build_index([int(datetime(2026, 3, 7, 10, 0, tzinfo=UTC).timestamp())]),
            nibp_data=None,
            nibp_index=None,
            timezone_name="UTC",
        )

        encounter = create_or_replace_encounter(
            db,
            upload=db.get(Upload, upload.id),
            patient=patient,
            encounter_date_local=date(2026, 3, 6),
            timezone_name="UTC",
            label=None,
            notes=None,
        )

        before_measurements = db.scalar(select(func.count(Measurement.id))) or 0
        result = trim_uploads_to_saved_encounter_windows(db)

        kept_upload = db.get(Upload, encounter.upload_id)
        assert kept_upload is not None
        assert db.get(Upload, orphan_upload.id) is None
        assert result.deleted_orphan_uploads == 1
        trimmed_timestamps = db.scalars(
            select(UploadMeasurementLink.timestamp)
            .where(UploadMeasurementLink.upload_id == kept_upload.id)
            .order_by(UploadMeasurementLink.timestamp.asc())
        ).all()
        assert trimmed_timestamps
        assert all(timestamp.date() == date(2026, 3, 6) for timestamp in trimmed_timestamps)
        assert kept_upload.detected_local_dates == ["2026-03-06"]
        assert (db.scalar(select(func.count(Measurement.id))) or 0) < before_measurements


def test_staged_upload_api_create_returns_stage_id_and_processing_state(staged_api_client, monkeypatch) -> None:
    client, _session_factory = staged_api_client
    unix_seconds = [int(datetime(2026, 3, 6, 8, 0, tzinfo=UTC).timestamp())]
    trend_data = _build_trend_data(unix_seconds)
    trend_index = _build_index(unix_seconds)

    monkeypatch.setattr("app.routers.staged_uploads.process_staged_upload", lambda _stage_id: None)

    response = client.post(
        "/api/staged-uploads",
        data=_api_form_data(),
        files=_api_files(trend_data=trend_data, trend_index=trend_index),
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["stage_id"]
    assert payload["status"] == "processing"
    assert payload["phase"] == "parsing"
    assert payload["timezone"] == "UTC"


def test_staged_upload_api_get_returns_completed_discovery(staged_api_client) -> None:
    client, _session_factory = staged_api_client
    unix_seconds = [
        int(datetime(2026, 3, 5, 23, 59, tzinfo=UTC).timestamp()),
        int(datetime(2026, 3, 6, 0, 5, tzinfo=UTC).timestamp()),
    ]
    trend_data = _build_trend_data(unix_seconds)
    trend_index = _build_index(unix_seconds)

    create_response = client.post(
        "/api/staged-uploads",
        data=_api_form_data(),
        files=_api_files(trend_data=trend_data, trend_index=trend_index),
    )
    assert create_response.status_code == 202
    stage_id = create_response.json()["stage_id"]

    read_response = client.get(f"/api/staged-uploads/{stage_id}")

    assert read_response.status_code == 200
    payload = read_response.json()
    assert payload["status"] == "completed"
    assert payload["trend_frames"] == 2
    assert payload["periods"] == 1
    assert payload["segments"] == 1
    assert payload["detected_local_dates"] == ["2026-03-05", "2026-03-06"]


def test_staged_upload_api_delete_removes_stage(staged_api_client) -> None:
    client, _session_factory = staged_api_client
    unix_seconds = [int(datetime(2026, 3, 6, 8, 0, tzinfo=UTC).timestamp())]
    trend_data = _build_trend_data(unix_seconds)
    trend_index = _build_index(unix_seconds)

    create_response = client.post(
        "/api/staged-uploads",
        data=_api_form_data(),
        files=_api_files(trend_data=trend_data, trend_index=trend_index),
    )
    stage_id = create_response.json()["stage_id"]

    delete_response = client.delete(f"/api/staged-uploads/{stage_id}")

    assert delete_response.status_code == 200
    assert delete_response.json() == {"deleted": True, "stage_id": stage_id}
    assert client.get(f"/api/staged-uploads/{stage_id}").status_code == 404


def test_staged_upload_api_save_encounter_persists_selected_day_slice(staged_api_client) -> None:
    client, session_factory = staged_api_client
    unix_seconds = [
        int(datetime(2026, 3, 5, 12, 0, tzinfo=UTC).timestamp()),
        int(datetime(2026, 3, 6, 0, 5, tzinfo=UTC).timestamp()),
        int(datetime(2026, 3, 6, 12, 10, tzinfo=UTC).timestamp()),
    ]
    trend_data = _build_trend_data(unix_seconds)
    trend_index = _build_index(unix_seconds)
    nibp_data = _build_nibp_data([(120, 90, 70), (121, 91, 71), (122, 92, 72)])
    nibp_index = _build_index(unix_seconds)
    create_response = client.post(
        "/api/staged-uploads",
        data=_api_form_data(),
        files=_api_files(
            trend_data=trend_data,
            trend_index=trend_index,
            nibp_data=nibp_data,
            nibp_index=nibp_index,
        ),
    )
    stage_id = create_response.json()["stage_id"]

    save_response = client.post(
        f"/api/staged-uploads/{stage_id}/encounters",
        json={
            "encounter_date_local": "2026-03-06",
            "timezone": "UTC",
        },
    )

    assert save_response.status_code == 200
    payload = save_response.json()
    assert payload["encounter_date_local"] == "2026-03-06"
    assert payload["trend_frames"] == 2
    assert payload["nibp_frames"] == 2
    assert client.get(f"/api/staged-uploads/{stage_id}").status_code == 404

    with session_factory() as db:
        upload = db.get(Upload, payload["upload_id"])
        assert upload is not None
        assert upload.detected_local_dates == ["2026-03-06"]
        timestamps = db.scalars(
            select(UploadMeasurementLink.timestamp)
            .where(UploadMeasurementLink.upload_id == upload.id)
            .order_by(UploadMeasurementLink.timestamp.asc())
        ).all()
        assert timestamps
        assert all(timestamp.date() == date(2026, 3, 6) for timestamp in timestamps)


def test_staged_upload_api_rejects_invalid_file_pair(staged_api_client) -> None:
    client, _session_factory = staged_api_client
    unix_seconds = [int(datetime(2026, 3, 6, 8, 0, tzinfo=UTC).timestamp())]
    trend_data = _build_trend_data(unix_seconds)
    trend_index = _build_index(unix_seconds)
    nibp_data = _build_nibp_data([(120, 90, 70)])

    response = client.post(
        "/api/staged-uploads",
        data=_api_form_data(),
        files=_api_files(trend_data=trend_data, trend_index=trend_index, nibp_data=nibp_data),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Nibp files must be uploaded together: nibp_data + nibp_index"


def test_staged_upload_api_rejects_missing_patient(staged_api_client) -> None:
    client, _session_factory = staged_api_client
    unix_seconds = [int(datetime(2026, 3, 6, 8, 0, tzinfo=UTC).timestamp())]
    trend_data = _build_trend_data(unix_seconds)
    trend_index = _build_index(unix_seconds)

    response = client.post(
        "/api/staged-uploads",
        data=_api_form_data(patient_id=999),
        files=_api_files(trend_data=trend_data, trend_index=trend_index),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Patient not found"


def test_staged_upload_api_rejects_invalid_selected_day(staged_api_client) -> None:
    client, _session_factory = staged_api_client
    unix_seconds = [int(datetime(2026, 3, 6, 8, 0, tzinfo=UTC).timestamp())]
    trend_data = _build_trend_data(unix_seconds)
    trend_index = _build_index(unix_seconds)

    create_response = client.post(
        "/api/staged-uploads",
        data=_api_form_data(),
        files=_api_files(trend_data=trend_data, trend_index=trend_index),
    )
    stage_id = create_response.json()["stage_id"]

    response = client.post(
        f"/api/staged-uploads/{stage_id}/encounters",
        json={
            "encounter_date_local": "2026-03-07",
            "timezone": "UTC",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Selected encounter date is not available in this staged upload"


def test_staged_upload_api_returns_404_for_expired_stage(staged_api_client, staged_settings: Path) -> None:
    client, _session_factory = staged_api_client
    unix_seconds = [int(datetime(2026, 3, 6, 8, 0, tzinfo=UTC).timestamp())]
    trend_data = _build_trend_data(unix_seconds)
    trend_index = _build_index(unix_seconds)

    create_response = client.post(
        "/api/staged-uploads",
        data=_api_form_data(),
        files=_api_files(trend_data=trend_data, trend_index=trend_index),
    )
    stage_id = create_response.json()["stage_id"]

    metadata_path = _stage_metadata_path(staged_settings, stage_id)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["expires_at"] = "2020-01-01T00:00:00Z"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    response = client.get(f"/api/staged-uploads/{stage_id}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Staged upload not found"
