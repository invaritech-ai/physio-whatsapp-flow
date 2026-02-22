"""add preferred timezone to user

Revision ID: 8d9f4af7c2b6
Revises: d07c59821a15
Create Date: 2026-02-22 13:31:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "8d9f4af7c2b6"
down_revision = "d07c59821a15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("preferred_timezone", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user", "preferred_timezone")
