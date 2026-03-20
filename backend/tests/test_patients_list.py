from __future__ import annotations

from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import Encounter, Patient, Upload, UploadStatus
from app.routers.encounters import create_upload_encounter
from app.routers.patients import get_patient_available_report_dates, list_patients, update_patient
from app.schemas import PatientUpdate
from app.schemas.api import EncounterCreate


def _make_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)()


def _new_upload(patient_id: int, upload_time: datetime) -> Upload:
    checksum = upload_time.strftime("%Y%m%d%H%M%S").ljust(64, "0")
    return Upload(
        patient_id=patient_id,
        upload_time=upload_time,
        status=UploadStatus.completed,
        phase="completed",
        progress_current=1,
        progress_total=1,
        trend_frames=1,
        nibp_frames=0,
        trend_sha256=checksum,
        trend_index_sha256=checksum,
        nibp_sha256=checksum,
        nibp_index_sha256=checksum,
        combined_hash=checksum,
    )


def test_list_patients_uses_preferred_report_date_without_changing_latest_report_date() -> None:
    db = _make_session()

    patient = Patient(
        patient_id_code="PT-001",
        name="Kitty",
        species="cat",
        age="5",
        owner_name="Tan Iee Hong",
        notes="Gender: Male\nAge: 5",
    )
    db.add(patient)
    db.flush()

    older_upload = _new_upload(patient.id, datetime(2026, 1, 18, 22, 15, 0))
    newer_upload = _new_upload(patient.id, datetime(2026, 1, 19, 6, 30, 0))
    db.add_all([older_upload, newer_upload])
    db.flush()

    preferred_encounter = Encounter(
        patient_id=patient.id,
        upload_id=older_upload.id,
        encounter_date_local=date(2026, 1, 18),
        timezone="Asia/Singapore",
    )
    latest_encounter = Encounter(
        patient_id=patient.id,
        upload_id=newer_upload.id,
        encounter_date_local=date(2026, 1, 19),
        timezone="Asia/Singapore",
    )
    db.add_all([preferred_encounter, latest_encounter])
    db.flush()

    patient.preferred_encounter_id = preferred_encounter.id
    db.add(patient)
    db.commit()

    patients = list_patients(q=None, limit=50, offset=0, db=db)

    assert patients.total == 1
    assert len(patients.items) == 1
    assert patients.items[0].age == "5"
    assert patients.items[0].owner_name == "Tan Iee Hong"
    assert patients.items[0].notes == "Gender: Male\nAge: 5"
    assert patients.items[0].preferred_encounter_id == preferred_encounter.id
    assert patients.items[0].upload_count == 2
    assert patients.items[0].last_upload_time == datetime(2026, 1, 19, 6, 30, 0)
    assert patients.items[0].latest_report_date == date(2026, 1, 19)
    assert patients.items[0].report_date == date(2026, 1, 18)


def test_list_patients_returns_null_report_dates_when_patient_has_no_encounters() -> None:
    db = _make_session()

    patient = Patient(patient_id_code="PT-002", name="Nova", species="dog")
    db.add(patient)
    db.flush()

    db.add(_new_upload(patient.id, datetime(2026, 2, 2, 8, 45, 0)))
    db.commit()

    patients = list_patients(q=None, limit=50, offset=0, db=db)

    assert patients.total == 1
    assert len(patients.items) == 1
    assert patients.items[0].upload_count == 1
    assert patients.items[0].latest_report_date is None
    assert patients.items[0].report_date is None


def test_update_patient_allows_updating_patient_id_code() -> None:
    db = _make_session()

    patient = Patient(patient_id_code="PT-003", name="Milo", species="dog")
    db.add(patient)
    db.commit()

    updated = update_patient(
        patient.id,
        PatientUpdate(patient_id_code="PT-003-UPDATED", name="Milo", species="dog", age="7"),
        db,
    )

    assert updated.patient_id_code == "PT-003-UPDATED"
    assert updated.age == "7"


def test_update_patient_rejects_duplicate_patient_id_code() -> None:
    db = _make_session()

    first = Patient(patient_id_code="PT-004", name="First", species="dog")
    second = Patient(patient_id_code="PT-005", name="Second", species="cat")
    db.add_all([first, second])
    db.commit()

    try:
        update_patient(
            second.id,
            PatientUpdate(patient_id_code="PT-004"),
            db,
        )
    except HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail == "patient_id_code already exists"
    else:
        raise AssertionError("Expected duplicate patient_id_code to be rejected")


def test_update_patient_rejects_preferred_encounter_for_another_patient() -> None:
    db = _make_session()

    first = Patient(patient_id_code="PT-006", name="First", species="dog")
    second = Patient(patient_id_code="PT-007", name="Second", species="cat")
    db.add_all([first, second])
    db.flush()

    upload = _new_upload(first.id, datetime(2026, 2, 4, 10, 0, 0))
    db.add(upload)
    db.flush()

    encounter = Encounter(
        patient_id=first.id,
        upload_id=upload.id,
        encounter_date_local=date(2026, 2, 4),
        timezone="UTC",
    )
    db.add(encounter)
    db.commit()

    try:
        update_patient(
            second.id,
            PatientUpdate(preferred_encounter_id=encounter.id),
            db,
        )
    except HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail == "preferred_encounter_id must reference an encounter for this patient"
    else:
        raise AssertionError("Expected preferred_encounter_id to be rejected for a different patient")


def test_available_report_dates_include_detected_dates_without_saved_encounters() -> None:
    db = _make_session()

    patient = Patient(patient_id_code="PT-008", name="Ruyee", species="dog")
    db.add(patient)
    db.flush()

    older_upload = _new_upload(patient.id, datetime(2026, 2, 24, 10, 0, 0))
    older_upload.combined_hash = "2" * 64
    older_upload.detected_local_dates = ["2026-02-24"]

    newer_upload = _new_upload(patient.id, datetime(2026, 2, 26, 10, 0, 0))
    newer_upload.combined_hash = "3" * 64
    newer_upload.detected_local_dates = ["2026-02-25", "2026-02-26"]
    db.add_all([older_upload, newer_upload])
    db.flush()

    saved_encounter = Encounter(
        patient_id=patient.id,
        upload_id=newer_upload.id,
        encounter_date_local=date(2026, 2, 25),
        timezone="Asia/Singapore",
    )
    db.add(saved_encounter)
    db.commit()

    available_dates = get_patient_available_report_dates(patient.id, db)

    assert [item.encounter_date_local for item in available_dates] == [
        date(2026, 2, 26),
        date(2026, 2, 25),
        date(2026, 2, 24),
    ]
    assert available_dates[0].is_saved is False
    assert available_dates[0].encounter_id is None
    assert available_dates[0].upload_id == newer_upload.id
    assert available_dates[1].is_saved is True
    assert available_dates[1].encounter_id == saved_encounter.id
    assert available_dates[1].upload_id == newer_upload.id


def test_create_upload_encounter_rejects_snapshot_from_another_patient() -> None:
    db = _make_session()

    first = Patient(patient_id_code="PT-009", name="First", species="dog")
    second = Patient(patient_id_code="PT-010", name="Second", species="cat")
    db.add_all([first, second])
    db.flush()

    upload = _new_upload(first.id, datetime(2026, 2, 10, 10, 0, 0))
    upload.combined_hash = "4" * 64
    upload.detected_local_dates = ["2026-02-10"]
    db.add(upload)
    db.commit()

    try:
        create_upload_encounter(
            upload.id,
            EncounterCreate(
                patient_id=second.id,
                encounter_date_local=date(2026, 2, 10),
                timezone="UTC",
            ),
            db,
        )
    except HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail == "upload_id must reference a snapshot for this patient"
    else:
        raise AssertionError("Expected create_upload_encounter to reject uploads from another patient")
