from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import AuthContext, create_token, get_ctx, verify_password
from ..db import get_db
from ..models.audit import AuditLog
from ..models.identity import Membership, User, Workspace

router = APIRouter(prefix="/api/auth", tags=["auth"])


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
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.lower().strip(), User.active == True).first()  # noqa: E712
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Wrong email or password")
    membership = db.query(Membership).filter(Membership.user_id == user.id).first()
    if not membership:
        raise HTTPException(403, "User has no organization membership")
    user.last_login_at = datetime.utcnow()
    db.add(AuditLog(org_id=membership.org_id, user_id=user.id, action="login"))
    db.commit()
    return {
        "token": create_token(user, membership),
        "role": membership.role,
        "user": {"id": user.id, "email": user.email, "name": user.name},
    }


@router.get("/me")
def me(ctx: AuthContext = Depends(get_ctx)):
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
        # Masters see the switcher list; a client sees exactly one workspace.
        "workspaces": [{"id": w.id, "name": w.name, "slug": w.slug} for w in ws],
    }
