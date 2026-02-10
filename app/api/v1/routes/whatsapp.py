from typing import cast

from celery import Task
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.core.rate_limit import limiter
from app.core.webhook_security import verify_twilio_signature
from app.tasks.process_whatsapp import process_whatsapp_message

router = APIRouter()


@router.post("/whatsapp", dependencies=[Depends(verify_twilio_signature)])
@limiter.limit("60/minute")
async def whatsapp_webhook(request: Request):
    """
    Twilio WhatsApp webhook endpoint.
    Enqueues inbound messages as Celery tasks and returns immediately.
    """
    try:
        form_data = await request.form()
        payload = dict(form_data)

        # Enqueue message processing as background task
        task = cast(Task, process_whatsapp_message).delay(payload)

        return {"status": "queued", "task_id": task.id}
    except Exception as e:
        import traceback

        print(f"Error enqueueing WhatsApp message: {str(e)}\n{traceback.format_exc()}")
        return JSONResponse(status_code=500, content={"error": "Internal server error"})
