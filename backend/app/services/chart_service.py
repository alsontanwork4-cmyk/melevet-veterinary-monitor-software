from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Integer, Select, and_, cast, func, select
from sqlalchemy.orm import Session

from ..models import (
    Alarm,
    AlarmCategory,
    Channel,
    Encounter,
    Measurement,
    NibpEvent,
    RecordingPeriod,
    Segment,
    SourceType,
    UploadAlarmLink,
    UploadMeasurementLink,
    UploadNibpEventLink,
)
from .encounter_service import encounter_day_window


@dataclass(frozen=True)
class MeasurementQueryResult:
    rows: list[tuple[Measurement, str]]
    matched_row_count: int
    returned_row_count: int


def _apply_time_filter(stmt: Select, model_timestamp, from_ts: datetime | None, to_ts: datetime | None) -> Select:
    conditions = []
    if from_ts is not None:
        conditions.append(model_timestamp >= from_ts)
    if to_ts is not None:
        conditions.append(model_timestamp <= to_ts)
    if conditions:
        stmt = stmt.where(and_(*conditions))
    return stmt


def _normalize_utc_naive(timestamp: datetime | None) -> datetime | None:
    if timestamp is None:
        return None
    if timestamp.tzinfo is None:
        return timestamp
    return timestamp.astimezone(UTC).replace(tzinfo=None)


def _has_measurement_links_for_upload(db: Session, upload_id: int) -> bool:
    return bool(
        db.scalar(select(func.count(UploadMeasurementLink.id)).where(UploadMeasurementLink.upload_id == upload_id))
        or 0
    )


def _has_measurement_links_for_segment(db: Session, segment_id: int) -> bool:
    return bool(
        db.scalar(select(func.count(UploadMeasurementLink.id)).where(UploadMeasurementLink.segment_id == segment_id))
        or 0
    )


def _has_nibp_links_for_upload(db: Session, upload_id: int) -> bool:
    return bool(
        db.scalar(select(func.count(UploadNibpEventLink.id)).where(UploadNibpEventLink.upload_id == upload_id))
        or 0
    )


def _has_alarm_links_for_upload(db: Session, upload_id: int) -> bool:
    return bool(db.scalar(select(func.count(UploadAlarmLink.id)).where(UploadAlarmLink.upload_id == upload_id)) or 0)


def _build_measurement_row_query(source_type: SourceType) -> Select:
    return (
        select(
            Measurement.id.label("id"),
            UploadMeasurementLink.upload_id.label("upload_id"),
            UploadMeasurementLink.segment_id.label("segment_id"),
            UploadMeasurementLink.channel_id.label("channel_id"),
            UploadMeasurementLink.timestamp.label("timestamp"),
            Measurement.value.label("value"),
            Channel.name.label("channel_name"),
        )
        .select_from(UploadMeasurementLink)
        .join(Measurement, Measurement.id == UploadMeasurementLink.measurement_id)
        .join(Channel, Channel.id == UploadMeasurementLink.channel_id)
        .where(Channel.source_type == source_type)
    )


def _build_measurement_count_query(source_type: SourceType) -> Select:
    return (
        select(func.count())
        .select_from(UploadMeasurementLink)
        .join(Measurement, Measurement.id == UploadMeasurementLink.measurement_id)
        .join(Channel, Channel.id == UploadMeasurementLink.channel_id)
        .where(Channel.source_type == source_type)
    )


def _materialize_measurement_rows(query_rows) -> list[tuple[Measurement, str]]:
    rows: list[tuple[Measurement, str]] = []
    for row in query_rows:
        rows.append(
            (
                Measurement(
                    id=row.id,
                    upload_id=row.upload_id,
                    segment_id=row.segment_id,
                    channel_id=row.channel_id,
                    timestamp=row.timestamp,
                    value=row.value,
                ),
                row.channel_name,
            )
        )
    return rows


def _downsample_materialized_rows(
    rows: list[tuple[Measurement, str]],
    *,
    max_points: int,
) -> list[tuple[Measurement, str]]:
    if max_points <= 0:
        return rows

    rows_by_channel: dict[int, list[tuple[Measurement, str]]] = {}
    for row in rows:
        rows_by_channel.setdefault(row[0].channel_id, []).append(row)

    sampled: list[tuple[Measurement, str]] = []
    for channel_rows in rows_by_channel.values():
        if len(channel_rows) <= max_points:
            sampled.extend(channel_rows)
            continue

        selected_indexes = {
            int((position * (len(channel_rows) - 1)) / max(1, max_points - 1))
            for position in range(max_points)
        }
        sampled.extend(channel_rows[index] for index in sorted(selected_indexes))

    return sorted(sampled, key=lambda row: (row[0].timestamp, row[0].channel_id))


def _apply_sql_downsampling(stmt: Select, max_points: int) -> Select:
    base_subquery = (
        stmt.add_columns(
            func.row_number()
            .over(
                partition_by=UploadMeasurementLink.channel_id,
                order_by=(UploadMeasurementLink.timestamp.asc(), Measurement.id.asc()),
            )
            .label("channel_row_number"),
            func.count().over(partition_by=UploadMeasurementLink.channel_id).label("channel_row_count"),
        )
    ).subquery()

    bucketed_subquery = select(
        base_subquery.c.id,
        base_subquery.c.upload_id,
        base_subquery.c.segment_id,
        base_subquery.c.channel_id,
        base_subquery.c.timestamp,
        base_subquery.c.value,
        base_subquery.c.channel_name,
        cast(
            ((base_subquery.c.channel_row_number - 1) * max_points) / base_subquery.c.channel_row_count,
            Integer,
        ).label("channel_bucket"),
    ).subquery()

    ranked_subquery = select(
        bucketed_subquery.c.id,
        bucketed_subquery.c.upload_id,
        bucketed_subquery.c.segment_id,
        bucketed_subquery.c.channel_id,
        bucketed_subquery.c.timestamp,
        bucketed_subquery.c.value,
        bucketed_subquery.c.channel_name,
        func.row_number()
        .over(
            partition_by=(bucketed_subquery.c.channel_id, bucketed_subquery.c.channel_bucket),
            order_by=(bucketed_subquery.c.timestamp.asc(), bucketed_subquery.c.id.asc()),
        )
        .label("bucket_rank"),
    ).subquery()

    return (
        select(
            ranked_subquery.c.id,
            ranked_subquery.c.upload_id,
            ranked_subquery.c.segment_id,
            ranked_subquery.c.channel_id,
            ranked_subquery.c.timestamp,
            ranked_subquery.c.value,
            ranked_subquery.c.channel_name,
        )
        .where(ranked_subquery.c.bucket_rank == 1)
        .order_by(ranked_subquery.c.timestamp.asc(), ranked_subquery.c.channel_id.asc())
    )


def _execute_measurement_query(
    db: Session,
    *,
    scope_filters: list[object],
    channel_ids: list[int] | None,
    from_ts: datetime | None,
    to_ts: datetime | None,
    max_points: int | None,
    source_type: SourceType,
) -> MeasurementQueryResult:
    from_ts = _normalize_utc_naive(from_ts)
    to_ts = _normalize_utc_naive(to_ts)

    count_stmt = _build_measurement_count_query(source_type)
    row_stmt = _build_measurement_row_query(source_type)

    for scope_filter in scope_filters:
        count_stmt = count_stmt.where(scope_filter)
        row_stmt = row_stmt.where(scope_filter)

    if channel_ids:
        count_stmt = count_stmt.where(UploadMeasurementLink.channel_id.in_(channel_ids))
        row_stmt = row_stmt.where(UploadMeasurementLink.channel_id.in_(channel_ids))

    count_stmt = _apply_time_filter(count_stmt, UploadMeasurementLink.timestamp, from_ts, to_ts)
    row_stmt = _apply_time_filter(row_stmt, UploadMeasurementLink.timestamp, from_ts, to_ts)

    matched_row_count = db.scalar(count_stmt) or 0

    if max_points is not None and max_points > 0 and matched_row_count > 0:
        query_rows = db.execute(_apply_sql_downsampling(row_stmt, max_points)).all()
    else:
        query_rows = db.execute(
            row_stmt.order_by(UploadMeasurementLink.timestamp.asc(), UploadMeasurementLink.channel_id.asc())
        ).all()

    rows = _materialize_measurement_rows(query_rows)
    return MeasurementQueryResult(
        rows=rows,
        matched_row_count=matched_row_count,
        returned_row_count=len(rows),
    )


def _execute_legacy_measurement_query(
    db: Session,
    *,
    scope_filters: list[object],
    channel_ids: list[int] | None,
    from_ts: datetime | None,
    to_ts: datetime | None,
    max_points: int | None,
    source_type: SourceType,
) -> MeasurementQueryResult:
    from_ts = _normalize_utc_naive(from_ts)
    to_ts = _normalize_utc_naive(to_ts)

    count_stmt = (
        select(func.count())
        .select_from(Measurement)
        .join(Channel, Channel.id == Measurement.channel_id)
        .where(Channel.source_type == source_type)
    )
    row_stmt = (
        select(
            Measurement.id.label("id"),
            Measurement.upload_id.label("upload_id"),
            Measurement.segment_id.label("segment_id"),
            Measurement.channel_id.label("channel_id"),
            Measurement.timestamp.label("timestamp"),
            Measurement.value.label("value"),
            Channel.name.label("channel_name"),
        )
        .select_from(Measurement)
        .join(Channel, Channel.id == Measurement.channel_id)
        .where(Channel.source_type == source_type)
    )

    for scope_filter in scope_filters:
        count_stmt = count_stmt.where(scope_filter)
        row_stmt = row_stmt.where(scope_filter)

    if channel_ids:
        count_stmt = count_stmt.where(Measurement.channel_id.in_(channel_ids))
        row_stmt = row_stmt.where(Measurement.channel_id.in_(channel_ids))

    count_stmt = _apply_time_filter(count_stmt, Measurement.timestamp, from_ts, to_ts)
    row_stmt = _apply_time_filter(row_stmt, Measurement.timestamp, from_ts, to_ts)

    matched_row_count = db.scalar(count_stmt) or 0
    query_rows = db.execute(row_stmt.order_by(Measurement.timestamp.asc(), Measurement.channel_id.asc())).all()
    rows = _materialize_measurement_rows(query_rows)
    if max_points is not None and max_points > 0 and rows:
        rows = _downsample_materialized_rows(rows, max_points=max_points)
    return MeasurementQueryResult(
        rows=rows,
        matched_row_count=matched_row_count,
        returned_row_count=len(rows),
    )


def _encounter_window(encounter: Encounter) -> tuple[datetime, datetime]:
    return encounter_day_window(encounter.encounter_date_local, encounter.timezone)


def list_periods(db: Session, upload_id: int) -> list[RecordingPeriod]:
    return list(
        db.scalars(
            select(RecordingPeriod)
            .where(RecordingPeriod.upload_id == upload_id)
            .order_by(RecordingPeriod.period_index.asc())
        )
    )


def list_segments(db: Session, period_id: int) -> list[Segment]:
    return list(
        db.scalars(
            select(Segment).where(Segment.period_id == period_id).order_by(Segment.segment_index.asc())
        )
    )


def list_segment_channels(
    db: Session,
    segment_id: int,
    source_type: SourceType | None = None,
) -> list[Channel]:
    segment = db.get(Segment, segment_id)
    if segment is None:
        return []

    channels: list[Channel] = []

    if source_type in (None, SourceType.trend):
        if _has_measurement_links_for_segment(db, segment_id):
            trend_stmt = (
                select(Channel)
                .join(UploadMeasurementLink, UploadMeasurementLink.channel_id == Channel.id)
                .where(Channel.source_type == SourceType.trend)
                .where(UploadMeasurementLink.segment_id == segment_id)
                .group_by(Channel.id)
                .order_by(Channel.channel_index.asc())
            )
        else:
            trend_stmt = (
                select(Channel)
                .join(Measurement, Measurement.channel_id == Channel.id)
                .where(Channel.upload_id == segment.upload_id)
                .where(Channel.source_type == SourceType.trend)
                .where(Measurement.segment_id == segment_id)
                .group_by(Channel.id)
                .order_by(Channel.channel_index.asc())
            )
        channels.extend(list(db.scalars(trend_stmt)))

    if source_type in (None, SourceType.nibp):
        nibp_stmt = (
            select(Channel)
            .where(Channel.upload_id == segment.upload_id)
            .where(Channel.source_type == SourceType.nibp)
            .where(Channel.valid_count > 0)
            .order_by(Channel.channel_index.asc())
        )
        channels.extend(list(db.scalars(nibp_stmt)))

    return channels


def list_upload_channels(
    db: Session,
    upload_id: int,
    source_type: SourceType | None = None,
) -> list[Channel]:
    channels: list[Channel] = []

    if source_type in (None, SourceType.trend):
        if _has_measurement_links_for_upload(db, upload_id):
            trend_stmt = (
                select(Channel)
                .join(UploadMeasurementLink, UploadMeasurementLink.channel_id == Channel.id)
                .where(Channel.source_type == SourceType.trend)
                .where(UploadMeasurementLink.upload_id == upload_id)
                .group_by(Channel.id)
                .order_by(Channel.channel_index.asc())
            )
        else:
            trend_stmt = (
                select(Channel)
                .join(Measurement, Measurement.channel_id == Channel.id)
                .where(Channel.upload_id == upload_id)
                .where(Channel.source_type == SourceType.trend)
                .where(Measurement.upload_id == upload_id)
                .group_by(Channel.id)
                .order_by(Channel.channel_index.asc())
            )
        channels.extend(list(db.scalars(trend_stmt)))

    if source_type in (None, SourceType.nibp):
        nibp_stmt = (
            select(Channel)
            .where(Channel.upload_id == upload_id)
            .where(Channel.source_type == SourceType.nibp)
            .where(Channel.valid_count > 0)
            .order_by(Channel.channel_index.asc())
        )
        channels.extend(list(db.scalars(nibp_stmt)))

    return channels


def list_encounter_channels(
    db: Session,
    encounter_id: int,
    source_type: SourceType | None = None,
) -> list[Channel]:
    encounter = db.get(Encounter, encounter_id)
    if encounter is None:
        return []

    from_ts, to_ts = _encounter_window(encounter)
    channels: list[Channel] = []

    if source_type in (None, SourceType.trend):
        if _has_measurement_links_for_upload(db, encounter.upload_id):
            trend_stmt = (
                select(Channel)
                .join(UploadMeasurementLink, UploadMeasurementLink.channel_id == Channel.id)
                .where(Channel.source_type == SourceType.trend)
                .where(UploadMeasurementLink.upload_id == encounter.upload_id)
                .group_by(Channel.id)
                .order_by(Channel.channel_index.asc())
            )
            trend_stmt = _apply_time_filter(trend_stmt, UploadMeasurementLink.timestamp, from_ts, to_ts)
        else:
            trend_stmt = (
                select(Channel)
                .join(Measurement, Measurement.channel_id == Channel.id)
                .where(Channel.upload_id == encounter.upload_id)
                .where(Channel.source_type == SourceType.trend)
                .where(Measurement.upload_id == encounter.upload_id)
                .group_by(Channel.id)
                .order_by(Channel.channel_index.asc())
            )
            trend_stmt = _apply_time_filter(trend_stmt, Measurement.timestamp, from_ts, to_ts)
        channels.extend(list(db.scalars(trend_stmt)))

    if source_type in (None, SourceType.nibp):
        nibp_stmt = (
            select(Channel)
            .where(Channel.upload_id == encounter.upload_id)
            .where(Channel.source_type == SourceType.nibp)
            .where(Channel.valid_count > 0)
            .order_by(Channel.channel_index.asc())
        )
        channels.extend(list(db.scalars(nibp_stmt)))

    return channels


def list_measurements(
    db: Session,
    segment_id: int,
    channel_ids: list[int] | None,
    from_ts: datetime | None,
    to_ts: datetime | None,
    max_points: int | None,
    source_type: SourceType = SourceType.trend,
) -> list[tuple[Measurement, str]]:
    return query_measurements(
        db,
        segment_id=segment_id,
        channel_ids=channel_ids,
        from_ts=from_ts,
        to_ts=to_ts,
        max_points=max_points,
        source_type=source_type,
    ).rows


def query_measurements(
    db: Session,
    segment_id: int,
    channel_ids: list[int] | None,
    from_ts: datetime | None,
    to_ts: datetime | None,
    max_points: int | None,
    source_type: SourceType = SourceType.trend,
) -> MeasurementQueryResult:
    if not _has_measurement_links_for_segment(db, segment_id):
        return _execute_legacy_measurement_query(
            db,
            scope_filters=[Measurement.segment_id == segment_id],
            channel_ids=channel_ids,
            from_ts=from_ts,
            to_ts=to_ts,
            max_points=max_points,
            source_type=source_type,
        )
    return _execute_measurement_query(
        db,
        scope_filters=[UploadMeasurementLink.segment_id == segment_id],
        channel_ids=channel_ids,
        from_ts=from_ts,
        to_ts=to_ts,
        max_points=max_points,
        source_type=source_type,
    )


def list_upload_measurements(
    db: Session,
    upload_id: int,
    channel_ids: list[int] | None,
    from_ts: datetime | None,
    to_ts: datetime | None,
    max_points: int | None,
    source_type: SourceType = SourceType.trend,
) -> list[tuple[Measurement, str]]:
    return query_upload_measurements(
        db,
        upload_id=upload_id,
        channel_ids=channel_ids,
        from_ts=from_ts,
        to_ts=to_ts,
        max_points=max_points,
        source_type=source_type,
    ).rows


def query_upload_measurements(
    db: Session,
    upload_id: int,
    channel_ids: list[int] | None,
    from_ts: datetime | None,
    to_ts: datetime | None,
    max_points: int | None,
    source_type: SourceType = SourceType.trend,
) -> MeasurementQueryResult:
    if not _has_measurement_links_for_upload(db, upload_id):
        return _execute_legacy_measurement_query(
            db,
            scope_filters=[Measurement.upload_id == upload_id, Channel.upload_id == upload_id],
            channel_ids=channel_ids,
            from_ts=from_ts,
            to_ts=to_ts,
            max_points=max_points,
            source_type=source_type,
        )
    return _execute_measurement_query(
        db,
        scope_filters=[UploadMeasurementLink.upload_id == upload_id, Channel.upload_id == upload_id],
        channel_ids=channel_ids,
        from_ts=from_ts,
        to_ts=to_ts,
        max_points=max_points,
        source_type=source_type,
    )


def list_encounter_measurements(
    db: Session,
    encounter_id: int,
    channel_ids: list[int] | None,
    max_points: int | None,
    source_type: SourceType = SourceType.trend,
) -> list[tuple[Measurement, str]]:
    result = query_encounter_measurements(
        db,
        encounter_id=encounter_id,
        channel_ids=channel_ids,
        max_points=max_points,
        source_type=source_type,
    )
    return result.rows


def query_encounter_measurements(
    db: Session,
    encounter_id: int,
    channel_ids: list[int] | None,
    max_points: int | None,
    source_type: SourceType = SourceType.trend,
) -> MeasurementQueryResult:
    encounter = db.get(Encounter, encounter_id)
    if encounter is None:
        return MeasurementQueryResult(rows=[], matched_row_count=0, returned_row_count=0)

    from_ts, to_ts = _encounter_window(encounter)
    if not _has_measurement_links_for_upload(db, encounter.upload_id):
        return _execute_legacy_measurement_query(
            db,
            scope_filters=[Measurement.upload_id == encounter.upload_id, Channel.upload_id == encounter.upload_id],
            channel_ids=channel_ids,
            from_ts=from_ts,
            to_ts=to_ts,
            max_points=max_points,
            source_type=source_type,
        )
    return _execute_measurement_query(
        db,
        scope_filters=[UploadMeasurementLink.upload_id == encounter.upload_id, Channel.upload_id == encounter.upload_id],
        channel_ids=channel_ids,
        from_ts=from_ts,
        to_ts=to_ts,
        max_points=max_points,
        source_type=source_type,
    )


def list_alarms(
    db: Session,
    upload_id: int,
    segment_id: int | None = None,
    category: AlarmCategory | None = None,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
) -> list[Alarm]:
    from_ts = _normalize_utc_naive(from_ts)
    to_ts = _normalize_utc_naive(to_ts)

    if _has_alarm_links_for_upload(db, upload_id):
        stmt = select(Alarm).join(UploadAlarmLink, UploadAlarmLink.alarm_id == Alarm.id).where(
            UploadAlarmLink.upload_id == upload_id
        )

        if segment_id is not None:
            stmt = stmt.where(UploadAlarmLink.segment_id == segment_id)
        if category is not None:
            stmt = stmt.where(Alarm.alarm_category == category)
        stmt = _apply_time_filter(stmt, UploadAlarmLink.timestamp, from_ts, to_ts)
    else:
        stmt = select(Alarm).where(Alarm.upload_id == upload_id)

        if segment_id is not None:
            stmt = stmt.where(Alarm.segment_id == segment_id)
        if category is not None:
            stmt = stmt.where(Alarm.alarm_category == category)
        stmt = _apply_time_filter(stmt, Alarm.timestamp, from_ts, to_ts)

    stmt = stmt.order_by(Alarm.timestamp.asc(), Alarm.id.asc())
    return list(db.scalars(stmt))


def list_nibp_events(
    db: Session,
    upload_id: int,
    segment_id: int | None = None,
    measurements_only: bool = False,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
) -> list[NibpEvent]:
    from_ts = _normalize_utc_naive(from_ts)
    to_ts = _normalize_utc_naive(to_ts)

    if _has_nibp_links_for_upload(db, upload_id):
        stmt = select(NibpEvent).join(
            UploadNibpEventLink, UploadNibpEventLink.nibp_event_id == NibpEvent.id
        ).where(UploadNibpEventLink.upload_id == upload_id)

        if segment_id is not None:
            stmt = stmt.where(UploadNibpEventLink.segment_id == segment_id)
        if measurements_only:
            stmt = stmt.where(NibpEvent.has_measurement.is_(True))
        stmt = _apply_time_filter(stmt, UploadNibpEventLink.timestamp, from_ts, to_ts)
    else:
        stmt = select(NibpEvent).where(NibpEvent.upload_id == upload_id)

        if segment_id is not None:
            stmt = stmt.where(NibpEvent.segment_id == segment_id)
        if measurements_only:
            stmt = stmt.where(NibpEvent.has_measurement.is_(True))
        stmt = _apply_time_filter(stmt, NibpEvent.timestamp, from_ts, to_ts)

    stmt = stmt.order_by(NibpEvent.timestamp.asc(), NibpEvent.id.asc())
    return list(db.scalars(stmt))


def list_encounter_nibp_events(
    db: Session,
    encounter_id: int,
    measurements_only: bool = False,
) -> list[NibpEvent]:
    encounter = db.get(Encounter, encounter_id)
    if encounter is None:
        return []

    from_ts, to_ts = _encounter_window(encounter)
    return list_nibp_events(
        db,
        upload_id=encounter.upload_id,
        measurements_only=measurements_only,
        from_ts=from_ts,
        to_ts=to_ts,
    )
