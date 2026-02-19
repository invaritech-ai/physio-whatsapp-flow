"""add plans assignments and payment metadata

Revision ID: b4c8d2f1e9a3
Revises: a3d9ef41c2b0
Create Date: 2026-02-19 18:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b4c8d2f1e9a3"
down_revision = "a3d9ef41c2b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "billing_plan",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_billing_plan_duration_minutes", "billing_plan", ["duration_minutes"], unique=False)

    op.create_table(
        "client_plan_assignment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("billing_plan_id", sa.Integer(), nullable=False),
        sa.Column("assigned_by_user_id", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["assigned_by_user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["billing_plan_id"], ["billing_plan.id"]),
        sa.ForeignKeyConstraint(["client_id"], ["client.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "client_id",
            "duration_minutes",
            name="uq_client_plan_assignment_client_duration",
        ),
    )
    op.create_index(
        "ix_client_plan_assignment_billing_plan_id",
        "client_plan_assignment",
        ["billing_plan_id"],
        unique=False,
    )
    op.create_index(
        "ix_client_plan_assignment_client_id",
        "client_plan_assignment",
        ["client_id"],
        unique=False,
    )
    op.create_index(
        "ix_client_plan_assignment_duration_minutes",
        "client_plan_assignment",
        ["duration_minutes"],
        unique=False,
    )
    op.create_index(
        "ix_client_plan_assignment_assigned_by_user_id",
        "client_plan_assignment",
        ["assigned_by_user_id"],
        unique=False,
    )

    op.add_column("payment_record", sa.Column("received_by_role", sa.String(length=20), nullable=True))
    op.add_column("payment_record", sa.Column("received_by_name", sa.String(length=120), nullable=True))
    op.add_column("payment_record", sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payment_record", sa.Column("reference", sa.String(length=255), nullable=True))
    op.add_column("payment_record", sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("payment_record", "notes")
    op.drop_column("payment_record", "reference")
    op.drop_column("payment_record", "paid_at")
    op.drop_column("payment_record", "received_by_name")
    op.drop_column("payment_record", "received_by_role")

    op.drop_index("ix_client_plan_assignment_assigned_by_user_id", table_name="client_plan_assignment")
    op.drop_index("ix_client_plan_assignment_duration_minutes", table_name="client_plan_assignment")
    op.drop_index("ix_client_plan_assignment_client_id", table_name="client_plan_assignment")
    op.drop_index("ix_client_plan_assignment_billing_plan_id", table_name="client_plan_assignment")
    op.drop_table("client_plan_assignment")

    op.drop_index("ix_billing_plan_duration_minutes", table_name="billing_plan")
    op.drop_table("billing_plan")
