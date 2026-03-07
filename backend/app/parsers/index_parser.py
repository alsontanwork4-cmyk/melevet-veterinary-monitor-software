from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


INDEX_HEADER_SIZE = 16
INDEX_TRAILER_SIZE = 6
INDEX_ENTRY_SIZE = 16
FRAME_SIZE = 124


@dataclass(frozen=True)
class IndexHeader:
    version: int
    buffer_size: int
    payload_size: int
    padding: int


@dataclass(frozen=True)
class IndexEntry:
    frame_index: int
    flags: int
    ptr: int
    ts_lo: int
    ts_hi: int
    unix_seconds: int
    timestamp_utc: datetime


@dataclass(frozen=True)
class ParsedIndex:
    header: IndexHeader
    entries: list[IndexEntry]
    trailer: bytes
    rollback_indices: list[int]


class IndexParseError(ValueError):
    pass


def decode_unix_seconds(ts_lo: int, ts_hi: int) -> int:
    return ((ts_hi & 0x0000FFFF) << 16) | (ts_lo >> 16)


def parse_index_bytes(
    index_bytes: bytes,
    data_bytes: bytes | None = None,
    *,
    require_monotonic: bool = True,
) -> ParsedIndex:
    if len(index_bytes) < (INDEX_HEADER_SIZE + INDEX_TRAILER_SIZE):
        raise IndexParseError("Index file is too small")

    payload_length = len(index_bytes) - INDEX_HEADER_SIZE - INDEX_TRAILER_SIZE
    if payload_length < 0 or payload_length % INDEX_ENTRY_SIZE != 0:
        raise IndexParseError("Index payload is not aligned to 16-byte entries")

    version = int.from_bytes(index_bytes[0:4], "little")
    buffer_size = int.from_bytes(index_bytes[4:8], "little")
    payload_size = int.from_bytes(index_bytes[8:12], "little")
    padding = int.from_bytes(index_bytes[12:16], "little")
    header = IndexHeader(
        version=version,
        buffer_size=buffer_size,
        payload_size=payload_size,
        padding=padding,
    )

    entry_count = payload_length // INDEX_ENTRY_SIZE
    entries: list[IndexEntry] = []

    offset = INDEX_HEADER_SIZE
    previous_ts: datetime | None = None
    rollback_indices: list[int] = []
    for frame_index in range(entry_count):
        chunk = index_bytes[offset : offset + INDEX_ENTRY_SIZE]
        flags = int.from_bytes(chunk[0:4], "little")
        ptr = int.from_bytes(chunk[4:8], "little")
        ts_lo = int.from_bytes(chunk[8:12], "little")
        ts_hi = int.from_bytes(chunk[12:16], "little")

        unix_seconds = decode_unix_seconds(ts_lo=ts_lo, ts_hi=ts_hi)
        timestamp_utc = datetime.fromtimestamp(unix_seconds, tz=UTC)

        if previous_ts is not None and timestamp_utc < previous_ts:
            if require_monotonic:
                raise IndexParseError(
                    f"Index timestamps are not monotonic at entry {frame_index}: "
                    f"{timestamp_utc.isoformat()} < {previous_ts.isoformat()}"
                )
            rollback_indices.append(frame_index)

        entries.append(
            IndexEntry(
                frame_index=frame_index,
                flags=flags,
                ptr=ptr,
                ts_lo=ts_lo,
                ts_hi=ts_hi,
                unix_seconds=unix_seconds,
                timestamp_utc=timestamp_utc,
            )
        )
        previous_ts = timestamp_utc
        offset += INDEX_ENTRY_SIZE

    trailer = index_bytes[-INDEX_TRAILER_SIZE:]

    if data_bytes is not None:
        frame_count = len(data_bytes) // FRAME_SIZE
        if len(data_bytes) % FRAME_SIZE != 0:
            raise IndexParseError("Data file size is not aligned to 124-byte frames")
        if frame_count != len(entries):
            raise IndexParseError(
                f"Index entries ({len(entries)}) do not match data frames ({frame_count})"
            )

    return ParsedIndex(
        header=header,
        entries=entries,
        trailer=trailer,
        rollback_indices=rollback_indices,
    )
