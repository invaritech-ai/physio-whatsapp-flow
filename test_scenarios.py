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

def test_admin_flow():
    print("\n>>> Testing Admin Flow")
    # 1. Approve payment
    send_message(ADMIN_NUMBER, "approve")

if __name__ == "__main__":
    print(f"Targeting: {BASE_URL}")
    print("Make sure your uvicorn server is running: 'uvicorn main:app --reload'")
    
    test_customer_flow()
    test_physio_flow()
    test_admin_flow()
