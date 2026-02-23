"""add_financial_triggers

Revision ID: ad3233c7e17f
Revises: aa6950b50814
Create Date: 2026-02-23 22:19:56.442604

"""

from __future__ import annotations

from alembic import op


revision = 'ad3233c7e17f'
down_revision = 'aa6950b50814'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION update_client_financial_totals()
        RETURNS TRIGGER AS $$
        DECLARE
            v_client_id INTEGER;
        BEGIN
            IF TG_TABLE_NAME = 'payment_record' THEN
                IF TG_OP = 'DELETE' THEN
                    v_client_id := OLD.client_id;
                ELSE
                    v_client_id := NEW.client_id;
                END IF;
            ELSIF TG_TABLE_NAME = 'receipt' THEN
                IF TG_OP = 'DELETE' THEN
                    v_client_id := OLD.client_id;
                ELSE
                    v_client_id := NEW.client_id;
                END IF;
            END IF;

            INSERT INTO client_financial (client_id, total_paid_cents, total_receipted_cents, currency, updated_at)
            SELECT 
                v_client_id,
                COALESCE((
                    SELECT SUM(amount_cents)
                    FROM payment_record
                    WHERE client_id = v_client_id AND status = 'confirmed'
                ), 0),
                COALESCE((
                    SELECT SUM(amount_cents)
                    FROM receipt
                    WHERE client_id = v_client_id AND status = 'issued'
                ), 0),
                COALESCE((
                    SELECT currency
                    FROM payment_record
                    WHERE client_id = v_client_id AND status = 'confirmed'
                    LIMIT 1
                ), 'HKD'),
                NOW()
            ON CONFLICT (client_id) DO UPDATE SET
                total_paid_cents = EXCLUDED.total_paid_cents,
                total_receipted_cents = EXCLUDED.total_receipted_cents,
                currency = EXCLUDED.currency,
                updated_at = NOW();

            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            ELSE
                RETURN NEW;
            END IF;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER trg_payment_record_update_financial
        AFTER INSERT OR UPDATE OR DELETE ON payment_record
        FOR EACH ROW
        WHEN (pg_trigger_depth() = 0)
        EXECUTE FUNCTION update_client_financial_totals();
    """)

    op.execute("""
        CREATE TRIGGER trg_receipt_update_financial
        AFTER INSERT OR UPDATE OR DELETE ON receipt
        FOR EACH ROW
        WHEN (pg_trigger_depth() = 0)
        EXECUTE FUNCTION update_client_financial_totals();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_receipt_update_financial ON receipt")
    op.execute("DROP TRIGGER IF EXISTS trg_payment_record_update_financial ON payment_record")
    op.execute("DROP FUNCTION IF EXISTS update_client_financial_totals()")
