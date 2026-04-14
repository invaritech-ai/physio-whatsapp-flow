import os
import json
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
    to: str
    body: NotRequired[str]
    media_url: NotRequired[list[str]]
    content_sid: NotRequired[str]
    content_variables: NotRequired[str]


def send_whatsapp_message(
    to: str,
    body: str | None,
    media_url: list[str] | None = None,
    *,
    content_sid: str | None = None,
    content_variables: dict[str, str] | None = None,
) -> str:
    """
    Send a WhatsApp message.
    'to' should be in the format 'whatsapp:+1234567890'.

    When TWILIO_DRY_RUN=true, messages are printed only (no Twilio API).
    DEBUG_MODE does not affect delivery — use TWILIO_DRY_RUN for safe local testing.
    """
    if settings.twilio_dry_run:
        dry_payload = {
            "to": to,
            "body": body,
            "media_url": media_url,
            "content_sid": content_sid,
            "content_variables": content_variables,
        }
        print(f"\n[PHYSIO BOT] Would send WhatsApp payload: {dry_payload}\n")
        # Return a unique SID to avoid collisions in message_log
        return f"debug-{uuid.uuid4().hex}"

    normalized_content_sid = content_sid.strip() if content_sid else None

    if body is None and not normalized_content_sid:
        raise ValueError("Either body or content_sid must be provided for WhatsApp send")
    if body is not None and normalized_content_sid:
        raise ValueError("Provide either body or content_sid, not both")

    message_args: MessageCreateArgs = {
        "from_": TWILIO_WHATSAPP_NUMBER,
        "to": to,
    }
    if body is not None:
        message_args["body"] = body

    intercept_nums = ["whatsapp:+1111111111", "whatsapp:+0987654321"]
    if to in intercept_nums:
        print(f"\n[TEST MODE] Would send to {to}: body={body!r} content_sid={normalized_content_sid!r}\n")
        return "test-sid-intercepted"

    if media_url is not None:
        message_args["media_url"] = media_url
    if normalized_content_sid:
        message_args["content_sid"] = normalized_content_sid
        if content_variables:
            message_args["content_variables"] = json.dumps(content_variables)

    message = client.messages.create(**message_args)
    return message.sid
