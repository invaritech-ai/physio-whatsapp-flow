"""add_payout_cents_to_therapist_event_type

Revision ID: c9f3a1b7e2d5
Revises: b8e2d4f1a9c3
Create Date: 2026-06-19 14:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c9f3a1b7e2d5"
down_revision = "b8e2d4f1a9c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "therapist_event_type",
        sa.Column("payout_cents", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("therapist_event_type", "payout_cents")
