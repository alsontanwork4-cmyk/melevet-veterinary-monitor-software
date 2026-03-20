from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.parsers.index_parser import (
    INDEX_ENTRY_SIZE,
    INDEX_HEADER_SIZE,
    INDEX_TRAILER_SIZE,
    IndexParseError,
    decode_unix_seconds,
    parse_index_bytes,
)


def _encode_index_entry(unix_seconds: int) -> bytes:
    ts_lo = (unix_seconds & 0xFFFF) << 16
    ts_hi = (unix_seconds >> 16) & 0xFFFF
    return (
        int(0).to_bytes(4, "little")
        + int(0).to_bytes(4, "little")
        + ts_lo.to_bytes(4, "little")
        + ts_hi.to_bytes(4, "little")
    )


def _build_index_bytes(unix_seconds_list: list[int]) -> bytes:
    payload = b"".join(_encode_index_entry(ts) for ts in unix_seconds_list)
    header = (
        int(1).to_bytes(4, "little")
        + int(0).to_bytes(4, "little")
        + len(payload).to_bytes(4, "little")
        + int(0).to_bytes(4, "little")
    )
    trailer = b"\x00" * INDEX_TRAILER_SIZE
    return header + payload + trailer


def test_index_layout_formula(data_dir):
    index_path = data_dir / "TrendChartRecord.Index"
    data_path = data_dir / "TrendChartRecord.data"
    if not index_path.exists():
        index_path = data_dir / "Records" / "TrendChartRecord.Index"
    if not data_path.exists():
        data_path = data_dir / "Records" / "TrendChartRecord.data"

    index_bytes = index_path.read_bytes()
    data_bytes = data_path.read_bytes()

    parsed = parse_index_bytes(index_bytes, data_bytes)
    expected_entries = (len(index_bytes) - INDEX_HEADER_SIZE - INDEX_TRAILER_SIZE) // INDEX_ENTRY_SIZE
    assert len(parsed.entries) == expected_entries


def test_timestamp_decode_formula():
    ts_lo = 0x589C0000
    ts_hi = 0x07673871
    unix_seconds = decode_unix_seconds(ts_lo=ts_lo, ts_hi=ts_hi)
    assert unix_seconds == 946952348


def test_non_monotonic_index_raises_in_strict_mode():
    base = int(datetime(2026, 3, 2, 13, 51, 52, tzinfo=UTC).timestamp())
    index_bytes = _build_index_bytes([base, base + 60, base - 120])

    with pytest.raises(IndexParseError, match="Index timestamps are not monotonic at entry 2"):
        parse_index_bytes(index_bytes, require_monotonic=True)


def test_non_monotonic_index_allowed_in_tolerant_mode():
    base = int(datetime(2026, 3, 2, 13, 51, 52, tzinfo=UTC).timestamp())
    index_bytes = _build_index_bytes([base, base + 60, base - 120])

    parsed = parse_index_bytes(index_bytes, require_monotonic=False)

    assert len(parsed.entries) == 3
    assert parsed.rollback_indices == [2]
