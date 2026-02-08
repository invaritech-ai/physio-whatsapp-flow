#!/bin/bash
# Test Phase 2 WhatsApp bot flow end-to-end
# This simulates a complete conversation with the bot

set -e

BASE_URL="http://localhost:8000/api/v1/whatsapp/test"
PHONE="whatsapp:+85299887766"
COUNTER=1

echo "=========================================="
echo "Phase 2 Bot Flow Test"
echo "=========================================="
echo ""

send_message() {
    local body="$1"
    local sid="test-sid-$(printf "%03d" $COUNTER)"

    echo "[$COUNTER] User: $body"

    response=$(curl -s -X POST "$BASE_URL" \
        -H "Content-Type: application/json" \
        -d "{
            \"From\": \"$PHONE\",
            \"Body\": \"$body\",
            \"MessageSid\": \"$sid\"
        }")

    echo "    Response: $response"
    echo ""

    COUNTER=$((COUNTER + 1))
    sleep 3  # Give Celery time to process (increased from 1 to 3 seconds)
}

echo "Starting new conversation..."
echo ""

# Step 1: Initial greeting
send_message "hi"

# Step 2: Provide name
send_message "John Doe"

# Step 3: Select duration (2 = 45 minutes)
send_message "2"

# Step 4: Select specialty (1 = Sports Rehabilitation)
send_message "1"

# Step 5: Select time band (2 = Afternoon)
send_message "2"

# Step 6: Select days (1,3,5 = Mon, Wed, Fri)
send_message "1,3,5"

# Step 7: Confirm match (1 = Confirm)
send_message "1"

echo "=========================================="
echo "✓ Test flow complete!"
echo ""
echo "Check your Celery worker logs for bot responses."
echo "If DEBUG_MODE=true, no actual Twilio messages are sent."
echo ""
echo "To check the client record in the database:"
echo "  SELECT * FROM client WHERE phone_e164 = '+85299887766';"
echo ""
echo "To check message logs:"
echo "  SELECT * FROM message_log WHERE client_id = (SELECT id FROM client WHERE phone_e164 = '+85299887766') ORDER BY created_at;"
echo "=========================================="
