from __future__ import annotations

import hashlib
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePath

from fastapi import HTTPException, UploadFile, status

from ..config import settings


CANONICAL_UPLOAD_FILENAMES: dict[str, str] = {
    "trend_data": "TrendChartRecord.data",
    "trend_index": "TrendChartRecord.Index",
    "nibp_data": "NibpRecord.data",
    "nibp_index": "NibpRecord.Index",
}


@dataclass(frozen=True)
class StoredUploadFile:
    field_name: str
    path: Path
    size: int
    sha256: str


def upload_spool_root() -> Path:
    root = settings.resolved_upload_spool_dir
    root.mkdir(parents=True, exist_ok=True)
    return root


def create_upload_spool_dir(*, prefix: str = "upload-") -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix, dir=upload_spool_root()))


def cleanup_upload_dir(path: Path | str) -> None:
    shutil.rmtree(Path(path), ignore_errors=True)


def _validate_client_filename(filename: str | None) -> None:
    if not filename:
        return
    parsed = PurePath(filename)
    if parsed.is_absolute() or any(part in {"..", "."} for part in parsed.parts) or len(parsed.parts) > 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid upload filename")


async def store_upload_file(
    *,
    field_name: str,
    upload_file: UploadFile | None,
    destination_dir: Path,
    current_total_bytes: int,
) -> tuple[StoredUploadFile | None, int]:
    if upload_file is None:
        return None, current_total_bytes

    _validate_client_filename(upload_file.filename)
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / CANONICAL_UPLOAD_FILENAMES[field_name]
    hasher = hashlib.sha256()
    file_size = 0
    remove_destination = False

    with destination.open("wb") as handle:
        while True:
            chunk = await upload_file.read(1024 * 1024)
            if not chunk:
                break
            file_size += len(chunk)
            current_total_bytes += len(chunk)
            if file_size > settings.max_upload_file_bytes or current_total_bytes > settings.max_upload_request_bytes:
                remove_destination = True
                break
            handle.write(chunk)
            hasher.update(chunk)

    if remove_destination:
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Upload exceeds configured size limits",
        )

    if file_size == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Empty file: {upload_file.filename or CANONICAL_UPLOAD_FILENAMES[field_name]}",
        )

    return (
        StoredUploadFile(field_name=field_name, path=destination, size=file_size, sha256=hasher.hexdigest()),
        current_total_bytes,
    )


def read_optional_upload_bytes(path: Path | None) -> bytes | None:
    if path is None or not path.exists():
        return None
    return path.read_bytes()
