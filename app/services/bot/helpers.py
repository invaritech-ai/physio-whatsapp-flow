"""Helper utilities for bot operations."""

import json
import re
from time import perf_counter
from typing import Final

from sqlmodel import Session, select

from app.models import Client
from app.core.process_trace import CHANNEL_WHATSAPP_BOT, process_trace
from app.services.twilio_client import send_whatsapp_message

_CLIENT_ID_CACHE: Final[dict[str, int]] = {}


def get_or_create_client(db: Session, phone_e164: str) -> Client:
    """
    Get existing client or create new one.
    Phone should be in E.164 format (e.g., 'whatsapp:+85212345678')
    Strip 'whatsapp:' prefix if present.
    """
    clean_phone = re.sub(r"[\s\-()]", "", phone_e164.replace("whatsapp:", ""))
    t_start = perf_counter()
    cached_client_id = _CLIENT_ID_CACHE.get(clean_phone)
    if cached_client_id is not None:
        t_cache_get = perf_counter()
        client = db.get(Client, cached_client_id)
        process_trace(
            CHANNEL_WHATSAPP_BOT,
            "client_cache_lookup",
            cache_hit=True,
            cached_client_id=cached_client_id,
            cache_get_ms=round((perf_counter() - t_cache_get) * 1000, 2),
            elapsed_ms_from_client_lookup_start=round((perf_counter() - t_start) * 1000, 2),
        )
        if client and client.phone_e164 == clean_phone:
            return client

    t_select = perf_counter()
    stmt = select(Client).where(Client.phone_e164 == clean_phone)
    client = db.exec(stmt).first()
    process_trace(
        CHANNEL_WHATSAPP_BOT,
        "client_db_select",
        cache_hit=False,
        found=client is not None,
        select_ms=round((perf_counter() - t_select) * 1000, 2),
        elapsed_ms_from_client_lookup_start=round((perf_counter() - t_start) * 1000, 2),
    )

    if not client:
        t_create = perf_counter()
        client = Client(phone_e164=clean_phone, conversation_state="IDLE")
        db.add(client)
        # Flush to assign PK; caller performs the request-level commit.
        db.flush()
        process_trace(
            CHANNEL_WHATSAPP_BOT,
            "client_created",
            create_flush_ms=round((perf_counter() - t_create) * 1000, 2),
            elapsed_ms_from_client_lookup_start=round((perf_counter() - t_start) * 1000, 2),
        )

    if client.id is not None:
        _CLIENT_ID_CACHE[clean_phone] = client.id

    return client


def get_conversation_data(client: Client) -> dict:
    """Parse conversation_data JSON or return empty dict."""
    if not client.conversation_data:
        return {}
    try:
        return json.loads(client.conversation_data)
    except json.JSONDecodeError:
        return {}


def set_conversation_data(client: Client, data: dict) -> None:
    """Serialize conversation_data to JSON string."""
    client.conversation_data = json.dumps(data)


def update_conversation_data(client: Client, **kwargs) -> dict:
    """Update specific keys in conversation_data, return full dict."""
    data = get_conversation_data(client)
    data.update(kwargs)
    set_conversation_data(client, data)
    return data


def validate_numbered_choice(body: str, valid_choices: list[int]) -> int | None:
    """
    Extract exactly one numeric choice and validate against valid_choices.
    Returns the choice as int or None if invalid.
    Examples: "1", "2.", " 3 ", "I choose 2" all return a valid choice.
    Inputs with multiple numbers like "1,3" are rejected.
    """
    body = body.strip().lower()
    # Try direct match first
    for choice in valid_choices:
        if body == str(choice):
            return choice

    # Extract all numbers in text and require exactly one numeric intent.
    matches = re.findall(r"\b(\d+)\b", body)
    if len(matches) != 1:
        return None

    num = int(matches[0])
    if num in valid_choices:
        return num

    return None


def validate_comma_separated_choices(
    body: str, valid_choices: list[int]
) -> list[int] | None:
    """
    Parse comma-separated list of numbers (e.g., "1,2,3" or "1, 3, 5").
    Returns list of valid choices or None if any invalid.
    """
    # Extract all digits from input
    matches = re.findall(r"\b(\d+)\b", body)
    if not matches:
        return None

    try:
        choices = [int(m) for m in matches]
        # Validate all choices are valid
        if all(c in valid_choices for c in choices):
            # Remove duplicates, preserve order
            seen = set()
            unique = []
            for c in choices:
                if c not in seen:
                    unique.append(c)
                    seen.add(c)
            return unique
    except ValueError:
        return None

    return None


def send_and_log(
    db: Session,
    phone_e164: str,
    body: str,
    client_id: int,
    media_url: list[str] | None = None,
) -> str | None:
    """
    Send WhatsApp message and log to MessageLog.
    Returns Twilio message SID.
    """
    # Import here to avoid circular dependency
    from app.services.message_logger import log_outbound

    # Ensure phone has 'whatsapp:' prefix for Twilio
    if not phone_e164.startswith("whatsapp:"):
        phone_e164 = f"whatsapp:{phone_e164}"

    # Send via Twilio
    twilio_sid = send_whatsapp_message(phone_e164, body, media_url)

    # Log outbound message
    log_outbound(
        db=db,
        phone_e164=phone_e164.replace("whatsapp:", ""),
        body=body,
        twilio_sid=twilio_sid,
        client_id=client_id,
    )

    return twilio_sid


def reset_conversation(client: Client, db: Session) -> None:
    """Reset client to IDLE state and clear conversation_data."""
    client.conversation_state = "IDLE"
    client.conversation_data = None
    db.add(client)
    db.commit()
