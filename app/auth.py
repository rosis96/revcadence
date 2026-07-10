"""Authentication + workspace isolation.

Rules enforced here (not in the UI):
- owner/admin ("master" roles): access every workspace in their org, get the
  workspace switcher and the all-workspaces rollup.
- member: only workspaces listed in their membership.
- client: hard-locked to exactly ONE workspace. Any request for another
  workspace — or for "all workspaces" — is a 403.

Every business query MUST go through `scoped(...)` or use
`ctx.workspace_ids_for_query()` so a forgotten filter fails safe.
"""
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from . import config
from .db import get_db
from .models.identity import MASTER_ROLES, Membership, Organization, User, Workspace

# ---------------------------------------------------------------- passwords
_ITER = 260_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITER).hex()
    return f"pbkdf2${_ITER}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters)).hex()
        return secrets.compare_digest(candidate, digest)
    except Exception:
        return False


# ---------------------------------------------------------------- tokens
def create_token(user: User, membership: Membership) -> str:
    payload = {
        "sub": str(user.id),
        "org": membership.org_id,
        "role": membership.role,
        "ws": membership.workspace_ids or [],
        "exp": datetime.now(timezone.utc) + timedelta(hours=config.ACCESS_TOKEN_HOURS),
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")


# ---------------------------------------------------------------- context
class AuthContext:
    def __init__(self, user: User, org_id: int, role: str, workspace_ids: list, db: Session):
        self.user = user
        self.org_id = org_id
        self.role = role
        self._workspace_ids = workspace_ids
        self.db = db

    @property
    def is_master(self) -> bool:
        return self.role in MASTER_ROLES

    def allowed_workspace_ids(self) -> list:
        """Workspace ids this identity may touch."""
        if self.is_master:
            rows = self.db.query(Workspace.id).filter(Workspace.org_id == self.org_id).all()
            return [r[0] for r in rows]
        return list(self._workspace_ids or [])

    def require_workspace(self, workspace_id: int) -> int:
        """403 unless this identity may access the workspace. Clients asking for
        anything outside their single workspace are refused."""
        if workspace_id not in self.allowed_workspace_ids():
            raise HTTPException(403, "No access to this workspace")
        return workspace_id

    def workspace_ids_for_query(self, requested: int | None = None) -> list:
        """The ONLY sanctioned way to build a workspace filter.
        - requested=None → all allowed (masters: whole org; client: their one).
        - requested=<id> → that id, if allowed."""
        allowed = self.allowed_workspace_ids()
        if requested is None:
            return allowed
        if requested not in allowed:
            raise HTTPException(403, "No access to this workspace")
        return [requested]


# Proper OpenAPI security scheme: Swagger shows the global Authorize button and
# sends "Authorization: Bearer <token>" automatically on every protected route.
bearer_scheme = HTTPBearer(auto_error=False, description="Paste the JWT from POST /api/auth/login")


def get_ctx(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> AuthContext:
    if credentials is None or not credentials.credentials:
        raise HTTPException(401, "Missing bearer token")
    claims = decode_token(credentials.credentials)
    user = db.query(User).filter(User.id == int(claims["sub"]), User.active == True).first()  # noqa: E712
    if not user:
        raise HTTPException(401, "Unknown or deactivated user")
    return AuthContext(user, claims["org"], claims["role"], claims.get("ws", []), db)


def require_master(ctx: AuthContext = Depends(get_ctx)) -> AuthContext:
    if not ctx.is_master:
        raise HTTPException(403, "Master (owner/admin) access required")
    return ctx


def scoped(query, model, ctx: AuthContext, workspace_id: int | None = None):
    """Apply the mandatory workspace filter to any query on a scoped model."""
    return query.filter(model.workspace_id.in_(ctx.workspace_ids_for_query(workspace_id)))
