from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Channel, Encounter, Patient, RecordingPeriod, Segment, Upload, UploadStatus
from ..schemas import DiscoveryResponse, UploadDeleteResponse, UploadOut, UploadResponse
from ..services.encounter_service import refresh_upload_detected_local_dates
from ..services.patient_service import prune_orphaned_canonical_rows
from ..services.upload_service import (
    DuplicateUploadError,
    build_combined_hash,
    create_upload_stub,
    fail_stale_upload_if_needed,
    find_reusable_upload,
    process_upload_background,
)


router = APIRouter(tags=["uploads"])


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


async def _read_uploaded_file(file: UploadFile | None, fallback_name: str) -> bytes | None:
    if file is None:
        return None
    payload = await file.read()
    filename = file.filename or fallback_name
    if not payload:
        raise HTTPException(status_code=400, detail=f"Empty file: {filename}")
    return payload


@router.post("/uploads", response_model=UploadResponse)
async def create_upload(
    background_tasks: BackgroundTasks,
    trend_data: UploadFile = File(...),
    trend_index: UploadFile | None = File(default=None),
    nibp_data: UploadFile | None = File(default=None),
    nibp_index: UploadFile | None = File(default=None),
    alarm_data: UploadFile | None = File(default=None),
    alarm_index: UploadFile | None = File(default=None),
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
        required=False,
    )
    _validate_pair_presence(
        pair_name="Alarm",
        data_present=alarm_data is not None,
        index_present=alarm_index is not None,
        data_field="alarm_data",
        index_field="alarm_index",
        required=False,
    )

    trend_data_bytes = await _read_uploaded_file(trend_data, "trend_data")
    trend_index_bytes = await _read_uploaded_file(trend_index, "trend_index")
    nibp_data_bytes = await _read_uploaded_file(nibp_data, "nibp_data")
    nibp_index_bytes = await _read_uploaded_file(nibp_index, "nibp_index")
    alarm_data_bytes = await _read_uploaded_file(alarm_data, "alarm_data")
    alarm_index_bytes = await _read_uploaded_file(alarm_index, "alarm_index")

    if trend_data_bytes is None:
        raise HTTPException(status_code=400, detail="Trend data file is required: trend_data")

    combined_hash = build_combined_hash(
        trend_data=trend_data_bytes,
        trend_index=trend_index_bytes,
        nibp_data=nibp_data_bytes,
        nibp_index=nibp_index_bytes,
        alarm_data=alarm_data_bytes,
        alarm_index=alarm_index_bytes,
    )

    reusable_upload = find_reusable_upload(db, combined_hash=combined_hash)
    if reusable_upload is not None:
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

    patient: Patient | None = None
    if patient_id is not None:
        patient = db.get(Patient, patient_id)
        if patient is None:
            raise HTTPException(status_code=404, detail="Patient not found")
    else:
        patient = db.scalar(select(Patient).where(Patient.patient_id_code == patient_id_code))
        if patient is None:
            patient = Patient(
                patient_id_code=patient_id_code or "",
                name=patient_name or "",
                species=patient_species or "",
            )
            db.add(patient)
            db.commit()
            db.refresh(patient)

    if patient is None:
        raise HTTPException(status_code=500, detail="Patient could not be resolved")

    try:
        upload = create_upload_stub(
            db,
            patient=patient,
            trend_data=trend_data_bytes,
            trend_index=trend_index_bytes,
            nibp_data=nibp_data_bytes,
            nibp_index=nibp_index_bytes,
            alarm_data=alarm_data_bytes,
            alarm_index=alarm_index_bytes,
            combined_hash=combined_hash,
        )
    except DuplicateUploadError as exc:
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

    background_tasks.add_task(
        process_upload_background,
        upload_id=upload.id,
        trend_data=trend_data_bytes,
        trend_index=trend_index_bytes,
        nibp_data=nibp_data_bytes,
        nibp_index=nibp_index_bytes,
        alarm_data=alarm_data_bytes,
        alarm_index=alarm_index_bytes,
        combined_hash=combined_hash,
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
        alarm_frames=upload.alarm_frames,
        periods=len(periods),
        segments=len(segments),
        channels=list(channels),
        detected_local_dates=list(upload.detected_local_dates or []),
    )


@router.delete("/uploads/{upload_id}", response_model=UploadDeleteResponse)
def delete_upload(upload_id: int, db: Session = Depends(get_db)):
    upload = db.get(Upload, upload_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="Upload not found")

    encounter_count = db.scalar(select(Encounter).where(Encounter.upload_id == upload_id).limit(1))
    if encounter_count is not None:
        raise HTTPException(status_code=409, detail="Cannot delete a snapshot that is linked to encounters")

    db.delete(upload)
    db.flush()
    prune_orphaned_canonical_rows(db)
    db.commit()
    return UploadDeleteResponse(deleted=True, upload_id=upload_id)
