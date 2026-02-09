"""Encryption utilities for sensitive data storage."""

from cryptography.fernet import Fernet

from app.core.config import settings


def get_fernet() -> Fernet:
    """Get Fernet cipher instance using encryption key from settings."""
    if not settings.encryption_key:
        raise ValueError("ENCRYPTION_KEY not set in environment")

    # Ensure key is bytes
    key = settings.encryption_key.encode() if isinstance(settings.encryption_key, str) else settings.encryption_key
    return Fernet(key)


def encrypt_string(plaintext: str) -> str:
    """Encrypt a string and return base64-encoded ciphertext.

    Args:
        plaintext: String to encrypt

    Returns:
        Base64-encoded encrypted string
    """
    if not plaintext:
        return ""

    fernet = get_fernet()
    encrypted_bytes = fernet.encrypt(plaintext.encode())
    return encrypted_bytes.decode()  # Return as string for DB storage


def decrypt_string(ciphertext: str) -> str:
    """Decrypt a base64-encoded ciphertext and return plaintext.

    Args:
        ciphertext: Base64-encoded encrypted string

    Returns:
        Decrypted plaintext string
    """
    if not ciphertext:
        return ""

    fernet = get_fernet()
    decrypted_bytes = fernet.decrypt(ciphertext.encode())
    return decrypted_bytes.decode()
