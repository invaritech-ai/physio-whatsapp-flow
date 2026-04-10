import os
import uuid
from typing import NotRequired, TypedDict

from twilio.rest import Client

from app.core.config import settings

TWILIO_ACCOUNT_SID = settings.twilio_account_sid or os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = settings.twilio_auth_token or os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = settings.twilio_whatsapp_number

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


class MessageCreateArgs(TypedDict):
    from_: str
    body: str
    to: str
    media_url: NotRequired[list[str]]


def send_whatsapp_message(
    to: str,
    body: str,
    media_url: list[str] | None = None,
):
    """
    Send a WhatsApp message.
    'to' should be in the format 'whatsapp:+1234567890'.

    When TWILIO_DRY_RUN=true, messages are printed only (no Twilio API).
    DEBUG_MODE does not affect delivery — use TWILIO_DRY_RUN for safe local testing.
    """
    if settings.twilio_dry_run:
        print(f"\n[PHYSIO BOT] Would send to {to}: {body}\n")
        # Return a unique SID to avoid collisions in message_log
        return f"debug-{uuid.uuid4().hex}"

    message_args: MessageCreateArgs = {
        "from_": TWILIO_WHATSAPP_NUMBER,
        "body": body,
        "to": to,
    }

    intercept_nums = ["whatsapp:+1111111111", "whatsapp:+0987654321"]
    if to in intercept_nums:
        print(f"\n[TEST MODE] Would send to {to}: {body}\n")
        return "test-sid-intercepted"

    if media_url is not None:
        message_args["media_url"] = media_url

    message = client.messages.create(**message_args)
    return message.sid
