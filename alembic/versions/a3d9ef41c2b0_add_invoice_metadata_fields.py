"""add invoice metadata fields

Revision ID: a3d9ef41c2b0
Revises: f2a1c9d4b7e8
Create Date: 2026-02-19 16:35:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a3d9ef41c2b0"
down_revision = "f2a1c9d4b7e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("receipt", sa.Column("payment_mode", sa.String(length=120), nullable=True))
    op.add_column("receipt", sa.Column("diagnosis", sa.Text(), nullable=True))
    op.add_column("receipt", sa.Column("special_notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("receipt", "special_notes")
    op.drop_column("receipt", "diagnosis")
    op.drop_column("receipt", "payment_mode")
