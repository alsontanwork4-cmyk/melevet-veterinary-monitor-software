from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..config import APP_VERSION, settings


logger = logging.getLogger(__name__)
_cache_lock = Lock()
_cache: dict[str, Any] | None = None
_SEMVER_PATTERN = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")


def _parse_semver(value: str | None) -> tuple[int, int, int] | None:
    if not value:
        return None
    match = _SEMVER_PATTERN.match(value.strip())
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())


def _is_update_available(current_version: str, latest_version: str | None) -> bool:
    current = _parse_semver(current_version)
    latest = _parse_semver(latest_version)
    if current is None or latest is None:
        return False
    return latest > current


def _now() -> datetime:
    return datetime.now(UTC)


def _is_stale(cache: dict[str, Any] | None) -> bool:
    if cache is None:
        return True
    checked_at = cache.get("checked_at")
    if not isinstance(checked_at, datetime):
        return True
    return _now() - checked_at >= timedelta(hours=max(1, settings.update_check_interval_hours))


def _default_status() -> dict[str, Any]:
    return {
        "current_version": APP_VERSION,
        "latest_version": None,
        "download_url": None,
        "release_url": None,
        "checked_at": None,
        "is_update_available": False,
        "error": None,
    }


def _fetch_latest_release() -> dict[str, Any]:
    url = f"{settings.update_check_api_base.rstrip('/')}/repos/{settings.update_check_repo}/releases/latest"
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"Melevet/{APP_VERSION}",
        },
    )
    with urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return {
        "latest_version": payload.get("tag_name") or payload.get("name"),
        "download_url": payload.get("html_url"),
        "release_url": payload.get("html_url"),
    }


def refresh_update_status(*, force: bool = False) -> dict[str, Any]:
    global _cache
    with _cache_lock:
        if not settings.update_check_enabled:
            _cache = _default_status()
            return dict(_cache)

        if not force and not _is_stale(_cache):
            return dict(_cache or _default_status())

        status = _default_status()
        try:
            release = _fetch_latest_release()
            status.update(release)
            status["is_update_available"] = _is_update_available(APP_VERSION, release.get("latest_version"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            logger.warning("Update check failed: %s", exc)
            status["error"] = str(exc)
        status["checked_at"] = _now()
        _cache = status
        return dict(status)


def get_update_status() -> dict[str, Any]:
    return refresh_update_status(force=False)
