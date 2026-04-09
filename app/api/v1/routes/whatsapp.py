import logging
import traceback
from unittest.mock import patch

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlmodel import Session

from app.core.config import settings
from app.core.process_trace import (
    CHANNEL_WHATSAPP_WEBHOOK,
    attach_trace_to_result,
    mask_twilio_whatsapp_from,
    new_trace_id,
    process_trace,
    reset_trace_id,
)
from app.core.rate_limit import limiter
from app.core.webhook_security import verify_twilio_signature
from app.db.session import get_session
from app.services.bot.router import process_message

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/whatsapp", dependencies=[Depends(verify_twilio_signature)])
@limiter.limit("60/minute")
async def whatsapp_webhook(request: Request, db: Session = Depends(get_session)):
    """
    Twilio WhatsApp webhook endpoint.
    Processes inbound messages synchronously by default.
    Can fallback to async Celery processing when sync mode is disabled.
    """
    _, trace_token = new_trace_id()
    try:
        form_data = await request.form()
        payload = dict(form_data)

        body_raw = str(payload.get("Body") or "")
        process_trace(
            CHANNEL_WHATSAPP_WEBHOOK,
            "http_received",
            path=str(request.url.path),
            client_host=getattr(request.client, "host", None),
            form_keys_sorted=sorted(payload.keys()),
            from_masked=mask_twilio_whatsapp_from(payload.get("From")),
            body_char_len=len(body_raw),
            num_media=int(payload.get("NumMedia") or 0),
            message_sid=payload.get("MessageSid"),
        )

        result = process_message(payload, db)

        process_trace(
            CHANNEL_WHATSAPP_WEBHOOK,
            "http_complete",
            result_status=result.get("status"),
            result_keys=sorted(result.keys()) if isinstance(result, dict) else None,
            next_state=result.get("next_state") if isinstance(result, dict) else None,
            client_id=result.get("client_id") if isinstance(result, dict) else None,
        )
        out = {"mode": "sync", **result}
        return attach_trace_to_result(out)
    except Exception as e:
        tb = traceback.format_exc()
        process_trace(
            CHANNEL_WHATSAPP_WEBHOOK,
            "http_exception",
            error_type=type(e).__name__,
            error=str(e)[:500],
        )
        if settings.debug_mode:
            logger.exception("WhatsApp webhook error: %s", e)
        else:
            logger.error("WhatsApp webhook error: %s\n%s", e, tb)
        return JSONResponse(status_code=500, content={"error": "Internal server error"})
    finally:
        reset_trace_id(trace_token)


@router.post("/whatsapp/test")
async def whatsapp_test(request: Request, db: Session = Depends(get_session)):
    """Test endpoint: runs the full bot flow synchronously, returns the reply.

    Same code path as production (process_message), but with Twilio
    sending and message logging stubbed out.

    Accepts JSON: {"From": "whatsapp:+85212345678", "Body": "hi"}
    Only available when DEBUG_MODE=true.
    """
    if not settings.debug_mode:
        raise HTTPException(status_code=404, detail="Not found")

    data = await request.json()

    # Capture the reply text from send_and_log calls
    captured_reply = {}

    def fake_send_and_log(db, phone_e164, body, client_id, media_url=None):
        captured_reply["body"] = body
        return None

    def fake_log_inbound(**kwargs):
        pass

    with (
        patch("app.services.bot.router.send_and_log", fake_send_and_log),
        patch("app.services.bot.router.log_inbound", fake_log_inbound),
    ):
        result = process_message(data, db)

    result["reply"] = captured_reply.get("body", "")
    return result
