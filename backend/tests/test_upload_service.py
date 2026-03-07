from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.upload_service import SegmentWindowRef, _resolve_segment_for_timestamp


def test_resolve_segment_uses_chronological_bounds_when_windows_unsorted():
    base = datetime(2026, 3, 2, 13, 0, 0, tzinfo=UTC)
    earlier = SegmentWindowRef(
        id=1,
        start_time=base,
        end_time=base + timedelta(minutes=30),
    )
    later = SegmentWindowRef(
        id=2,
        start_time=base + timedelta(hours=1),
        end_time=base + timedelta(hours=2),
    )

    windows = [later, earlier]

    assert _resolve_segment_for_timestamp(base - timedelta(minutes=5), windows) == 1
    assert _resolve_segment_for_timestamp(base + timedelta(hours=3), windows) == 2
    assert _resolve_segment_for_timestamp(base + timedelta(minutes=40), windows) == 1
