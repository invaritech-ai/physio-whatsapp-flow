from types import SimpleNamespace
from unittest.mock import patch

from app.services.invoice_whatsapp import send_invoice_whatsapp


def _client(*, phone: str = "+85250000001", name: str = "Avi") -> SimpleNamespace:
    return SimpleNamespace(id=9, phone_e164=phone, name=name)


def _invoice(
    *,
    invoice_id: int = 12,
    client_id: int = 9,
    pdf_url: str = "s3://bucket/invoices/invoice-12.pdf",
) -> SimpleNamespace:
    return SimpleNamespace(id=invoice_id, client_id=client_id, pdf_url=pdf_url)


def test_send_invoice_whatsapp_uses_template_when_content_sid_configured(monkeypatch):
    monkeypatch.setattr("app.services.invoice_whatsapp.settings.twilio_whatsapp_receipt_content_sid", "HX1234567890")
    monkeypatch.setattr("app.services.invoice_whatsapp.settings.twilio_whatsapp_receipt_media_var_index", 3)

    with patch(
        "app.services.invoice_whatsapp.resolve_invoice_pdf_url",
        return_value="https://files.example.com/invoice-12.pdf",
    ), patch(
        "app.services.invoice_whatsapp.send_whatsapp_message",
        return_value="SM123",
    ) as mock_send:
        sent, error = send_invoice_whatsapp(client=_client(), invoice=_invoice())

    assert sent is True
    assert error is None
    mock_send.assert_called_once_with(
        "whatsapp:+85250000001",
        body=None,
        content_sid="HX1234567890",
        content_variables={
            "1": "Avi",
            "2": "12-P09",
            "3": "https://files.example.com/invoice-12.pdf",
        },
    )


def test_send_invoice_whatsapp_uses_freeform_when_template_not_configured(monkeypatch):
    monkeypatch.setattr("app.services.invoice_whatsapp.settings.twilio_whatsapp_receipt_content_sid", None)
    monkeypatch.setattr("app.services.invoice_whatsapp.settings.twilio_whatsapp_receipt_media_var_index", None)

    with patch(
        "app.services.invoice_whatsapp.resolve_invoice_pdf_url",
        return_value="https://files.example.com/invoice-12.pdf",
    ), patch(
        "app.services.invoice_whatsapp.send_whatsapp_message",
        return_value="SM123",
    ) as mock_send:
        sent, error = send_invoice_whatsapp(client=_client(), invoice=_invoice())

    assert sent is True
    assert error is None
    mock_send.assert_called_once_with(
        "whatsapp:+85250000001",
        "Hi Avi, here is your receipt #12. Thank you!",
        media_url=["https://files.example.com/invoice-12.pdf"],
    )


def test_send_invoice_whatsapp_rejects_template_media_index_collision(monkeypatch):
    monkeypatch.setattr("app.services.invoice_whatsapp.settings.twilio_whatsapp_receipt_content_sid", "HX1234567890")
    monkeypatch.setattr("app.services.invoice_whatsapp.settings.twilio_whatsapp_receipt_media_var_index", 2)

    with patch(
        "app.services.invoice_whatsapp.resolve_invoice_pdf_url",
        return_value="https://files.example.com/invoice-12.pdf",
    ), patch("app.services.invoice_whatsapp.send_whatsapp_message") as mock_send:
        sent, error = send_invoice_whatsapp(client=_client(), invoice=_invoice())

    assert sent is False
    assert "cannot be 1 or 2" in (error or "")
    mock_send.assert_not_called()
