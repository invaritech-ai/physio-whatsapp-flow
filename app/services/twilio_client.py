import os

from twilio.rest import Client

from app.core.config import settings

TWILIO_ACCOUNT_SID = settings.twilio_account_sid or os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = settings.twilio_auth_token or os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = settings.twilio_whatsapp_number
DEBUG_MODE = settings.debug_mode

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


def send_whatsapp_message(to: str, body: str, media_url: list | None = None):
    """
    Send a WhatsApp message.
    'to' should be in the format 'whatsapp:+1234567890'.

    In DEBUG_MODE, messages are logged but not sent via Twilio.
    """
    if DEBUG_MODE:
        print(f"\n[PHYSIO BOT] Would send to {to}: {body}\n")
        return "debug-mode-sid"

    message_args = {"from_": TWILIO_WHATSAPP_NUMBER, "body": body, "to": to}

    intercept_nums = ["whatsapp:+1111111111", "whatsapp:+0987654321"]
    if to in intercept_nums:
        print(f"\n[TEST MODE] Would send to {to}: {body}\n")
        return "test-sid-intercepted"

    if media_url:
        message_args["media_url"] = media_url

    message = client.messages.create(**message_args)
    return message.sid
