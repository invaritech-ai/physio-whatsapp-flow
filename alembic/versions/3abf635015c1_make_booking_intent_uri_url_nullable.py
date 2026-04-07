"""make_booking_intent_uri_url_nullable

Revision ID: 3abf635015c1
Revises: 6f2e4b9c1d7a
Create Date: 2026-04-07 15:42:09.828498

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '3abf635015c1'
down_revision = '6f2e4b9c1d7a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('booking_intent', 'calendly_event_type_uri',
                    existing_type=sa.VARCHAR(),
                    nullable=True)
    op.alter_column('booking_intent', 'scheduling_url',
                    existing_type=sa.VARCHAR(),
                    nullable=True)


def downgrade() -> None:
    op.alter_column('booking_intent', 'scheduling_url',
                    existing_type=sa.VARCHAR(),
                    nullable=False)
    op.alter_column('booking_intent', 'calendly_event_type_uri',
                    existing_type=sa.VARCHAR(),
                    nullable=False)
