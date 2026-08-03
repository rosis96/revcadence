"""Sign in with Google — the one-click 'pick your account' connect, like
Instantly's Login button. It sits on top of domain-wide delegation: OAuth just
identifies which mailbox the user controls; the service account does the actual
sending/reading. So the admin still authorizes our Client ID once per domain,
but individual users no longer type their address — they click, choose, done.

Config (Railway env), only needed to enable this button:
  GOOGLE_OAUTH_CLIENT_ID       an OAuth 2.0 *Web application* client id
  GOOGLE_OAUTH_CLIENT_SECRET   its secret
  PUBLIC_BASE_URL              e.g. https://engine.revcadence.com (for the redirect)
"""
import base64
import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse

from ..auth import AuthContext, get_ctx
from ..mailbox import service

router = APIRouter(prefix="/api/oauth", tags=["oauth"])


def _base() -> str:
    return (os.getenv("PUBLIC_BASE_URL", "") or "").rstrip("/")


def _cfg():
    cid = (os.getenv("GOOGLE_OAUTH_CLIENT_ID", "") or "").strip()
    sec = (os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "") or "").strip()
    if not (cid and sec):
        return None
    return {"client_id": cid, "client_secret": sec, "redirect": _base() + "/api/oauth/google/callback"}


def enabled() -> bool:
    return _cfg() is not None


# --- signed state (CSRF + carries who/where, since the callback has no JWT) ---
def _secret() -> bytes:
    return (os.getenv("JWT_SECRET", "") or "revcadence").encode()


def _sign_state(payload: dict) -> str:
    raw = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{raw}.{sig}"


def _verify_state(state: str):
    try:
        raw, sig = state.rsplit(".", 1)
        exp = hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(sig, exp):
            return None
        d = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        if time.time() - d.get("t", 0) > 600:      # 10-minute window
            return None
        return d
    except Exception:  # noqa: BLE001
        return None


@router.get("/google/config")
def google_config(ctx: AuthContext = Depends(get_ctx)):
    """Frontend uses this to decide whether to show the 'Sign in with Google' button."""
    return {"enabled": enabled()}


@router.get("/google/start")
def google_start(workspace_id: int, ctx: AuthContext = Depends(get_ctx)):
    """Return the Google consent URL for the frontend to navigate to. (JSON, not a
    redirect, so the browser sends our auth header here.)"""
    c = _cfg()
    if not c:
        raise HTTPException(400, "Google sign-in isn't configured (GOOGLE_OAUTH_CLIENT_ID/SECRET).")
    ctx.require_workspace(workspace_id)
    state = _sign_state({"ws": workspace_id, "u": ctx.user.id, "t": time.time()})
    params = {"client_id": c["client_id"], "redirect_uri": c["redirect"], "response_type": "code",
              "scope": "openid email profile", "access_type": "online", "prompt": "select_account",
              "include_granted_scopes": "true", "state": state}
    return {"url": "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)}


@router.get("/google/callback")
def google_callback(code: str = "", state: str = "", error: str = ""):
    """Google redirects here. Exchange the code, read the verified email, and
    create the mailbox connection (domain-wide delegation does the sending)."""
    fail = RedirectResponse(_base() + "/#/settings/email?oauth=error")
    d = _verify_state(state) if state else None
    c = _cfg()
    if error or not code or not d or not c:
        return fail
    try:
        tok = requests.post("https://oauth2.googleapis.com/token", data={
            "code": code, "client_id": c["client_id"], "client_secret": c["client_secret"],
            "redirect_uri": c["redirect"], "grant_type": "authorization_code"}, timeout=15)
        if tok.status_code != 200:
            return fail
        access = tok.json().get("access_token", "")
        ui = requests.get("https://www.googleapis.com/oauth2/v3/userinfo",
                          headers={"Authorization": f"Bearer {access}"}, timeout=15)
        if ui.status_code != 200:
            return fail
        info = ui.json()
        email = (info.get("email") or "").lower().strip()
        if not email or not info.get("email_verified"):
            return fail
    except Exception:  # noqa: BLE001
        return fail

    from ..db import SessionLocal
    db = SessionLocal()
    try:
        service.connect_mailbox(db, d["ws"], d["u"], provider="google_workspace",
                                email=email, secret="", from_name=info.get("name", ""))
    except Exception:  # noqa: BLE001
        db.rollback()
        return fail
    finally:
        db.close()
    return RedirectResponse(_base() + "/#/settings/email?connected=1")
