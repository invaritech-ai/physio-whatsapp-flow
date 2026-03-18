"""Send invoice/receipt PDFs to clients via WhatsApp."""

from __future__ import annotations

import logging

from app.models import Client, Receipt
from app.services.invoice_storage import resolve_invoice_pdf_url
from app.services.twilio_client import send_whatsapp_message

logger = logging.getLogger(__name__)


def send_invoice_whatsapp(*, client: Client, invoice: Receipt) -> tuple[bool, str | None]:
    """Send the invoice PDF to the client's WhatsApp number.

    Returns (sent, error_message). Never raises — all exceptions are caught
    so that receipt generation is never blocked by a WhatsApp failure.
    """
    try:
        if not client.phone_e164:
            return False, "Client has no phone number"

        if not invoice.pdf_url:
            return False, "No PDF available for this invoice"

        resolved_url = resolve_invoice_pdf_url(invoice.pdf_url)
        if not resolved_url:
            return False, "Could not resolve PDF URL"

        client_name = client.name or "Client"
        to = client.phone_e164
        if not to.startswith("whatsapp:"):
            to = f"whatsapp:{to}"

        body = f"Hi {client_name}, here is your receipt #{invoice.id}. Thank you!"

        send_whatsapp_message(to, body, media_url=[resolved_url])
        return True, None

    except Exception as exc:
        logger.exception(
            "WhatsApp send failed for invoice %s to client %s: %s",
            invoice.id,
            client.id,
            exc,
        )
        return False, str(exc)
