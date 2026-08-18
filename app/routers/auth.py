import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import config
from ..auth import (AuthContext, create_refresh_token, create_token, decode_token,
                    get_ctx_unverified, hash_password, verify_password)
from ..db import get_db
from ..models.audit import AuditLog
from ..models.identity import Membership, User, Workspace

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _hash_token(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


def _secure_request(request: Request) -> bool:
    """Honor the public scheme when running behind Railway's HTTPS proxy."""
    forwarded = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
    return request.url.scheme == "https" or forwarded == "https"


def _set_refresh_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        key=config.REFRESH_COOKIE_NAME,
        value=token,
        max_age=config.REFRESH_TOKEN_DAYS * 24 * 60 * 60,
        expires=datetime.now(timezone.utc) + timedelta(days=config.REFRESH_TOKEN_DAYS),
        path="/api/auth",
        secure=_secure_request(request),
        httponly=True,
        samesite="lax",
    )


def _clear_refresh_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        key=config.REFRESH_COOKIE_NAME,
        path="/api/auth",
        secure=_secure_request(request),
        httponly=True,
        samesite="lax",
    )


def _refresh_failure(request: Request, detail: str) -> JSONResponse:
    response = JSONResponse(status_code=401, content={"detail": detail})
    _clear_refresh_cookie(response, request)
    return response


def make_reset_token(db, user: User) -> str:
    """Issue a one-time password-reset token (raw returned once; only its hash is
    stored). Valid for 1 hour."""
    raw = secrets.token_urlsafe(32)
    user.reset_token_hash = _hash_token(raw)
    user.reset_expires_at = datetime.utcnow() + timedelta(hours=1)
    db.commit()
    return raw


class LoginIn(BaseModel):
    email: str
    password: str


class BootstrapIn(BaseModel):
    org: str = "RevCadence"
    email: str
    password: str
    name: str = ""


@router.post("/bootstrap")
def bootstrap(body: BootstrapIn, db: Session = Depends(get_db)):
    """One-time first-admin creation. Works ONLY while zero users exist —
    permanently 403 afterwards. No token required (there is nobody to have one)."""
    from ..bootstrap import create_first_admin, users_exist
    if users_exist(db):
        raise HTTPException(403, "Bootstrap disabled: users already exist")
    if len(body.password) < 12:
        raise HTTPException(422, "Password must be at least 12 characters")
    try:
        result = create_first_admin(db, body.org, body.email, body.password, body.name)
    except RuntimeError as e:  # race: someone bootstrapped between check and write
        raise HTTPException(403, str(e))
    return {"ok": True, **result, "next": "POST /api/auth/login with these credentials"}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.lower().strip(), User.active == True).first()  # noqa: E712
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Wrong email or password")
    membership = db.query(Membership).filter(Membership.user_id == user.id).first()
    if not membership:
        raise HTTPException(403, "User has no organization membership")
    user.last_login_at = datetime.utcnow()
    db.add(AuditLog(org_id=membership.org_id, user_id=user.id, action="login"))
    db.commit()
    _set_refresh_cookie(response, request, create_refresh_token(user))
    return {
        "token": create_token(user, membership),
        "role": membership.role,
        # True for an account still on the temporary password from its invite.
        # The token is real and the session is real — but every business route
        # refuses it until the password is changed (see auth.get_ctx).
        "must_change_password": bool(user.must_change_password),
        "user": {"id": user.id, "email": user.email, "name": user.name},
    }


@router.post("/refresh")
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    """Restore/extend a browser session without asking for the password again."""
    raw = request.cookies.get(config.REFRESH_COOKIE_NAME, "")
    try:
        if raw:
            claims = decode_token(raw, expected_type="refresh")
        else:
            # One-time migration path for browsers that still have a valid
            # access token from before persistent refresh cookies existed.
            authorization = request.headers.get("authorization", "")
            if not authorization.startswith("Bearer "):
                return _refresh_failure(request, "No refresh session")
            claims = decode_token(authorization.removeprefix("Bearer ").strip())
        user_id = int(claims["sub"])
    except (HTTPException, KeyError, TypeError, ValueError):
        return _refresh_failure(request, "Refresh session expired or invalid")

    user = db.query(User).filter(User.id == user_id, User.active == True).first()  # noqa: E712
    membership = db.query(Membership).filter(Membership.user_id == user_id).first() if user else None
    if not user or not membership:
        return _refresh_failure(request, "Unknown, deactivated, or unassigned user")

    # Rotate and slide the refresh session on successful use. Logging in on a
    # second browser/device does not revoke this cookie or its access token.
    _set_refresh_cookie(response, request, create_refresh_token(user))
    return {"token": create_token(user, membership)}


@router.post("/logout")
def logout(request: Request, response: Response):
    _clear_refresh_cookie(response, request)
    return {"ok": True}


class ForgotIn(BaseModel):
    email: str


@router.post("/forgot")
def forgot(body: ForgotIn, db: Session = Depends(get_db)):
    """Start a password reset. Always returns the same message (no account
    enumeration). If the account exists a reset token is created; the workspace
    owner can hand the reset link to the user (email delivery not configured yet)."""
    user = db.query(User).filter(User.email == body.email.lower().strip(), User.active == True).first()  # noqa: E712
    if user:
        raw = make_reset_token(db, user)
        # server-side breadcrumb for the operator; not returned to the requester.
        print(f"[auth] password reset requested for {user.email} → /#/reset/{raw}")
    return {"ok": True, "message": "If that account exists, a reset link has been created. "
            "Ask your workspace owner for it if you don't receive an email."}


class ResetIn(BaseModel):
    token: str
    password: str


@router.post("/reset")
def reset(body: ResetIn, db: Session = Depends(get_db)):
    if len(body.password) < 6:
        raise HTTPException(422, "Password must be at least 6 characters")
    h = _hash_token(body.token.strip())
    user = db.query(User).filter(User.reset_token_hash == h, User.active == True).first()  # noqa: E712
    if not user or not user.reset_expires_at or user.reset_expires_at < datetime.utcnow():
        raise HTTPException(400, "This reset link is invalid or has expired.")
    user.password_hash = hash_password(body.password)
    user.reset_token_hash = ""
    user.reset_expires_at = None
    # A reset satisfies the invite's "change it before you use it" requirement:
    # the user has just chosen a password nobody emailed them.
    user.must_change_password = False
    m = db.query(Membership).filter(Membership.user_id == user.id).first()
    if m:
        db.add(AuditLog(org_id=m.org_id, user_id=user.id, action="password_reset"))
    db.commit()
    return {"ok": True, "message": "Password updated. You can sign in now."}


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password")
def change_password(body: ChangePasswordIn, ctx: AuthContext = Depends(get_ctx_unverified)):
    """Change your own password, and the only route an invited account can reach
    before it has.

    The current password is required even though the caller already holds a valid
    token: a token picked up from a shared machine must not be enough to take the
    account over, and on the invite path "current" is the temporary password from
    the email — which proves the person at the keyboard is the one it was sent to.
    """
    user = ctx.user
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Your current password is not correct")
    if len(body.new_password) < 6:
        raise HTTPException(422, "Password must be at least 6 characters")
    if verify_password(body.new_password, user.password_hash):
        raise HTTPException(422, "Choose a password you have not used here before")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    # A pending reset link is a second way in; changing the password closes it.
    user.reset_token_hash = ""
    user.reset_expires_at = None
    ctx.db.add(AuditLog(org_id=ctx.org_id, user_id=user.id, action="change_password"))
    ctx.db.commit()
    return {"ok": True, "message": "Password updated."}


@router.get("/me")
def me(ctx: AuthContext = Depends(get_ctx_unverified)):
    # Reachable while a password change is pending, on purpose: this is how the
    # app learns it has to ask. Everything else stays locked.
    ws = (
        ctx.db.query(Workspace)
        .filter(Workspace.id.in_(ctx.allowed_workspace_ids()))
        .order_by(Workspace.name)
        .all()
    )
    return {
        "user": {"id": ctx.user.id, "email": ctx.user.email, "name": ctx.user.name},
        "role": ctx.role,
        "is_master": ctx.is_master,
        "must_change_password": bool(ctx.user.must_change_password),
        # Masters see the switcher list; a client sees exactly one workspace.
        # logo_url powers the white-label mark at the top of the client workspace rail.
        "workspaces": [{"id": w.id, "name": w.name, "slug": w.slug, "logo_url": w.logo_url or ""} for w in ws],
    }
