"""add_idempotency_key_table

Revision ID: aa6950b50814
Revises: df03baf0ef2f
Create Date: 2026-02-23 22:03:36.479656

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = 'aa6950b50814'
down_revision = 'df03baf0ef2f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'idempotency_key',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('idempotency_key', sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False),
        sa.Column('endpoint', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('request_hash', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column('response_status', sa.Integer(), nullable=False),
        sa.Column('response_json', sa.Text(), nullable=False),
        sa.Column('status', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_idempotency_key_created_at'), 'idempotency_key', ['created_at'], unique=False)
    op.create_index(op.f('ix_idempotency_key_endpoint'), 'idempotency_key', ['endpoint'], unique=False)
    op.create_index(op.f('ix_idempotency_key_expires_at'), 'idempotency_key', ['expires_at'], unique=False)
    op.create_index(op.f('ix_idempotency_key_idempotency_key'), 'idempotency_key', ['idempotency_key'], unique=True)
    op.create_index(op.f('ix_idempotency_key_status'), 'idempotency_key', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_idempotency_key_status'), table_name='idempotency_key')
    op.drop_index(op.f('ix_idempotency_key_idempotency_key'), table_name='idempotency_key')
    op.drop_index(op.f('ix_idempotency_key_expires_at'), table_name='idempotency_key')
    op.drop_index(op.f('ix_idempotency_key_endpoint'), table_name='idempotency_key')
    op.drop_index(op.f('ix_idempotency_key_created_at'), table_name='idempotency_key')
    op.drop_table('idempotency_key')
