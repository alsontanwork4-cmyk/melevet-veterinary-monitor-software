from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.parsers.index_parser import parse_index_bytes
from app.parsers.nibp_parser import parse_nibp_frames
from app.parsers.segmenter import split_periods_and_segments
from app.parsers.trend_parser import parse_trend_frames


def _read(path):
    if not path.exists():
        records_path = path.parent / "Records" / path.name
        if records_path.exists():
            path = records_path
    return path.read_bytes()


def test_sample_frame_counts(data_dir):
    trend_data = _read(data_dir / "TrendChartRecord.data")
    nibp_data = _read(data_dir / "NibpRecord.data")
    alarm_data = _read(data_dir / "AlarmRecord.data")

    assert len(trend_data) // 124 == 18496
    assert len(nibp_data) // 124 == 73
    assert len(alarm_data) // 124 == 1763


def test_trend_first_timestamp(data_dir):
    trend_index = _read(data_dir / "TrendChartRecord.Index")
    trend_data = _read(data_dir / "TrendChartRecord.data")

    parsed = parse_index_bytes(trend_index, trend_data)
    assert parsed.entries[0].timestamp_utc == datetime(2000, 1, 4, 2, 19, 8, tzinfo=UTC)


def test_trend_frame_timestamp_comes_from_data_frame(data_dir):
    trend_index = bytearray(_read(data_dir / "TrendChartRecord.Index"))
    trend_data = _read(data_dir / "TrendChartRecord.data")

    # Corrupt entry 0 timestamp in index to ensure parser uses frame bytes for trend timestamps.
    trend_index[24:28] = (0).to_bytes(4, "little")
    trend_index[28:32] = (0).to_bytes(4, "little")

    parsed = parse_index_bytes(bytes(trend_index), trend_data, require_monotonic=False)
    frames = parse_trend_frames(trend_data, parsed, {65535, 21845})

    expected_unix = int.from_bytes(trend_data[2:6], "little")
    expected_timestamp = datetime.fromtimestamp(expected_unix, tz=UTC)

    assert parsed.entries[0].timestamp_utc != expected_timestamp
    assert frames[0].timestamp == expected_timestamp


def test_trend_parser_converts_invalid_sentinels_to_none(data_dir):
    trend_index = _read(data_dir / "TrendChartRecord.Index")
    trend_data = _read(data_dir / "TrendChartRecord.data")

    parsed = parse_index_bytes(trend_index, trend_data, require_monotonic=False)
    frames = parse_trend_frames(trend_data, parsed, {65535, 21845})

    # Sample data has known invalid sentinel values at first frame channel offsets 28 and 32.
    assert frames[0].values[14] is None
    assert frames[0].values[16] is None


def test_trend_parser_accepts_missing_index(data_dir):
    trend_data = _read(data_dir / "TrendChartRecord.data")

    frames = parse_trend_frames(trend_data, None, {65535, 21845})

    expected_unix = int.from_bytes(trend_data[2:6], "little")
    expected_timestamp = datetime.fromtimestamp(expected_unix, tz=UTC)

    assert len(frames) == len(trend_data) // 124
    assert frames[0].timestamp == expected_timestamp


def test_segmenter_sample_boundaries(data_dir):
    trend_index = _read(data_dir / "TrendChartRecord.Index")
    trend_data = _read(data_dir / "TrendChartRecord.data")
    parsed = parse_index_bytes(trend_index, trend_data)

    timestamps = [entry.timestamp_utc for entry in parsed.entries]
    periods = split_periods_and_segments(
        timestamps=timestamps,
        period_gap_seconds=24 * 60 * 60,
        segment_gap_seconds=10 * 60,
    )

    assert len(periods) == 9
    assert sum(len(period.segments) for period in periods) == 12


def test_segmenter_starts_new_period_on_timestamp_rollback():
    start = datetime(2026, 3, 2, 13, 51, 52, tzinfo=UTC)
    timestamps = [
        start,
        start + timedelta(seconds=30),
        start + timedelta(seconds=60),
        start - timedelta(days=38),
        (start - timedelta(days=38)) + timedelta(seconds=45),
    ]

    periods = split_periods_and_segments(
        timestamps=timestamps,
        period_gap_seconds=24 * 60 * 60,
        segment_gap_seconds=10 * 60,
    )

    assert len(periods) == 2
    assert len(periods[0].segments) == 1
    assert len(periods[1].segments) == 1
    assert periods[0].segments[0].start_idx == 0
    assert periods[0].segments[0].end_idx == 2
    assert periods[1].segments[0].start_idx == 3
    assert periods[1].segments[0].end_idx == 4
    assert sum(period.frame_count for period in periods) == len(timestamps)


def test_nibp_parser_adds_inferred_bp_fields(data_dir):
    nibp_index = _read(data_dir / "NibpRecord.Index")
    nibp_data = _read(data_dir / "NibpRecord.data")

    parsed = parse_index_bytes(nibp_index, nibp_data, require_monotonic=False)
    frames = parse_nibp_frames(nibp_data, parsed, {65535, 21845})

    first_measurement = next(frame for frame in frames if frame.channel_values["bp_systolic_inferred"] is not None)
    assert first_measurement.channel_values["bp_systolic_inferred"] == 98
    assert first_measurement.channel_values["bp_diastolic_inferred"] == 94
    assert first_measurement.channel_values["bp_mean_inferred"] == 95
