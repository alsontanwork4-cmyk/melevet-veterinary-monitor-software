from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import DatabaseStatsOut
from ..services.settings_service import get_database_stats


router = APIRouter(tags=["database"])


@router.get("/database/stats", response_model=DatabaseStatsOut)
def read_database_stats(db: Session = Depends(get_db)) -> DatabaseStatsOut:
    return get_database_stats(db)
