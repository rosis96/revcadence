"""Gmail API transport via a Google Workspace service account with domain-wide
delegation — the same model Instantly uses.

Why this exists: our host (Railway) blocks outbound SMTP/IMAP, so app-password
mail can't connect. The Gmail API runs over HTTPS (443), which is never blocked.
A single Google service account impersonates each connected mailbox; the mailbox's
Workspace admin authorizes our client_id once (Admin console -> Security -> API
controls -> Domain-wide delegation) with the scopes below.

Config (Railway env):
  GOOGLE_WORKSPACE_SA_JSON   the service-account key, raw JSON or base64 of it
  GOOGLE_WORKSPACE_CLIENT_ID (optional) shown in the connect instructions; falls
                             back to the client_id inside the key.
"""
import base64
import json
import os

import requests

# gmail.send to send, gmail.readonly to pull replies for deal threading.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]
# RevCadence's permanent service-account Client ID — the one every Workspace admin
# authorizes (published, not secret, exactly like Instantly). Env overrides it.
DEFAULT_CLIENT_ID = "101484446945354944460"
_BASE = "https://gmail.googleapis.com/gmail/v1/users"


def _sa_info():
    """Return the service-account dict from env, or None if unset/invalid."""
    raw = (os.getenv("GOOGLE_WORKSPACE_SA_JSON", "") or "").strip()
    if not raw:
        return None
    try:
        if raw.startswith("{"):
            return json.loads(raw)
        return json.loads(base64.b64decode(raw).decode())   # allow base64-wrapped JSON
    except Exception:  # noqa: BLE001
        return None


def enabled() -> bool:
    return _sa_info() is not None


def client_id() -> str:
    info = _sa_info() or {}
    return (os.getenv("GOOGLE_WORKSPACE_CLIENT_ID", "") or info.get("client_id", "") or DEFAULT_CLIENT_ID).strip()


def _token(subject: str) -> str:
    """Mint an OAuth token that impersonates `subject` (the mailbox address)."""
    from google.oauth2 import service_account
    import google.auth.transport.requests as gart
    info = _sa_info()
    if not info:
        raise RuntimeError("Google Workspace is not configured (set GOOGLE_WORKSPACE_SA_JSON).")
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES, subject=subject)
    creds.refresh(gart.Request())
    return creds.token


def _friendly(text: str) -> str:
    """Turn Google's cryptic auth errors into a clear next step."""
    low = (text or "").lower()
    if ("unauthorized_client" in low or "access_denied" in low or "not authorized" in low
            or "forbidden" in low or "\"code\": 403" in low or "status\": 403" in low):
        return (f"This Google Workspace hasn't authorized RevCadence yet. In that domain's "
                f"Google Admin → Security → API controls → Domain-wide delegation, add Client ID "
                f"{client_id()} with scopes: {', '.join(SCOPES)}. Then Test again.")
    return text[:300]


def gmail_test(email: str) -> tuple[bool, str]:
    """Verify delegation works for this mailbox (reads its profile). (ok, error)."""
    try:
        token = _token(email)
        r = requests.get(f"{_BASE}/{email}/profile",
                         headers={"Authorization": f"Bearer {token}"}, timeout=15)
        if r.status_code == 200:
            return True, ""
        return False, _friendly(f"Gmail API {r.status_code}: {r.text[:200]}")
    except Exception as e:  # noqa: BLE001
        return False, _friendly(str(e))


def gmail_send(email: str, msg, thread_id: str = "") -> str:
    """Send a built MIME message as `email`. Returns Gmail's threadId. Raises on failure."""
    token = _token(email)
    payload = {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}
    if thread_id:
        payload["threadId"] = thread_id
    r = requests.post(f"{_BASE}/{email}/messages/send",
                      headers={"Authorization": f"Bearer {token}"}, json=payload, timeout=25)
    if r.status_code not in (200, 202):
        raise RuntimeError(f"Gmail send failed {r.status_code}: {r.text[:200]}")
    return (r.json() or {}).get("threadId", "")


def gmail_thread(email: str, thread_id: str) -> list[dict]:
    """Every message in a Gmail thread, oldest first — for full-context import."""
    from . import transport
    out = []
    if not thread_id:
        return out
    try:
        token = _token(email)
        r = requests.get(f"{_BASE}/{email}/threads/{thread_id}",
                         headers={"Authorization": f"Bearer {token}"}, params={"format": "raw"}, timeout=25)
        if r.status_code != 200:
            return out
        for m in (r.json().get("messages") or []):
            raw_b64 = m.get("raw", "")
            if not raw_b64:
                continue
            parsed = transport.parse_message(base64.urlsafe_b64decode(raw_b64.encode()))
            parsed["internal_ts"] = int(m.get("internalDate") or 0)
            out.append(parsed)
        out.sort(key=lambda x: x.get("internal_ts", 0))
    except Exception:  # noqa: BLE001
        return out
    return out


def gmail_labels(email: str) -> list[dict]:
    """User-visible labels for this mailbox, so the UI can offer 'import a label'."""
    try:
        token = _token(email)
        r = requests.get(f"{_BASE}/{email}/labels",
                         headers={"Authorization": f"Bearer {token}"}, timeout=15)
        if r.status_code != 200:
            return []
        keep_system = {"INBOX", "SENT", "IMPORTANT", "STARRED"}
        out = []
        for lb in (r.json().get("labels") or []):
            if lb.get("type") == "system" and lb.get("id") not in keep_system:
                continue
            out.append({"id": lb.get("id"), "name": lb.get("name")})
        return sorted(out, key=lambda x: (x["name"] or "").lower())
    except Exception:  # noqa: BLE001
        return []


def gmail_fetch_since(email: str, days: int = 60, limit: int = 200, folder: str = "INBOX",
                      query: str = "") -> list[dict]:
    """Best-effort: pull recent messages and parse them like the IMAP path. `query`
    is a Gmail search string (e.g. 'label:\"Clients\" acme') that overrides folder.
    Returns [] on any failure so callers degrade gracefully."""
    from . import transport
    out = []
    try:
        token = _token(email)
        hdr = {"Authorization": f"Bearer {token}"}
        q = f"newer_than:{max(1, days)}d"
        if query.strip():
            q += " " + query.strip()
        elif folder and folder.upper() != "INBOX":
            q += f" label:{folder.lower()}"
        else:
            q += " in:inbox"
        r = requests.get(f"{_BASE}/{email}/messages", headers=hdr,
                         params={"q": q, "maxResults": min(limit, 200)}, timeout=20)
        if r.status_code != 200:
            return out
        for m in (r.json().get("messages") or [])[:limit]:
            g = requests.get(f"{_BASE}/{email}/messages/{m['id']}", headers=hdr,
                             params={"format": "raw"}, timeout=20)
            if g.status_code != 200:
                continue
            gj = g.json() or {}
            raw_b64 = gj.get("raw", "")
            if not raw_b64:
                continue
            parsed = transport.parse_message(base64.urlsafe_b64decode(raw_b64.encode()))
            parsed["thread_id"] = gj.get("threadId") or m.get("threadId") or ""
            parsed["internal_ts"] = int(gj.get("internalDate") or 0)   # for newest-per-thread
            out.append(parsed)
    except Exception:  # noqa: BLE001
        return out
    return out
