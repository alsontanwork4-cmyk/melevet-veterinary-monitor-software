from __future__ import annotations

import logging
import os
from pathlib import Path

from ..config import settings
from .logging_service import JsonLogFormatter

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class RuntimeLockHandle:
    def __init__(self, file_handle=None):
        self._file_handle = file_handle

    def release(self) -> None:
        if self._file_handle is None:
            return
        try:
            if os.name == "nt":
                self._file_handle.seek(0)
                msvcrt.locking(self._file_handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(self._file_handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._file_handle.close()
            self._file_handle = None


def runtime_lock_path(root: Path | None = None) -> Path:
    base_root = root or settings.data_root_path
    return base_root / ".runtime.lock"


def hold_runtime_lock_for_path(lock_path: Path) -> RuntimeLockHandle:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        file_handle = lock_path.open("r+b")
    else:
        file_handle = lock_path.open("w+b")
    try:
        if os.name == "nt":
            file_handle.seek(0)
            if file_handle.tell() == 0 and lock_path.stat().st_size == 0:
                file_handle.write(b"0")
            file_handle.flush()
            file_handle.seek(0)
            msvcrt.locking(file_handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(file_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return RuntimeLockHandle(file_handle)
    except OSError as exc:
        file_handle.close()
        raise RuntimeError("Another Melevet backend instance is already using this runtime directory.") from exc


def ensure_runtime_directories() -> None:
    settings.data_root_path.mkdir(parents=True, exist_ok=True)
    settings.resolved_stage_storage_dir.mkdir(parents=True, exist_ok=True)
    settings.resolved_upload_spool_dir.mkdir(parents=True, exist_ok=True)
    settings.log_dir_path.mkdir(parents=True, exist_ok=True)
    settings.archive_dir_path.mkdir(parents=True, exist_ok=True)
    settings.telemetry_dir_path.mkdir(parents=True, exist_ok=True)


def configure_runtime_logging() -> None:
    ensure_runtime_directories()
    root_logger = logging.getLogger()
    log_path = settings.runtime_log_path
    desired_file = str(log_path)

    for handler in root_logger.handlers:
        if isinstance(handler, logging.FileHandler) and getattr(handler, "baseFilename", None) == desired_file:
            return

    root_logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(JsonLogFormatter())
    root_logger.addHandler(file_handler)


def hold_local_runtime_lock() -> RuntimeLockHandle:
    if not settings.is_local_app:
        return RuntimeLockHandle()
    return hold_runtime_lock_for_path(runtime_lock_path())
