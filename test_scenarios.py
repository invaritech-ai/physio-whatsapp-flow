import requests
import os
import time
from dotenv import load_dotenv

# Load env vars to get the special phone numbers
load_dotenv()

BASE_URL = "http://localhost:8000/whatsapp"

# Default mock numbers if env vars are missing
ADMIN_NUMBER = os.getenv("ADMIN_PHONE_NUMBER", "whatsapp:+1234567890")
PHYSIO_NUMBER = os.getenv("PHYSIO_PHONE_NUMBER", "whatsapp:+0987654321")
CUSTOMER_NUMBER = "whatsapp:+1111111111"

def send_message(from_number, body):
    print(f"\n--- Sending '{body}' from {from_number} ---")
    data = {"From": from_number, "Body": body}
    try:
        response = requests.post(BASE_URL, data=data)
        if response.status_code == 200:
            print("Server received message successfully.")
        else:
            print(f"Server returned error: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Failed to connect to server: {e}")

def test_customer_flow():
    print("\n>>> Testing Customer Flow")
    send_message(CUSTOMER_NUMBER, "Hi")
    send_message(CUSTOMER_NUMBER, "I need 30 min session")
    send_message(CUSTOMER_NUMBER, "book")

def test_physio_flow():
    print("\n>>> Testing Physio Flow")
    send_message(PHYSIO_NUMBER, "help")
    send_message(PHYSIO_NUMBER, "start 1")

def test_physio_payment_flow_cash():
    """Test the complete payment flow with cash payment
    
    Note: Sessions end AUTOMATICALLY after their duration.
    The scheduler runs every 5 mins to check for ended sessions.
    This test simulates the payment flow AFTER session auto-ends.
    """
    print("\n>>> Testing Physio Payment Flow - Cash Payment")
    print("Note: This assumes the session has auto-ended and physio is in payment flow state")
    # Physio receives prompt after session auto-ends, then responds:
    send_message(PHYSIO_NUMBER, "1")  # Select "Payment received"
    send_message(PHYSIO_NUMBER, "cash")  # Select cash

def test_physio_payment_flow_card():
    """Test the complete payment flow with card payment"""
    print("\n>>> Testing Physio Payment Flow - Card Payment")
    print("Note: This assumes the session has auto-ended and physio is in payment flow state")
    send_message(PHYSIO_NUMBER, "Payment received")
    send_message(PHYSIO_NUMBER, "card")

def test_physio_payment_flow_fps():
    """Test the complete payment flow with FPS"""
    print("\n>>> Testing Physio Payment Flow - FPS")
    print("Note: This assumes the session has auto-ended and physio is in payment flow state")
    send_message(PHYSIO_NUMBER, "2")  # FPS option

def test_physio_payment_flow_consolidating():
    """Test the complete payment flow with consolidating"""
    print("\n>>> Testing Physio Payment Flow - Consolidating")
    print("Note: This assumes the session has auto-ended and physio is in payment flow state")
    send_message(PHYSIO_NUMBER, "3")  # Consolidating option

def test_admin_flow():
    print("\n>>> Testing Admin Flow")
    send_message(ADMIN_NUMBER, "approve")

def test_session_notes_flow():
    """Test the complete session notes feature"""
    print("\n>>> Testing Session Notes Flow")
    # 1. Start a session first (assuming ID 1 exists)
    send_message(PHYSIO_NUMBER, "start 1")
    # 2. Enter note-taking mode
    send_message(PHYSIO_NUMBER, "add notes")
    # 3. Add some notes (with mixed case to test case preservation)
    send_message(PHYSIO_NUMBER, "Patient showed improved ROM in left shoulder")
    send_message(PHYSIO_NUMBER, "Applied ultrasound therapy for 10 minutes")
    send_message(PHYSIO_NUMBER, "Recommended home exercises - Pendulum Swings 3x daily")
    # 4. Exit note-taking mode
    send_message(PHYSIO_NUMBER, "done")
    # 5. Re-enter note mode (should work while session is still active)
    send_message(PHYSIO_NUMBER, "add notes")
    send_message(PHYSIO_NUMBER, "Additional note: Patient reported pain level 3/10")
    send_message(PHYSIO_NUMBER, "done")

def test_session_notes_no_active_session():
    """Test that notes cannot be added without an active session"""
    print("\n>>> Testing Session Notes - No Active Session")
    send_message(CUSTOMER_NUMBER, "switch to physio")
    send_message(CUSTOMER_NUMBER, "add notes")  # Should fail - no active session

def test_session_notes_case_preservation():
    """Test that note text preserves original case"""
    print("\n>>> Testing Session Notes - Case Preservation")
    send_message(PHYSIO_NUMBER, "start 1")
    send_message(PHYSIO_NUMBER, "add notes")
    send_message(PHYSIO_NUMBER, "ROM: 45 degrees. MRI shows improvement. PT recommends RICE protocol.")
    send_message(PHYSIO_NUMBER, "done")

def test_view_notes():
    """Test viewing notes for a completed session"""
    print("\n>>> Testing View Notes")
    # First add some notes to session 1
    send_message(PHYSIO_NUMBER, "start 1")
    send_message(PHYSIO_NUMBER, "add notes")
    send_message(PHYSIO_NUMBER, "Patient arrived on time and in good spirits")
    send_message(PHYSIO_NUMBER, "Completed full range of motion exercises")
    send_message(PHYSIO_NUMBER, "Recommended follow-up in 2 weeks")
    send_message(PHYSIO_NUMBER, "done")
    # Now view the notes
    send_message(PHYSIO_NUMBER, "view notes 1")

def test_view_notes_no_notes():
    """Test viewing notes for a session with no notes"""
    print("\n>>> Testing View Notes - No Notes")
    send_message(PHYSIO_NUMBER, "view notes 999")  # Assuming 999 doesn't exist or has no notes

def test_view_notes_invalid():
    """Test view notes with invalid input"""
    print("\n>>> Testing View Notes - Invalid Input")
    send_message(PHYSIO_NUMBER, "view notes")  # Missing ID

if __name__ == "__main__":
    print(f"Targeting: {BASE_URL}")
    print("Make sure your uvicorn server is running: 'uvicorn app.main:app --reload'")
    print("\n" + "="*60)
    print("BASIC FLOW TESTS")
    print("="*60)
    
    test_customer_flow()
    test_physio_flow()
    test_admin_flow()
    
    print("\n" + "="*60)
    print("PHYSIO PAYMENT FLOW TESTS")
    print("="*60)
    print("Note: Sessions end AUTOMATICALLY after their duration.")
    print("The scheduler checks every 5 mins for ended sessions.")
    print("These tests simulate responses AFTER auto-end triggers payment flow.")
    print("="*60)
    
    # Uncomment these to test payment flows (after session auto-ends)
    # test_physio_payment_flow_cash()
    # test_physio_payment_flow_card()
    # test_physio_payment_flow_fps()
    # test_physio_payment_flow_consolidating()
    
    print("\n" + "="*60)
    print("SESSION NOTES TESTS")
    print("="*60)
    print("Note: These tests require an active appointment (ID 1)")
    print("="*60)
    
    # Uncomment these to test session notes
    # test_session_notes_flow()
    # test_session_notes_no_active_session()
    # test_session_notes_case_preservation()
    # test_view_notes()
    # test_view_notes_no_notes()
    # test_view_notes_invalid()
