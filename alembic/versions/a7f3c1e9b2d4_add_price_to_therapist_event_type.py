

"""add_price_to_therapist_event_type

Revision ID: a7f3c1e9b2d4
Revises: 6a1d9b2c4e7f
Create Date: 2026-06-19 12:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a7f3c1e9b2d4"
down_revision = "6a1d9b2c4e7f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "therapist_event_type",
        sa.Column("amount_cents", sa.Integer(), nullable=True),
    )
    op.add_column(
        "therapist_event_type",
        sa.Column("currency", sa.String(length=8), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("therapist_event_type", "currency")
    op.drop_column("therapist_event_type", "amount_cents")
