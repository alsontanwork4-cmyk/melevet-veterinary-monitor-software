from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Connection
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings
from .parsers.nibp_parser import (
    DIASTOLIC_CHANNEL_INDEX,
    MEAN_CHANNEL_INDEX,
    SYSTOLIC_CHANNEL_INDEX,
    infer_nibp_measurement,
    nibp_channel_name,
)
from .services.channel_mapping import resolve_channel_metadata


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()


SQLITE_CORE_STORAGE_SCHEMA_VERSION = 2
SQLITE_UPLOAD_DEDUP_SCHEMA_VERSION = 3
COMPACT_STORAGE_USER_VERSION = SQLITE_CORE_STORAGE_SCHEMA_VERSION
CORE_TREND_CHANNELS: dict[int, tuple[str, str | None]] = {
    14: ("spo2_be_u16", "%"),
    16: ("heart_rate_be_u16", "bpm"),
}
CORE_NIBP_CHANNELS: dict[int, tuple[str, str | None]] = {
    SYSTOLIC_CHANNEL_INDEX: ("bp_systolic_inferred", "mmHg"),
    MEAN_CHANNEL_INDEX: ("bp_mean_inferred", "mmHg"),
    DIASTOLIC_CHANNEL_INDEX: ("bp_diastolic_inferred", "mmHg"),
}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _build_combined_hash_from_component_hashes(*, parts: list[str]) -> str:
    checksum_input = "|".join(parts)
    return hashlib.sha256(checksum_input.encode("utf-8")).hexdigest()


def _resolve_core_channel_metadata(
    *,
    source_type: str,
    channel_index: int,
    fallback_name: str,
    fallback_unit: str | None,
) -> tuple[str, str | None]:
    return resolve_channel_metadata(
        source_type=source_type,
        channel_index=channel_index,
        default_name=fallback_name,
        default_unit=fallback_unit,
    )


def _normalize_positive_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float) and value.is_integer():
        integer = int(value)
        return integer if integer > 0 else None
    return None


def _decode_channel_values(raw_value) -> dict[str, int | None]:
    if isinstance(raw_value, dict):
        payload = raw_value
    elif isinstance(raw_value, str) and raw_value.strip():
        try:
            decoded = json.loads(raw_value)
        except json.JSONDecodeError:
            return {}
        payload = decoded if isinstance(decoded, dict) else {}
    else:
        payload = {}

    normalized: dict[str, int | None] = {}
    for key, value in payload.items():
        if isinstance(key, str):
            normalized[key] = value
    return normalized


def _trim_nibp_channel_values(channel_values: dict[str, int | None]) -> tuple[dict[str, int | None], bool]:
    inferred_values = infer_nibp_measurement(channel_values)
    trimmed: dict[str, int | None] = {}

    for channel_index, (fallback_name, _fallback_unit) in CORE_NIBP_CHANNELS.items():
        value = _normalize_positive_int(inferred_values.get(fallback_name))
        if value is None:
            value = _normalize_positive_int(channel_values.get(fallback_name))
        if value is None:
            value = _normalize_positive_int(channel_values.get(nibp_channel_name(channel_index)))
        trimmed[fallback_name] = value

    has_measurement = any(value is not None for value in trimmed.values())
    return trimmed, has_measurement


def _normalize_dedup_timestamp(value) -> str:
    if isinstance(value, datetime):
        timestamp = value
    elif isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        timestamp = datetime.fromisoformat(normalized)
    else:
        raise TypeError(f"Unsupported timestamp value for dedup key: {type(value)!r}")

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    else:
        timestamp = timestamp.astimezone(UTC)
    return timestamp.isoformat().replace("+00:00", "Z")


def build_measurement_dedup_key(*, timestamp, source_type: str, channel_index: int) -> str:
    return f"{_normalize_dedup_timestamp(timestamp)}|{source_type}|{channel_index}"


def build_nibp_dedup_key(*, timestamp) -> str:
    return _normalize_dedup_timestamp(timestamp)


def build_alarm_dedup_key(
    *,
    timestamp,
    alarm_category: str,
    message: str,
    flag_hi: int,
    flag_lo: int,
) -> str:
    return "|".join(
        [
            _normalize_dedup_timestamp(timestamp),
            alarm_category,
            str(flag_hi),
            str(flag_lo),
            message,
        ]
    )


def ensure_sqlite_upload_progress_columns(*, bind=None, database_url: str | None = None) -> None:
    active_engine = bind or engine
    active_database_url = database_url or settings.database_url

    if not active_database_url.startswith("sqlite"):
        return

    with active_engine.begin() as connection:
        upload_table_rows = connection.exec_driver_sql("PRAGMA table_info(uploads)").fetchall()
        if not upload_table_rows:
            return

        upload_columns = {row[1] for row in upload_table_rows}
        upload_columns_to_add = [
            ("phase", "TEXT NOT NULL DEFAULT 'reading'"),
            ("progress_current", "INTEGER NOT NULL DEFAULT 0"),
            ("progress_total", "INTEGER NOT NULL DEFAULT 0"),
            ("started_at", "DATETIME NULL"),
            ("heartbeat_at", "DATETIME NULL"),
            ("completed_at", "DATETIME NULL"),
            ("combined_hash", "TEXT NOT NULL DEFAULT ''"),
            ("detected_local_dates", "TEXT NOT NULL DEFAULT '[]'"),
            ("superseded_at", "DATETIME NULL"),
            ("measurements_new", "INTEGER NOT NULL DEFAULT 0"),
            ("measurements_reused", "INTEGER NOT NULL DEFAULT 0"),
            ("nibp_new", "INTEGER NOT NULL DEFAULT 0"),
            ("nibp_reused", "INTEGER NOT NULL DEFAULT 0"),
            ("alarms_new", "INTEGER NOT NULL DEFAULT 0"),
            ("alarms_reused", "INTEGER NOT NULL DEFAULT 0"),
        ]

        for column_name, column_def in upload_columns_to_add:
            if column_name in upload_columns:
                continue
            connection.exec_driver_sql(f"ALTER TABLE uploads ADD COLUMN {column_name} {column_def}")
            upload_columns.add(column_name)

        if {"combined_hash", "status"}.issubset(upload_columns):
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_uploads_combined_hash_status ON uploads (combined_hash, status)"
            )

        if {
            "trend_sha256",
            "trend_index_sha256",
            "nibp_sha256",
            "nibp_index_sha256",
            "alarm_sha256",
            "alarm_index_sha256",
            "combined_hash",
        }.issubset(upload_columns):
            legacy_rows = connection.exec_driver_sql(
                """
                SELECT id, trend_sha256, trend_index_sha256, nibp_sha256, nibp_index_sha256, alarm_sha256, alarm_index_sha256
                FROM uploads
                WHERE combined_hash = ''
                """
            ).fetchall()

            for row in legacy_rows:
                combined_hash = _build_combined_hash_from_component_hashes(
                    parts=[row[1], row[2], row[3], row[4], row[5], row[6]]
                )
                connection.exec_driver_sql(
                    "UPDATE uploads SET combined_hash = ? WHERE id = ?",
                    (combined_hash, row[0]),
                )

        patient_table_rows = connection.exec_driver_sql("PRAGMA table_info(patients)").fetchall()
        if not patient_table_rows:
            return

        patient_columns = {row[1] for row in patient_table_rows}
        if "age" not in patient_columns:
            connection.exec_driver_sql("ALTER TABLE patients ADD COLUMN age TEXT NULL")
            patient_columns.add("age")

        if "preferred_encounter_id" not in patient_columns:
            connection.exec_driver_sql("ALTER TABLE patients ADD COLUMN preferred_encounter_id INTEGER NULL")
            patient_columns.add("preferred_encounter_id")

        if "preferred_encounter_id" in patient_columns:
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_patients_preferred_encounter_id ON patients (preferred_encounter_id)"
            )


def _create_compact_storage_tables(connection: Connection) -> None:
    connection.exec_driver_sql("DROP TABLE IF EXISTS channels_compact")
    connection.exec_driver_sql("DROP TABLE IF EXISTS measurements_compact")
    connection.exec_driver_sql("DROP TABLE IF EXISTS nibp_events_compact")
    connection.exec_driver_sql("DROP TABLE IF EXISTS alarms_compact")

    connection.exec_driver_sql(
        """
        CREATE TABLE channels_compact (
            id INTEGER PRIMARY KEY,
            upload_id INTEGER NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
            source_type TEXT NOT NULL,
            channel_index INTEGER NOT NULL,
            name TEXT NOT NULL,
            unit TEXT NULL,
            valid_count INTEGER NOT NULL DEFAULT 0,
            CONSTRAINT uq_upload_source_channel UNIQUE (upload_id, source_type, channel_index)
        )
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TABLE measurements_compact (
            id INTEGER PRIMARY KEY,
            upload_id INTEGER NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
            segment_id INTEGER NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
            channel_id INTEGER NOT NULL REFERENCES channels_compact(id) ON DELETE CASCADE,
            timestamp DATETIME NOT NULL,
            value FLOAT NULL
        )
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TABLE nibp_events_compact (
            id INTEGER PRIMARY KEY,
            upload_id INTEGER NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
            segment_id INTEGER NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
            timestamp DATETIME NOT NULL,
            channel_values JSON NOT NULL,
            has_measurement BOOLEAN NOT NULL DEFAULT 0
        )
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TABLE alarms_compact (
            id INTEGER PRIMARY KEY,
            upload_id INTEGER NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
            segment_id INTEGER NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
            timestamp DATETIME NOT NULL,
            flag_hi INTEGER NOT NULL,
            flag_lo INTEGER NOT NULL,
            alarm_category TEXT NOT NULL,
            message TEXT NOT NULL
        )
        """
    )


def _copy_compact_channels(connection: Connection) -> None:
    rows = connection.exec_driver_sql(
        """
        SELECT id, upload_id, source_type, channel_index, COALESCE(valid_count, 0)
        FROM channels
        WHERE (source_type = 'trend' AND channel_index IN (14, 16))
           OR (source_type = 'nibp' AND channel_index IN (14, 15, 16))
        ORDER BY id ASC
        """
    ).fetchall()

    for row in rows:
        source_type = str(row[2])
        channel_index = int(row[3])
        valid_count = int(row[4] or 0)
        if source_type == 'trend':
            fallback_name, fallback_unit = CORE_TREND_CHANNELS[channel_index]
        else:
            fallback_name, fallback_unit = CORE_NIBP_CHANNELS[channel_index]

        channel_name, unit = _resolve_core_channel_metadata(
            source_type=source_type,
            channel_index=channel_index,
            fallback_name=fallback_name,
            fallback_unit=fallback_unit,
        )
        connection.exec_driver_sql(
            """
            INSERT INTO channels_compact (id, upload_id, source_type, channel_index, name, unit, valid_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (int(row[0]), int(row[1]), source_type, channel_index, channel_name, unit, valid_count),
        )


def _copy_compact_measurements(connection: Connection) -> None:
    connection.exec_driver_sql(
        """
        INSERT INTO measurements_compact (id, upload_id, segment_id, channel_id, timestamp, value)
        SELECT measurements.id, measurements.upload_id, measurements.segment_id, measurements.channel_id, measurements.timestamp, measurements.value
        FROM measurements
        JOIN channels ON channels.id = measurements.channel_id
        WHERE channels.source_type = 'trend' AND channels.channel_index IN (14, 16)
        """
    )


def _copy_compact_nibp_events(connection: Connection) -> None:
    rows = connection.exec_driver_sql(
        "SELECT id, upload_id, segment_id, timestamp, channel_values FROM nibp_events ORDER BY id ASC"
    ).fetchall()

    for row in rows:
        trimmed_channel_values, has_measurement = _trim_nibp_channel_values(_decode_channel_values(row[4]))
        connection.exec_driver_sql(
            """
            INSERT INTO nibp_events_compact (id, upload_id, segment_id, timestamp, channel_values, has_measurement)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                int(row[0]),
                int(row[1]),
                int(row[2]),
                row[3],
                json.dumps(trimmed_channel_values),
                int(has_measurement),
            ),
        )


def _copy_compact_alarms(connection: Connection) -> None:
    connection.exec_driver_sql(
        """
        INSERT INTO alarms_compact (id, upload_id, segment_id, timestamp, flag_hi, flag_lo, alarm_category, message)
        SELECT id, upload_id, segment_id, timestamp, flag_hi, flag_lo, alarm_category, message
        FROM alarms
        """
    )


def _swap_in_compact_storage_tables(connection: Connection) -> None:
    connection.exec_driver_sql("DROP TABLE measurements")
    connection.exec_driver_sql("DROP TABLE nibp_events")
    connection.exec_driver_sql("DROP TABLE alarms")
    connection.exec_driver_sql("DROP TABLE channels")

    connection.exec_driver_sql("ALTER TABLE channels_compact RENAME TO channels")
    connection.exec_driver_sql("ALTER TABLE measurements_compact RENAME TO measurements")
    connection.exec_driver_sql("ALTER TABLE nibp_events_compact RENAME TO nibp_events")
    connection.exec_driver_sql("ALTER TABLE alarms_compact RENAME TO alarms")

    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_channels_upload_id ON channels (upload_id)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_channels_source_type ON channels (source_type)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_measurements_upload_segment_channel_ts ON measurements (upload_id, segment_id, channel_id, timestamp)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_measurements_upload_ts ON measurements (upload_id, timestamp)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_measurements_upload_id ON measurements (upload_id)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_measurements_segment_id ON measurements (segment_id)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_measurements_channel_id ON measurements (channel_id)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_measurements_timestamp ON measurements (timestamp)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_nibp_upload_segment_ts ON nibp_events (upload_id, segment_id, timestamp)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_nibp_events_upload_id ON nibp_events (upload_id)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_nibp_events_segment_id ON nibp_events (segment_id)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_nibp_events_timestamp ON nibp_events (timestamp)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_alarms_upload_segment_ts ON alarms (upload_id, segment_id, timestamp)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_alarms_upload_category_ts ON alarms (upload_id, alarm_category, timestamp)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_alarms_upload_id ON alarms (upload_id)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_alarms_segment_id ON alarms (segment_id)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_alarms_timestamp ON alarms (timestamp)"
    )


def ensure_sqlite_core_storage_compaction(*, bind=None, database_url: str | None = None) -> bool:
    active_engine = bind or engine
    active_database_url = database_url or settings.database_url

    if not active_database_url.startswith('sqlite'):
        return False

    with active_engine.begin() as connection:
        current_version = int(connection.exec_driver_sql('PRAGMA user_version').scalar() or 0)
        if current_version >= SQLITE_CORE_STORAGE_SCHEMA_VERSION:
            return False

        upload_table_rows = connection.exec_driver_sql('PRAGMA table_info(uploads)').fetchall()
        if not upload_table_rows:
            return False

        _create_compact_storage_tables(connection)
        _copy_compact_channels(connection)
        _copy_compact_measurements(connection)
        _copy_compact_nibp_events(connection)
        _copy_compact_alarms(connection)
        _swap_in_compact_storage_tables(connection)
        connection.exec_driver_sql(f'PRAGMA user_version = {SQLITE_CORE_STORAGE_SCHEMA_VERSION}')

    with active_engine.connect().execution_options(isolation_level='AUTOCOMMIT') as connection:
        connection.exec_driver_sql('PRAGMA wal_checkpoint(TRUNCATE)')
        connection.exec_driver_sql('VACUUM')

    return True


def _ensure_unique_upload_hashes(connection: Connection) -> None:
    duplicate_rows = connection.exec_driver_sql(
        """
        SELECT combined_hash
        FROM uploads
        WHERE combined_hash != ''
        GROUP BY combined_hash
        HAVING COUNT(*) > 1
        """
    ).fetchall()

    for (combined_hash,) in duplicate_rows:
        uploads = connection.exec_driver_sql(
            """
            SELECT uploads.id, COUNT(encounters.id) AS encounter_count
            FROM uploads
            LEFT JOIN encounters ON encounters.upload_id = uploads.id
            WHERE uploads.combined_hash = ?
            GROUP BY uploads.id
            ORDER BY encounter_count DESC, COALESCE(uploads.completed_at, uploads.upload_time) DESC, uploads.id DESC
            """,
            (combined_hash,),
        ).fetchall()
        if not uploads:
            continue

        for losing_row in uploads[1:]:
            upload_id = int(losing_row[0])
            replacement_hash = hashlib.sha256(f"{combined_hash}|legacy|{upload_id}".encode("utf-8")).hexdigest()
            connection.exec_driver_sql(
                "UPDATE uploads SET combined_hash = ? WHERE id = ?",
                (replacement_hash, upload_id),
            )


def _rebuild_measurement_dedup_tables(connection: Connection) -> None:
    connection.exec_driver_sql("DROP TABLE IF EXISTS upload_measurement_links")
    connection.exec_driver_sql("DROP TABLE IF EXISTS measurements_dedup_new")

    connection.exec_driver_sql(
        """
        CREATE TABLE measurements_dedup_new (
            id INTEGER PRIMARY KEY,
            upload_id INTEGER NULL REFERENCES uploads(id) ON DELETE SET NULL,
            segment_id INTEGER NULL REFERENCES segments(id) ON DELETE SET NULL,
            channel_id INTEGER NULL REFERENCES channels(id) ON DELETE SET NULL,
            timestamp DATETIME NOT NULL,
            value FLOAT NULL,
            dedup_key TEXT NOT NULL UNIQUE
        )
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TABLE upload_measurement_links (
            id INTEGER PRIMARY KEY,
            upload_id INTEGER NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
            segment_id INTEGER NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
            channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
            measurement_id INTEGER NOT NULL REFERENCES measurements_dedup_new(id) ON DELETE CASCADE,
            timestamp DATETIME NOT NULL,
            CONSTRAINT uq_upload_segment_channel_measurement UNIQUE (upload_id, segment_id, channel_id, measurement_id)
        )
        """
    )

    measurement_rows = connection.exec_driver_sql(
        """
        SELECT
            measurements.id,
            measurements.upload_id,
            measurements.segment_id,
            measurements.channel_id,
            measurements.timestamp,
            measurements.value,
            channels.source_type,
            channels.channel_index
        FROM measurements
        JOIN channels ON channels.id = measurements.channel_id
        ORDER BY measurements.id ASC
        """
    ).fetchall()

    measurement_ids_by_key: dict[str, int] = {}
    for row in measurement_rows:
        dedup_key = build_measurement_dedup_key(
            timestamp=row[4],
            source_type=str(row[6]),
            channel_index=int(row[7]),
        )
        measurement_id = measurement_ids_by_key.get(dedup_key)
        if measurement_id is None:
            existing_row = connection.exec_driver_sql(
                "SELECT id FROM measurements_dedup_new WHERE dedup_key = ?",
                (dedup_key,),
            ).fetchone()
            if existing_row is None:
                connection.exec_driver_sql(
                    """
                    INSERT INTO measurements_dedup_new (upload_id, segment_id, channel_id, timestamp, value, dedup_key)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (row[1], row[2], row[3], row[4], row[5], dedup_key),
                )
                measurement_id = int(connection.exec_driver_sql("SELECT last_insert_rowid()").scalar_one())
            else:
                measurement_id = int(existing_row[0])
            measurement_ids_by_key[dedup_key] = measurement_id

        connection.exec_driver_sql(
            """
            INSERT OR IGNORE INTO upload_measurement_links (upload_id, segment_id, channel_id, measurement_id, timestamp)
            VALUES (?, ?, ?, ?, ?)
            """,
            (row[1], row[2], row[3], measurement_id, row[4]),
        )

    connection.exec_driver_sql("DROP TABLE measurements")
    connection.exec_driver_sql("ALTER TABLE measurements_dedup_new RENAME TO measurements")
    connection.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_measurements_dedup_key ON measurements (dedup_key)"
    )
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_measurements_ts ON measurements (timestamp)")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_measurements_upload_id ON measurements (upload_id)")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_measurements_segment_id ON measurements (segment_id)")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_measurements_channel_id ON measurements (channel_id)")
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_upload_measurement_upload_channel_ts ON upload_measurement_links (upload_id, channel_id, timestamp)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_upload_measurement_segment_ts ON upload_measurement_links (segment_id, timestamp)"
    )


def _rebuild_nibp_dedup_tables(connection: Connection) -> None:
    connection.exec_driver_sql("DROP TABLE IF EXISTS upload_nibp_event_links")
    connection.exec_driver_sql("DROP TABLE IF EXISTS nibp_events_dedup_new")

    connection.exec_driver_sql(
        """
        CREATE TABLE nibp_events_dedup_new (
            id INTEGER PRIMARY KEY,
            upload_id INTEGER NULL REFERENCES uploads(id) ON DELETE SET NULL,
            segment_id INTEGER NULL REFERENCES segments(id) ON DELETE SET NULL,
            timestamp DATETIME NOT NULL,
            channel_values JSON NOT NULL,
            has_measurement BOOLEAN NOT NULL DEFAULT 0,
            dedup_key TEXT NOT NULL UNIQUE
        )
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TABLE upload_nibp_event_links (
            id INTEGER PRIMARY KEY,
            upload_id INTEGER NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
            segment_id INTEGER NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
            nibp_event_id INTEGER NOT NULL REFERENCES nibp_events_dedup_new(id) ON DELETE CASCADE,
            timestamp DATETIME NOT NULL,
            CONSTRAINT uq_upload_segment_nibp_event UNIQUE (upload_id, segment_id, nibp_event_id)
        )
        """
    )

    nibp_rows = connection.exec_driver_sql(
        """
        SELECT id, upload_id, segment_id, timestamp, channel_values, has_measurement
        FROM nibp_events
        ORDER BY id ASC
        """
    ).fetchall()

    nibp_ids_by_key: dict[str, int] = {}
    for row in nibp_rows:
        dedup_key = build_nibp_dedup_key(timestamp=row[3])
        nibp_event_id = nibp_ids_by_key.get(dedup_key)
        if nibp_event_id is None:
            existing_row = connection.exec_driver_sql(
                "SELECT id FROM nibp_events_dedup_new WHERE dedup_key = ?",
                (dedup_key,),
            ).fetchone()
            if existing_row is None:
                connection.exec_driver_sql(
                    """
                    INSERT INTO nibp_events_dedup_new (upload_id, segment_id, timestamp, channel_values, has_measurement, dedup_key)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (row[1], row[2], row[3], row[4], row[5], dedup_key),
                )
                nibp_event_id = int(connection.exec_driver_sql("SELECT last_insert_rowid()").scalar_one())
            else:
                nibp_event_id = int(existing_row[0])
            nibp_ids_by_key[dedup_key] = nibp_event_id

        connection.exec_driver_sql(
            """
            INSERT OR IGNORE INTO upload_nibp_event_links (upload_id, segment_id, nibp_event_id, timestamp)
            VALUES (?, ?, ?, ?)
            """,
            (row[1], row[2], nibp_event_id, row[3]),
        )

    connection.exec_driver_sql("DROP TABLE nibp_events")
    connection.exec_driver_sql("ALTER TABLE nibp_events_dedup_new RENAME TO nibp_events")
    connection.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_nibp_events_dedup_key ON nibp_events (dedup_key)"
    )
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_nibp_events_ts ON nibp_events (timestamp)")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_nibp_events_upload_id ON nibp_events (upload_id)")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_nibp_events_segment_id ON nibp_events (segment_id)")
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_upload_nibp_upload_ts ON upload_nibp_event_links (upload_id, timestamp)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_upload_nibp_segment_ts ON upload_nibp_event_links (segment_id, timestamp)"
    )


def _rebuild_alarm_dedup_tables(connection: Connection) -> None:
    connection.exec_driver_sql("DROP TABLE IF EXISTS upload_alarm_links")
    connection.exec_driver_sql("DROP TABLE IF EXISTS alarms_dedup_new")

    connection.exec_driver_sql(
        """
        CREATE TABLE alarms_dedup_new (
            id INTEGER PRIMARY KEY,
            upload_id INTEGER NULL REFERENCES uploads(id) ON DELETE SET NULL,
            segment_id INTEGER NULL REFERENCES segments(id) ON DELETE SET NULL,
            timestamp DATETIME NOT NULL,
            flag_hi INTEGER NOT NULL,
            flag_lo INTEGER NOT NULL,
            alarm_category TEXT NOT NULL,
            message TEXT NOT NULL,
            dedup_key TEXT NOT NULL UNIQUE
        )
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TABLE upload_alarm_links (
            id INTEGER PRIMARY KEY,
            upload_id INTEGER NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
            segment_id INTEGER NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
            alarm_id INTEGER NOT NULL REFERENCES alarms_dedup_new(id) ON DELETE CASCADE,
            timestamp DATETIME NOT NULL,
            CONSTRAINT uq_upload_segment_alarm UNIQUE (upload_id, segment_id, alarm_id)
        )
        """
    )

    alarm_rows = connection.exec_driver_sql(
        """
        SELECT id, upload_id, segment_id, timestamp, flag_hi, flag_lo, alarm_category, message
        FROM alarms
        ORDER BY id ASC
        """
    ).fetchall()

    alarm_ids_by_key: dict[str, int] = {}
    for row in alarm_rows:
        dedup_key = build_alarm_dedup_key(
            timestamp=row[3],
            alarm_category=str(row[6]),
            flag_hi=int(row[4]),
            flag_lo=int(row[5]),
            message=str(row[7]),
        )
        alarm_id = alarm_ids_by_key.get(dedup_key)
        if alarm_id is None:
            existing_row = connection.exec_driver_sql(
                "SELECT id FROM alarms_dedup_new WHERE dedup_key = ?",
                (dedup_key,),
            ).fetchone()
            if existing_row is None:
                connection.exec_driver_sql(
                    """
                    INSERT INTO alarms_dedup_new (upload_id, segment_id, timestamp, flag_hi, flag_lo, alarm_category, message, dedup_key)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (row[1], row[2], row[3], row[4], row[5], row[6], row[7], dedup_key),
                )
                alarm_id = int(connection.exec_driver_sql("SELECT last_insert_rowid()").scalar_one())
            else:
                alarm_id = int(existing_row[0])
            alarm_ids_by_key[dedup_key] = alarm_id

        connection.exec_driver_sql(
            """
            INSERT OR IGNORE INTO upload_alarm_links (upload_id, segment_id, alarm_id, timestamp)
            VALUES (?, ?, ?, ?)
            """,
            (row[1], row[2], alarm_id, row[3]),
        )

    connection.exec_driver_sql("DROP TABLE alarms")
    connection.exec_driver_sql("ALTER TABLE alarms_dedup_new RENAME TO alarms")
    connection.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS uq_alarms_dedup_key ON alarms (dedup_key)")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_alarms_ts ON alarms (timestamp)")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_alarms_upload_id ON alarms (upload_id)")
    connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_alarms_segment_id ON alarms (segment_id)")
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_upload_alarm_upload_ts ON upload_alarm_links (upload_id, timestamp)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_upload_alarm_segment_ts ON upload_alarm_links (segment_id, timestamp)"
    )


def ensure_sqlite_upload_dedup_schema(*, bind=None, database_url: str | None = None) -> bool:
    active_engine = bind or engine
    active_database_url = database_url or settings.database_url

    if not active_database_url.startswith("sqlite"):
        return False

    changed = False
    with active_engine.begin() as connection:
        upload_table_rows = connection.exec_driver_sql("PRAGMA table_info(uploads)").fetchall()
        if not upload_table_rows:
            return False

        current_version = int(connection.exec_driver_sql("PRAGMA user_version").scalar() or 0)
        measurement_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(measurements)").fetchall()}
        dedup_ready = "dedup_key" in measurement_columns and bool(
            connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'upload_measurement_links'"
            ).fetchone()
        )

        if not dedup_ready or current_version < SQLITE_UPLOAD_DEDUP_SCHEMA_VERSION:
            _ensure_unique_upload_hashes(connection)
            _rebuild_measurement_dedup_tables(connection)
            _rebuild_nibp_dedup_tables(connection)
            _rebuild_alarm_dedup_tables(connection)
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_uploads_combined_hash ON uploads (combined_hash)"
            )
            connection.exec_driver_sql(f"PRAGMA user_version = {SQLITE_UPLOAD_DEDUP_SCHEMA_VERSION}")
            changed = True
        else:
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_uploads_combined_hash ON uploads (combined_hash)"
            )

    return changed


