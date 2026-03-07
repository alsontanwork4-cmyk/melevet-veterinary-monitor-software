from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import create_engine
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
from app.schemas.api import MeasurementPoint
from app.services.chart_service import (
    list_alarms,
    list_measurements,
    list_nibp_events,
    list_upload_channels,
    list_upload_measurements,
    query_upload_measurements,
)


def _make_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)()


def _new_upload(patient_id: int) -> Upload:
    checksum = "1" * 64
    return Upload(
        patient_id=patient_id,
        status=UploadStatus.completed,
        phase="complete",
        progress_current=1,
        progress_total=1,
        trend_frames=1,
        nibp_frames=0,
        alarm_frames=0,
        trend_sha256=checksum,
        trend_index_sha256=checksum,
        nibp_sha256=checksum,
        nibp_index_sha256=checksum,
        alarm_sha256=checksum,
        alarm_index_sha256=checksum,
    )


def test_datetime_serializes_with_explicit_utc_suffix() -> None:
    point = MeasurementPoint(
        timestamp=datetime(2026, 3, 5, 12, 34, 56),
        channel_id=123,
        channel_name="heart_rate_be_u16",
        value=98.0,
    )

    payload = point.model_dump_json()
    assert '"timestamp":"2026-03-05T12:34:56Z"' in payload


def test_measurement_window_filter_is_timezone_stable() -> None:
    db = _make_session()

    patient = Patient(patient_id_code="TZ-1", name="Patient", species="canine")
    db.add(patient)
    db.flush()

    upload = _new_upload(patient.id)
    db.add(upload)
    db.flush()

    period = RecordingPeriod(
        upload_id=upload.id,
        period_index=0,
        start_time=datetime(2026, 1, 19, 14, 0, 0),
        end_time=datetime(2026, 1, 19, 14, 30, 0),
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
        duration_seconds=1800,
    )
    db.add(segment)
    db.flush()

    channel = Channel(
        upload_id=upload.id,
        source_type=SourceType.trend,
        channel_index=14,
        name="heart_rate_be_u16",
        unit="bpm",
        valid_count=2,
    )
    db.add(channel)
    db.flush()

    db.add_all(
        [
            Measurement(
                upload_id=upload.id,
                segment_id=segment.id,
                channel_id=channel.id,
                timestamp=datetime(2026, 1, 19, 14, 10, 0),
                value=95.0,
            ),
            Measurement(
                upload_id=upload.id,
                segment_id=segment.id,
                channel_id=channel.id,
                timestamp=datetime(2026, 1, 19, 14, 12, 0),
                value=96.0,
            ),
        ]
    )
    db.commit()

    utc_from = datetime(2026, 1, 19, 14, 9, 0, tzinfo=UTC)
    utc_to = datetime(2026, 1, 19, 14, 13, 0, tzinfo=UTC)

    sg_tz = timezone(timedelta(hours=8))
    sg_from = utc_from.astimezone(sg_tz)
    sg_to = utc_to.astimezone(sg_tz)

    rows_utc = list_measurements(
        db,
        segment_id=segment.id,
        channel_ids=[channel.id],
        from_ts=utc_from,
        to_ts=utc_to,
        max_points=None,
        source_type=SourceType.trend,
    )
    rows_sg = list_measurements(
        db,
        segment_id=segment.id,
        channel_ids=[channel.id],
        from_ts=sg_from,
        to_ts=sg_to,
        max_points=None,
        source_type=SourceType.trend,
    )

    assert len(rows_utc) == 2
    assert len(rows_sg) == 2


def test_upload_measurements_include_multiple_segments_and_timezone_stable() -> None:
    db = _make_session()

    patient = Patient(patient_id_code="TZ-2", name="Patient", species="canine")
    db.add(patient)
    db.flush()

    upload = _new_upload(patient.id)
    db.add(upload)
    db.flush()

    period = RecordingPeriod(
        upload_id=upload.id,
        period_index=0,
        start_time=datetime(2026, 1, 19, 10, 0, 0),
        end_time=datetime(2026, 1, 19, 11, 0, 0),
        frame_count=4,
        label="Period 1",
    )
    db.add(period)
    db.flush()

    segment_a = Segment(
        period_id=period.id,
        upload_id=upload.id,
        segment_index=0,
        start_time=datetime(2026, 1, 19, 10, 0, 0),
        end_time=datetime(2026, 1, 19, 10, 20, 0),
        frame_count=2,
        duration_seconds=1200,
    )
    segment_b = Segment(
        period_id=period.id,
        upload_id=upload.id,
        segment_index=1,
        start_time=datetime(2026, 1, 19, 10, 30, 0),
        end_time=datetime(2026, 1, 19, 11, 0, 0),
        frame_count=2,
        duration_seconds=1800,
    )
    db.add_all([segment_a, segment_b])
    db.flush()

    channel = Channel(
        upload_id=upload.id,
        source_type=SourceType.trend,
        channel_index=10,
        name="spo2_be_u16",
        unit="%",
        valid_count=4,
    )
    db.add(channel)
    db.flush()

    db.add_all(
        [
            Measurement(
                upload_id=upload.id,
                segment_id=segment_a.id,
                channel_id=channel.id,
                timestamp=datetime(2026, 1, 19, 10, 5, 0),
                value=95.0,
            ),
            Measurement(
                upload_id=upload.id,
                segment_id=segment_b.id,
                channel_id=channel.id,
                timestamp=datetime(2026, 1, 19, 10, 35, 0),
                value=96.0,
            ),
        ]
    )
    db.commit()

    utc_from = datetime(2026, 1, 19, 10, 0, 0, tzinfo=UTC)
    utc_to = datetime(2026, 1, 19, 10, 40, 0, tzinfo=UTC)
    sg_tz = timezone(timedelta(hours=8))

    rows_utc = list_upload_measurements(
        db,
        upload_id=upload.id,
        channel_ids=[channel.id],
        from_ts=utc_from,
        to_ts=utc_to,
        max_points=None,
        source_type=SourceType.trend,
    )
    rows_sg = list_upload_measurements(
        db,
        upload_id=upload.id,
        channel_ids=[channel.id],
        from_ts=utc_from.astimezone(sg_tz),
        to_ts=utc_to.astimezone(sg_tz),
        max_points=None,
        source_type=SourceType.trend,
    )

    assert len(rows_utc) == 2
    assert len(rows_sg) == 2
    assert rows_utc[0][0].segment_id != rows_utc[1][0].segment_id


def test_alarm_and_nibp_range_filters_apply_at_upload_scope() -> None:
    db = _make_session()

    patient = Patient(patient_id_code="TZ-3", name="Patient", species="canine")
    db.add(patient)
    db.flush()

    upload = _new_upload(patient.id)
    db.add(upload)
    db.flush()

    period = RecordingPeriod(
        upload_id=upload.id,
        period_index=0,
        start_time=datetime(2026, 1, 19, 12, 0, 0),
        end_time=datetime(2026, 1, 19, 12, 30, 0),
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
        duration_seconds=1800,
    )
    db.add(segment)
    db.flush()

    db.add_all(
        [
            Alarm(
                upload_id=upload.id,
                segment_id=segment.id,
                timestamp=datetime(2026, 1, 19, 12, 5, 0),
                flag_hi=0,
                flag_lo=0,
                alarm_category=AlarmCategory.informational,
                message="before-window",
            ),
            Alarm(
                upload_id=upload.id,
                segment_id=segment.id,
                timestamp=datetime(2026, 1, 19, 12, 10, 0),
                flag_hi=1,
                flag_lo=0,
                alarm_category=AlarmCategory.physiological_warning,
                message="in-window",
            ),
        ]
    )

    db.add_all(
        [
            NibpEvent(
                upload_id=upload.id,
                segment_id=segment.id,
                timestamp=datetime(2026, 1, 19, 12, 8, 0),
                channel_values={"bp_systolic_inferred": 120, "bp_mean_inferred": 100, "bp_diastolic_inferred": 90},
                has_measurement=True,
            ),
            NibpEvent(
                upload_id=upload.id,
                segment_id=segment.id,
                timestamp=datetime(2026, 1, 19, 12, 20, 0),
                channel_values={"bp_systolic_inferred": 130, "bp_mean_inferred": 110, "bp_diastolic_inferred": 95},
                has_measurement=True,
            ),
        ]
    )
    db.commit()

    from_ts = datetime(2026, 1, 19, 12, 9, 0, tzinfo=UTC)
    to_ts = datetime(2026, 1, 19, 12, 15, 0, tzinfo=UTC)

    filtered_alarms = list_alarms(
        db,
        upload_id=upload.id,
        from_ts=from_ts,
        to_ts=to_ts,
    )
    filtered_nibp = list_nibp_events(
        db,
        upload_id=upload.id,
        from_ts=from_ts,
        to_ts=to_ts,
    )

    assert [alarm.message for alarm in filtered_alarms] == ["in-window"]
    assert len(filtered_nibp) == 0


def test_upload_channel_listing_supports_source_filters() -> None:
    db = _make_session()

    patient = Patient(patient_id_code="TZ-4", name="Patient", species="canine")
    db.add(patient)
    db.flush()

    upload = _new_upload(patient.id)
    db.add(upload)
    db.flush()

    period = RecordingPeriod(
        upload_id=upload.id,
        period_index=0,
        start_time=datetime(2026, 1, 19, 8, 0, 0),
        end_time=datetime(2026, 1, 19, 8, 10, 0),
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
        duration_seconds=600,
    )
    db.add(segment)
    db.flush()

    trend_with_measurement = Channel(
        upload_id=upload.id,
        source_type=SourceType.trend,
        channel_index=1,
        name="heart_rate_be_u16",
        unit="bpm",
        valid_count=1,
    )
    trend_without_measurement = Channel(
        upload_id=upload.id,
        source_type=SourceType.trend,
        channel_index=2,
        name="unused_trend_channel",
        unit=None,
        valid_count=0,
    )
    nibp_channel = Channel(
        upload_id=upload.id,
        source_type=SourceType.nibp,
        channel_index=14,
        name="bp_systolic_inferred",
        unit="mmHg",
        valid_count=1,
    )
    db.add_all([trend_with_measurement, trend_without_measurement, nibp_channel])
    db.flush()

    db.add(
        Measurement(
            upload_id=upload.id,
            segment_id=segment.id,
            channel_id=trend_with_measurement.id,
            timestamp=datetime(2026, 1, 19, 8, 1, 0),
            value=100.0,
        )
    )
    db.commit()

    trend_channels = list_upload_channels(db, upload_id=upload.id, source_type=SourceType.trend)
    nibp_channels = list_upload_channels(db, upload_id=upload.id, source_type=SourceType.nibp)
    all_channels = list_upload_channels(db, upload_id=upload.id, source_type=None)

    assert [channel.name for channel in trend_channels] == ["heart_rate_be_u16"]
    assert [channel.name for channel in nibp_channels] == ["bp_systolic_inferred"]
    assert [channel.name for channel in all_channels] == ["heart_rate_be_u16", "bp_systolic_inferred"]


def test_alarm_and_nibp_filters_apply_with_segment_and_time_window() -> None:
    db = _make_session()

    patient = Patient(patient_id_code="TZ-5", name="Patient", species="canine")
    db.add(patient)
    db.flush()

    upload = _new_upload(patient.id)
    db.add(upload)
    db.flush()

    period = RecordingPeriod(
        upload_id=upload.id,
        period_index=0,
        start_time=datetime(2026, 1, 19, 12, 0, 0),
        end_time=datetime(2026, 1, 19, 13, 0, 0),
        frame_count=6,
        label="Period 1",
    )
    db.add(period)
    db.flush()

    segment_a = Segment(
        period_id=period.id,
        upload_id=upload.id,
        segment_index=0,
        start_time=datetime(2026, 1, 19, 12, 0, 0),
        end_time=datetime(2026, 1, 19, 12, 30, 0),
        frame_count=3,
        duration_seconds=1800,
    )
    segment_b = Segment(
        period_id=period.id,
        upload_id=upload.id,
        segment_index=1,
        start_time=datetime(2026, 1, 19, 12, 30, 0),
        end_time=datetime(2026, 1, 19, 13, 0, 0),
        frame_count=3,
        duration_seconds=1800,
    )
    db.add_all([segment_a, segment_b])
    db.flush()

    db.add_all(
        [
            Alarm(
                upload_id=upload.id,
                segment_id=segment_a.id,
                timestamp=datetime(2026, 1, 19, 12, 10, 0),
                flag_hi=0,
                flag_lo=1,
                alarm_category=AlarmCategory.informational,
                message="segment-a-hit",
            ),
            Alarm(
                upload_id=upload.id,
                segment_id=segment_b.id,
                timestamp=datetime(2026, 1, 19, 12, 10, 0),
                flag_hi=0,
                flag_lo=2,
                alarm_category=AlarmCategory.informational,
                message="segment-b-ignore",
            ),
        ]
    )

    db.add_all(
        [
            NibpEvent(
                upload_id=upload.id,
                segment_id=segment_a.id,
                timestamp=datetime(2026, 1, 19, 12, 10, 0),
                channel_values={"bp_systolic_inferred": 120, "bp_mean_inferred": 100, "bp_diastolic_inferred": 90},
                has_measurement=True,
            ),
            NibpEvent(
                upload_id=upload.id,
                segment_id=segment_b.id,
                timestamp=datetime(2026, 1, 19, 12, 11, 0),
                channel_values={"bp_systolic_inferred": 130, "bp_mean_inferred": 110, "bp_diastolic_inferred": 95},
                has_measurement=True,
            ),
        ]
    )
    db.commit()

    from_ts = datetime(2026, 1, 19, 12, 9, 0, tzinfo=UTC)
    to_ts = datetime(2026, 1, 19, 12, 11, 0, tzinfo=UTC)

    filtered_alarms = list_alarms(
        db,
        upload_id=upload.id,
        segment_id=segment_a.id,
        from_ts=from_ts,
        to_ts=to_ts,
    )
    filtered_nibp = list_nibp_events(
        db,
        upload_id=upload.id,
        segment_id=segment_a.id,
        from_ts=from_ts,
        to_ts=to_ts,
    )

    assert [alarm.message for alarm in filtered_alarms] == ["segment-a-hit"]
    assert [event.channel_values["bp_systolic_inferred"] for event in filtered_nibp] == [120]


def test_upload_measurement_downsampling_caps_points_per_channel() -> None:
    db = _make_session()

    patient = Patient(patient_id_code="TZ-6", name="Patient", species="canine")
    db.add(patient)
    db.flush()

    upload = _new_upload(patient.id)
    db.add(upload)
    db.flush()

    period = RecordingPeriod(
        upload_id=upload.id,
        period_index=0,
        start_time=datetime(2026, 1, 19, 10, 0, 0),
        end_time=datetime(2026, 1, 19, 10, 30, 0),
        frame_count=50,
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
        frame_count=50,
        duration_seconds=1800,
    )
    db.add(segment)
    db.flush()

    channel_a = Channel(
        upload_id=upload.id,
        source_type=SourceType.trend,
        channel_index=1,
        name="heart_rate_be_u16",
        unit="bpm",
        valid_count=25,
    )
    channel_b = Channel(
        upload_id=upload.id,
        source_type=SourceType.trend,
        channel_index=2,
        name="spo2_be_u16",
        unit="%",
        valid_count=25,
    )
    db.add_all([channel_a, channel_b])
    db.flush()

    base = datetime(2026, 1, 19, 10, 0, 0)
    measurements: list[Measurement] = []
    for idx in range(25):
        ts = base + timedelta(seconds=idx)
        measurements.append(
            Measurement(
                upload_id=upload.id,
                segment_id=segment.id,
                channel_id=channel_a.id,
                timestamp=ts,
                value=80.0 + idx,
            )
        )
        measurements.append(
            Measurement(
                upload_id=upload.id,
                segment_id=segment.id,
                channel_id=channel_b.id,
                timestamp=ts,
                value=95.0 + idx,
            )
        )
    db.add_all(measurements)
    db.commit()

    rows = list_upload_measurements(
        db,
        upload_id=upload.id,
        channel_ids=[channel_a.id, channel_b.id],
        from_ts=None,
        to_ts=None,
        max_points=10,
        source_type=SourceType.trend,
    )

    counts = Counter(row[0].channel_id for row in rows)
    assert counts[channel_a.id] <= 10
    assert counts[channel_b.id] <= 10


def test_query_upload_measurements_reports_matched_and_returned_row_counts() -> None:
    db = _make_session()

    patient = Patient(patient_id_code="TZ-7", name="Patient", species="canine")
    db.add(patient)
    db.flush()

    upload = _new_upload(patient.id)
    db.add(upload)
    db.flush()

    period = RecordingPeriod(
        upload_id=upload.id,
        period_index=0,
        start_time=datetime(2026, 1, 19, 10, 0, 0),
        end_time=datetime(2026, 1, 19, 10, 30, 0),
        frame_count=12,
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
        frame_count=12,
        duration_seconds=1800,
    )
    db.add(segment)
    db.flush()

    channel = Channel(
        upload_id=upload.id,
        source_type=SourceType.trend,
        channel_index=1,
        name="heart_rate_be_u16",
        unit="bpm",
        valid_count=12,
    )
    db.add(channel)
    db.flush()

    base = datetime(2026, 1, 19, 10, 0, 0)
    db.add_all(
        [
            Measurement(
                upload_id=upload.id,
                segment_id=segment.id,
                channel_id=channel.id,
                timestamp=base + timedelta(seconds=idx),
                value=100.0 + idx,
            )
            for idx in range(12)
        ]
    )
    db.commit()

    result = query_upload_measurements(
        db,
        upload_id=upload.id,
        channel_ids=[channel.id],
        from_ts=None,
        to_ts=None,
        max_points=5,
        source_type=SourceType.trend,
    )

    assert result.matched_row_count == 12
    assert result.returned_row_count <= 5


