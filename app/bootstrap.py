"""First-admin bootstrapping — solves the fresh-deployment deadlock
(admin endpoints need a token; login needs a user).

Two equivalent paths, both usable ONLY while the users table is empty:
1. Startup: if ADMIN_EMAIL + ADMIN_PASSWORD env vars are set, the first admin
   is created automatically on boot (ADMIN_NAME / ADMIN_ORG optional).
2. POST /api/auth/bootstrap — one-time endpoint, hard-403 once any user exists.

After the first user exists both paths permanently deactivate; nothing else
about auth changes.
"""
import os

from sqlalchemy.orm import Session

from .auth import hash_password
from .models.audit import AuditLog
from .models.identity import Membership, Organization, User


def users_exist(db: Session) -> bool:
    return db.query(User.id).first() is not None


def create_first_admin(db: Session, org_name: str, email: str, password: str, name: str = "") -> dict:
    """Create org + owner. Caller must have verified users_exist() is False;
    this re-checks to close the race."""
    if users_exist(db):
        raise RuntimeError("Bootstrap refused: users already exist")
    email = email.lower().strip()
    slug = "".join(c if c.isalnum() else "-" for c in org_name.lower()).strip("-") or "org"
    org = db.query(Organization).filter(Organization.slug == slug).first()
    if org is None:
        org = Organization(name=org_name, slug=slug)
        db.add(org)
        db.flush()
    user = User(email=email, name=name or email.split("@")[0], password_hash=hash_password(password))
    db.add(user)
    db.flush()
    db.add(Membership(user_id=user.id, org_id=org.id, role="owner", workspace_ids=[]))
    db.add(AuditLog(org_id=org.id, user_id=user.id, action="bootstrap_first_admin"))
    db.commit()
    return {"org_id": org.id, "user_id": user.id, "email": email, "role": "owner"}


def maybe_reset_admin(db: Session) -> dict | None:
    """Deterministic recovery via env. Set ADMIN_FORCE_RESET=1 (with ADMIN_EMAIL +
    ADMIN_PASSWORD) and redeploy: the matching owner's password is reset (and
    the user reactivated). If that email doesn't exist yet, it's created as an
    owner so you always have a way back in. Remove ADMIN_FORCE_RESET afterward."""
    if os.getenv("ADMIN_FORCE_RESET", "").lower() not in ("1", "true", "yes"):
        return None
    email = os.getenv("ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("ADMIN_PASSWORD", "")
    if not email or not password:
        return None
    user = db.query(User).filter(User.email == email).first()
    if user:
        user.password_hash = hash_password(password)
        user.active = True
        db.commit()
        print(f"[bootstrap] ADMIN_FORCE_RESET: reset password for {email}")
        return {"reset": email}
    # email not found → create as owner in the first org so access is guaranteed
    org = db.query(Organization).order_by(Organization.id).first()
    if org is None:
        org = Organization(name=os.getenv("ADMIN_ORG", "RevCadence"), slug="revcadence")
        db.add(org)
        db.flush()
    user = User(email=email, name=os.getenv("ADMIN_NAME", "") or email.split("@")[0],
                password_hash=hash_password(password))
    db.add(user)
    db.flush()
    db.add(Membership(user_id=user.id, org_id=org.id, role="owner", workspace_ids=[]))
    db.commit()
    print(f"[bootstrap] ADMIN_FORCE_RESET: created owner {email}")
    return {"created": email}


def bootstrap_from_env(db: Session) -> dict | None:
    """Called on startup. No-op unless the users table is empty AND
    ADMIN_EMAIL + ADMIN_PASSWORD are set."""
    if users_exist(db):
        return None
    email = os.getenv("ADMIN_EMAIL", "").strip()
    password = os.getenv("ADMIN_PASSWORD", "")
    if not email or not password:
        return None
    result = create_first_admin(
        db,
        org_name=os.getenv("ADMIN_ORG", "RevCadence"),
        email=email,
        password=password,
        name=os.getenv("ADMIN_NAME", ""),
    )
    print(f"[bootstrap] first admin created from env: {result['email']} (owner)")
    return result
