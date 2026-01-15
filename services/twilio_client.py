import os
from twilio.rest import Client

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

def send_whatsapp_message(to: str, body: str, media_url: list = None):
    """
    Send a WhatsApp message.
    'to' should be in the format 'whatsapp:+1234567890'.
    
    In DEBUG_MODE, messages are logged but not sent via Twilio.
    """
    # DEBUG_MODE: Log messages instead of sending via Twilio
    if DEBUG_MODE:
        print(f"\n[PHYSIO BOT] Would send to {to}: {body}\n")
        return "debug-mode-sid"
    
    message_args = {
        "from_": TWILIO_WHATSAPP_NUMBER,
        "body": body,
        "to": to
    }
    
    # Intercept test numbers from test_scenarios.py to avoid Twilio errors
    # We only intercept the dummy numbers now. Real numbers will receive real messages.
    intercept_nums = ["whatsapp:+1111111111", "whatsapp:+0987654321"]
        
    if to in intercept_nums:
        print(f"\n[TEST MODE] Would send to {to}: {body}\n")
        return "test-sid-intercepted"

    if media_url:
        message_args["media_url"] = media_url

    message = client.messages.create(**message_args)
    return message.sid
