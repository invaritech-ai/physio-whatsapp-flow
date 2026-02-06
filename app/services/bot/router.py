"""Main router for WhatsApp bot - entry point for message processing."""

from sqlmodel import Session

from app.services.bot.handlers import HANDLER_MAP, handle_idle
from app.services.bot.helpers import get_or_create_client, send_and_log
from app.services.message_logger import log_inbound


def process_message(form_data: dict, db: Session) -> dict:
    """
    Process an inbound WhatsApp message through the bot state machine.

    Args:
        form_data: Dictionary containing Twilio form data (From, Body, MessageSid, etc.)
        db: Database session

    Returns:
        Dictionary with processing status and next state

    Flow:
    1. Extract message details from Twilio form data
    2. Get or create client record
    3. Log inbound message
    4. Get handler for current conversation state
    5. Execute handler to get next state and response
    6. Update client state
    7. Send response and log outbound message
    """
    try:
        # Extract message details
        sender = form_data.get("From", "")  # e.g., "whatsapp:+85212345678"
        body = form_data.get("Body", "").strip()
        message_sid = form_data.get("MessageSid")
        num_media = int(form_data.get("NumMedia", "0"))

        # Get media URL if present (only first one for now)
        media_url = None
        if num_media > 0:
            media_url = form_data.get("MediaUrl0")

        # Validate required fields
        if not sender or not body:
            return {
                "status": "error",
                "message": "Missing required fields (From, Body)",
            }

        # Get or create client
        client = get_or_create_client(db, sender)

        # Log inbound message
        log_inbound(
            db=db,
            phone_e164=client.phone_e164,
            body=body,
            twilio_sid=message_sid,
            client_id=client.id,
            media_url=media_url,
        )

        # Get handler for current state
        current_state = client.conversation_state
        handler = HANDLER_MAP.get(current_state, handle_idle)

        # Execute handler
        next_state, response_text = handler(client, body.lower(), db)

        # Update client state
        client.conversation_state = next_state
        db.add(client)
        db.commit()

        # Send response and log outbound message
        send_and_log(
            db=db,
            phone_e164=client.phone_e164,
            body=response_text,
            client_id=client.id,
        )

        return {
            "status": "success",
            "next_state": next_state,
            "client_id": client.id,
        }

    except Exception as e:
        # Log error and send user-friendly message
        error_message = f"Error processing message: {str(e)}"

        # Try to send error message to user
        try:
            if "client" in locals() and client.id:
                send_and_log(
                    db=db,
                    phone_e164=client.phone_e164,
                    body="Sorry, something went wrong. Please try again later.",
                    client_id=client.id,
                )
        except Exception:
            # Silently fail if we can't send error message
            pass

        return {
            "status": "error",
            "message": error_message,
        }
