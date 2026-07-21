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


_mx_hosts: dict = {}  # domain → lowercase MX host string (for ESP detection)


def esp_for(domain: str) -> str:
    """Email provider from MX host (legacy esp.py): Microsoft / Google / Other."""
    hosts = _mx_hosts.get(domain, "")
    if not hosts:
        return ""
    if "outlook" in hosts or "microsoft" in hosts or "office365" in hosts:
        return "Microsoft"
    if "google" in hosts or "googlemail" in hosts:
        return "Google"
    return "Other"


def _dnspython_mx(domain: str):
    """Direct DNS MX lookup via dnspython (UDP/TCP :53). Tries the system resolver
    first, then PUBLIC resolvers (8.8.8.8 / 1.1.1.1) — the container often has no
    resolver configured (this is the fallback the legacy esp.py relied on, and why
    ESP populated before). True = MX exists, False = definitively none,
    None = couldn't determine (→ let DoH try)."""
    try:
        import dns.resolver
    except Exception:
        return None
    for configure in (True, False):
        try:
            r = dns.resolver.Resolver(configure=configure)
            if not configure:
                r.nameservers = ["8.8.8.8", "1.1.1.1"]
            r.timeout = 5
            r.lifetime = 5
            ans = r.resolve(domain, "MX")
            hosts = " ".join(str(rec.exchange).lower().rstrip(".") for rec in ans).strip()
            if hosts:
                _mx_hosts[domain] = hosts
                return True
            return None
        except dns.resolver.NXDOMAIN:
            return False
        except dns.resolver.NoAnswer:
            try:  # no MX → implicit MX (A record) per RFC 5321
                r.resolve(domain, "A")
                return True
            except Exception:
                return False
        except Exception:
            continue  # broken/misconfigured resolver → try public, then DoH
    return None


def _doh_mx(domain: str):
    """Resolve MX, trying direct DNS first then DNS-over-HTTPS (works where raw
    :53 is blocked). Populates _mx_hosts (for ESP detection) on success.
    True = MX exists, False = definitively none, None = couldn't determine.

    DoH endpoints are LITERAL IPs (1.1.1.1 / 8.8.8.8), not hostnames: on a host
    whose own DNS is broken, resolving 'dns.google' would itself fail — so the
    hostname-based DoH could never connect. IPs need no DNS and ride over :443,
    which is already proven working (the app reaches Instantly/OpenAI over HTTPS).
    Their TLS certs include these IPs as SANs, so verification still passes."""
    direct = _dnspython_mx(domain)
    if direct is not None:
        return direct
    for host in ("https://1.1.1.1/dns-query", "https://8.8.8.8/resolve",
                 "https://dns.google/resolve", "https://cloudflare-dns.com/dns-query"):
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
                    _mx_hosts[domain] = " ".join(str(a.get("data", "")).lower()
                                                 for a in j.get("Answer", []))
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


def mx_diagnostics(domain: str = "gmail.com") -> dict:
    """Probe every MX-resolution tier independently so we can see EXACTLY which
    path works (or fails) on this host. Used by the /diag/dns endpoint."""
    out = {"domain": domain, "tiers": {}}
    try:
        import dns.resolver
        for name, configure in (("dnspython_system", True), ("dnspython_public_8.8.8.8/1.1.1.1", False)):
            try:
                r = dns.resolver.Resolver(configure=configure)
                if not configure:
                    r.nameservers = ["8.8.8.8", "1.1.1.1"]
                r.timeout = 5
                r.lifetime = 5
                ans = r.resolve(domain, "MX")
                out["tiers"][name] = {"ok": True,
                                      "hosts": " ".join(str(x.exchange).lower() for x in ans)[:120]}
            except Exception as e:
                out["tiers"][name] = {"ok": False, "err": f"{type(e).__name__}: {str(e)[:80]}"}
    except Exception as e:
        out["tiers"]["dnspython_import"] = {"ok": False, "err": str(e)[:80]}
    for host in ("https://1.1.1.1/dns-query", "https://8.8.8.8/resolve", "https://dns.google/resolve"):
        try:
            r = requests.get(host, params={"name": domain, "type": "MX"},
                             headers={"accept": "application/dns-json"}, timeout=6)
            ans = (r.json().get("Answer") or []) if r.status_code == 200 else []
            out["tiers"][f"doh {host}"] = {"ok": bool(ans), "http": r.status_code, "answers": len(ans)}
        except Exception as e:
            out["tiers"][f"doh {host}"] = {"ok": False, "err": f"{type(e).__name__}: {str(e)[:80]}"}
    _mx_hosts.pop(domain, None)
    res = _doh_mx(domain)
    out["result"] = {"resolved": res, "esp": esp_for(domain) or "Unknown",
                     "mx_hosts": _mx_hosts.get(domain, "")[:140]}
    return out


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
