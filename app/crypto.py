"""Secrets-at-rest encryption (Fernet, key derived from JWT_SECRET).
Used for reply-workspace API keys / Calendly tokens — the legacy system stored
them plaintext and they leaked in screenshots; here they arrive encrypted."""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from . import config


def _fernet() -> Fernet:
    key = hashlib.sha256(("revcadence-secrets:" + config.JWT_SECRET).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode()).decode()
    except (InvalidToken, Exception):
        return value  # tolerate legacy/plaintext rows during migration
