"""add_is_female_to_therapist

Revision ID: b1e7f3c9d2a4
Revises: ad3233c7e17f
Create Date: 2026-02-24 12:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b1e7f3c9d2a4"
down_revision = "ad3233c7e17f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "therapist",
        sa.Column("is_female", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("therapist", "is_female")
