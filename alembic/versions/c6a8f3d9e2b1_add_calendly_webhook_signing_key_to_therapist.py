"""add encrypted calendly webhook signing key to therapist

Revision ID: c6a8f3d9e2b1
Revises: 9b4c2d1a6e5f
Create Date: 2026-02-12 12:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c6a8f3d9e2b1"
down_revision = "9b4c2d1a6e5f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "therapist",
        sa.Column("calendly_webhook_signing_key_encrypted", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("therapist", "calendly_webhook_signing_key_encrypted")
