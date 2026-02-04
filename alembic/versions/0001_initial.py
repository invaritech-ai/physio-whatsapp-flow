"""initial

Revision ID: 0001_initial
Revises:
Create Date: 2026-02-04

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("phone_number", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("role", sa.String(), nullable=False, server_default="customer"),
        sa.Column("conversation_state", sa.String(), nullable=False, server_default="idle"),
        sa.Column("last_proposed_start", sa.DateTime(), nullable=True),
        sa.Column("last_proposed_duration", sa.Integer(), nullable=True),
        sa.Column("active_appointment_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_user_phone_number", "user", ["phone_number"], unique=True)

    op.create_table(
        "appointment",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("start_time", sa.DateTime(), nullable=False),
        sa.Column("end_time", sa.DateTime(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="scheduled"),
        sa.Column("calendly_uuid", sa.String(), nullable=False),
        sa.Column("reminder_sent", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("physio_notified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("physio_payment_status", sa.String(), nullable=True),
        sa.Column("physio_payment_method", sa.String(), nullable=True),
    )

    op.create_table(
        "payment",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("appointment_id", sa.Integer(), sa.ForeignKey("appointment.id"), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("payment_method", sa.String(), nullable=False),
        sa.Column("proof_url", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "sessionnote",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("appointment_id", sa.Integer(), sa.ForeignKey("appointment.id"), nullable=False),
        sa.Column("note_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False, server_default="physio"),
    )


def downgrade() -> None:
    op.drop_table("sessionnote")
    op.drop_table("payment")
    op.drop_table("appointment")
    op.drop_index("ix_user_phone_number", table_name="user")
    op.drop_table("user")
