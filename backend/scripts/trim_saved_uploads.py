from __future__ import annotations

from app.database import SessionLocal
from app.services.upload_maintenance_service import trim_uploads_to_saved_encounter_windows, vacuum_sqlite_database


def main() -> None:
    with SessionLocal() as db:
        result = trim_uploads_to_saved_encounter_windows(db)
        vacuum_sqlite_database(db)

    print(
        "Upload maintenance complete "
        f"deleted_orphan_uploads={result.deleted_orphan_uploads} "
        f"trimmed_uploads={result.trimmed_uploads} "
        f"deleted_segments={result.deleted_segments} "
        f"deleted_periods={result.deleted_periods} "
        f"deleted_channels={result.deleted_channels} "
        f"deleted_orphan_measurements={result.deleted_orphan_measurements} "
        f"deleted_orphan_nibp_events={result.deleted_orphan_nibp_events} "
        f"deleted_orphan_alarms={result.deleted_orphan_alarms}"
    )


if __name__ == "__main__":
    main()
