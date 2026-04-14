"""Main router for WhatsApp bot - entry point for message processing."""

from time import perf_counter

from sqlmodel import Session

from app.core.debug_probe import debug_probe
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
    run_id = f"msg-{int(perf_counter() * 1000)}"
    t_start = perf_counter()
    try:
        # Extract message details
        sender = form_data.get("From", "")  # e.g., "whatsapp:+85212345678"
        body = form_data.get("Body", "").strip()
        message_sid = form_data.get("MessageSid")
        num_media = int(form_data.get("NumMedia", "0"))

        process_trace(
            CHANNEL_WHATSAPP_BOT,
            "process_message_start",
            run_id=run_id,
            from_masked=mask_twilio_whatsapp_from(sender),
            body_char_len=len(body),
            num_media=num_media,
            message_sid=message_sid,
        )
        # region agent log
        debug_probe(
            run_id=run_id,
            hypothesis_id="H4",
            location="app/services/bot/router.py:process_message_start",
            message="Process message entered",
            data={"num_media": num_media, "body_len": len(body)},
        )
        # endregion

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
        t_client_lookup = perf_counter()
        client = get_or_create_client(db, sender)
        client_lookup_ms = round((perf_counter() - t_client_lookup) * 1000, 2)

        process_trace(
            CHANNEL_WHATSAPP_BOT,
            "client_resolved",
            run_id=run_id,
            client_id=client.id,
            conversation_state=client.conversation_state,
            elapsed_ms_from_start=round((perf_counter() - t_start) * 1000, 2),
            client_lookup_ms=client_lookup_ms,
        )

        # Log inbound message (ALWAYS log, even if body is empty)
        t_log_inbound = perf_counter()
        log_inbound(
            db=db,
            phone_e164=client.phone_e164,
            body=body,
            twilio_sid=message_sid,
            client_id=client.id,
            media_url=media_url,
        )
        process_trace(
            CHANNEL_WHATSAPP_BOT,
            "inbound_logged",
            run_id=run_id,
            client_id=client.id,
            log_inbound_ms=round((perf_counter() - t_log_inbound) * 1000, 2),
            elapsed_ms_from_start=round((perf_counter() - t_start) * 1000, 2),
        )
        # region agent log
        debug_probe(
            run_id=run_id,
            hypothesis_id="H2",
            location="app/services/bot/router.py:inbound_logged",
            message="Inbound logging completed",
            data={
                "client_lookup_ms": client_lookup_ms,
                "log_inbound_ms": round((perf_counter() - t_log_inbound) * 1000, 2),
                "elapsed_ms": round((perf_counter() - t_start) * 1000, 2),
            },
        )
        # endregion

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
                run_id=run_id,
                outcome="success",
                reason="empty_body_or_media_only",
                client_id=client.id,
                next_state=client.conversation_state,
                elapsed_ms_total=round((perf_counter() - t_start) * 1000, 2),
            )
            return {
                "status": "success",
                "next_state": client.conversation_state,
                "client_id": client.id,
                "note": "Empty body or media-only message",
            }

        # Check for global keywords first (work from any state)
        body_lower = body.lower()
        t_dispatch = perf_counter()
        keyword_result = check_global_keywords(client, body_lower, db)
        dispatch_ms = round((perf_counter() - t_dispatch) * 1000, 2)

        if keyword_result is not None:
            next_state, response_text = keyword_result
            process_trace(
                CHANNEL_WHATSAPP_BOT,
                "dispatch_global_keyword",
                run_id=run_id,
                previous_state=client.conversation_state,
                next_state=next_state,
                response_char_len=len(response_text or ""),
                dispatch_ms=dispatch_ms,
                elapsed_ms_from_start=round((perf_counter() - t_start) * 1000, 2),
            )
            # region agent log
            debug_probe(
                run_id=run_id,
                hypothesis_id="H1",
                location="app/services/bot/router.py:dispatch_global_keyword",
                message="Global keyword dispatched",
                data={
                    "dispatch_ms": dispatch_ms,
                    "next_state": next_state,
                    "elapsed_ms": round((perf_counter() - t_start) * 1000, 2),
                },
            )
            # endregion
        else:
            # Normal state handler dispatch
            current_state = client.conversation_state
            handler = HANDLER_MAP.get(current_state, handle_idle)
            handler_name = getattr(handler, "__name__", str(handler))
            process_trace(
                CHANNEL_WHATSAPP_BOT,
                "dispatch_state_handler",
                run_id=run_id,
                conversation_state=current_state,
                handler=handler_name,
            )
            next_state, response_text = handler(client, body_lower, db)
            process_trace(
                CHANNEL_WHATSAPP_BOT,
                "handler_returned",
                run_id=run_id,
                handler=handler_name,
                next_state=next_state,
                response_char_len=len(response_text or ""),
                dispatch_ms=dispatch_ms,
                elapsed_ms_from_start=round((perf_counter() - t_start) * 1000, 2),
            )

        # Update client state
        t_state_commit = perf_counter()
        client.conversation_state = next_state
        db.add(client)
        db.commit()

        process_trace(
            CHANNEL_WHATSAPP_BOT,
            "state_persisted",
            run_id=run_id,
            client_id=client.id,
            next_state=next_state,
            state_commit_ms=round((perf_counter() - t_state_commit) * 1000, 2),
            elapsed_ms_from_start=round((perf_counter() - t_start) * 1000, 2),
        )

        # Send response and log outbound message
        t_send = perf_counter()
        send_and_log(
            db=db,
            phone_e164=client.phone_e164,
            body=response_text,
            client_id=client.id,
        )

        process_trace(
            CHANNEL_WHATSAPP_BOT,
            "process_message_end",
            run_id=run_id,
            outcome="success",
            client_id=client.id,
            next_state=next_state,
            send_and_log_ms=round((perf_counter() - t_send) * 1000, 2),
            elapsed_ms_total=round((perf_counter() - t_start) * 1000, 2),
        )
        # region agent log
        debug_probe(
            run_id=run_id,
            hypothesis_id="H1",
            location="app/services/bot/router.py:process_message_end",
            message="Process message completed",
            data={
                "send_and_log_ms": round((perf_counter() - t_send) * 1000, 2),
                "elapsed_ms_total": round((perf_counter() - t_start) * 1000, 2),
                "next_state": next_state,
            },
        )
        # endregion
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
            run_id=run_id,
            outcome="error",
            error_type=type(e).__name__,
            error=str(e)[:500],
            client_id=client.id if "client" in locals() and getattr(client, "id", None) else None,
            elapsed_ms_total=round((perf_counter() - t_start) * 1000, 2),
        )
        return {
            "status": "error",
            "message": error_message,
        }
