from __future__ import annotations

from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Channel, Encounter, Measurement, NibpEvent, Patient, RecordingPeriod, Segment, SourceType, Upload, UploadStatus
from app.routers.patients import delete_patient
from app.services.patient_service import delete_patient_hard


def _checksum(seed: str) -> str:
    return seed * 64


def _make_session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


def _new_upload(patient_id: int, *, seed: str) -> Upload:
    checksum = _checksum(seed)
    return Upload(
        patient_id=patient_id,
        upload_time=datetime(2026, 3, 7, 12, 0, 0),
        status=UploadStatus.completed,
        phase="completed",
        progress_current=1,
        progress_total=1,
        trend_frames=2,
        nibp_frames=1,
        alarm_frames=0,
        trend_sha256=checksum,
        trend_index_sha256=checksum,
        nibp_sha256=checksum,
        nibp_index_sha256=checksum,
        alarm_sha256=checksum,
        alarm_index_sha256=checksum,
        combined_hash=checksum,
        detected_local_dates=["2026-03-07"],
    )


def _seed_patient_graph(db: Session, *, code: str, seed: str) -> tuple[Patient, Upload, Encounter]:
    seed_offset = int(seed)
    patient = Patient(patient_id_code=code, name=f"Patient {code}", species="dog")
    db.add(patient)
    db.flush()

    upload = _new_upload(patient.id, seed=seed)
    db.add(upload)
    db.flush()

    period = RecordingPeriod(
        upload_id=upload.id,
        period_index=0,
        start_time=datetime(2026, 3, 7, 0, 0, 0),
        end_time=datetime(2026, 3, 7, 1, 0, 0),
        frame_count=2,
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
        frame_count=2,
        duration_seconds=3600,
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
            timestamp=datetime(2026, 3, 7, 0, 15 + seed_offset, 0),
            value=88.0,
        )
    )
    db.add(
        NibpEvent(
            upload_id=upload.id,
            segment_id=segment.id,
            timestamp=datetime(2026, 3, 7, 0, 20 + seed_offset, 0),
            channel_values={"bp_systolic_inferred": 120},
            has_measurement=True,
        )
    )
    encounter = Encounter(
        patient_id=patient.id,
        upload_id=upload.id,
        encounter_date_local=date(2026, 3, 7),
        timezone="UTC",
        label=f"Encounter {code}",
    )
    db.add(encounter)
    db.flush()

    patient.preferred_encounter_id = encounter.id
    db.add(patient)
    db.commit()
    db.refresh(patient)
    db.refresh(upload)
    db.refresh(encounter)
    return patient, upload, encounter


def test_delete_patient_route_removes_related_data_and_keeps_other_patient() -> None:
    session_factory = _make_session_factory()

    with session_factory() as db:
        target_patient, target_upload, target_encounter = _seed_patient_graph(db, code="DEL-1", seed="1")
        other_patient, other_upload, other_encounter = _seed_patient_graph(db, code="KEEP-1", seed="2")
        target_patient_id = target_patient.id
        target_upload_id = target_upload.id
        target_encounter_id = target_encounter.id
        other_patient_id = other_patient.id
        other_upload_id = other_upload.id
        other_encounter_id = other_encounter.id
        response = delete_patient(target_patient.id, db)

        assert response.deleted is True
        assert response.patient_id == target_patient_id

        assert db.get(Patient, target_patient_id) is None
        assert db.get(Upload, target_upload_id) is None
        assert db.get(Encounter, target_encounter_id) is None
        assert db.query(Measurement).count() == 1
        assert db.query(NibpEvent).count() == 1
        assert db.get(Patient, other_patient_id) is not None
        assert db.get(Upload, other_upload_id) is not None
        assert db.get(Encounter, other_encounter_id) is not None


def test_delete_patient_route_succeeds_without_related_records() -> None:
    session_factory = _make_session_factory()
    with session_factory() as db:
        patient = Patient(patient_id_code="EMPTY-1", name="Empty", species="cat")
        db.add(patient)
        db.commit()
        db.refresh(patient)
        response = delete_patient(patient.id, db)

        assert response.deleted is True
        assert response.patient_id == patient.id
        assert db.get(Patient, patient.id) is None


def test_delete_patient_route_returns_not_found_after_repeated_delete() -> None:
    session_factory = _make_session_factory()
    with session_factory() as db:
        patient, _, _ = _seed_patient_graph(db, code="DEL-2", seed="3")
        first_response = delete_patient(patient.id, db)

        assert first_response.deleted is True

        try:
            delete_patient(patient.id, db)
        except HTTPException as exc:
            assert exc.status_code == 404
            assert exc.detail == "Patient not found"
        else:
            raise AssertionError("Expected second patient delete to return not found")


def test_delete_patient_hard_regression_avoids_circular_dependency_cycle() -> None:
    session_factory = _make_session_factory()
    with session_factory() as db:
        patient, upload, encounter = _seed_patient_graph(db, code="DEL-3", seed="4")
        patient_id = patient.id
        upload_id = upload.id
        encounter_id = encounter.id

        result = delete_patient_hard(db, patient.id)

        assert result.patient_id == patient_id
        assert result.upload_count == 1
        assert result.encounter_count_before == 1
        assert db.get(Patient, patient_id) is None
        assert db.get(Upload, upload_id) is None
        assert db.get(Encounter, encounter_id) is None
