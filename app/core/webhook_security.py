"""Webhook signature verification dependencies."""

import logging

from fastapi import HTTPException, Request, status
from twilio.request_validator import RequestValidator

from app.core.config import settings

logger = logging.getLogger(__name__)


async def verify_twilio_signature(request: Request) -> None:
    """FastAPI dependency that verifies Twilio webhook signatures.

    Uses Twilio's RequestValidator to verify the request came from Twilio.
    Skips verification if TWILIO_AUTH_TOKEN is not set (development mode).

    Raises:
        HTTPException 403: Invalid or missing Twilio signature
    """
    if not settings.twilio_auth_token:
        logger.warning("TWILIO_AUTH_TOKEN not set - skipping signature verification")
        return

    validator = RequestValidator(settings.twilio_auth_token)

    signature = request.headers.get("X-Twilio-Signature", "")
    if not signature:
        logger.warning("Missing X-Twilio-Signature header")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing Twilio signature",
        )

    # Use PUBLIC_BASE_URL for URL reconstruction (proxy-safe)
    if settings.public_base_url:
        url = f"{settings.public_base_url.rstrip('/')}{request.url.path}"
    else:
        url = str(request.url)

    # Get POST body as form data (Starlette caches this, safe to call twice)
    form_data = await request.form()
    params = dict(form_data)

    if not validator.validate(url, params, signature):
        logger.warning("Invalid Twilio signature for %s", request.url.path)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Twilio signature",
        )
