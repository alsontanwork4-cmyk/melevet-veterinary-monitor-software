from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.database import SessionLocal  # noqa: E402
from app.services.channel_mapping import load_channel_map  # noqa: E402
from app.services.channel_metadata_backfill import backfill_channel_metadata  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill channel display metadata using the current channel_map.json rules."
    )
    parser.add_argument("--upload-id", type=int, default=None, help="Optional upload id to backfill.")
    args = parser.parse_args()

    # Ensure mapping changes are picked up for this process.
    load_channel_map.cache_clear()

    db = SessionLocal()
    try:
        result = backfill_channel_metadata(db, upload_id=args.upload_id)
    finally:
        db.close()

    scope = f"upload_id={args.upload_id}" if args.upload_id is not None else "all uploads"
    print(f"Backfill completed for {scope}: scanned={result.scanned}, updated={result.updated}")


if __name__ == "__main__":
    main()
