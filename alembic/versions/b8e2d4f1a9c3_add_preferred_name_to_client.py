"""add_preferred_name_to_client

Revision ID: b8e2d4f1a9c3
Revises: a7f3c1e9b2d4
Create Date: 2026-06-19 13:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b8e2d4f1a9c3"
down_revision = "a7f3c1e9b2d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "client",
        sa.Column("preferred_name", sa.String(length=120), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("client", "preferred_name")
