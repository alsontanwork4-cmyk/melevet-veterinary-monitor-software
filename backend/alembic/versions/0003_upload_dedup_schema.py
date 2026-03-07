"""add upload dedup schema

Revision ID: 0003_upload_dedup_schema
Revises: 0002_patient_preferred_encounter
Create Date: 2026-03-07 00:00:00
"""

from __future__ import annotations

from alembic import op

from app.database import (
    ensure_sqlite_upload_dedup_schema,
    ensure_sqlite_upload_progress_columns,
)

# revision identifiers, used by Alembic.
revision = "0003_upload_dedup_schema"
down_revision = "0002_patient_preferred_encounter"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    ensure_sqlite_upload_progress_columns(bind=bind.engine, database_url=str(bind.engine.url))
    ensure_sqlite_upload_dedup_schema(bind=bind.engine, database_url=str(bind.engine.url))


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for the upload dedup schema migration.")
