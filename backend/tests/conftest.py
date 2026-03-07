from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def data_dir() -> Path:
    return Path(__file__).resolve().parents[2]