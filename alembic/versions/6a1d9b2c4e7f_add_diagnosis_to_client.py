"""add diagnosis to client

Revision ID: 6a1d9b2c4e7f
Revises: 3c3933060850
Create Date: 2026-04-20 01:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6a1d9b2c4e7f"
down_revision = "3c3933060850"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("client", sa.Column("diagnosis", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("client", "diagnosis")
