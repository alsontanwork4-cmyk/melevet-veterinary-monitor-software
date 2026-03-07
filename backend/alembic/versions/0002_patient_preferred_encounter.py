"""add patient preferred encounter

Revision ID: 0002_patient_preferred_encounter
Revises: 0001_initial
Create Date: 2026-03-07 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0002_patient_preferred_encounter"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("patients") as batch_op:
        batch_op.add_column(sa.Column("preferred_encounter_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_patients_preferred_encounter_id", ["preferred_encounter_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_patients_preferred_encounter_id_encounters",
            "encounters",
            ["preferred_encounter_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("patients") as batch_op:
        batch_op.drop_constraint("fk_patients_preferred_encounter_id_encounters", type_="foreignkey")
        batch_op.drop_index("ix_patients_preferred_encounter_id")
        batch_op.drop_column("preferred_encounter_id")
