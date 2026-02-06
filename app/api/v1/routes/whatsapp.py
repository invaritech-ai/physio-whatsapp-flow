from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.tasks.process_whatsapp import process_whatsapp_message
from app.core.config import settings

router = APIRouter()


class WhatsAppTestMessage(BaseModel):
    """Schema for manual WhatsApp message testing"""
    From: str
    Body: str
    NumMedia: int = 0
    MediaUrl0: str | None = None


@router.post("/whatsapp")
async def whatsapp_webhook(request: Request):
    """
    Twilio WhatsApp webhook endpoint.
    Enqueues inbound messages as Celery tasks and returns immediately.
    """
    try:
        form_data = await request.form()
        payload = dict(form_data)

        # Enqueue message processing as background task
        task = process_whatsapp_message.delay(payload)

        return {"status": "queued", "task_id": task.id}
    except Exception as e:
        import traceback

        print(f"Error enqueueing WhatsApp message: {str(e)}\n{traceback.format_exc()}")
        return JSONResponse(status_code=500, content={"message": str(e), "traceback": traceback.format_exc()})


@router.post("/whatsapp/test")
async def whatsapp_test_endpoint(message: WhatsAppTestMessage):
    """
    Manual test endpoint for WhatsApp messages.
    Accepts JSON instead of form data, enqueues the same Celery task.
    """
    try:
        # Convert Pydantic model to dict matching Twilio's form data format
        # NumMedia must be string to match Twilio's format
        payload = {
            "From": message.From,
            "Body": message.Body,
            "NumMedia": str(message.NumMedia),
        }

        # Add MediaUrl0 if present
        if message.MediaUrl0:
            payload["MediaUrl0"] = message.MediaUrl0

        # Enqueue message processing as background task
        task = process_whatsapp_message.delay(payload)

        return {
            "status": "queued",
            "task_id": task.id,
            "debug_mode": settings.debug_mode,
            "note": "Check Celery worker logs for processing output. No Twilio sends if DEBUG_MODE=true"
        }
    except Exception as e:
        import traceback

        print(f"Error enqueueing test message: {str(e)}\n{traceback.format_exc()}")
        return JSONResponse(status_code=500, content={"message": str(e), "traceback": traceback.format_exc()})
