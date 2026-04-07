"""make_therapist_event_type_uri_nullable

Revision ID: 3c3933060850
Revises: 3abf635015c1
Create Date: 2026-04-07 15:46:46.179303

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '3c3933060850'
down_revision = '3abf635015c1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('therapist_event_type', 'calendly_event_type_uri',
                    existing_type=sa.VARCHAR(),
                    nullable=True)


def downgrade() -> None:
    op.alter_column('therapist_event_type', 'calendly_event_type_uri',
                    existing_type=sa.VARCHAR(),
                    nullable=False)
