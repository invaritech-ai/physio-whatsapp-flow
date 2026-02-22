"""add flexible receipting fields to receipt

Revision ID: de8eaecb40c5
Revises: c3e9d1a4b5f7
Create Date: 2026-02-22 12:03:54.245737

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa



revision = 'de8eaecb40c5'
down_revision = 'c3e9d1a4b5f7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("receipt", sa.Column("therapist_id", sa.Integer(), nullable=True))
    op.add_column(
        "receipt",
        sa.Column(
            "service_type",
            sa.String(length=40),
            nullable=False,
            server_default="standard",
        ),
    )
    op.add_column("receipt", sa.Column("trainer_name", sa.String(length=120), nullable=True))
    op.add_column("receipt", sa.Column("reference_note", sa.Text(), nullable=True))

    op.create_index("ix_receipt_therapist_id", "receipt", ["therapist_id"], unique=False)

    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.create_foreign_key(
            "fk_receipt_therapist_id_therapist",
            "receipt",
            "therapist",
            ["therapist_id"],
            ["id"],
        )
        op.execute(
            sa.text(
                """
                UPDATE receipt AS r
                SET therapist_id = s.therapist_id
                FROM session AS s
                WHERE r.session_id = s.id
                  AND r.therapist_id IS NULL
                """
            )
        )
    else:
        op.execute(
            sa.text(
                """
                UPDATE receipt
                SET therapist_id = (
                    SELECT s.therapist_id
                    FROM session AS s
                    WHERE s.id = receipt.session_id
                )
                WHERE session_id IS NOT NULL
                  AND therapist_id IS NULL
                """
            )
        )

    op.alter_column("receipt", "service_type", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.drop_constraint(
            "fk_receipt_therapist_id_therapist",
            "receipt",
            type_="foreignkey",
        )
    op.drop_index("ix_receipt_therapist_id", table_name="receipt")

    op.drop_column("receipt", "reference_note")
    op.drop_column("receipt", "trainer_name")
    op.drop_column("receipt", "service_type")
    op.drop_column("receipt", "therapist_id")
