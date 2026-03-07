from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from ..models import Channel, SourceType
from ..parsers.nibp_parser import nibp_channel_name
from ..parsers.trend_parser import trend_channel_name
from .channel_mapping import resolve_channel_metadata


@dataclass(frozen=True)
class ChannelMetadataBackfillResult:
    scanned: int
    updated: int


def _default_name(source_type: SourceType, channel_index: int) -> str:
    if source_type == SourceType.nibp:
        return nibp_channel_name(channel_index)
    return trend_channel_name(channel_index)


def backfill_channel_metadata(db: Session, *, upload_id: int | None = None) -> ChannelMetadataBackfillResult:
    stmt: Select = select(Channel).order_by(Channel.upload_id.asc(), Channel.source_type.asc(), Channel.channel_index.asc())
    if upload_id is not None:
        stmt = stmt.where(Channel.upload_id == upload_id)

    rows = list(db.scalars(stmt))
    updated = 0
    for channel in rows:
        default_name = _default_name(channel.source_type, channel.channel_index)
        resolved_name, resolved_unit = resolve_channel_metadata(
            source_type=channel.source_type.value,
            channel_index=channel.channel_index,
            default_name=default_name,
            default_unit=None,
        )

        if channel.name == resolved_name and channel.unit == resolved_unit:
            continue

        channel.name = resolved_name
        channel.unit = resolved_unit
        db.add(channel)
        updated += 1

    if updated > 0:
        db.commit()

    return ChannelMetadataBackfillResult(scanned=len(rows), updated=updated)
