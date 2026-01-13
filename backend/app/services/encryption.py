"""Encryption service for API keys using Fernet symmetric encryption."""
import base64
import hashlib

from cryptography.fernet import Fernet

from app.core.config import get_settings


def get_fernet() -> Fernet:
    """Get Fernet instance using app secret_key as basis."""
    settings = get_settings()
    # Derive a valid 32-byte Fernet key from the secret_key
    key = hashlib.sha256(settings.secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_api_key(plaintext: str) -> str:
    """Encrypt an API key."""
    f = get_fernet()
    return f.encrypt(plaintext.encode()).decode()


def decrypt_api_key(ciphertext: str) -> str:
    """Decrypt an API key."""
    f = get_fernet()
    return f.decrypt(ciphertext.encode()).decode()
