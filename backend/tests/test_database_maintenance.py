from __future__ import annotations

import hashlib
import json

from sqlalchemy import create_engine

from app.database import (
    COMPACT_STORAGE_USER_VERSION,
    ensure_sqlite_core_storage_compaction,
    ensure_sqlite_upload_dedup_schema,
    ensure_sqlite_upload_progress_columns,
)


def test_sqlite_upload_maintenance_backfills_combined_hash_and_index(tmp_path) -> None:
    db_path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite+pysqlite:///{db_path}")

    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE uploads (
                id INTEGER PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'completed',
                trend_sha256 TEXT NOT NULL,
                trend_index_sha256 TEXT NOT NULL,
                nibp_sha256 TEXT NOT NULL,
                nibp_index_sha256 TEXT NOT NULL,
                alarm_sha256 TEXT NOT NULL,
                alarm_index_sha256 TEXT NOT NULL,
                combined_hash TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO uploads (
                id,
                status,
                trend_sha256,
                trend_index_sha256,
                nibp_sha256,
                nibp_index_sha256,
                alarm_sha256,
                alarm_index_sha256,
                combined_hash
            ) VALUES (
                1,
                'completed',
                'trend',
                'trend-index',
                'nibp',
                'nibp-index',
                'alarm',
                'alarm-index',
                ''
            )
            """
        )

    ensure_sqlite_upload_progress_columns(bind=engine, database_url=f"sqlite+pysqlite:///{db_path}")

    expected = hashlib.sha256("trend|trend-index|nibp|nibp-index|alarm|alarm-index".encode("utf-8")).hexdigest()

    with engine.begin() as connection:
        combined_hash = connection.exec_driver_sql("SELECT combined_hash FROM uploads WHERE id = 1").scalar_one()
        indexes = connection.exec_driver_sql("PRAGMA index_list(uploads)").fetchall()

    assert combined_hash == expected
    assert any(index[1] == "ix_uploads_combined_hash_status" for index in indexes)


def test_sqlite_core_storage_compaction_prunes_rows_and_rebuilds_schema(tmp_path) -> None:
    db_path = tmp_path / "legacy-core.db"
    engine = create_engine(f"sqlite+pysqlite:///{db_path}")

    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE uploads (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE segments (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO uploads (id) VALUES (1)")
        connection.exec_driver_sql("INSERT INTO segments (id) VALUES (1)")

        connection.exec_driver_sql(
            """
            CREATE TABLE channels (
                id INTEGER PRIMARY KEY,
                upload_id INTEGER NOT NULL,
                source_type TEXT NOT NULL,
                channel_index INTEGER NOT NULL,
                name TEXT NOT NULL,
                unit TEXT NULL,
                valid_count INTEGER NOT NULL DEFAULT 0,
                invalid_count INTEGER NOT NULL DEFAULT 0,
                min_val FLOAT NULL,
                max_val FLOAT NULL,
                mean_val FLOAT NULL,
                unique_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE measurements (
                id INTEGER PRIMARY KEY,
                upload_id INTEGER NOT NULL,
                segment_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                timestamp DATETIME NOT NULL,
                value FLOAT NULL,
                frame_index INTEGER NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE nibp_events (
                id INTEGER PRIMARY KEY,
                upload_id INTEGER NOT NULL,
                segment_id INTEGER NOT NULL,
                timestamp DATETIME NOT NULL,
                channel_values JSON NOT NULL,
                has_measurement BOOLEAN NOT NULL DEFAULT 0,
                frame_index INTEGER NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE alarms (
                id INTEGER PRIMARY KEY,
                upload_id INTEGER NOT NULL,
                segment_id INTEGER NOT NULL,
                timestamp DATETIME NOT NULL,
                flag_hi INTEGER NOT NULL,
                flag_lo INTEGER NOT NULL,
                alarm_category TEXT NOT NULL,
                alarm_sub_id INTEGER NULL,
                message TEXT NOT NULL,
                frame_index INTEGER NOT NULL
            )
            """
        )

        connection.exec_driver_sql(
            """
            INSERT INTO channels (
                id, upload_id, source_type, channel_index, name, unit, valid_count, invalid_count, min_val, max_val, mean_val, unique_count
            ) VALUES
                (1, 1, 'trend', 14, 'trend_raw_be_u16_o28', NULL, 2, 0, NULL, NULL, NULL, 2),
                (2, 1, 'trend', 16, 'trend_raw_be_u16_o32', NULL, 2, 0, NULL, NULL, NULL, 2),
                (3, 1, 'trend', 25, 'trend_raw_be_u16_o50', NULL, 2, 0, NULL, NULL, NULL, 2),
                (4, 1, 'nibp', 14, 'nibp_raw_be_u16_o28', NULL, 1, 0, NULL, NULL, NULL, 1),
                (5, 1, 'nibp', 15, 'nibp_raw_be_u16_o30', NULL, 0, 0, NULL, NULL, NULL, 0),
                (6, 1, 'nibp', 16, 'nibp_raw_be_u16_o32', NULL, 1, 0, NULL, NULL, NULL, 1),
                (7, 1, 'nibp', 20, 'nibp_raw_be_u16_o40', NULL, 1, 0, NULL, NULL, NULL, 1)
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO measurements (id, upload_id, segment_id, channel_id, timestamp, value, frame_index) VALUES
                (1, 1, 1, 1, '2026-01-01T00:00:00', 98.0, 0),
                (2, 1, 1, 3, '2026-01-01T00:00:00', 123.0, 0)
            """
        )
        connection.exec_driver_sql(
            "INSERT INTO measurements (id, upload_id, segment_id, channel_id, timestamp, value, frame_index) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (row_id, 1, 1, 3, f"2026-01-01T00:00:{row_id % 60:02d}", 123.0, row_id)
                for row_id in range(3, 4003)
            ],
        )

        bloated_payload = json.dumps(
            {
                "nibp_raw_be_u16_o28": 120,
                "nibp_raw_be_u16_o30": 100,
                "nibp_raw_be_u16_o32": 90,
                "bp_systolic_inferred": 120,
                "bp_mean_inferred": 100,
                "bp_diastolic_inferred": 90,
                "unused_blob": "x" * 4000,
            }
        )
        connection.exec_driver_sql(
            """
            INSERT INTO nibp_events (id, upload_id, segment_id, timestamp, channel_values, has_measurement, frame_index)
            VALUES (1, 1, 1, '2026-01-01T00:01:00', ?, 1, 0)
            """,
            (bloated_payload,),
        )
        connection.exec_driver_sql(
            """
            INSERT INTO alarms (id, upload_id, segment_id, timestamp, flag_hi, flag_lo, alarm_category, alarm_sub_id, message, frame_index)
            VALUES (1, 1, 1, '2026-01-01T00:02:00', 1, 0, 'informational', NULL, 'alarm message', 0)
            """
        )

    size_before = db_path.stat().st_size

    changed = ensure_sqlite_core_storage_compaction(bind=engine, database_url=f"sqlite+pysqlite:///{db_path}")

    with engine.begin() as connection:
        channel_columns = [row[1] for row in connection.exec_driver_sql("PRAGMA table_info(channels)").fetchall()]
        measurement_columns = [row[1] for row in connection.exec_driver_sql("PRAGMA table_info(measurements)").fetchall()]
        nibp_columns = [row[1] for row in connection.exec_driver_sql("PRAGMA table_info(nibp_events)").fetchall()]
        alarm_columns = [row[1] for row in connection.exec_driver_sql("PRAGMA table_info(alarms)").fetchall()]
        user_version = connection.exec_driver_sql("PRAGMA user_version").scalar_one()

        channels = connection.exec_driver_sql(
            "SELECT id, source_type, channel_index, name, unit, valid_count FROM channels ORDER BY id"
        ).fetchall()
        measurements = connection.exec_driver_sql(
            "SELECT id, channel_id, value FROM measurements ORDER BY id"
        ).fetchall()
        nibp_row = connection.exec_driver_sql(
            "SELECT channel_values, has_measurement FROM nibp_events WHERE id = 1"
        ).fetchone()
        alarms = connection.exec_driver_sql(
            "SELECT flag_hi, flag_lo, alarm_category, message FROM alarms WHERE id = 1"
        ).fetchall()

    assert changed is True
    assert channel_columns == ["id", "upload_id", "source_type", "channel_index", "name", "unit", "valid_count"]
    assert measurement_columns == ["id", "upload_id", "segment_id", "channel_id", "timestamp", "value"]
    assert nibp_columns == ["id", "upload_id", "segment_id", "timestamp", "channel_values", "has_measurement"]
    assert alarm_columns == ["id", "upload_id", "segment_id", "timestamp", "flag_hi", "flag_lo", "alarm_category", "message"]
    assert user_version == COMPACT_STORAGE_USER_VERSION

    assert channels == [
        (1, "trend", 14, "spo2_be_u16", "%", 2),
        (2, "trend", 16, "heart_rate_be_u16", "bpm", 2),
        (4, "nibp", 14, "bp_systolic_inferred", "mmHg", 1),
        (5, "nibp", 15, "bp_mean_inferred", "mmHg", 0),
        (6, "nibp", 16, "bp_diastolic_inferred", "mmHg", 1),
    ]
    assert measurements == [(1, 1, 98.0)]
    assert nibp_row is not None
    assert json.loads(nibp_row[0]) == {
        "bp_systolic_inferred": 120,
        "bp_mean_inferred": 100,
        "bp_diastolic_inferred": 90,
    }
    assert nibp_row[1] == 1
    assert alarms == [(1, 0, "informational", "alarm message")]
    assert db_path.stat().st_size < size_before


def test_sqlite_upload_dedup_schema_backfills_canonical_rows_and_links(tmp_path) -> None:
    db_path = tmp_path / "legacy-dedup.db"
    engine = create_engine(f"sqlite+pysqlite:///{db_path}")

    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE uploads (
                id INTEGER PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'completed',
                trend_sha256 TEXT NOT NULL,
                trend_index_sha256 TEXT NOT NULL,
                nibp_sha256 TEXT NOT NULL,
                nibp_index_sha256 TEXT NOT NULL,
                alarm_sha256 TEXT NOT NULL,
                alarm_index_sha256 TEXT NOT NULL,
                combined_hash TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.exec_driver_sql("CREATE TABLE segments (id INTEGER PRIMARY KEY, upload_id INTEGER NOT NULL)")
        connection.exec_driver_sql(
            """
            CREATE TABLE channels (
                id INTEGER PRIMARY KEY,
                upload_id INTEGER NOT NULL,
                source_type TEXT NOT NULL,
                channel_index INTEGER NOT NULL,
                name TEXT NOT NULL,
                unit TEXT NULL,
                valid_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE measurements (
                id INTEGER PRIMARY KEY,
                upload_id INTEGER NOT NULL,
                segment_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                timestamp DATETIME NOT NULL,
                value FLOAT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE nibp_events (
                id INTEGER PRIMARY KEY,
                upload_id INTEGER NOT NULL,
                segment_id INTEGER NOT NULL,
                timestamp DATETIME NOT NULL,
                channel_values JSON NOT NULL,
                has_measurement BOOLEAN NOT NULL DEFAULT 0
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE alarms (
                id INTEGER PRIMARY KEY,
                upload_id INTEGER NOT NULL,
                segment_id INTEGER NOT NULL,
                timestamp DATETIME NOT NULL,
                flag_hi INTEGER NOT NULL,
                flag_lo INTEGER NOT NULL,
                alarm_category TEXT NOT NULL,
                message TEXT NOT NULL
            )
            """
        )

        checksum_a = "a" * 64
        checksum_b = "b" * 64
        connection.exec_driver_sql(
            """
            INSERT INTO uploads (
                id, status, trend_sha256, trend_index_sha256, nibp_sha256, nibp_index_sha256, alarm_sha256, alarm_index_sha256, combined_hash
            ) VALUES
                (1, 'completed', ?, ?, ?, ?, ?, ?, ?),
                (2, 'completed', ?, ?, ?, ?, ?, ?, ?)
            """,
            (checksum_a, checksum_a, checksum_a, checksum_a, checksum_a, checksum_a, checksum_a,
             checksum_b, checksum_b, checksum_b, checksum_b, checksum_b, checksum_b, checksum_b),
        )
        connection.exec_driver_sql("INSERT INTO segments (id, upload_id) VALUES (1, 1), (2, 2)")
        connection.exec_driver_sql(
            """
            INSERT INTO channels (id, upload_id, source_type, channel_index, name, unit, valid_count) VALUES
                (1, 1, 'trend', 16, 'heart_rate_be_u16', 'bpm', 1),
                (2, 2, 'trend', 16, 'heart_rate_be_u16', 'bpm', 1)
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO measurements (id, upload_id, segment_id, channel_id, timestamp, value) VALUES
                (1, 1, 1, 1, '2026-01-01T00:00:00', 88.0),
                (2, 2, 2, 2, '2026-01-01T00:00:00', 88.0),
                (3, 2, 2, 2, '2026-01-01T00:01:00', 89.0)
            """
        )

    ensure_sqlite_upload_progress_columns(bind=engine, database_url=f"sqlite+pysqlite:///{db_path}")
    changed = ensure_sqlite_upload_dedup_schema(bind=engine, database_url=f"sqlite+pysqlite:///{db_path}")

    with engine.begin() as connection:
        measurement_columns = [row[1] for row in connection.exec_driver_sql("PRAGMA table_info(measurements)").fetchall()]
        measurement_count = connection.exec_driver_sql("SELECT COUNT(*) FROM measurements").scalar_one()
        measurement_link_count = connection.exec_driver_sql("SELECT COUNT(*) FROM upload_measurement_links").scalar_one()
        reused_upload_count = connection.exec_driver_sql(
            "SELECT COUNT(*) FROM upload_measurement_links WHERE upload_id = 2"
        ).scalar_one()

    assert changed is True
    assert "dedup_key" in measurement_columns
    assert measurement_count == 2
    assert measurement_link_count == 3
    assert reused_upload_count == 2
