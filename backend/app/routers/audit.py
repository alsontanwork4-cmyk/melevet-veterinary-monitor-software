from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import PaginatedAuditLog
from ..services.audit_service import list_audit_logs


router = APIRouter(tags=["audit-log"])


@router.get("/audit-log", response_model=PaginatedAuditLog)
def get_audit_log(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    entity_type: Annotated[str | None, Query()] = None,
    db: Session = Depends(get_db),
) -> PaginatedAuditLog:
    page = list_audit_logs(db, limit=limit, offset=offset, entity_type=entity_type)
    return PaginatedAuditLog(items=list(page.items), total=page.total)
