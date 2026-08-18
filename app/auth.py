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
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, Header, HTTPException
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
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(hours=config.ACCESS_TOKEN_HOURS),
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def create_refresh_token(user: User) -> str:
    """Create a long-lived session credential for the secure browser cookie.

    Refresh tokens intentionally carry only the user identity. Organization,
    role, and workspace access are re-read from the database whenever an access
    token is refreshed, so permission changes take effect without a new login.
    """
    payload = {
        "sub": str(user.id),
        "type": "refresh",
        "jti": secrets.token_urlsafe(16),
        "exp": datetime.now(timezone.utc) + timedelta(days=config.REFRESH_TOKEN_DAYS),
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def decode_token(token: str, expected_type: str = "access") -> dict:
    try:
        claims = jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")
    # Tokens issued before token types were introduced are access tokens. This
    # keeps already signed-in production users working through the rollout.
    token_type = claims.get("type", "access")
    if token_type != expected_type:
        raise HTTPException(401, "Invalid token type")
    return claims


# ---------------------------------------------------------------- context
class AuthContext:
    def __init__(self, user: User, org_id: int, role: str, workspace_ids: list, db: Session,
                 preview_as_client: bool = False):
        self.user = user
        self.org_id = org_id
        self.role = role
        self._workspace_ids = workspace_ids
        self.db = db
        # "Preview as client" (the X-Client-Preview header) can only ever REMOVE
        # what an operator sees. It never grants access, never widens a workspace
        # filter, and is a no-op for a real client — so the worst a forged header
        # can do is show its sender less than they are entitled to.
        self.preview_as_client = bool(preview_as_client) and role != "client"

    @property
    def is_master(self) -> bool:
        return self.role in MASTER_ROLES

    @property
    def sees_as_client(self) -> bool:
        """True when this request must be answered with a client's field of view.

        Deliberately `role == "client"` and not `not is_master`: a `member` is an
        internal operator and keeps seeing internal work. Routers ask this rather
        than checking the role themselves, so the preview toggle reaches every
        endpoint that already respects the client's view — including ones written
        after it."""
        return self.role == "client" or self.preview_as_client

    def allowed_workspace_ids(self) -> list:
        """Workspace ids this identity may touch.

        Archived workspaces are excluded HERE rather than at each call site.
        This is the one function every scoped query, every switcher and every
        `require_workspace` already goes through, so a workspace that has been
        archived stops being reachable everywhere at once — including from
        screens written after the archive feature existed."""
        if self.is_master:
            rows = (self.db.query(Workspace.id)
                    .filter(Workspace.org_id == self.org_id, Workspace.archived_at.is_(None)).all())
            return [r[0] for r in rows]
        ids = list(self._workspace_ids or [])
        if not ids:
            return []
        # A member/client carries their ids in the token, which was minted
        # before the archive happened — so they are re-checked against the
        # table rather than trusted.
        live = {r[0] for r in self.db.query(Workspace.id)
                .filter(Workspace.id.in_(ids), Workspace.archived_at.is_(None)).all()}
        return [i for i in ids if i in live]

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


def get_ctx_unverified(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
    x_client_preview: str | None = Header(default=None, alias="X-Client-Preview"),
) -> AuthContext:
    """Authenticate WITHOUT the pending-password-change gate.

    Only two endpoints may use this — `/api/auth/me`, so the app can find out it
    needs to ask, and `/api/auth/change-password`, so the user can answer. Every
    other route takes `get_ctx` below and is locked until the temporary password
    is gone."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(401, "Missing bearer token")
    claims = decode_token(credentials.credentials)
    user = db.query(User).filter(User.id == int(claims["sub"]), User.active == True).first()  # noqa: E712
    if not user:
        raise HTTPException(401, "Unknown or deactivated user")
    return AuthContext(user, claims["org"], claims["role"], claims.get("ws", []), db,
                       preview_as_client=(x_client_preview or "").strip() in ("1", "true", "yes"))


# The 403 detail is matched by the frontend, so keep the string and the check
# together rather than leaving the contract to a comment in two files.
PASSWORD_CHANGE_REQUIRED = "Password change required"


def get_ctx(ctx: AuthContext = Depends(get_ctx_unverified)) -> AuthContext:
    """The dependency every business route uses.

    An account still holding the temporary password from its invite is refused
    here, in the data layer's doorway — not hidden behind a screen it could skip
    by typing a URL or calling the API directly. `require_master` and every
    router depend on this, so the lock applies everywhere by construction."""
    if ctx.user.must_change_password:
        raise HTTPException(403, PASSWORD_CHANGE_REQUIRED)
    return ctx


def require_master(ctx: AuthContext = Depends(get_ctx)) -> AuthContext:
    if not ctx.is_master:
        raise HTTPException(403, "Master (owner/admin) access required")
    return ctx


def scoped(query, model, ctx: AuthContext, workspace_id: int | None = None):
    """Apply the mandatory workspace filter to any query on a scoped model."""
    return query.filter(model.workspace_id.in_(ctx.workspace_ids_for_query(workspace_id)))
