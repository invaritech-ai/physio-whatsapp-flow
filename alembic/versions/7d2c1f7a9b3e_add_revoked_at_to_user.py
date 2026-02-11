"""add revoked_at to user

Revision ID: 7d2c1f7a9b3e
Revises: 21c691d3f693
Create Date: 2026-02-11 12:30:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "7d2c1f7a9b3e"
down_revision = "21c691d3f693"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user", sa.Column("revoked_at", sa.DateTime(), nullable=True))
    op.create_index(op.f("ix_user_revoked_at"), "user", ["revoked_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_user_revoked_at"), table_name="user")
    op.drop_column("user", "revoked_at")
