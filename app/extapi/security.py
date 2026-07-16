"""Security utilities for the external API: key generation + peppered hashing,
credential encryption (Fernet), HMAC webhook signatures, SSRF-safe URL checks,
and a per-key rate limiter. No raw secret is ever persisted."""
import base64
import hashlib
import hmac
import ipaddress
import os
import secrets
import socket
import time
from datetime import datetime
from urllib.parse import urlparse

from .. import config

API_KEY_PEPPER = os.getenv("API_KEY_PEPPER", config.JWT_SECRET)
WEBHOOK_SIGNING_PEPPER = os.getenv("WEBHOOK_SIGNING_PEPPER", config.JWT_SECRET)
_CRED_KEY_RAW = os.getenv("CREDENTIAL_ENCRYPTION_KEY", "")

RATE_LIMIT_PER_MINUTE = int(os.getenv("EXTAPI_RATE_LIMIT_PER_MINUTE", "120"))
RATE_LIMIT_BURST_PER_SECOND = int(os.getenv("EXTAPI_BURST_PER_SECOND", "20"))


# ---------------------------------------------------------------- API keys
def generate_api_key() -> tuple[str, str, str]:
    """Returns (full_key, prefix, key_hash). Full key shown ONCE, never stored."""
    prefix = "rck_" + secrets.token_hex(4)                 # public identifier
    secret = secrets.token_urlsafe(32)
    full = f"{prefix}_{secret}"
    return full, prefix, hash_api_key(full)


def hash_api_key(full_key: str) -> str:
    return hmac.new(API_KEY_PEPPER.encode(), full_key.encode(), hashlib.sha256).hexdigest()


def key_prefix_of(full_key: str) -> str:
    parts = full_key.split("_")
    return "_".join(parts[:2]) if len(parts) >= 3 else ""


def verify_api_key(full_key: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_api_key(full_key), stored_hash)


# ---------------------------------------------------------------- credential encryption
def _fernet():
    from cryptography.fernet import Fernet
    if _CRED_KEY_RAW:
        try:
            return Fernet(_CRED_KEY_RAW.encode())
        except Exception:
            pass
    # derive a stable key from the app secret so dev environments work out of the box
    derived = base64.urlsafe_b64encode(hashlib.sha256(("cred:" + config.JWT_SECRET).encode()).digest())
    return Fernet(derived)


def encrypt_credentials(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_credentials(token: str) -> str:
    if not token:
        return ""
    return _fernet().decrypt(token.encode()).decode()


# ---------------------------------------------------------------- webhook signatures
def sign_webhook(secret: str, timestamp: str, body: bytes) -> str:
    """v1 signature: HMAC-SHA256(secret, "{timestamp}.{body}") hex."""
    msg = timestamp.encode() + b"." + body
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def generate_webhook_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(24)


# ---------------------------------------------------------------- SSRF guard
def is_safe_webhook_url(url: str) -> tuple[bool, str]:
    """Only http(s), no localhost/private/link-local/metadata targets."""
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            return False, "URL must be http(s)"
        host = p.hostname or ""
        if not host or host.lower() in ("localhost",):
            return False, "Host not allowed"
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror:
            return False, "Host does not resolve"
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False, "Private or local addresses are not allowed"
        return True, ""
    except Exception as ex:
        return False, str(ex)


# ---------------------------------------------------------------- rate limiting (per key, in-process)
_BUCKETS: dict = {}   # key_id -> {"min_start": ts, "min_count": n, "sec_start": ts, "sec_count": n}


def rate_limit_check(key_id: int) -> tuple[bool, int]:
    """Sliding minute window + per-second burst. Returns (allowed, retry_after_s).
    In-process by design (single web replica); swap for Redis if replicas grow."""
    now = time.time()
    b = _BUCKETS.setdefault(key_id, {"min_start": now, "min_count": 0, "sec_start": now, "sec_count": 0})
    if now - b["min_start"] >= 60:
        b["min_start"], b["min_count"] = now, 0
    if now - b["sec_start"] >= 1:
        b["sec_start"], b["sec_count"] = now, 0
    if b["sec_count"] >= RATE_LIMIT_BURST_PER_SECOND:
        return False, 1
    if b["min_count"] >= RATE_LIMIT_PER_MINUTE:
        return False, max(1, int(60 - (now - b["min_start"])))
    b["min_count"] += 1
    b["sec_count"] += 1
    return True, 0


def reset_rate_limits():   # for tests
    _BUCKETS.clear()


def utcnow() -> datetime:
    return datetime.utcnow()
