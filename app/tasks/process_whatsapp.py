from app.worker import celery_app


@celery_app.task(name="tasks.process_whatsapp_message", bind=True, max_retries=2)
def process_whatsapp_message(self, form_data: dict) -> dict:
    """
    Process an inbound WhatsApp message.

    STUB: This will be implemented in Phase 2 (WhatsApp Bot Rewrite).

    Args:
        form_data: Dictionary containing Twilio form data (From, Body, NumMedia, etc.)

    Returns:
        Dictionary with processing status
    """
    # Phase 1: Return stub to avoid crashes
    return {"status": "stub", "message": "Bot logic not implemented yet (Phase 2)"}
