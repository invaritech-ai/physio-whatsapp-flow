"""Generate a Fernet encryption key for ENCRYPTION_KEY environment variable.

Usage:
    python scripts/generate_encryption_key.py
"""

from cryptography.fernet import Fernet


def main():
    """Generate and print a new Fernet encryption key."""
    key = Fernet.generate_key()
    key_str = key.decode()

    print("=" * 60)
    print("New Encryption Key Generated")
    print("=" * 60)
    print()
    print("Add this to your .env file:")
    print()
    print(f"ENCRYPTION_KEY={key_str}")
    print()
    print("⚠️  WARNING:")
    print("- Keep this key secret and secure")
    print("- Store it in a password manager")
    print("- DO NOT commit it to version control")
    print("- If you lose this key, you cannot decrypt stored PATs")
    print("- Changing this key will invalidate all encrypted PATs")
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
