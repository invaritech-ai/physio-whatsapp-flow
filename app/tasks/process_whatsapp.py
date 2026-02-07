from app.worker import celery_app


@celery_app.task(name="tasks.process_whatsapp_message", bind=True, max_retries=2)
def process_whatsapp_message(self, form_data: dict) -> dict:
    """
    Process an inbound WhatsApp message through the bot state machine.

    Args:
        form_data: Dictionary containing Twilio form data (From, Body, NumMedia, etc.)

    Returns:
        Dictionary with processing status and next state
    """
    # Deferred imports to avoid circular dependencies
    from app.db.session import get_session
    from app.services.bot import process_message

    # Process message within database session
    with next(get_session()) as db:
        return process_message(form_data, db)
