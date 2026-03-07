"""create initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-03-04 00:00:00
"""

from __future__ import annotations

from alembic import op

from app.database import Base
from app.models import *  # noqa: F403, F401

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)