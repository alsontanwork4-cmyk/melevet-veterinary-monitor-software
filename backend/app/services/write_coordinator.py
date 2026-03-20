from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from time import monotonic
from typing import Iterator


logger = logging.getLogger(__name__)
_lock = threading.Lock()
_state_lock = threading.Lock()


@dataclass(frozen=True)
class ActiveWrite:
    name: str
    started_at: float


class ExclusiveWriteBusyError(RuntimeError):
    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


_active_write: ActiveWrite | None = None


def active_write_name() -> str | None:
    with _state_lock:
        return _active_write.name if _active_write is not None else None


@contextmanager
def exclusive_write(
    name: str,
    *,
    wait: bool,
    busy_detail: str,
) -> Iterator[None]:
    global _active_write

    acquired = _lock.acquire(blocking=wait)
    if not acquired:
        holder = active_write_name()
        logger.info("Exclusive write rejected requested=%s holder=%s", name, holder)
        raise ExclusiveWriteBusyError(busy_detail)

    started_at = monotonic()
    with _state_lock:
        _active_write = ActiveWrite(name=name, started_at=started_at)

    logger.info("Exclusive write acquired name=%s", name)
    try:
        yield
    finally:
        elapsed_ms = (monotonic() - started_at) * 1000
        with _state_lock:
            _active_write = None
        _lock.release()
        logger.info("Exclusive write released name=%s elapsed_ms=%.2f", name, elapsed_ms)
