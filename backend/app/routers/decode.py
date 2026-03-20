from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from ..services.upload_security import cleanup_upload_dir, create_upload_spool_dir, read_optional_upload_bytes, store_upload_file
from ..services.decode_export_service import build_decode_export_archive
from ..services.decode_job_service import consume_decode_job_archive, create_decode_job, get_decode_job, start_decode_job


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


async def _spool_decode_uploads(
    *,
    trend_data: UploadFile | None,
    trend_index: UploadFile | None,
    nibp_data: UploadFile | None,
    nibp_index: UploadFile | None,
) -> str:
    spool_dir = create_upload_spool_dir(prefix="decode-upload-")
    total_bytes = 0
    try:
        _, total_bytes = await store_upload_file(
            field_name="trend_data",
            upload_file=trend_data,
            destination_dir=spool_dir,
            current_total_bytes=total_bytes,
        )
        _, total_bytes = await store_upload_file(
            field_name="trend_index",
            upload_file=trend_index,
            destination_dir=spool_dir,
            current_total_bytes=total_bytes,
        )
        _, total_bytes = await store_upload_file(
            field_name="nibp_data",
            upload_file=nibp_data,
            destination_dir=spool_dir,
            current_total_bytes=total_bytes,
        )
        _, total_bytes = await store_upload_file(
            field_name="nibp_index",
            upload_file=nibp_index,
            destination_dir=spool_dir,
            current_total_bytes=total_bytes,
        )
        return str(spool_dir)
    except Exception:
        cleanup_upload_dir(spool_dir)
        raise


@router.post("/decode/export")
async def decode_export(
    trend_data: UploadFile | None = File(default=None),
    trend_index: UploadFile | None = File(default=None),
    nibp_data: UploadFile | None = File(default=None),
    nibp_index: UploadFile | None = File(default=None),
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
    if all(file is None for file in (trend_data, trend_index, nibp_data, nibp_index)):
        raise HTTPException(status_code=400, detail="Upload at least one complete record pair to decode")

    spool_dir = await _spool_decode_uploads(
        trend_data=trend_data,
        trend_index=trend_index,
        nibp_data=nibp_data,
        nibp_index=nibp_index,
    )
    try:
        archive_bytes = build_decode_export_archive(
            trend_data=read_optional_upload_bytes(Path(spool_dir) / "TrendChartRecord.data"),
            trend_index=read_optional_upload_bytes(Path(spool_dir) / "TrendChartRecord.Index"),
            nibp_data=read_optional_upload_bytes(Path(spool_dir) / "NibpRecord.data"),
            nibp_index=read_optional_upload_bytes(Path(spool_dir) / "NibpRecord.Index"),
            timezone_name=timezone,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        cleanup_upload_dir(spool_dir)

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
    if all(file is None for file in (trend_data, trend_index, nibp_data, nibp_index)):
        raise HTTPException(status_code=400, detail="Upload at least one complete record pair to decode")

    spool_dir = await _spool_decode_uploads(
        trend_data=trend_data,
        trend_index=trend_index,
        nibp_data=nibp_data,
        nibp_index=nibp_index,
    )
    spool_path = Path(spool_dir)
    try:
        trend_data_bytes = read_optional_upload_bytes(spool_path / "TrendChartRecord.data")
        trend_index_bytes = read_optional_upload_bytes(spool_path / "TrendChartRecord.Index")
        nibp_data_bytes = read_optional_upload_bytes(spool_path / "NibpRecord.data")
        nibp_index_bytes = read_optional_upload_bytes(spool_path / "NibpRecord.Index")

        selected_families = [
            label
            for label, selected in (
                ("Trend Chart", trend_data_bytes is not None and trend_index_bytes is not None),
                ("NIBP", nibp_data_bytes is not None and nibp_index_bytes is not None),
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
            timezone_name=timezone,
        )
        refreshed_job = get_decode_job(job.id)
        if refreshed_job is None:
            raise HTTPException(status_code=500, detail="Decode job could not be started")
        return refreshed_job.to_payload()
    finally:
        cleanup_upload_dir(spool_dir)


@router.get("/decode/jobs/{job_id}")
def get_decode_export_job(job_id: str):
    job = get_decode_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Decode job not found")
    return job.to_payload()


@router.get("/decode/jobs/{job_id}/download")
def download_decode_export_job(job_id: str):
    job, archive_bytes, archive_state = consume_decode_job_archive(job_id)
    if archive_state == "not_found" or job is None:
        raise HTTPException(status_code=404, detail="Decode job not found")
    if archive_state == "error":
        raise HTTPException(status_code=409, detail=job.error_message or "Decode job failed")
    if archive_state == "not_ready":
        raise HTTPException(status_code=409, detail="Decode job is not ready yet")
    if archive_state == "consumed":
        raise HTTPException(
            status_code=410,
            detail="Decode archive already downloaded. Re-upload files to download again.",
        )
    if archive_state == "expired":
        raise HTTPException(
            status_code=410,
            detail="Decode archive expired from server memory. Re-upload files to download again.",
        )
    if archive_bytes is None:
        raise HTTPException(status_code=500, detail="Decode archive could not be prepared")

    return Response(
        content=archive_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{job.filename}"'},
    )
