"""Utilities for encrypting and decrypting sensitive data."""

from functools import lru_cache
from cryptography.fernet import Fernet
from pydantic import SecretStr

from .config import get_settings


@lru_cache
def get_cipher() -> Fernet:
    """Return a configured Fernet cipher based on settings."""
    s = get_settings()
    key_field: SecretStr = s.TOKEN_ENCRYPTION_KEY
    key = key_field.get_secret_value().encode()
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    """Encrypt ``plaintext`` using Fernet cipher."""
    return get_cipher().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt previously encrypted ``token``."""
    return get_cipher().decrypt(token.encode()).decode()


__all__ = ["get_cipher", "encrypt", "decrypt"]
