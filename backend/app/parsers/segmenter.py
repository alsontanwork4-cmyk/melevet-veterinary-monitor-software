from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SegmentWindow:
    segment_index: int
    start_idx: int
    end_idx: int
    start_time: datetime
    end_time: datetime

    @property
    def frame_count(self) -> int:
        return self.end_idx - self.start_idx + 1

    @property
    def duration_seconds(self) -> int:
        return int((self.end_time - self.start_time).total_seconds())


@dataclass
class PeriodWindow:
    period_index: int
    start_time: datetime
    end_time: datetime
    segments: list[SegmentWindow] = field(default_factory=list)

    @property
    def frame_count(self) -> int:
        return sum(segment.frame_count for segment in self.segments)


def split_periods_and_segments(
    timestamps: list[datetime],
    period_gap_seconds: int,
    segment_gap_seconds: int,
) -> list[PeriodWindow]:
    if not timestamps:
        return []

    periods: list[PeriodWindow] = []

    period_index = 0
    segment_index = 0

    current_period = PeriodWindow(period_index=period_index, start_time=timestamps[0], end_time=timestamps[0])
    current_segment = SegmentWindow(
        segment_index=segment_index,
        start_idx=0,
        end_idx=0,
        start_time=timestamps[0],
        end_time=timestamps[0],
    )

    for idx in range(1, len(timestamps)):
        now = timestamps[idx]
        previous = timestamps[idx - 1]
        gap = int((now - previous).total_seconds())

        if gap < 0 or gap > period_gap_seconds:
            current_period.end_time = current_segment.end_time
            current_period.segments.append(current_segment)
            periods.append(current_period)

            period_index += 1
            segment_index = 0
            current_period = PeriodWindow(period_index=period_index, start_time=now, end_time=now)
            current_segment = SegmentWindow(
                segment_index=segment_index,
                start_idx=idx,
                end_idx=idx,
                start_time=now,
                end_time=now,
            )
            continue

        if gap > segment_gap_seconds:
            current_period.segments.append(current_segment)
            segment_index += 1
            current_segment = SegmentWindow(
                segment_index=segment_index,
                start_idx=idx,
                end_idx=idx,
                start_time=now,
                end_time=now,
            )
        else:
            current_segment.end_idx = idx
            current_segment.end_time = now

        current_period.end_time = now

    current_period.segments.append(current_segment)
    current_period.end_time = current_segment.end_time
    periods.append(current_period)

    return periods
