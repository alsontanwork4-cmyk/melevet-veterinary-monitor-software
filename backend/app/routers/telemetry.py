from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from ..config import settings
from ..schemas import TelemetryEventIn, TelemetryStatusOut
from ..services.auth_service import enforce_csrf, require_active_user
from ..services.telemetry_service import export_telemetry_path, get_telemetry_status, record_event


router = APIRouter(tags=["telemetry"])
protected_dependencies = [] if settings.is_local_app else [Depends(require_active_user), Depends(enforce_csrf)]


@router.post("/telemetry/events", status_code=202)
def ingest_telemetry_event(payload: TelemetryEventIn) -> dict[str, bool]:
    record_event(payload)
    return {"accepted": True}


@router.get("/telemetry/status", response_model=TelemetryStatusOut, dependencies=protected_dependencies)
def read_telemetry_status() -> TelemetryStatusOut:
    return get_telemetry_status()


@router.get("/telemetry/export", dependencies=protected_dependencies)
def download_telemetry_export() -> FileResponse:
    try:
        path = export_telemetry_path()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Telemetry export not found") from exc
    return FileResponse(path, filename=path.name, media_type="application/x-ndjson")
