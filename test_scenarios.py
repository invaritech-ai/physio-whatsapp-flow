import requests
import os
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
    # 1. Start conversation
    send_message(CUSTOMER_NUMBER, "Hi")
    # 2. Ask for slot
    send_message(CUSTOMER_NUMBER, "I need 30 min session")
    # 3. Book (Simulating the user confirming)
    send_message(CUSTOMER_NUMBER, "book")

def test_physio_flow():
    print("\n>>> Testing Physio Flow")
    # 1. Check commands
    send_message(PHYSIO_NUMBER, "help")
    # 2. Start session (assuming ID 1 exists from customer test)
    send_message(PHYSIO_NUMBER, "start 1")

def test_physio_payment_flow_cash():
    """Test the complete payment flow with cash payment"""
    print("\n>>> Testing Physio Payment Flow - Cash Payment")
    # 1. Start session
    send_message(PHYSIO_NUMBER, "start 1")
    # 2. End session
    send_message(PHYSIO_NUMBER, "end 1")
    # 3. Select "Payment received"
    send_message(PHYSIO_NUMBER, "1")
    # 4. Select "Cash"
    send_message(PHYSIO_NUMBER, "1")

def test_physio_payment_flow_card():
    """Test the complete payment flow with card payment"""
    print("\n>>> Testing Physio Payment Flow - Card Payment")
    # 1. Start session (assuming ID 2 exists)
    send_message(PHYSIO_NUMBER, "start 2")
    # 2. End session
    send_message(PHYSIO_NUMBER, "end 2")
    # 3. Select "Payment received"
    send_message(PHYSIO_NUMBER, "Payment received")
    # 4. Select "Card"
    send_message(PHYSIO_NUMBER, "Card")

def test_physio_payment_flow_fps():
    """Test the complete payment flow with FPS"""
    print("\n>>> Testing Physio Payment Flow - FPS")
    # 1. Start session (assuming ID 3 exists)
    send_message(PHYSIO_NUMBER, "start 3")
    # 2. End session
    send_message(PHYSIO_NUMBER, "end 3")
    # 3. Select "FPS"
    send_message(PHYSIO_NUMBER, "2")

def test_physio_payment_flow_consolidating():
    """Test the complete payment flow with consolidating"""
    print("\n>>> Testing Physio Payment Flow - Consolidating")
    # 1. Start session (assuming ID 4 exists)
    send_message(PHYSIO_NUMBER, "start 4")
    # 2. End session
    send_message(PHYSIO_NUMBER, "end 4")
    # 3. Select "Consolidating with other session"
    send_message(PHYSIO_NUMBER, "3")

def test_admin_flow():
    print("\n>>> Testing Admin Flow")
    # 1. Approve payment
    send_message(ADMIN_NUMBER, "approve")

if __name__ == "__main__":
    print(f"Targeting: {BASE_URL}")
    print("Make sure your uvicorn server is running: 'uvicorn main:app --reload'")
    print("\n" + "="*60)
    print("BASIC FLOW TESTS")
    print("="*60)
    
    test_customer_flow()
    test_physio_flow()
    test_admin_flow()
    
    print("\n" + "="*60)
    print("PHYSIO PAYMENT FLOW TESTS")
    print("="*60)
    print("Note: These tests assume appointment IDs 1-4 exist in the database")
    print("Run these after creating appointments via customer flow")
    print("="*60)
    
    # Uncomment these to test payment flows
    # test_physio_payment_flow_cash()
    # test_physio_payment_flow_card()
    # test_physio_payment_flow_fps()
    # test_physio_payment_flow_consolidating()
