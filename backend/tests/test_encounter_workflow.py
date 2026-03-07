from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models import Channel, Encounter, Measurement, Patient, RecordingPeriod, Segment, SourceType, Upload, UploadStatus
from app.database import Base
from app.services.chart_service import list_encounter_measurements
from app.services.encounter_service import (
    create_or_replace_encounter,
    delete_encounter,
    detected_local_dates_for_ranges,
    resolve_timezone,
    update_encounter,
)
from app.services.upload_service import purge_stale_orphan_uploads


def _make_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
    return session_factory()


def _new_patient(db: Session, suffix: str) -> Patient:
    patient = Patient(
        patient_id_code=f"ENC-{suffix}",
        name=f"Encounter {suffix}",
        species="canine",
    )
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient


def _new_upload(patient_id: int, *, completed_at: datetime | None = None) -> Upload:
    checksum = "9" * 64
    return Upload(
        patient_id=patient_id,
        status=UploadStatus.completed,
        phase="completed",
        progress_current=1,
        progress_total=1,
        trend_frames=2,
        nibp_frames=1,
        alarm_frames=1,
        trend_sha256=checksum,
        trend_index_sha256=checksum,
        nibp_sha256=checksum,
        nibp_index_sha256=checksum,
        alarm_sha256=checksum,
        alarm_index_sha256=checksum,
        combined_hash=checksum,
        detected_local_dates=["2026-03-05"],
        completed_at=completed_at,
    )


def test_detected_local_dates_expand_in_local_timezone() -> None:
    ranges = [
        (
            datetime(2026, 3, 5, 16, 30, 0, tzinfo=UTC),
            datetime(2026, 3, 6, 18, 0, 0, tzinfo=UTC),
        )
    ]

    from app.services import encounter_service

    original = encounter_service.resolve_timezone
    encounter_service.resolve_timezone = lambda _: timezone(timedelta(hours=8))
    try:
        detected = detected_local_dates_for_ranges(ranges, "Clinic/Local")
    finally:
        encounter_service.resolve_timezone = original

    assert detected == ["2026-03-06", "2026-03-07"]


def test_resolve_timezone_accepts_iana_name() -> None:
    tz = resolve_timezone("Asia/Singapore")
    assert tz.utcoffset(datetime(2026, 3, 5, 12, 0, 0)) == timedelta(hours=8)


def test_create_or_replace_encounter_repoints_existing_date_and_removes_orphan_upload() -> None:
    with _make_session() as db:
        patient = _new_patient(db, "replace")

        older_upload = _new_upload(patient.id)
        newer_upload = _new_upload(patient.id)
        newer_upload.combined_hash = "8" * 64
        db.add_all([older_upload, newer_upload])
        db.commit()
        db.refresh(older_upload)
        db.refresh(newer_upload)

        first = create_or_replace_encounter(
            db,
            upload=older_upload,
            patient=patient,
            encounter_date_local=date(2026, 3, 5),
            timezone_name="UTC",
            label="Original",
            notes=None,
        )

        replaced = create_or_replace_encounter(
            db,
            upload=newer_upload,
            patient=patient,
            encounter_date_local=date(2026, 3, 5),
            timezone_name="UTC",
            label="Updated",
            notes="latest snapshot",
        )

        assert first.id == replaced.id
        assert replaced.upload_id == newer_upload.id
        assert replaced.label == "Updated"
        assert db.get(Upload, older_upload.id) is None
        assert db.get(Upload, newer_upload.id) is not None


def test_delete_encounter_removes_last_orphan_snapshot() -> None:
    with _make_session() as db:
        patient = _new_patient(db, "delete")
        upload = _new_upload(patient.id)
        db.add(upload)
        db.commit()
        db.refresh(upload)

        encounter = create_or_replace_encounter(
            db,
            upload=upload,
            patient=patient,
            encounter_date_local=date(2026, 3, 5),
            timezone_name="UTC",
            label=None,
            notes=None,
        )

        delete_encounter(db, encounter)

        assert db.get(Encounter, encounter.id) is None
        assert db.get(Upload, upload.id) is None


def test_purge_stale_orphan_uploads_keeps_referenced_snapshots_and_deletes_old_orphans() -> None:
    with _make_session() as db:
        patient = _new_patient(db, "purge")
        old_upload = _new_upload(patient.id, completed_at=datetime.now(UTC) - timedelta(days=10))
        kept_upload = _new_upload(patient.id, completed_at=datetime.now(UTC))
        kept_upload.combined_hash = "7" * 64
        db.add_all([old_upload, kept_upload])
        db.commit()
        db.refresh(old_upload)
        db.refresh(kept_upload)

        create_or_replace_encounter(
            db,
            upload=kept_upload,
            patient=patient,
            encounter_date_local=date(2026, 3, 5),
            timezone_name="UTC",
            label=None,
            notes=None,
        )

        purged = purge_stale_orphan_uploads(db)

        assert purged == 1
        assert db.get(Upload, old_upload.id) is None
        assert db.get(Upload, kept_upload.id) is not None


def test_uploads_enforce_global_combined_hash_uniqueness() -> None:
    with _make_session() as db:
        patient = _new_patient(db, "dup")
        referenced_upload = _new_upload(patient.id, completed_at=datetime.now(UTC))
        duplicate_orphan = _new_upload(patient.id, completed_at=datetime.now(UTC) - timedelta(hours=1))
        duplicate_orphan.combined_hash = referenced_upload.combined_hash
        db.add_all([referenced_upload, duplicate_orphan])
        with pytest.raises(IntegrityError):
            db.commit()


def test_encounter_measurements_are_scoped_to_saved_day_window() -> None:
    with _make_session() as db:
        patient = _new_patient(db, "window")
        upload = _new_upload(patient.id)
        db.add(upload)
        db.flush()

        period = RecordingPeriod(
            upload_id=upload.id,
            period_index=0,
            start_time=datetime(2026, 3, 5, 0, 0, 0),
            end_time=datetime(2026, 3, 6, 1, 0, 0),
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
            duration_seconds=25 * 3600,
        )
        db.add(segment)
        db.flush()

        channel = Channel(
            upload_id=upload.id,
            source_type=SourceType.trend,
            channel_index=1,
            name="heart_rate_be_u16",
            unit="bpm",
            valid_count=3,
        )
        db.add(channel)
        db.flush()

        db.add_all(
            [
                Measurement(
                    upload_id=upload.id,
                    segment_id=segment.id,
                    channel_id=channel.id,
                    timestamp=datetime(2026, 3, 5, 12, 0, 0),
                    value=80.0,
                ),
                Measurement(
                    upload_id=upload.id,
                    segment_id=segment.id,
                    channel_id=channel.id,
                    timestamp=datetime(2026, 3, 6, 0, 30, 0),
                    value=81.0,
                ),
            ]
        )
        db.commit()

        encounter = create_or_replace_encounter(
            db,
            upload=upload,
            patient=patient,
            encounter_date_local=date(2026, 3, 5),
            timezone_name="UTC",
            label=None,
            notes=None,
        )

        rows = list_encounter_measurements(
            db,
            encounter_id=encounter.id,
            channel_ids=[channel.id],
            max_points=None,
            source_type=SourceType.trend,
        )

        assert [row[0].value for row in rows] == [80.0]


def test_delete_encounter_clears_patient_preferred_encounter() -> None:
    with _make_session() as db:
        patient = _new_patient(db, "preferred-delete")
        upload = _new_upload(patient.id)
        db.add(upload)
        db.commit()
        db.refresh(upload)

        encounter = create_or_replace_encounter(
            db,
            upload=upload,
            patient=patient,
            encounter_date_local=date(2026, 3, 5),
            timezone_name="UTC",
            label=None,
            notes=None,
        )
        patient.preferred_encounter_id = encounter.id
        db.add(patient)
        db.commit()

        delete_encounter(db, encounter)

        refreshed_patient = db.get(Patient, patient.id)
        assert refreshed_patient is not None
        assert refreshed_patient.preferred_encounter_id is None


def test_update_encounter_rejects_date_not_in_upload_detected_dates() -> None:
    with _make_session() as db:
        patient = _new_patient(db, "invalid-update")
        upload = _new_upload(patient.id)
        db.add(upload)
        db.commit()
        db.refresh(upload)

        encounter = create_or_replace_encounter(
            db,
            upload=upload,
            patient=patient,
            encounter_date_local=date(2026, 3, 5),
            timezone_name="UTC",
            label=None,
            notes=None,
        )

        try:
            update_encounter(
                db,
                encounter=encounter,
                encounter_date_local=date(2026, 3, 6),
                timezone_name="UTC",
                label=None,
                notes=None,
            )
        except ValueError as exc:
            assert str(exc) == "Selected encounter date is not available in this upload"
        else:
            raise AssertionError("Expected encounter update to reject a date without saved data")


def test_update_encounter_allows_switching_to_another_detected_date() -> None:
    with _make_session() as db:
        patient = _new_patient(db, "valid-update")
        upload = _new_upload(patient.id)
        db.add(upload)
        db.commit()
        db.refresh(upload)

        encounter = create_or_replace_encounter(
            db,
            upload=upload,
            patient=patient,
            encounter_date_local=date(2026, 3, 5),
            timezone_name="UTC",
            label=None,
            notes=None,
        )
        upload.detected_local_dates = ["2026-03-05", "2026-03-06"]
        db.add(upload)
        db.commit()

        updated = update_encounter(
            db,
            encounter=encounter,
            encounter_date_local=date(2026, 3, 6),
            timezone_name="UTC",
            label=None,
            notes=None,
        )

        assert updated.encounter_date_local == date(2026, 3, 6)

