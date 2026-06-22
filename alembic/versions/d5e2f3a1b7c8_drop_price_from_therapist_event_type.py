

"""drop_price_from_therapist_event_type

Revision ID: d5e2f3a1b7c8
Revises: c9f3a1b7e2d5
Create Date: 2026-06-22 12:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d5e2f3a1b7c8"
down_revision = "c9f3a1b7e2d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("therapist_event_type", "currency")
    op.drop_column("therapist_event_type", "amount_cents")


def downgrade() -> None:
    op.add_column(
        "therapist_event_type",
        sa.Column("amount_cents", sa.Integer(), nullable=True),
    )
    op.add_column(
        "therapist_event_type",
        sa.Column("currency", sa.String(length=8), nullable=True),
    )
