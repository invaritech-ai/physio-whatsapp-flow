from unittest.mock import patch

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlmodel import Session

from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.webhook_security import verify_twilio_signature
from app.db.session import get_session
from app.services.bot.router import process_message

router = APIRouter()


@router.post("/whatsapp", dependencies=[Depends(verify_twilio_signature)])
@limiter.limit("60/minute")
async def whatsapp_webhook(request: Request, db: Session = Depends(get_session)):
    """
    Twilio WhatsApp webhook endpoint.
    Processes inbound messages synchronously by default.
    Can fallback to async Celery processing when sync mode is disabled.
    """
    try:
        form_data = await request.form()
        payload = dict(form_data)

        result = process_message(payload, db)
        return {"mode": "sync", **result}
    except Exception as e:
        import traceback

        print(f"Error processing WhatsApp message: {str(e)}\n{traceback.format_exc()}")
        return JSONResponse(status_code=500, content={"error": "Internal server error"})


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

    from app.services.bot.router import process_message

    with (
        patch("app.services.bot.router.send_and_log", fake_send_and_log),
        patch("app.services.bot.router.log_inbound", fake_log_inbound),
    ):
        result = process_message(data, db)

    result["reply"] = captured_reply.get("body", "")
    return result
