"""add encrypted PAT to therapist

Revision ID: 533a19db5a8b
Revises: ab5432edcf4e
Create Date: 2026-02-09 16:06:18.754373

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa



revision = '533a19db5a8b'
down_revision = 'ab5432edcf4e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add calendly_pat_encrypted column to therapist table
    op.add_column('therapist', sa.Column('calendly_pat_encrypted', sa.String(), nullable=True))


def downgrade() -> None:
    # Remove calendly_pat_encrypted column
    op.drop_column('therapist', 'calendly_pat_encrypted')
