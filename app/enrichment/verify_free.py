"""Free email verification — port of integrations/email_verify.py.
Design rule preserved: SAFE rejections only. Reject ONLY when definitively
undeliverable (bad syntax / no MX / disposable). On ANY DNS uncertainty, FAIL
OPEN ("ok") so the lead falls through to Reoon. Role accounts are flagged,
never rejected. MX results cached per domain."""
import re
import threading

import requests

_SYNTAX = re.compile(r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")

_DISPOSABLE = {
    "mailinator.com", "guerrillamail.com", "sharklasers.com", "10minutemail.com",
    "tempmail.com", "temp-mail.org", "tempmailo.com", "throwawaymail.com", "yopmail.com",
    "getnada.com", "trashmail.com", "mailnesia.com", "maildrop.cc", "dispostable.com",
    "fakeinbox.com", "mohmal.com", "emailondeck.com", "mintemail.com", "spamgourmet.com",
    "mytemp.email", "moakt.com", "burnermail.io", "tempinbox.com", "discard.email",
    "spam4.me", "grr.la", "mailcatch.com", "inboxkitten.com", "33mail.com", "temp-mail.io",
}

_ROLE = {
    "info", "sales", "support", "admin", "administrator", "contact", "hello", "hi",
    "team", "office", "billing", "accounts", "accounting", "hr", "jobs", "careers",
    "marketing", "press", "media", "help", "service", "services", "enquiries", "inquiries",
    "noreply", "no-reply", "donotreply", "do-not-reply", "webmaster", "postmaster",
    "abuse", "privacy", "legal", "security", "orders", "order", "feedback", "general",
}

_cache: dict = {}
_lock = threading.Lock()


def _doh_mx(domain: str):
    """DNS-over-HTTPS MX lookup (port 443 works where raw :53 is blocked).
    True = MX exists, False = definitively none, None = couldn't determine."""
    for host in ("https://dns.google/resolve", "https://cloudflare-dns.com/dns-query"):
        try:
            r = requests.get(host, params={"name": domain, "type": "MX"},
                             headers={"accept": "application/dns-json"}, timeout=6)
            if r.status_code != 200:
                continue
            j = r.json()
            if j.get("Status") == 3:      # NXDOMAIN
                return False
            if j.get("Status") == 0:
                if j.get("Answer"):
                    return True
                # no MX record: try A (implicit MX fallback per RFC)
                r2 = requests.get(host, params={"name": domain, "type": "A"},
                                  headers={"accept": "application/dns-json"}, timeout=6)
                if r2.status_code == 200 and r2.json().get("Answer"):
                    return True
                return False
        except Exception:
            continue
    return None  # uncertain → fail open


def check(email: str) -> dict:
    """Returns {"verdict": "ok"|"role"|"bad syntax"|"disposable"|"no mail server (MX)",
    "reject": bool}. Reject=True only for definitive failures."""
    email = (email or "").strip().lower()
    if not email or not _SYNTAX.match(email):
        return {"verdict": "bad syntax", "reject": True}
    local, _, domain = email.partition("@")
    if domain in _DISPOSABLE:
        return {"verdict": "disposable", "reject": True}
    with _lock:
        mx = _cache.get(domain, "MISS")
    if mx == "MISS":
        mx = _doh_mx(domain)
        with _lock:
            _cache[domain] = mx
    if mx is False:
        return {"verdict": "no mail server (MX)", "reject": True}
    # mx True or None (uncertain → fail open)
    if local in _ROLE:
        return {"verdict": "role", "reject": False}
    return {"verdict": "ok", "reject": False}
