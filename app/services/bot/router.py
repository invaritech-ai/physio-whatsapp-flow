"""Main router for WhatsApp bot - entry point for message processing."""

from sqlmodel import Session

from app.core.process_trace import CHANNEL_WHATSAPP_BOT, mask_twilio_whatsapp_from, process_trace
from app.services.bot.handlers import HANDLER_MAP, check_global_keywords, handle_idle
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

        process_trace(
            CHANNEL_WHATSAPP_BOT,
            "process_message_start",
            from_masked=mask_twilio_whatsapp_from(sender),
            body_char_len=len(body),
            num_media=num_media,
            message_sid=message_sid,
        )

        # Get media URL if present (only first one for now)
        media_url = None
        if num_media > 0:
            media_url = form_data.get("MediaUrl0")

        # Validate sender (required)
        if not sender:
            process_trace(CHANNEL_WHATSAPP_BOT, "process_message_end", outcome="error", reason="missing_from")
            return {
                "status": "error",
                "message": "Missing required field: From",
            }

        # Get or create client (before validation so we can log)
        client = get_or_create_client(db, sender)

        process_trace(
            CHANNEL_WHATSAPP_BOT,
            "client_resolved",
            client_id=client.id,
            conversation_state=client.conversation_state,
        )

        # Log inbound message (ALWAYS log, even if body is empty)
        log_inbound(
            db=db,
            phone_e164=client.phone_e164,
            body=body,
            twilio_sid=message_sid,
            client_id=client.id,
            media_url=media_url,
        )

        # Handle empty body (media-only or blank message)
        if not body:
            # Media-only messages or blank messages get a helpful response
            response_text = (
                "I received your message! However, I can only respond to text messages. "
                "Please send me a text message to continue our conversation."
            )
            send_and_log(
                db=db,
                phone_e164=client.phone_e164,
                body=response_text,
                client_id=client.id,
            )
            process_trace(
                CHANNEL_WHATSAPP_BOT,
                "process_message_end",
                outcome="success",
                reason="empty_body_or_media_only",
                client_id=client.id,
                next_state=client.conversation_state,
            )
            return {
                "status": "success",
                "next_state": client.conversation_state,
                "client_id": client.id,
                "note": "Empty body or media-only message",
            }

        # Check for global keywords first (work from any state)
        body_lower = body.lower()
        keyword_result = check_global_keywords(client, body_lower, db)

        if keyword_result is not None:
            next_state, response_text = keyword_result
            process_trace(
                CHANNEL_WHATSAPP_BOT,
                "dispatch_global_keyword",
                previous_state=client.conversation_state,
                next_state=next_state,
                response_char_len=len(response_text or ""),
            )
        else:
            # Normal state handler dispatch
            current_state = client.conversation_state
            handler = HANDLER_MAP.get(current_state, handle_idle)
            handler_name = getattr(handler, "__name__", str(handler))
            process_trace(
                CHANNEL_WHATSAPP_BOT,
                "dispatch_state_handler",
                conversation_state=current_state,
                handler=handler_name,
            )
            next_state, response_text = handler(client, body_lower, db)
            process_trace(
                CHANNEL_WHATSAPP_BOT,
                "handler_returned",
                handler=handler_name,
                next_state=next_state,
                response_char_len=len(response_text or ""),
            )

        # Update client state
        client.conversation_state = next_state
        db.add(client)
        db.commit()

        process_trace(
            CHANNEL_WHATSAPP_BOT,
            "state_persisted",
            client_id=client.id,
            next_state=next_state,
        )

        # Send response and log outbound message
        send_and_log(
            db=db,
            phone_e164=client.phone_e164,
            body=response_text,
            client_id=client.id,
        )

        process_trace(
            CHANNEL_WHATSAPP_BOT,
            "process_message_end",
            outcome="success",
            client_id=client.id,
            next_state=next_state,
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

        process_trace(
            CHANNEL_WHATSAPP_BOT,
            "process_message_end",
            outcome="error",
            error_type=type(e).__name__,
            error=str(e)[:500],
            client_id=client.id if "client" in locals() and getattr(client, "id", None) else None,
        )
        return {
            "status": "error",
            "message": error_message,
        }
