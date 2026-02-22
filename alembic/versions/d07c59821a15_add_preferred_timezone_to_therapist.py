"""add preferred timezone to therapist

Revision ID: d07c59821a15
Revises: de8eaecb40c5
Create Date: 2026-02-22 12:48:59.403974

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa



revision = 'd07c59821a15'
down_revision = 'de8eaecb40c5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "therapist",
        sa.Column("preferred_timezone", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("therapist", "preferred_timezone")
