"""Reoon email verification (mailbox-level). Real when REOON_API_KEY is set;
demo verdict otherwise (same demo philosophy as the old dashboard — the full
pipeline runs at zero cost). SAFE = proceed; anything else = unsafe/stop."""
import os

import requests

SAFE_STATUSES = {"safe", "valid"}
API = "https://emailverifier.reoon.com/api/v1/verify"


def verify_one(email: str) -> dict:
    """Returns {"status": "safe"|"invalid"|"catch_all"|"unknown"|..., "raw": {...}, "demo": bool}"""
    key = os.getenv("REOON_API_KEY", "")
    if not key:
        return {"status": "safe", "raw": {"note": "demo mode — REOON_API_KEY not set"}, "demo": True}
    try:
        r = requests.get(API, params={"email": email, "key": key, "mode": "power"}, timeout=45)
        r.raise_for_status()
        j = r.json()
        return {"status": str(j.get("status", "unknown")).lower(), "raw": j, "demo": False}
    except Exception as e:
        # verification infrastructure failure ≠ bad email → fail open as unknown
        return {"status": "unknown", "raw": {"error": str(e)}, "demo": False}
