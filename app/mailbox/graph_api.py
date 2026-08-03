"""Microsoft 365 transport via the Graph API (app-only / client credentials) — the
Microsoft analog of the Gmail domain-wide-delegation path. Runs over HTTPS (443),
so it works where SMTP/IMAP are blocked (Railway).

A single Azure AD app registration is granted **application** permissions
(Mail.Send, Mail.Read) with admin consent. The app then sends/reads as any
mailbox in that tenant. For a client's tenant, their admin grants consent to our
app via the admin-consent URL.

Config (Railway env):
  MS_GRAPH_TENANT_ID       our tenant (or 'organizations'); per-connect tenant may override
  MS_GRAPH_CLIENT_ID       the Azure app (client) id
  MS_GRAPH_CLIENT_SECRET   the app client secret
"""
import base64
import os

import requests

SCOPES_DISPLAY = ["Mail.Send", "Mail.Read"]   # application permissions to grant
_GRAPH = "https://graph.microsoft.com/v1.0"


def _cfg():
    cid = (os.getenv("MS_GRAPH_CLIENT_ID", "") or "").strip()
    sec = (os.getenv("MS_GRAPH_CLIENT_SECRET", "") or "").strip()
    ten = (os.getenv("MS_GRAPH_TENANT_ID", "") or "organizations").strip()
    if not (cid and sec):
        return None
    return {"client_id": cid, "client_secret": sec, "tenant": ten}


def enabled() -> bool:
    return _cfg() is not None


def client_id() -> str:
    return (os.getenv("MS_GRAPH_CLIENT_ID", "") or "").strip()


def admin_consent_url() -> str:
    c = _cfg()
    if not c:
        return ""
    # A client's admin visits this once to grant our app access to their tenant.
    return (f"https://login.microsoftonline.com/{c['tenant']}/adminconsent"
            f"?client_id={c['client_id']}")


def _token() -> str:
    c = _cfg()
    if not c:
        raise RuntimeError("Microsoft 365 is not configured (set MS_GRAPH_CLIENT_ID/SECRET).")
    r = requests.post(
        f"https://login.microsoftonline.com/{c['tenant']}/oauth2/v2.0/token",
        data={"client_id": c["client_id"], "client_secret": c["client_secret"],
              "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials"},
        timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"Microsoft token {r.status_code}: {r.text[:200]}")
    return r.json()["access_token"]


def graph_test(email: str) -> tuple[bool, str]:
    """Verify the app can access this mailbox. (ok, error)."""
    try:
        token = _token()
        r = requests.get(f"{_GRAPH}/users/{email}/mailFolders/inbox",
                         headers={"Authorization": f"Bearer {token}"}, timeout=15)
        if r.status_code == 200:
            return True, ""
        return False, f"Graph {r.status_code}: {r.text[:200]}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:300]


def graph_send(email: str, msg) -> str:
    """Send a built MIME message as `email` (raw-MIME sendMail keeps our threading
    headers). Raises on failure."""
    token = _token()
    raw_b64 = base64.b64encode(msg.as_bytes()).decode()
    r = requests.post(f"{_GRAPH}/users/{email}/sendMail",
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "text/plain"},
                      data=raw_b64, timeout=25)
    if r.status_code not in (200, 202):
        raise RuntimeError(f"Graph send failed {r.status_code}: {r.text[:200]}")
    return ""


def graph_thread(email: str, conversation_id: str) -> list[dict]:
    """Every message in an Outlook conversation, oldest first."""
    from . import transport
    out = []
    if not conversation_id:
        return out
    try:
        token = _token()
        hdr = {"Authorization": f"Bearer {token}"}
        cid = conversation_id.replace("'", "''")
        r = requests.get(f"{_GRAPH}/users/{email}/messages", headers=hdr,
                         params={"$filter": f"conversationId eq '{cid}'", "$select": "id,receivedDateTime",
                                 "$orderby": "receivedDateTime asc", "$top": 50}, timeout=20)
        if r.status_code != 200:
            return out
        for m in (r.json().get("value") or []):
            g = requests.get(f"{_GRAPH}/users/{email}/messages/{m['id']}/$value", headers=hdr, timeout=20)
            if g.status_code != 200 or not g.content:
                continue
            out.append(transport.parse_message(g.content))
    except Exception:  # noqa: BLE001
        return out
    return out


def graph_folders(email: str) -> list[dict]:
    """Mail folders for this mailbox (the Microsoft analog of Gmail labels)."""
    try:
        token = _token()
        r = requests.get(f"{_GRAPH}/users/{email}/mailFolders",
                         headers={"Authorization": f"Bearer {token}"}, params={"$top": 100}, timeout=15)
        if r.status_code != 200:
            return []
        return [{"id": f.get("id"), "name": f.get("displayName")} for f in (r.json().get("value") or [])]
    except Exception:  # noqa: BLE001
        return []


def graph_fetch_since(email: str, days: int = 60, limit: int = 200, folder: str = "inbox") -> list[dict]:
    """Best-effort: pull recent messages as raw MIME and parse them like the IMAP
    path. Returns [] on any failure."""
    from . import transport
    import datetime as _dt
    out = []
    try:
        token = _token()
        hdr = {"Authorization": f"Bearer {token}"}
        since = (_dt.datetime.utcnow() - _dt.timedelta(days=max(1, days))).strftime("%Y-%m-%dT00:00:00Z")
        r = requests.get(
            f"{_GRAPH}/users/{email}/mailFolders/{folder}/messages",
            headers=hdr,
            params={"$top": min(limit, 200), "$select": "id,conversationId",
                    "$filter": f"receivedDateTime ge {since}",
                    "$orderby": "receivedDateTime desc"},
            timeout=20)
        if r.status_code != 200:
            return out
        for m in (r.json().get("value") or [])[:limit]:
            g = requests.get(f"{_GRAPH}/users/{email}/messages/{m['id']}/$value",
                             headers=hdr, timeout=20)
            if g.status_code != 200 or not g.content:
                continue
            parsed = transport.parse_message(g.content)
            parsed["thread_id"] = m.get("conversationId") or ""
            out.append(parsed)
    except Exception:  # noqa: BLE001
        return out
    return out
