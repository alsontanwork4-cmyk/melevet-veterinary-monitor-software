from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .index_parser import ParsedIndex


FRAME_SIZE = 124
PAYLOAD_SIZE = 122
CHANNEL_COUNT = 61
SYSTOLIC_CHANNEL_INDEX = 14
MEAN_CHANNEL_INDEX = 15
DIASTOLIC_CHANNEL_INDEX = 16


@dataclass(frozen=True)
class NibpFrame:
    frame_index: int
    timestamp: datetime
    channel_values: dict[str, int | None]
    has_measurement: bool


class NibpParseError(ValueError):
    pass


def nibp_channel_name(channel_index: int) -> str:
    byte_offset = channel_index * 2
    return f"nibp_raw_be_u16_o{byte_offset:02d}"


def _positive_bp_value(value: int | None) -> int | None:
    if value is None:
        return None
    return value if value > 0 else None


def infer_nibp_measurement(channel_values: dict[str, int | None]) -> dict[str, int | None]:
    systolic = _positive_bp_value(channel_values.get(nibp_channel_name(SYSTOLIC_CHANNEL_INDEX)))
    diastolic = _positive_bp_value(channel_values.get(nibp_channel_name(DIASTOLIC_CHANNEL_INDEX)))
    mean = _positive_bp_value(channel_values.get(nibp_channel_name(MEAN_CHANNEL_INDEX)))

    if mean is None and systolic is not None and diastolic is not None and systolic >= diastolic:
        mean = round(diastolic + (systolic - diastolic) / 3)

    return {
        "bp_systolic_inferred": systolic,
        "bp_mean_inferred": mean,
        "bp_diastolic_inferred": diastolic,
    }


def parse_nibp_frames(data_bytes: bytes, parsed_index: ParsedIndex, invalid_u16_values: set[int]) -> list[NibpFrame]:
    if len(data_bytes) % FRAME_SIZE != 0:
        raise NibpParseError("NIBP data file size is not aligned to 124-byte frames")

    frame_count = len(data_bytes) // FRAME_SIZE
    if frame_count != len(parsed_index.entries):
        raise NibpParseError(
            f"NIBP frame count ({frame_count}) does not match index entries ({len(parsed_index.entries)})"
        )

    frames: list[NibpFrame] = []

    for i in range(frame_count):
        frame_start = i * FRAME_SIZE
        payload = data_bytes[frame_start : frame_start + PAYLOAD_SIZE]

        channel_values: dict[str, int | None] = {}
        has_measurement = False

        for channel_index in range(CHANNEL_COUNT):
            offset = channel_index * 2
            raw = int.from_bytes(payload[offset : offset + 2], "big")
            value = None if raw in invalid_u16_values else raw
            channel_values[nibp_channel_name(channel_index)] = value
            if value is not None:
                has_measurement = True

        channel_values.update(infer_nibp_measurement(channel_values))

        frames.append(
            NibpFrame(
                frame_index=i,
                timestamp=parsed_index.entries[i].timestamp_utc,
                channel_values=channel_values,
                has_measurement=has_measurement,
            )
        )

    return frames
