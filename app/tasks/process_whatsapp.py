import asyncio
from app.worker import celery_app


@celery_app.task(name="tasks.process_whatsapp_message", bind=True, max_retries=2)
def process_whatsapp_message(self, form_data: dict) -> dict:
    """
    Process an inbound WhatsApp message asynchronously.

    Args:
        form_data: Dictionary containing Twilio form data (From, Body, NumMedia, etc.)

    Returns:
        Dictionary with processing status
    """
    try:
        # Deferred imports to avoid circular dependencies
        from app.bot_logic import process_message
        from app.db.session import Session, engine

        # Create DB session and run async process_message
        with Session(engine) as session:
            asyncio.run(process_message(form_data, session))

        return {"status": "success"}
    except Exception as exc:
        import traceback
        error_msg = f"Error processing WhatsApp message: {str(exc)}\n{traceback.format_exc()}"
        print(error_msg)

        # Retry on transient failures
        try:
            self.retry(countdown=5, exc=exc)
        except self.MaxRetriesExceededError:
            return {"status": "failed", "error": str(exc)}
