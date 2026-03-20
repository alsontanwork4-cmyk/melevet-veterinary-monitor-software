from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Measurement, Upload, UploadMeasurementLink, UploadNibpEventLink, NibpEvent
from ..schemas import AppSettingsOut, AppSettingsUpdate, DatabaseDiagnostics, DatabaseStatsOut, SpeciesVitalThresholds


SAFE_RUNTIME_SETTING_FIELDS = (
    "archive_retention_days",
    "link_table_warning_threshold",
    "log_level",
    "orphan_upload_retention_days",
    "segment_gap_seconds",
    "recording_period_gap_seconds",
    "usage_reporting_enabled",
)
VITAL_THRESHOLDS_FIELD = "vital_thresholds"
THRESHOLD_METRICS = (
    "spo2",
    "heart_rate",
    "nibp_systolic",
    "nibp_map",
    "nibp_diastolic",
)
ALLOWED_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}
SETTINGS_FILENAME = "settings.json"
logger = logging.getLogger(__name__)


def settings_file_path() -> Path:
    return settings.data_root_path / SETTINGS_FILENAME


def _default_settings_payload() -> dict[str, Any]:
    return {
        "archive_retention_days": settings.archive_retention_days,
        "link_table_warning_threshold": settings.link_table_warning_threshold,
        "log_level": settings.log_level,
        "orphan_upload_retention_days": settings.orphan_upload_retention_days,
        "segment_gap_seconds": settings.segment_gap_seconds,
        "recording_period_gap_seconds": settings.recording_period_gap_seconds,
        "usage_reporting_enabled": settings.usage_reporting_enabled,
        VITAL_THRESHOLDS_FIELD: {},
    }


def _normalize_log_level(value: str) -> str:
    normalized = value.strip().upper()
    if normalized not in ALLOWED_LOG_LEVELS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="log_level must be one of DEBUG, INFO, WARNING, or ERROR.",
        )
    return normalized


def _validate_runtime_settings_payload(payload: dict[str, Any]) -> dict[str, int | str | bool | None]:
    archive_retention_days = payload.get("archive_retention_days")
    link_table_warning_threshold = int(payload["link_table_warning_threshold"])
    orphan_upload_retention_days = int(payload["orphan_upload_retention_days"])
    segment_gap_seconds = int(payload["segment_gap_seconds"])
    recording_period_gap_seconds = int(payload["recording_period_gap_seconds"])
    usage_reporting_enabled = bool(payload.get("usage_reporting_enabled", False))

    normalized_archive_retention_days: int | None = None
    if archive_retention_days is not None:
        normalized_archive_retention_days = int(archive_retention_days)
        if normalized_archive_retention_days < 1:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="archive_retention_days must be at least 1.")

    if link_table_warning_threshold < 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="link_table_warning_threshold must be at least 1.",
        )
    if orphan_upload_retention_days < 1:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="orphan_upload_retention_days must be at least 1.")
    if segment_gap_seconds < 60:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="segment_gap_seconds must be at least 60.")
    if recording_period_gap_seconds < 60:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="recording_period_gap_seconds must be at least 60.")

    return {
        "archive_retention_days": normalized_archive_retention_days,
        "link_table_warning_threshold": link_table_warning_threshold,
        "log_level": _normalize_log_level(str(payload["log_level"])),
        "orphan_upload_retention_days": orphan_upload_retention_days,
        "segment_gap_seconds": segment_gap_seconds,
        "recording_period_gap_seconds": recording_period_gap_seconds,
        "usage_reporting_enabled": usage_reporting_enabled,
    }


def _normalize_threshold_bound(value: Any, *, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{field_name} must be numeric.")
    if isinstance(value, (int, float)):
        number = float(value)
        if number <= 0:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{field_name} must be greater than 0.")
        return number
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{field_name} must be numeric.")


def _validate_vital_thresholds(payload: Any) -> dict[str, dict[str, dict[str, float | None]]]:
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="vital_thresholds must be an object.")

    normalized: dict[str, dict[str, dict[str, float | None]]] = {}
    for raw_species, raw_thresholds in payload.items():
        species = str(raw_species).strip()
        if not species:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Species names cannot be empty.")
        if not isinstance(raw_thresholds, dict):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Thresholds for {species} must be an object.")

        normalized_species: dict[str, dict[str, float | None]] = {}
        for metric_name in THRESHOLD_METRICS:
            raw_range = raw_thresholds.get(metric_name) or {}
            if not isinstance(raw_range, dict):
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{species} {metric_name} thresholds must be an object.")
            low = _normalize_threshold_bound(raw_range.get("low"), field_name=f"{species} {metric_name} low")
            high = _normalize_threshold_bound(raw_range.get("high"), field_name=f"{species} {metric_name} high")
            if low is not None and high is not None and low >= high:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"{species} {metric_name} low threshold must be below the high threshold.",
                )
            normalized_species[metric_name] = {"low": low, "high": high}
        normalized[species] = normalized_species
    return normalized


def load_persisted_settings() -> dict[str, Any]:
    path = settings_file_path()
    payload = _default_settings_payload()
    if not path.exists():
        return payload

    with path.open("r", encoding="utf-8") as handle:
        raw_payload = json.load(handle)
    if not isinstance(raw_payload, dict):
        raise RuntimeError(f"Settings file must contain a JSON object: {path}")

    for key in SAFE_RUNTIME_SETTING_FIELDS:
        if key in raw_payload:
            payload[key] = raw_payload[key]
    payload[VITAL_THRESHOLDS_FIELD] = raw_payload.get(VITAL_THRESHOLDS_FIELD, {})

    validated_runtime = _validate_runtime_settings_payload(payload)
    validated_runtime[VITAL_THRESHOLDS_FIELD] = _validate_vital_thresholds(payload.get(VITAL_THRESHOLDS_FIELD))
    return validated_runtime


def get_settings() -> AppSettingsOut:
    payload = load_persisted_settings()
    return AppSettingsOut(**payload)


def update_settings(update: AppSettingsUpdate) -> AppSettingsOut:
    current = load_persisted_settings()
    update_payload = update.model_dump(exclude_unset=True)
    for key, value in update_payload.items():
        current[key] = value

    validated = _validate_runtime_settings_payload(current)
    validated[VITAL_THRESHOLDS_FIELD] = _validate_vital_thresholds(current.get(VITAL_THRESHOLDS_FIELD))
    path = settings_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(validated, handle, indent=2, sort_keys=True)
        handle.write("\n")

    for key in SAFE_RUNTIME_SETTING_FIELDS:
        value = validated[key]
        setattr(settings, key, value)
    logging.getLogger().setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    logger.info("Updated runtime settings: %s", {key: validated[key] for key in SAFE_RUNTIME_SETTING_FIELDS})
    return AppSettingsOut(**validated)


def get_database_diagnostics(db: Session) -> DatabaseDiagnostics:
    database_kind = "other"
    sqlite_file_size_bytes: int | None = None
    database_url = settings.resolved_database_url
    if database_url.startswith("sqlite:///"):
        database_kind = "sqlite"
        database_path = Path(database_url.removeprefix("sqlite:///"))
        if database_path.exists():
            sqlite_file_size_bytes = database_path.stat().st_size

    measurement_count = int(db.scalar(select(func.count(Measurement.id))) or 0)
    upload_measurement_link_count = int(db.scalar(select(func.count(UploadMeasurementLink.id))) or 0)
    upload_nibp_event_link_count = int(db.scalar(select(func.count(UploadNibpEventLink.id))) or 0)
    threshold = int(settings.link_table_warning_threshold)

    return DatabaseDiagnostics(
        database_kind=database_kind,
        sqlite_file_size_bytes=sqlite_file_size_bytes,
        measurement_count=measurement_count,
        upload_measurement_link_count=upload_measurement_link_count,
        upload_nibp_event_link_count=upload_nibp_event_link_count,
        link_table_warning_threshold=threshold,
        upload_measurement_links_over_threshold=upload_measurement_link_count > threshold,
        upload_nibp_event_links_over_threshold=upload_nibp_event_link_count > threshold,
    )


def get_database_stats(db: Session) -> DatabaseStatsOut:
    database_kind = "other"
    sqlite_file_size_bytes: int | None = None
    database_url = settings.resolved_database_url
    if database_url.startswith("sqlite:///"):
        database_kind = "sqlite"
        database_path = Path(database_url.removeprefix("sqlite:///"))
        if database_path.exists():
            sqlite_file_size_bytes = database_path.stat().st_size

    archive_paths = sorted(settings.archive_dir_path.glob("archive-*.zip"))
    archive_sizes = [path.stat().st_size for path in archive_paths if path.exists()]
    archive_mtimes = [path.stat().st_mtime for path in archive_paths if path.exists()]

    oldest_archive_at = None
    newest_archive_at = None
    if archive_mtimes:
        oldest_archive_at = datetime.fromtimestamp(min(archive_mtimes), tz=UTC)
        newest_archive_at = datetime.fromtimestamp(max(archive_mtimes), tz=UTC)

    return DatabaseStatsOut(
        database_kind=database_kind,
        sqlite_file_size_bytes=sqlite_file_size_bytes,
        live_measurement_count=int(db.scalar(select(func.count(Measurement.id))) or 0),
        live_nibp_event_count=int(db.scalar(select(func.count(NibpEvent.id))) or 0),
        archived_upload_count=int(db.scalar(select(func.count(Upload.id)).where(Upload.archived_at.is_not(None))) or 0),
        archive_file_count=len(archive_paths),
        archive_total_size_bytes=sum(archive_sizes),
        oldest_archive_at=oldest_archive_at,
        newest_archive_at=newest_archive_at,
    )
