"""Test Neon Auth authentication and get JWT token.

This script helps you get a valid JWT token from Neon Auth for testing.
"""

import os
import sys
from getpass import getpass

import requests
from dotenv import load_dotenv

load_dotenv()

NEON_AUTH_URL = os.getenv("NEON_AUTH_URL")


def get_jwt_token():
    """Authenticate with Neon Auth and get JWT token."""
    print("=" * 60)
    print("Neon Auth JWT Token Retrieval")
    print("=" * 60)
    print()
    print(f"Auth URL: {NEON_AUTH_URL}")
    print()

    # Get credentials
    email = input("Enter your email: ").strip()
    password = getpass("Enter your password: ")

    # Try to authenticate
    # Note: This is a placeholder - actual Neon Auth flow might be different
    # You may need to adjust this based on Neon Auth's actual API

    print()
    print("Attempting to authenticate...")
    print()

    # TODO: Replace this with actual Neon Auth authentication endpoint
    # The exact endpoint and flow depends on your Neon Auth configuration

    print("⚠️  Note: This script needs to be updated with your Neon Auth's")
    print("   actual authentication endpoint and flow.")
    print()
    print("Alternative methods to get JWT token:")
    print()
    print("1. Use your frontend application:")
    print("   - Log in normally")
    print("   - Open browser DevTools (F12)")
    print("   - Go to Application > Local Storage or Session Storage")
    print("   - Look for 'id_token' or 'access_token'")
    print()
    print("2. Use browser Network tab:")
    print("   - Open DevTools > Network tab")
    print("   - Log in to your frontend")
    print("   - Look for auth callback requests")
    print("   - Copy the id_token from the response")
    print()
    print("3. Check your frontend console:")
    print("   - Add: console.log('JWT Token:', token)")
    print("   - Log in and check browser console")
    print()


if __name__ == "__main__":
    get_jwt_token()
