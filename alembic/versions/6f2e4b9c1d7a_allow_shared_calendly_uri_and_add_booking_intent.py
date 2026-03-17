"""allow shared calendly uri and add booking intent

Revision ID: 6f2e4b9c1d7a
Revises: b1e7f3c9d2a4
Create Date: 2026-03-17 16:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6f2e4b9c1d7a"
down_revision = "b1e7f3c9d2a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index(
        "ix_therapist_event_type_calendly_event_type_uri",
        table_name="therapist_event_type",
    )
    op.create_index(
        "ix_therapist_event_type_calendly_event_type_uri",
        "therapist_event_type",
        ["calendly_event_type_uri"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_therapist_event_type_therapist_duration",
        "therapist_event_type",
        ["therapist_id", "duration_minutes"],
    )

    op.create_table(
        "booking_intent",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("therapist_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=True),
        sa.Column("client_phone_e164", sa.String(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("calendly_event_type_uri", sa.String(), nullable=False),
        sa.Column("scheduling_url", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.ForeignKeyConstraint(["therapist_id"], ["therapist.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_booking_intent_therapist_id", "booking_intent", ["therapist_id"], unique=False)
    op.create_index("ix_booking_intent_client_id", "booking_intent", ["client_id"], unique=False)
    op.create_index("ix_booking_intent_client_phone_e164", "booking_intent", ["client_phone_e164"], unique=False)
    op.create_index(
        "ix_booking_intent_calendly_event_type_uri",
        "booking_intent",
        ["calendly_event_type_uri"],
        unique=False,
    )
    op.create_index("ix_booking_intent_consumed_at", "booking_intent", ["consumed_at"], unique=False)
    op.create_index("ix_booking_intent_created_at", "booking_intent", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_booking_intent_created_at", table_name="booking_intent")
    op.drop_index("ix_booking_intent_consumed_at", table_name="booking_intent")
    op.drop_index("ix_booking_intent_calendly_event_type_uri", table_name="booking_intent")
    op.drop_index("ix_booking_intent_client_phone_e164", table_name="booking_intent")
    op.drop_index("ix_booking_intent_client_id", table_name="booking_intent")
    op.drop_index("ix_booking_intent_therapist_id", table_name="booking_intent")
    op.drop_table("booking_intent")

    op.drop_constraint(
        "uq_therapist_event_type_therapist_duration",
        "therapist_event_type",
        type_="unique",
    )
    op.drop_index(
        "ix_therapist_event_type_calendly_event_type_uri",
        table_name="therapist_event_type",
    )
    op.create_index(
        "ix_therapist_event_type_calendly_event_type_uri",
        "therapist_event_type",
        ["calendly_event_type_uri"],
        unique=True,
    )
