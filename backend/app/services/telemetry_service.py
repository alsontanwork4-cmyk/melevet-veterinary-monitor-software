from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

from ..config import APP_VERSION, settings
from ..schemas import TelemetryEventIn, TelemetryStatusOut


ALLOWED_METADATA_KEYS = {
    "boundary",
    "context",
    "feature",
    "screen",
}


def _events_path() -> Path:
    return settings.telemetry_dir_path / "events.ndjson"


def _crashes_path() -> Path:
    return settings.telemetry_dir_path / "crashes.ndjson"


def _line_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for _ in handle)


def _append_ndjson(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")))
        handle.write("\n")


def sanitize_event(payload: TelemetryEventIn) -> dict[str, Any]:
    event_type = payload.event_type.strip().lower()
    if not event_type:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="event_type is required.")

    metadata = {
        key: value
        for key, value in payload.metadata.items()
        if key in ALLOWED_METADATA_KEYS and (isinstance(value, (str, int, float, bool)) or value is None)
    }

    return {
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "event_type": event_type,
        "action_name": payload.action_name,
        "route": payload.route,
        "status": payload.status,
        "duration_ms": payload.duration_ms,
        "count": payload.count,
        "app_version": payload.app_version or APP_VERSION,
        "browser": _truncate(payload.browser, 256),
        "platform": _truncate(payload.platform, 256),
        "error_name": _truncate(payload.error_name, 128),
        "error_message": _truncate(payload.error_message, 2000),
        "stack": _sanitize_stack(payload.stack),
        "component_stack": _sanitize_stack(payload.component_stack),
        "metadata": metadata,
    }


def record_event(payload: TelemetryEventIn) -> None:
    sanitized = sanitize_event(payload)
    event_type = str(sanitized["event_type"])
    is_crash = event_type == "crash"
    if not settings.usage_reporting_enabled and not is_crash:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usage reporting is disabled.")

    _append_ndjson(_crashes_path() if is_crash else _events_path(), sanitized)


def get_telemetry_status() -> TelemetryStatusOut:
    events_path = _events_path()
    crashes_path = _crashes_path()
    return TelemetryStatusOut(
        usage_reporting_enabled=settings.usage_reporting_enabled,
        queued_event_count=_line_count(events_path),
        queued_size_bytes=events_path.stat().st_size if events_path.exists() else 0,
        crash_event_count=_line_count(crashes_path),
        crash_size_bytes=crashes_path.stat().st_size if crashes_path.exists() else 0,
    )


def export_telemetry_path() -> Path:
    path = _events_path()
    if not path.exists():
        raise FileNotFoundError("events.ndjson")
    return path


def _truncate(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized[:limit] if normalized else None


def _sanitize_stack(value: str | None) -> str | None:
    if value is None:
        return None
    lines = [line.strip() for line in value.splitlines()[:40] if line.strip()]
    if not lines:
        return None
    return "\n".join(line[:300] for line in lines)
