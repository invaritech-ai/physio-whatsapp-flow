"""add auth event table

Revision ID: 9b4c2d1a6e5f
Revises: 7d2c1f7a9b3e
Create Date: 2026-02-11 13:10:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "9b4c2d1a6e5f"
down_revision = "7d2c1f7a9b3e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("user_sub", sa.String(), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("details_json", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_auth_event_actor_user_id"), "auth_event", ["actor_user_id"], unique=False)
    op.create_index(op.f("ix_auth_event_created_at"), "auth_event", ["created_at"], unique=False)
    op.create_index(op.f("ix_auth_event_event_type"), "auth_event", ["event_type"], unique=False)
    op.create_index(op.f("ix_auth_event_reason"), "auth_event", ["reason"], unique=False)
    op.create_index(op.f("ix_auth_event_user_id"), "auth_event", ["user_id"], unique=False)
    op.create_index(op.f("ix_auth_event_user_sub"), "auth_event", ["user_sub"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_auth_event_user_sub"), table_name="auth_event")
    op.drop_index(op.f("ix_auth_event_user_id"), table_name="auth_event")
    op.drop_index(op.f("ix_auth_event_reason"), table_name="auth_event")
    op.drop_index(op.f("ix_auth_event_event_type"), table_name="auth_event")
    op.drop_index(op.f("ix_auth_event_created_at"), table_name="auth_event")
    op.drop_index(op.f("ix_auth_event_actor_user_id"), table_name="auth_event")
    op.drop_table("auth_event")
