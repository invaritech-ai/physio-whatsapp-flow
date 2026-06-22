"""make therapist_event_type.scheduling_url nullable

Revision ID: e7a3c2f1d9b4
Revises: d5e2f3a1b7c8
Create Date: 2026-06-22 16:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e7a3c2f1d9b4"
down_revision = "d5e2f3a1b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "therapist_event_type",
        "scheduling_url",
        existing_type=sa.String(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "therapist_event_type",
        "scheduling_url",
        existing_type=sa.String(),
        nullable=False,
    )
