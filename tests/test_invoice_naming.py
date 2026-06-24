from __future__ import annotations

from datetime import datetime, timezone

from app.services.naming import invoice_filename


def test_invoice_filename_slugifies_client_name() -> None:
    name = invoice_filename(
        invoice_id=7,
        client_name="  Jane   Doe / PT  ",
        date_value=datetime(2026, 5, 6, 8, 0, tzinfo=timezone.utc),
    )
    assert name == "jane-doe-pt_2026-05-06_MOVEMENT_PHYSIOTHERAPY_RECEIPT_7.pdf"


def test_invoice_filename_falls_back_when_client_name_missing() -> None:
    name = invoice_filename(
        invoice_id=42,
        client_name=None,
        date_value=datetime(2026, 5, 6, 8, 0, tzinfo=timezone.utc),
    )
    assert name == "client-42_2026-05-06_MOVEMENT_PHYSIOTHERAPY_RECEIPT_42.pdf"


def test_invoice_filename_applies_invoice_timezone_for_date_part(monkeypatch) -> None:
    from app.services import naming

    monkeypatch.setattr(naming.settings, "invoice_timezone", "Asia/Hong_Kong")
    name = naming.invoice_filename(
        invoice_id=9,
        client_name="Alex",
        date_value=datetime(2026, 5, 6, 16, 30, tzinfo=timezone.utc),
    )
    assert name == "alex_2026-05-07_MOVEMENT_PHYSIOTHERAPY_RECEIPT_9.pdf"
