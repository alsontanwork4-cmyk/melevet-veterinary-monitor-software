from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.routers.uploads import _validate_pair_presence


def test_required_pair_accepts_complete() -> None:
    _validate_pair_presence(
        pair_name="Trend",
        data_present=True,
        index_present=True,
        data_field="trend_data",
        index_field="trend_index",
        required=True,
    )


def test_required_pair_rejects_missing_one_or_both() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_pair_presence(
            pair_name="Trend",
            data_present=True,
            index_present=False,
            data_field="trend_data",
            index_field="trend_index",
            required=True,
        )
    assert exc.value.status_code == 400
    assert "Trend files are required" in str(exc.value.detail)

    with pytest.raises(HTTPException):
        _validate_pair_presence(
            pair_name="Trend",
            data_present=False,
            index_present=False,
            data_field="trend_data",
            index_field="trend_index",
            required=True,
        )


def test_optional_pair_accepts_none_or_complete() -> None:
    _validate_pair_presence(
        pair_name="Nibp",
        data_present=False,
        index_present=False,
        data_field="nibp_data",
        index_field="nibp_index",
        required=False,
    )
    _validate_pair_presence(
        pair_name="Nibp",
        data_present=True,
        index_present=True,
        data_field="nibp_data",
        index_field="nibp_index",
        required=False,
    )


@pytest.mark.parametrize(
    ("data_present", "index_present"),
    [
        (True, False),
        (False, True),
    ],
)
def test_optional_pair_rejects_incomplete(data_present: bool, index_present: bool) -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_pair_presence(
            pair_name="Alarm",
            data_present=data_present,
            index_present=index_present,
            data_field="alarm_data",
            index_field="alarm_index",
            required=False,
        )
    assert exc.value.status_code == 400
    assert "uploaded together" in str(exc.value.detail)
