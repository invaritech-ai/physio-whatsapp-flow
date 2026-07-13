"""make therapist_event_type.scheduling_url nullable

Allows admins to record an offered session length (with a payout) before a
Calendly booking link exists; the link is filled in later.

Revision ID: d4e5f6a7b8c9
Revises: c9f3a1b7e2d5
Create Date: 2026-07-13 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "c9f3a1b7e2d5"
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
