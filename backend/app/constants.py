"""Shared constants used across the Melevet backend."""

from __future__ import annotations

from .parsers.nibp_parser import (
    DIASTOLIC_CHANNEL_INDEX,
    MEAN_CHANNEL_INDEX,
    SYSTOLIC_CHANNEL_INDEX,
)

# Maps channel index → (canonical_name, unit) for the core trend channels
# retained after compaction.
CORE_TREND_CHANNELS: dict[int, tuple[str, str | None]] = {
    14: ("spo2_be_u16", "%"),
    16: ("heart_rate_be_u16", "bpm"),
}

# Maps channel index → (canonical_name, unit) for the core NIBP channels.
CORE_NIBP_CHANNELS: dict[int, tuple[str, str | None]] = {
    SYSTOLIC_CHANNEL_INDEX: ("bp_systolic_inferred", "mmHg"),
    MEAN_CHANNEL_INDEX: ("bp_mean_inferred", "mmHg"),
    DIASTOLIC_CHANNEL_INDEX: ("bp_diastolic_inferred", "mmHg"),
}

CORE_NIBP_VALUE_KEYS: tuple[str, ...] = tuple(
    name for name, _ in CORE_NIBP_CHANNELS.values()
)
