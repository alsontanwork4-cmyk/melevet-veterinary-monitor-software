from __future__ import annotations

from fastapi import APIRouter

from ..schemas import UpdateStatusOut
from ..services.update_check_service import get_update_status


router = APIRouter(tags=["updates"])


@router.get("/update-status", response_model=UpdateStatusOut)
def read_update_status() -> UpdateStatusOut:
    return UpdateStatusOut(**get_update_status())
