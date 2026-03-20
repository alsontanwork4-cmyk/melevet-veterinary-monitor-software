from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from ..schemas import ArchiveOut, ArchiveRunResponse
from ..services.archive_service import archive_file_path, list_archives, run_archival
from ..services.audit_service import resolve_actor_from_request
from ..services.write_coordinator import exclusive_write
from ..database import SessionLocal


router = APIRouter(tags=["archives"])
ARCHIVE_BUSY_DETAIL = "Archive work is already in progress. Please retry in a moment."


@router.get("/archives", response_model=list[ArchiveOut])
def get_archives() -> list[ArchiveOut]:
    return list_archives()


@router.post("/archives/run", response_model=ArchiveRunResponse)
def trigger_archival(request: Request) -> ArchiveRunResponse:
    with exclusive_write("archive run", wait=False, busy_detail=ARCHIVE_BUSY_DETAIL):
        with SessionLocal() as db:
            archives = run_archival(db, actor=resolve_actor_from_request(request))
    return ArchiveRunResponse(archived_upload_count=len(archives), archives=archives)


@router.get("/archives/{archive_id}/download")
def download_archive(archive_id: str) -> FileResponse:
    try:
        path = archive_file_path(archive_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Archive not found") from exc
    return FileResponse(path, filename=path.name, media_type="application/zip")
