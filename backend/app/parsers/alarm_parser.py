from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .index_parser import ParsedIndex
from ..models import AlarmCategory


FRAME_SIZE = 124


CATEGORY_MAP: dict[tuple[int, int], AlarmCategory] = {
    (0x01, 0x02): AlarmCategory.technical,
    (0x02, 0x03): AlarmCategory.physiological_warning,
    (0x03, 0x01): AlarmCategory.technical_critical,
    (0x03, 0x03): AlarmCategory.physiological_critical,
    (0x04, 0x01): AlarmCategory.system,
    (0x04, 0x02): AlarmCategory.informational,
}


@dataclass(frozen=True)
class AlarmFrame:
    frame_index: int
    timestamp: datetime
    flag_hi: int
    flag_lo: int
    category: AlarmCategory
    alarm_sub_id: int | None
    message: str


class AlarmParseError(ValueError):
    pass


def _clean_alarm_message(raw: bytes) -> str:
    msg = raw.split(b"\x00", 1)[0]
    text = msg.decode("ascii", errors="ignore").strip()
    while text and not text[0].isalnum() and text[0] not in {"[", "]", "(" , ")"}:
        text = text[1:]
    return text


def parse_alarm_frames(data_bytes: bytes, parsed_index: ParsedIndex) -> list[AlarmFrame]:
    if len(data_bytes) % FRAME_SIZE != 0:
        raise AlarmParseError("Alarm data file size is not aligned to 124-byte frames")

    frame_count = len(data_bytes) // FRAME_SIZE
    if frame_count != len(parsed_index.entries):
        raise AlarmParseError(
            f"Alarm frame count ({frame_count}) does not match index entries ({len(parsed_index.entries)})"
        )

    alarms: list[AlarmFrame] = []

    for i in range(frame_count):
        frame_start = i * FRAME_SIZE
        frame = data_bytes[frame_start : frame_start + FRAME_SIZE]

        flag_lo = frame[0]
        flag_hi = frame[1]
        alarm_sub_id = frame[25] if len(frame) > 25 else None
        message = _clean_alarm_message(frame[26:122])

        category = CATEGORY_MAP.get((flag_hi, flag_lo), AlarmCategory.informational)

        alarms.append(
            AlarmFrame(
                frame_index=i,
                timestamp=parsed_index.entries[i].timestamp_utc,
                flag_hi=flag_hi,
                flag_lo=flag_lo,
                category=category,
                alarm_sub_id=alarm_sub_id,
                message=message,
            )
        )

    return alarms