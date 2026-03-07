from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from ..services.decode_export_service import build_decode_export_archive
from ..services.decode_job_service import create_decode_job, get_decode_job, pop_decode_job_archive, start_decode_job


router = APIRouter(tags=["decode"])


def _validate_optional_pair(
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


async def _read_uploaded_file(file: UploadFile | None, fallback_name: str) -> bytes | None:
    if file is None:
        return None
    payload = await file.read()
    filename = file.filename or fallback_name
    if not payload:
        raise HTTPException(status_code=400, detail=f"Empty file: {filename}")
    return payload


@router.post("/decode/export")
async def decode_export(
    trend_data: UploadFile | None = File(default=None),
    trend_index: UploadFile | None = File(default=None),
    nibp_data: UploadFile | None = File(default=None),
    nibp_index: UploadFile | None = File(default=None),
    alarm_data: UploadFile | None = File(default=None),
    alarm_index: UploadFile | None = File(default=None),
    timezone: str = Form(default="UTC"),
):
    _validate_optional_pair(
        pair_name="Trend",
        data_present=trend_data is not None,
        index_present=trend_index is not None,
        data_field="trend_data",
        index_field="trend_index",
    )
    _validate_optional_pair(
        pair_name="Nibp",
        data_present=nibp_data is not None,
        index_present=nibp_index is not None,
        data_field="nibp_data",
        index_field="nibp_index",
    )
    _validate_optional_pair(
        pair_name="Alarm",
        data_present=alarm_data is not None,
        index_present=alarm_index is not None,
        data_field="alarm_data",
        index_field="alarm_index",
    )

    if all(file is None for file in (trend_data, trend_index, nibp_data, nibp_index, alarm_data, alarm_index)):
        raise HTTPException(status_code=400, detail="Upload at least one complete record pair to decode")

    trend_data_bytes = await _read_uploaded_file(trend_data, "trend_data")
    trend_index_bytes = await _read_uploaded_file(trend_index, "trend_index")
    nibp_data_bytes = await _read_uploaded_file(nibp_data, "nibp_data")
    nibp_index_bytes = await _read_uploaded_file(nibp_index, "nibp_index")
    alarm_data_bytes = await _read_uploaded_file(alarm_data, "alarm_data")
    alarm_index_bytes = await _read_uploaded_file(alarm_index, "alarm_index")

    try:
        archive_bytes = build_decode_export_archive(
            trend_data=trend_data_bytes,
            trend_index=trend_index_bytes,
            nibp_data=nibp_data_bytes,
            nibp_index=nibp_index_bytes,
            alarm_data=alarm_data_bytes,
            alarm_index=alarm_index_bytes,
            timezone_name=timezone,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return Response(
        content=archive_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="decoded-records.zip"'},
    )


@router.post("/decode/jobs", status_code=202)
async def create_decode_export_job(
    trend_data: UploadFile | None = File(default=None),
    trend_index: UploadFile | None = File(default=None),
    nibp_data: UploadFile | None = File(default=None),
    nibp_index: UploadFile | None = File(default=None),
    alarm_data: UploadFile | None = File(default=None),
    alarm_index: UploadFile | None = File(default=None),
    timezone: str = Form(default="UTC"),
):
    _validate_optional_pair(
        pair_name="Trend",
        data_present=trend_data is not None,
        index_present=trend_index is not None,
        data_field="trend_data",
        index_field="trend_index",
    )
    _validate_optional_pair(
        pair_name="Nibp",
        data_present=nibp_data is not None,
        index_present=nibp_index is not None,
        data_field="nibp_data",
        index_field="nibp_index",
    )
    _validate_optional_pair(
        pair_name="Alarm",
        data_present=alarm_data is not None,
        index_present=alarm_index is not None,
        data_field="alarm_data",
        index_field="alarm_index",
    )

    if all(file is None for file in (trend_data, trend_index, nibp_data, nibp_index, alarm_data, alarm_index)):
        raise HTTPException(status_code=400, detail="Upload at least one complete record pair to decode")

    trend_data_bytes = await _read_uploaded_file(trend_data, "trend_data")
    trend_index_bytes = await _read_uploaded_file(trend_index, "trend_index")
    nibp_data_bytes = await _read_uploaded_file(nibp_data, "nibp_data")
    nibp_index_bytes = await _read_uploaded_file(nibp_index, "nibp_index")
    alarm_data_bytes = await _read_uploaded_file(alarm_data, "alarm_data")
    alarm_index_bytes = await _read_uploaded_file(alarm_index, "alarm_index")

    selected_families = [
        label
        for label, selected in (
            ("Trend Chart", trend_data_bytes is not None and trend_index_bytes is not None),
            ("NIBP", nibp_data_bytes is not None and nibp_index_bytes is not None),
            ("Alarm", alarm_data_bytes is not None and alarm_index_bytes is not None),
        )
        if selected
    ]
    job = create_decode_job(selected_families=selected_families)
    start_decode_job(
        job_id=job.id,
        trend_data=trend_data_bytes,
        trend_index=trend_index_bytes,
        nibp_data=nibp_data_bytes,
        nibp_index=nibp_index_bytes,
        alarm_data=alarm_data_bytes,
        alarm_index=alarm_index_bytes,
        timezone_name=timezone,
    )
    refreshed_job = get_decode_job(job.id)
    if refreshed_job is None:
        raise HTTPException(status_code=500, detail="Decode job could not be started")
    return refreshed_job.to_payload()


@router.get("/decode/jobs/{job_id}")
def get_decode_export_job(job_id: str):
    job = get_decode_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Decode job not found")
    return job.to_payload()


@router.get("/decode/jobs/{job_id}/download")
def download_decode_export_job(job_id: str):
    job, archive_bytes = pop_decode_job_archive(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Decode job not found")
    if job.status == "error":
        raise HTTPException(status_code=409, detail=job.error_message or "Decode job failed")
    if job.status != "completed" or archive_bytes is None:
        raise HTTPException(status_code=409, detail="Decode job is not ready yet")

    return Response(
        content=archive_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{job.filename}"'},
    )
