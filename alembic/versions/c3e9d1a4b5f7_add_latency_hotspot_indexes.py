"""add latency hotspot indexes

Revision ID: c3e9d1a4b5f7
Revises: b4c8d2f1e9a3
Create Date: 2026-02-22 02:40:00.000000
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "c3e9d1a4b5f7"
down_revision = "b4c8d2f1e9a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_session_calendly_invitee_uri",
        "session",
        ["calendly_invitee_uri"],
        unique=False,
    )
    op.create_index(
        "ix_session_therapist_id_start_time",
        "session",
        ["therapist_id", "start_time"],
        unique=False,
    )
    op.create_index(
        "ix_session_client_id_start_time",
        "session",
        ["client_id", "start_time"],
        unique=False,
    )
    op.create_index(
        "ix_receipt_client_id_created_at",
        "receipt",
        ["client_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_receipt_session_id_created_at",
        "receipt",
        ["session_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_payment_record_session_id_created_at",
        "payment_record",
        ["session_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_session_note_session_id_author_user_id_created_at",
        "session_note",
        ["session_id", "author_user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_session_note_session_id_author_user_id_created_at",
        table_name="session_note",
    )
    op.drop_index(
        "ix_payment_record_session_id_created_at",
        table_name="payment_record",
    )
    op.drop_index(
        "ix_receipt_session_id_created_at",
        table_name="receipt",
    )
    op.drop_index(
        "ix_receipt_client_id_created_at",
        table_name="receipt",
    )
    op.drop_index(
        "ix_session_client_id_start_time",
        table_name="session",
    )
    op.drop_index(
        "ix_session_therapist_id_start_time",
        table_name="session",
    )
    op.drop_index(
        "ix_session_calendly_invitee_uri",
        table_name="session",
    )
