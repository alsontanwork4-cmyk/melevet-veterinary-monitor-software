from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import EncounterOut, StagedEncounterCreate, StagedUploadDeleteResponse, StagedUploadOut
from ..services.audit_service import resolve_actor_from_request
from ..services.staged_upload_service import (
    create_staged_upload,
    delete_staged_upload,
    get_staged_upload,
    process_staged_upload,
    save_staged_upload_as_encounter,
)
from ..services.write_coordinator import exclusive_write


router = APIRouter(tags=["staged-uploads"])
STAGED_SAVE_BUSY_DETAIL = "Patient delete or upload persistence is in progress. Please retry saving this staged upload."


def _validate_pair_presence(
    *,
    pair_name: str,
    data_present: bool,
    index_present: bool,
    data_field: str,
    index_field: str,
) -> None:
    if data_present != index_present:
        raise HTTPException(
            status_code=400,
            detail=f"{pair_name} files must be uploaded together: {data_field} + {index_field}",
        )


def _map_save_error(exc: ValueError) -> HTTPException:
    detail = str(exc)
    if detail == "Patient not found":
        return HTTPException(status_code=404, detail=detail)
    if detail == "Staged upload is missing patient information":
        return HTTPException(status_code=400, detail=detail)
    if detail in {
        "Staged upload is not ready to save",
        "Selected encounter date is not available in this staged upload",
        "Selected encounter date has no trend rows to save",
    }:
        return HTTPException(status_code=409, detail=detail)
    return HTTPException(status_code=400, detail=detail)


@router.post("/staged-uploads", response_model=StagedUploadOut, status_code=202)
async def create_stage(
    background_tasks: BackgroundTasks,
    trend_data: UploadFile = File(...),
    trend_index: UploadFile | None = File(default=None),
    nibp_data: UploadFile | None = File(default=None),
    nibp_index: UploadFile | None = File(default=None),
    patient_id: int | None = Form(default=None),
    patient_id_code: str | None = Form(default=None),
    patient_name: str | None = Form(default=None),
    patient_species: str | None = Form(default=None),
    timezone: str = Form(default="UTC"),
    db: Session = Depends(get_db),
):
    _validate_pair_presence(
        pair_name="Nibp",
        data_present=nibp_data is not None,
        index_present=nibp_index is not None,
        data_field="nibp_data",
        index_field="nibp_index",
    )
    if patient_id is None and (not patient_id_code or not patient_name or not patient_species):
        raise HTTPException(
            status_code=400,
            detail="Provide either patient_id or patient_id_code + patient_name + patient_species",
        )

    staged_upload = await create_staged_upload(
        db,
        trend_data=trend_data,
        trend_index=trend_index,
        nibp_data=nibp_data,
        nibp_index=nibp_index,
        patient_id=patient_id,
        patient_id_code=patient_id_code,
        patient_name=patient_name,
        patient_species=patient_species,
        timezone_name=timezone,
    )
    background_tasks.add_task(process_staged_upload, staged_upload["stage_id"])
    return staged_upload


@router.get("/staged-uploads/{stage_id}", response_model=StagedUploadOut)
def read_stage(stage_id: str):
    try:
        return get_staged_upload(stage_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Staged upload not found") from exc


@router.delete("/staged-uploads/{stage_id}", response_model=StagedUploadDeleteResponse)
def remove_stage(stage_id: str):
    deleted = delete_staged_upload(stage_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Staged upload not found")
    return StagedUploadDeleteResponse(deleted=True, stage_id=stage_id)


@router.post("/staged-uploads/{stage_id}/encounters", response_model=EncounterOut)
def create_stage_encounter(
    stage_id: str,
    payload: StagedEncounterCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    with exclusive_write("staged upload save", wait=False, busy_detail=STAGED_SAVE_BUSY_DETAIL):
        try:
            return save_staged_upload_as_encounter(
                db,
                stage_id=stage_id,
                encounter_date_local=payload.encounter_date_local,
                timezone_name=payload.timezone,
                label=payload.label,
                notes=payload.notes,
                actor=resolve_actor_from_request(request),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Staged upload not found") from exc
        except ValueError as exc:
            raise _map_save_error(exc) from exc
