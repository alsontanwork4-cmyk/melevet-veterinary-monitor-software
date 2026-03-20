from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import AuditLog


@dataclass(frozen=True)
class AuditPage:
    items: list[AuditLog]
    total: int


def resolve_actor_from_request(request: Request) -> str:
    auth_context = getattr(request.state, "auth_context", None)
    user = getattr(auth_context, "user", None)
    username = getattr(user, "username", None)
    if isinstance(username, str) and username.strip():
        return username.strip()
    return "local-app" if settings.is_local_app else "system"


def log_audit_event(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: int | str,
    actor: str,
    details: dict[str, Any] | None = None,
    commit: bool = False,
) -> AuditLog:
    entry = AuditLog(
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        actor=actor.strip() or ("local-app" if settings.is_local_app else "system"),
        details_json=details or {},
    )
    db.add(entry)
    if commit:
        db.commit()
        db.refresh(entry)
    return entry


def list_audit_logs(
    db: Session,
    *,
    limit: int,
    offset: int,
    entity_type: str | None = None,
) -> AuditPage:
    conditions = []
    normalized_entity_type = entity_type.strip().lower() if entity_type else None
    if normalized_entity_type:
        conditions.append(func.lower(AuditLog.entity_type) == normalized_entity_type)

    count_stmt = select(func.count(AuditLog.id))
    if conditions:
        count_stmt = count_stmt.where(*conditions)

    stmt = select(AuditLog).order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()).offset(offset).limit(limit)
    if conditions:
        stmt = stmt.where(*conditions)

    return AuditPage(
        items=list(db.scalars(stmt)),
        total=int(db.scalar(count_stmt) or 0),
    )
