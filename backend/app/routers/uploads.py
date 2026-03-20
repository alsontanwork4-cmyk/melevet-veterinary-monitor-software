from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Channel, Encounter, Patient, RecordingPeriod, Segment, Upload, UploadStatus
from ..schemas import (
    DiscoveryResponse,
    PaginatedNibpEventList,
    UploadDeleteResponse,
    UploadOut,
    UploadResponse,
)
from ..services.audit_service import resolve_actor_from_request
from ..services.encounter_service import refresh_upload_detected_local_dates
from ..services.patient_service import create_patient_record
from ..services.upload_maintenance_service import run_opportunistic_maintenance
from ..services.upload_security import cleanup_upload_dir, create_upload_spool_dir, store_upload_file
from ..services.chart_service import list_nibp_events_page
from ..services.upload_service import (
    DuplicateUploadError,
    EMPTY_SHA256,
    UploadComponentHashes,
    build_combined_hash_from_component_hashes,
    create_upload_record_from_component_hashes,
    delete_upload_record,
    fail_stale_upload_if_needed,
    find_reusable_upload,
    process_upload_background_from_spool,
)
from ..services.write_coordinator import exclusive_write


router = APIRouter(tags=["uploads"])
UPLOAD_WRITE_BUSY_DETAIL = "Upload or delete work is already in progress. Please retry in a moment."


def _validate_pair_presence(
    *,
    pair_name: str,
    data_present: bool,
    index_present: bool,
    data_field: str,
    index_field: str,
    required: bool,
) -> None:
    if required and (not data_present or not index_present):
        raise HTTPException(
            status_code=400,
            detail=f"{pair_name} files are required: {data_field} + {index_field}",
        )
    if data_present != index_present:
        raise HTTPException(
            status_code=400,
            detail=f"{pair_name} files must be uploaded together: {data_field} + {index_field}",
        )


async def _spool_upload_bundle(
    *,
    trend_data: UploadFile,
    trend_index: UploadFile | None,
    nibp_data: UploadFile | None,
    nibp_index: UploadFile | None,
) -> tuple[str, UploadComponentHashes]:
    spool_dir = create_upload_spool_dir(prefix="direct-upload-")
    total_bytes = 0
    try:
        trend_data_file, total_bytes = await store_upload_file(
            field_name="trend_data",
            upload_file=trend_data,
            destination_dir=spool_dir,
            current_total_bytes=total_bytes,
        )
        trend_index_file, total_bytes = await store_upload_file(
            field_name="trend_index",
            upload_file=trend_index,
            destination_dir=spool_dir,
            current_total_bytes=total_bytes,
        )
        nibp_data_file, total_bytes = await store_upload_file(
            field_name="nibp_data",
            upload_file=nibp_data,
            destination_dir=spool_dir,
            current_total_bytes=total_bytes,
        )
        nibp_index_file, total_bytes = await store_upload_file(
            field_name="nibp_index",
            upload_file=nibp_index,
            destination_dir=spool_dir,
            current_total_bytes=total_bytes,
        )
        if trend_data_file is None:
            raise HTTPException(status_code=400, detail="Trend data file is required: trend_data")

        component_hashes = UploadComponentHashes(
            trend_sha256=trend_data_file.sha256,
            trend_index_sha256=trend_index_file.sha256 if trend_index_file is not None else EMPTY_SHA256,
            nibp_sha256=nibp_data_file.sha256 if nibp_data_file is not None else EMPTY_SHA256,
            nibp_index_sha256=nibp_index_file.sha256 if nibp_index_file is not None else EMPTY_SHA256,
        )
        return str(spool_dir), component_hashes
    except Exception:
        cleanup_upload_dir(spool_dir)
        raise


@router.post("/uploads", response_model=UploadResponse)
async def create_upload(
    background_tasks: BackgroundTasks,
    request: Request,
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
    actor = resolve_actor_from_request(request)
    _validate_pair_presence(
        pair_name="Nibp",
        data_present=nibp_data is not None,
        index_present=nibp_index is not None,
        data_field="nibp_data",
        index_field="nibp_index",
        required=False,
    )
    spool_dir, component_hashes = await _spool_upload_bundle(
        trend_data=trend_data,
        trend_index=trend_index,
        nibp_data=nibp_data,
        nibp_index=nibp_index,
    )
    combined_hash = build_combined_hash_from_component_hashes(component_hashes)

    try:
        reusable_upload = find_reusable_upload(db, combined_hash=combined_hash)
        if reusable_upload is not None:
            cleanup_upload_dir(spool_dir)
            if reusable_upload.status == UploadStatus.completed:
                refresh_upload_detected_local_dates(db, reusable_upload, timezone_name=timezone)
            return UploadResponse(
                upload=reusable_upload,
                patient_id=reusable_upload.patient_id or 0,
                period_count=0,
                segment_count=0,
                channel_count=0,
                reused_existing=True,
                exact_duplicate=True,
            )

        if patient_id is None and (not patient_id_code or not patient_name or not patient_species):
            raise HTTPException(
                status_code=400,
                detail="Provide either patient_id or patient_id_code + patient_name + patient_species",
            )

        with exclusive_write("upload request bootstrap", wait=False, busy_detail=UPLOAD_WRITE_BUSY_DETAIL):
            patient: Patient | None = None
            if patient_id is not None:
                patient = db.get(Patient, patient_id)
                if patient is None:
                    raise HTTPException(status_code=404, detail="Patient not found")
            else:
                patient = db.scalar(select(Patient).where(Patient.patient_id_code == patient_id_code))
                if patient is None:
                    patient = create_patient_record(
                        db,
                        {
                            "patient_id_code": patient_id_code or "",
                            "name": patient_name or "",
                            "species": patient_species or "",
                        },
                        actor=actor,
                    )

            if patient is None:
                raise HTTPException(status_code=500, detail="Patient could not be resolved")

            upload = create_upload_record_from_component_hashes(
                db,
                patient=patient,
                component_hashes=component_hashes,
                actor=actor,
            )
        background_tasks.add_task(
            process_upload_background_from_spool,
            upload_id=upload.id,
            spool_dir=spool_dir,
            timezone_name=timezone,
        )

        return UploadResponse(
            upload=upload,
            patient_id=patient.id,
            period_count=0,
            segment_count=0,
            channel_count=0,
            reused_existing=False,
            exact_duplicate=False,
        )
    except DuplicateUploadError as exc:
        cleanup_upload_dir(spool_dir)
        upload = exc.upload
        if upload.status == UploadStatus.completed:
            refresh_upload_detected_local_dates(db, upload, timezone_name=timezone)
        return UploadResponse(
            upload=upload,
            patient_id=upload.patient_id or 0,
            period_count=0,
            segment_count=0,
            channel_count=0,
            reused_existing=True,
            exact_duplicate=True,
        )
    except Exception:
        cleanup_upload_dir(spool_dir)
        raise


@router.get("/uploads/{upload_id}", response_model=UploadOut)
def get_upload(upload_id: int, db: Session = Depends(get_db)):
    upload = db.get(Upload, upload_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="Upload not found")
    fail_stale_upload_if_needed(db, upload)
    db.refresh(upload)
    return upload


@router.get("/uploads/{upload_id}/discovery", response_model=DiscoveryResponse)
def get_upload_discovery(upload_id: int, db: Session = Depends(get_db)):
    upload = db.get(Upload, upload_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="Upload not found")
    fail_stale_upload_if_needed(db, upload)
    db.refresh(upload)
    if upload.status != UploadStatus.completed:
        raise HTTPException(status_code=409, detail="Upload is not completed yet")

    channels = db.scalars(
        select(Channel)
        .where(Channel.upload_id == upload_id)
        .order_by(Channel.valid_count.desc(), Channel.source_type.asc(), Channel.channel_index.asc())
    ).all()
    periods = db.scalars(select(RecordingPeriod).where(RecordingPeriod.upload_id == upload_id)).all()
    segments = db.scalars(select(Segment).where(Segment.upload_id == upload_id)).all()

    return DiscoveryResponse(
        upload_id=upload_id,
        trend_frames=upload.trend_frames,
        nibp_frames=upload.nibp_frames,
        periods=len(periods),
        segments=len(segments),
        channels=list(channels),
        detected_local_dates=list(upload.detected_local_dates or []),
        archived_at=upload.archived_at,
        archive_id=upload.archive_id,
    )


@router.get("/uploads/{upload_id}/nibp-events", response_model=PaginatedNibpEventList)
def get_upload_nibp_events(
    upload_id: int,
    segment_id: int | None = Query(default=None),
    measurements_only: bool = Query(default=False),
    from_ts: datetime | None = Query(default=None),
    to_ts: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    result = list_nibp_events_page(
        db,
        upload_id=upload_id,
        segment_id=segment_id,
        measurements_only=measurements_only,
        from_ts=from_ts,
        to_ts=to_ts,
        limit=limit,
        offset=offset,
    )
    return PaginatedNibpEventList(items=result.items, total=result.total, limit=limit, offset=offset)


@router.delete("/uploads/{upload_id}", response_model=UploadDeleteResponse)
def delete_upload(upload_id: int, request: Request, db: Session = Depends(get_db)):
    response: UploadDeleteResponse | None = None
    with exclusive_write("upload delete", wait=False, busy_detail=UPLOAD_WRITE_BUSY_DETAIL):
        upload = db.get(Upload, upload_id)
        if upload is None:
            raise HTTPException(status_code=404, detail="Upload not found")

        encounter_count = db.scalar(select(Encounter).where(Encounter.upload_id == upload_id).limit(1))
        if encounter_count is not None:
            raise HTTPException(status_code=409, detail="Cannot delete a snapshot that is linked to encounters")

        delete_upload_record(db, upload, actor=resolve_actor_from_request(request))
        response = UploadDeleteResponse(deleted=True, upload_id=upload_id)

    run_opportunistic_maintenance(bind=db.get_bind())
    return response or UploadDeleteResponse(deleted=True, upload_id=upload_id)
