from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .index_parser import ParsedIndex


FRAME_SIZE = 124
PAYLOAD_SIZE = 122
CHANNEL_COUNT = 61


@dataclass(frozen=True)
class TrendFrame:
    frame_index: int
    timestamp: datetime
    values: list[int | None]


class TrendParseError(ValueError):
    pass


def parse_trend_frames(
    data_bytes: bytes,
    parsed_index: ParsedIndex | None,
    invalid_u16_values: set[int],
) -> list[TrendFrame]:
    if len(data_bytes) % FRAME_SIZE != 0:
        raise TrendParseError("Trend data file size is not aligned to 124-byte frames")

    frame_count = len(data_bytes) // FRAME_SIZE
    if parsed_index is not None and frame_count != len(parsed_index.entries):
        raise TrendParseError(
            f"Trend frame count ({frame_count}) does not match index entries ({len(parsed_index.entries)})"
        )

    frames: list[TrendFrame] = []

    for i in range(frame_count):
        frame_start = i * FRAME_SIZE
        frame_timestamp_unix = int.from_bytes(data_bytes[frame_start + 2 : frame_start + 6], "little")
        frame_timestamp_utc = datetime.fromtimestamp(frame_timestamp_unix, tz=UTC)
        payload = data_bytes[frame_start : frame_start + PAYLOAD_SIZE]

        values: list[int | None] = []
        for channel_index in range(CHANNEL_COUNT):
            offset = channel_index * 2
            raw = int.from_bytes(payload[offset : offset + 2], "big")
            if raw in invalid_u16_values:
                values.append(None)
            else:
                values.append(raw)

        frames.append(
            TrendFrame(
                frame_index=i,
                timestamp=frame_timestamp_utc,
                values=values,
            )
        )

    return frames


def trend_channel_name(channel_index: int) -> str:
    byte_offset = channel_index * 2
    return f"trend_raw_be_u16_o{byte_offset:02d}"
