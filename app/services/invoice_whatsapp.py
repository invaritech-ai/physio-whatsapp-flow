"""Send invoice/receipt PDFs to clients via WhatsApp."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from app.core.config import settings
from app.models import Client, Receipt
from app.services.invoice_storage import resolve_invoice_pdf_url
from app.services.twilio_client import send_whatsapp_message

logger = logging.getLogger(__name__)


def _whatsapp_media_url_error(url: str) -> str | None:
    """Twilio WhatsApp requires a publicly reachable HTTPS URL for media (prod)."""
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme == "https":
        return None
    if scheme == "http" and settings.app_env.strip().lower() in ("development", "dev", "local"):
        return None
    if scheme in ("", "s3") or url.startswith("s3://"):
        return (
            "PDF URL must be resolved to HTTPS before WhatsApp (got s3:// or missing scheme). "
            "Configure invoice S3 endpoint and credentials for pre-signed URLs, or INVOICE_S3_PUBLIC_BASE_URL."
        )
    return (
        f"PDF URL must use HTTPS for WhatsApp media (got scheme {parsed.scheme!r}). "
        "Set INVOICE_S3_PUBLIC_BASE_URL to a public bucket URL or use an endpoint Twilio can reach."
    )


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

        media_err = _whatsapp_media_url_error(resolved_url)
        if media_err:
            logger.warning(
                "Skipping WhatsApp media for invoice %s: %s preview=%r",
                invoice.id,
                media_err,
                resolved_url[:160],
            )
            return False, media_err

        client_name = client.name or "Client"
        to = client.phone_e164
        if not to.startswith("whatsapp:"):
            to = f"whatsapp:{to}"

        body = f"Hi {client_name}, here is your receipt #{invoice.id}. Thank you!"
        template_sid = (settings.twilio_whatsapp_receipt_content_sid or "").strip()
        template_media_var_index = settings.twilio_whatsapp_receipt_media_var_index
        invoice_reference = f"{invoice.id}-P{invoice.client_id:02d}"
        if template_sid:
            content_variables: dict[str, str] = {
                "1": client_name,
                "2": invoice_reference,
            }
            if template_media_var_index is not None:
                if template_media_var_index in (1, 2):
                    return (
                        False,
                        "TWILIO_WHATSAPP_RECEIPT_MEDIA_VAR_INDEX cannot be 1 or 2 "
                        "(reserved for client name and receipt id).",
                    )
                content_variables[str(template_media_var_index)] = resolved_url
            sid = send_whatsapp_message(
                to,
                body=None,
                content_sid=template_sid,
                content_variables=content_variables,
            )
        else:
            sid = send_whatsapp_message(to, body, media_url=[resolved_url])
        logger.info(
            "Invoice %s WhatsApp message created sid=%s to=%s media_host=%s template_sid=%s",
            invoice.id,
            sid,
            to,
            urlparse(resolved_url).netloc,
            template_sid or "-",
        )
        return True, None

    except Exception as exc:
        logger.exception(
            "WhatsApp send failed for invoice %s to client %s: %s",
            invoice.id,
            client.id,
            exc,
        )
        return False, str(exc)
