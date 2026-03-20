from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import Patient, RecordingPeriod, Upload, UploadStatus
from app.routers.patients import list_patient_uploads


def _make_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)()


def _new_upload(patient_id: int, upload_time: datetime) -> Upload:
    checksum = "1" * 64
    return Upload(
        patient_id=patient_id,
        upload_time=upload_time,
        status=UploadStatus.completed,
        phase="completed",
        progress_current=1,
        progress_total=1,
        trend_frames=1,
        nibp_frames=0,
        measurements_new=3,
        measurements_reused=7,
        nibp_new=1,
        nibp_reused=2,
        trend_sha256=checksum,
        trend_index_sha256=checksum,
        nibp_sha256=checksum,
        nibp_index_sha256=checksum,
    )


def test_list_patient_uploads_includes_latest_recorded_at() -> None:
    db = _make_session()

    patient = Patient(patient_id_code="PH-1", name="Patient", species="canine")
    db.add(patient)
    db.flush()

    upload = _new_upload(patient.id, datetime(2026, 3, 6, 7, 25, 20))
    db.add(upload)
    db.flush()

    db.add_all(
        [
            RecordingPeriod(
                upload_id=upload.id,
                period_index=0,
                start_time=datetime(2026, 2, 25, 11, 50, 9),
                end_time=datetime(2026, 2, 26, 13, 37, 45),
                frame_count=14627,
                label="Period 1",
            ),
            RecordingPeriod(
                upload_id=upload.id,
                period_index=1,
                start_time=datetime(2026, 3, 2, 11, 23, 44),
                end_time=datetime(2026, 3, 2, 13, 51, 52),
                frame_count=8889,
                label="Period 2",
            ),
        ]
    )
    db.commit()

    response = list_patient_uploads(patient.id, db)

    assert response.total == 1
    assert response.limit == 50
    assert response.offset == 0
    assert len(response.items) == 1
    assert response.items[0].upload_time == datetime(2026, 3, 6, 7, 25, 20)
    assert response.items[0].latest_recorded_at == datetime(2026, 3, 2, 13, 51, 52)
    assert response.items[0].measurements_new == 3
    assert response.items[0].measurements_reused == 7
    assert response.items[0].nibp_new == 1
    assert response.items[0].nibp_reused == 2


def test_list_patient_uploads_returns_null_latest_recorded_at_without_periods() -> None:
    db = _make_session()

    patient = Patient(patient_id_code="PH-2", name="Patient", species="canine")
    db.add(patient)
    db.flush()

    upload = _new_upload(patient.id, datetime(2026, 3, 6, 9, 12, 0))
    db.add(upload)
    db.commit()

    response = list_patient_uploads(patient.id, db)

    assert response.total == 1
    assert len(response.items) == 1
    assert response.items[0].upload_time == datetime(2026, 3, 6, 9, 12, 0)
    assert response.items[0].latest_recorded_at is None
