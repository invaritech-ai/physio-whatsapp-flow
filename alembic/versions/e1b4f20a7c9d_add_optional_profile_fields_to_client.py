"""add optional profile fields to client

Revision ID: e1b4f20a7c9d
Revises: c6a8f3d9e2b1
Create Date: 2026-02-19 12:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e1b4f20a7c9d"
down_revision = "c6a8f3d9e2b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("client", sa.Column("email", sa.String(), nullable=True))
    op.add_column("client", sa.Column("date_of_birth", sa.Date(), nullable=True))
    op.add_column("client", sa.Column("address", sa.Text(), nullable=True))
    op.create_index("ix_client_email", "client", ["email"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_client_email", table_name="client")
    op.drop_column("client", "address")
    op.drop_column("client", "date_of_birth")
    op.drop_column("client", "email")
