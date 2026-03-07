from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import Channel, Patient, SourceType, Upload, UploadStatus
from app.services import channel_mapping
from app.services.channel_metadata_backfill import backfill_channel_metadata


def _make_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)()


def _new_upload(patient_id: int) -> Upload:
    checksum = "0" * 64
    return Upload(
        patient_id=patient_id,
        status=UploadStatus.completed,
        phase="complete",
        progress_current=1,
        progress_total=1,
        started_at=datetime(2026, 3, 5, 0, 0, 0),
        completed_at=datetime(2026, 3, 5, 0, 1, 0),
        trend_frames=0,
        nibp_frames=0,
        alarm_frames=0,
        trend_sha256=checksum,
        trend_index_sha256=checksum,
        nibp_sha256=checksum,
        nibp_index_sha256=checksum,
        alarm_sha256=checksum,
        alarm_index_sha256=checksum,
    )


def test_resolve_channel_metadata_prefers_index_over_legacy_offset(monkeypatch) -> None:
    monkeypatch.setattr(
        channel_mapping,
        "load_channel_map",
        lambda: {
            "trend": {
                "14": {"name": "index_wins", "unit": "bpm"},
                "28": {"name": "legacy_offset", "unit": "%"},
            }
        },
    )

    name, unit = channel_mapping.resolve_channel_metadata(
        source_type="trend",
        channel_index=14,
        default_name="fallback",
        default_unit=None,
    )

    assert name == "index_wins"
    assert unit == "bpm"


def test_resolve_channel_metadata_accepts_legacy_offset_alias(monkeypatch) -> None:
    monkeypatch.setattr(
        channel_mapping,
        "load_channel_map",
        lambda: {"nibp": {"o28": {"name": "legacy_systolic", "unit": "mmHg"}}},
    )

    name, unit = channel_mapping.resolve_channel_metadata(
        source_type="nibp",
        channel_index=14,
        default_name="fallback",
        default_unit=None,
    )

    assert name == "legacy_systolic"
    assert unit == "mmHg"


def test_resolve_channel_metadata_does_not_use_implicit_numeric_offset_alias(monkeypatch) -> None:
    monkeypatch.setattr(
        channel_mapping,
        "load_channel_map",
        lambda: {"trend": {"14": {"name": "heart_rate", "unit": "bpm"}}},
    )

    name, unit = channel_mapping.resolve_channel_metadata(
        source_type="trend",
        channel_index=7,
        default_name="trend_raw_be_u16_o14",
        default_unit=None,
    )

    assert name == "trend_raw_be_u16_o14"
    assert unit is None


def test_backfill_channel_metadata_updates_existing_rows() -> None:
    channel_mapping.load_channel_map.cache_clear()
    db = _make_session()

    patient = Patient(patient_id_code="P-1", name="Patient", species="canine")
    db.add(patient)
    db.flush()

    upload = _new_upload(patient.id)
    db.add(upload)
    db.flush()

    db.add_all(
        [
            Channel(
                upload_id=upload.id,
                source_type=SourceType.trend,
                channel_index=14,
                name="trend_raw_be_u16_o28",
                unit=None,
                valid_count=10,
            ),
            Channel(
                upload_id=upload.id,
                source_type=SourceType.trend,
                channel_index=16,
                name="trend_raw_be_u16_o32",
                unit=None,
                valid_count=10,
            ),
            Channel(
                upload_id=upload.id,
                source_type=SourceType.nibp,
                channel_index=14,
                name="nibp_raw_be_u16_o28",
                unit=None,
                valid_count=4,
            ),
            Channel(
                upload_id=upload.id,
                source_type=SourceType.nibp,
                channel_index=15,
                name="nibp_raw_be_u16_o30",
                unit=None,
                valid_count=4,
            ),
            Channel(
                upload_id=upload.id,
                source_type=SourceType.nibp,
                channel_index=16,
                name="nibp_raw_be_u16_o32",
                unit=None,
                valid_count=4,
            ),
            Channel(
                upload_id=upload.id,
                source_type=SourceType.trend,
                channel_index=25,
                name="trend_raw_be_u16_o50",
                unit=None,
                valid_count=9,
            ),
        ]
    )
    db.commit()

    result = backfill_channel_metadata(db, upload_id=upload.id)
    assert result.scanned == 6
    assert result.updated == 5

    trend_spo2 = db.query(Channel).filter(Channel.upload_id == upload.id, Channel.source_type == SourceType.trend, Channel.channel_index == 14).one()
    assert trend_spo2.name == "spo2_be_u16"
    assert trend_spo2.unit == "%"

    trend_hr = db.query(Channel).filter(Channel.upload_id == upload.id, Channel.source_type == SourceType.trend, Channel.channel_index == 16).one()
    assert trend_hr.name == "heart_rate_be_u16"
    assert trend_hr.unit == "bpm"

    nibp_sys = db.query(Channel).filter(Channel.upload_id == upload.id, Channel.source_type == SourceType.nibp, Channel.channel_index == 14).one()
    assert nibp_sys.name == "bp_systolic_inferred"
    assert nibp_sys.unit == "mmHg"

    nibp_mean = db.query(Channel).filter(Channel.upload_id == upload.id, Channel.source_type == SourceType.nibp, Channel.channel_index == 15).one()
    assert nibp_mean.name == "bp_mean_inferred"
    assert nibp_mean.unit == "mmHg"

    nibp_dia = db.query(Channel).filter(Channel.upload_id == upload.id, Channel.source_type == SourceType.nibp, Channel.channel_index == 16).one()
    assert nibp_dia.name == "bp_diastolic_inferred"
    assert nibp_dia.unit == "mmHg"

    untouched = db.query(Channel).filter(Channel.upload_id == upload.id, Channel.channel_index == 25).one()
    assert untouched.name == "trend_raw_be_u16_o50"

