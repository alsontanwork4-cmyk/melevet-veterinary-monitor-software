from __future__ import annotations

import pytest

from app.services.local_runtime import hold_runtime_lock_for_path


def test_runtime_lock_allows_only_one_holder_per_path(tmp_path) -> None:
    lock_path = tmp_path / ".runtime.lock"
    first = hold_runtime_lock_for_path(lock_path)
    try:
        with pytest.raises(RuntimeError, match="already using this runtime directory"):
            hold_runtime_lock_for_path(lock_path)
    finally:
        first.release()

    second = hold_runtime_lock_for_path(lock_path)
    second.release()
