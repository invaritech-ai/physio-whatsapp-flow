"""add license number to therapist

Revision ID: f2a1c9d4b7e8
Revises: e1b4f20a7c9d
Create Date: 2026-02-19 16:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f2a1c9d4b7e8"
down_revision = "e1b4f20a7c9d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("therapist", sa.Column("license_number", sa.String(length=64), nullable=True))
    op.create_index("ix_therapist_license_number", "therapist", ["license_number"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_therapist_license_number", table_name="therapist")
    op.drop_column("therapist", "license_number")
