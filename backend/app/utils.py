"""Shared utility helpers used across the Melevet backend."""

from __future__ import annotations

from datetime import UTC, datetime

from .constants import CORE_NIBP_CHANNELS
from .parsers.nibp_parser import infer_nibp_measurement, nibp_channel_name
from .services.channel_mapping import resolve_channel_metadata


def utcnow() -> datetime:
    """Return the current UTC time as an aware datetime."""
    return datetime.now(UTC)


def coerce_utc(dt: datetime) -> datetime:
    """Ensure *dt* is a UTC-aware datetime."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def coerce_utc_naive(dt: datetime | None) -> datetime | None:
    """Ensure *dt* is a UTC datetime with tzinfo stripped (naive).

    Returns ``None`` when *dt* is ``None``.
    Useful for SQLAlchemy datetime comparisons against naive-stored columns.
    """
    if dt is None:
        return None
    return coerce_utc(dt).replace(tzinfo=None)


def normalize_dedup_timestamp(value: datetime | str) -> str:
    """Normalise a timestamp to the canonical dedup-key string form.

    Accepts both ``datetime`` objects and ISO-8601 strings (with or without
    a trailing ``Z``).  Returns an ISO-8601 UTC string with a trailing ``Z``.
    """
    if isinstance(value, datetime):
        timestamp = value
    elif isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        timestamp = datetime.fromisoformat(normalized)
    else:
        raise TypeError(f"Unsupported timestamp value for dedup key: {type(value)!r}")

    return coerce_utc(timestamp).isoformat().replace("+00:00", "Z")


def resolve_core_channel_metadata(
    *,
    source_type: str,
    channel_index: int,
    fallback_name: str,
    fallback_unit: str | None,
) -> tuple[str, str | None]:
    """Resolve the display name and unit for a core channel.

    Delegates to the channel-mapping service, falling back to the provided
    defaults if no mapping is configured.
    """
    return resolve_channel_metadata(
        source_type=source_type if isinstance(source_type, str) else source_type.value,
        channel_index=channel_index,
        default_name=fallback_name,
        default_unit=fallback_unit,
    )


def _normalize_positive_int(value: object) -> int | None:
    """Coerce *value* to a positive ``int``, or return ``None``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float) and value.is_integer():
        integer = int(value)
        return integer if integer > 0 else None
    return None


def trim_nibp_channel_values(
    channel_values: dict[str, int | None],
) -> tuple[dict[str, int | None], bool]:
    """Trim an NIBP channel-values dict to only the core inferred fields.

    Returns ``(trimmed_dict, has_measurement)`` where *has_measurement* is
    ``True`` when at least one of the core values is non-``None``.
    """
    inferred_values = infer_nibp_measurement(channel_values)
    trimmed: dict[str, int | None] = {}

    for channel_index, (fallback_name, _fallback_unit) in CORE_NIBP_CHANNELS.items():
        value = _normalize_positive_int(inferred_values.get(fallback_name))
        if value is None:
            value = _normalize_positive_int(channel_values.get(fallback_name))
        if value is None:
            value = _normalize_positive_int(
                channel_values.get(nibp_channel_name(channel_index))
            )
        trimmed[fallback_name] = value

    has_measurement = any(value is not None for value in trimmed.values())
    return trimmed, has_measurement
