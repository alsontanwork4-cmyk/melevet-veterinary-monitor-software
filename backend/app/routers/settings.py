from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import AppSettingsOut, AppSettingsUpdate, DatabaseDiagnostics
from ..services.settings_service import get_database_diagnostics, get_settings, update_settings


router = APIRouter(tags=["settings"])


@router.get("/settings", response_model=AppSettingsOut)
def read_settings() -> AppSettingsOut:
    return get_settings()


@router.patch("/settings", response_model=AppSettingsOut)
def patch_settings(payload: AppSettingsUpdate) -> AppSettingsOut:
    return update_settings(payload)


@router.get("/settings/diagnostics", response_model=DatabaseDiagnostics)
def read_database_diagnostics(db: Session = Depends(get_db)) -> DatabaseDiagnostics:
    return get_database_diagnostics(db)
