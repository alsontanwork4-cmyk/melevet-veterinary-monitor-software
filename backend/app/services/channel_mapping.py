from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from ..config import settings


@lru_cache(maxsize=1)
def load_channel_map() -> dict[str, dict[str, dict[str, str | None]]]:
    path = settings.channel_map_file_path

    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        return {}
    return data


def resolve_channel_metadata(
    source_type: str,
    channel_index: int,
    default_name: str,
    default_unit: str | None = None,
) -> tuple[str, str | None]:
    channel_map = load_channel_map()
    source = channel_map.get(source_type, {}) if isinstance(channel_map, dict) else {}

    record: dict[str, str | None] = {}
    if isinstance(source, dict):
        byte_offset = channel_index * 2
        candidate_keys = (str(channel_index), f"o{byte_offset}")

        for key in candidate_keys:
            candidate = source.get(key)
            if isinstance(candidate, dict):
                record = candidate
                break

    name = record.get("name") if isinstance(record, dict) else None
    unit = record.get("unit") if isinstance(record, dict) else None

    return (name or default_name, unit if unit is not None else default_unit)
