"""Master-only administration: workspaces and users. This is where you create a
client login: POST /api/admin/users with role="client" and their workspace."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import AuthContext, hash_password, require_master
from ..models.audit import AuditLog
from ..models.crm import DEFAULT_STAGES, Stage
from ..models.identity import ROLES, Membership, User, Workspace

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _slugify(v: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in v.lower()).strip("-")


# ---------------------------------------------------------------- workspaces
class WorkspaceIn(BaseModel):
    name: str
    slug: str = ""
    legacy_name: str = ""


@router.get("/workspaces")
def list_workspaces(ctx: AuthContext = Depends(require_master)):
    ws = ctx.db.query(Workspace).filter(Workspace.org_id == ctx.org_id).order_by(Workspace.name).all()
    return [{"id": w.id, "name": w.name, "slug": w.slug, "active": w.active, "legacy_name": w.legacy_name} for w in ws]


@router.post("/workspaces")
def create_workspace(body: WorkspaceIn, ctx: AuthContext = Depends(require_master)):
    slug = body.slug or _slugify(body.name)
    if ctx.db.query(Workspace).filter(Workspace.org_id == ctx.org_id, Workspace.slug == slug).first():
        raise HTTPException(409, "Workspace slug already exists")
    w = Workspace(org_id=ctx.org_id, name=body.name, slug=slug, legacy_name=body.legacy_name)
    ctx.db.add(w)
    ctx.db.flush()
    # Seed the default pipeline for the new workspace
    for name, color, order, won, lost in DEFAULT_STAGES:
        ctx.db.add(Stage(workspace_id=w.id, name=name, color=color, sort_order=order, is_won=won, is_lost=lost))
    ctx.db.add(AuditLog(org_id=ctx.org_id, workspace_id=w.id, user_id=ctx.user.id,
                        action="create_workspace", object_type="workspace", object_id=w.id))
    ctx.db.commit()
    return {"id": w.id, "name": w.name, "slug": w.slug}


# ---------------------------------------------------------------- users
class UserIn(BaseModel):
    email: str
    name: str = ""
    password: str
    role: str = "member"            # owner / admin / member / client
    workspace_ids: list[int] = []   # required for member and client


@router.get("/users")
def list_users(ctx: AuthContext = Depends(require_master)):
    rows = (
        ctx.db.query(User, Membership)
        .join(Membership, Membership.user_id == User.id)
        .filter(Membership.org_id == ctx.org_id)
        .all()
    )
    return [
        {"id": u.id, "email": u.email, "name": u.name, "role": m.role,
         "workspace_ids": m.workspace_ids or [], "active": u.active}
        for u, m in rows
    ]


@router.post("/users")
def create_user(body: UserIn, ctx: AuthContext = Depends(require_master)):
    if body.role not in ROLES:
        raise HTTPException(422, f"role must be one of {ROLES}")
    if body.role == "client" and len(body.workspace_ids) != 1:
        raise HTTPException(422, "A client user must be locked to exactly one workspace")
    if body.role == "member" and not body.workspace_ids:
        raise HTTPException(422, "A member needs at least one workspace")
    # Verify the workspaces belong to this org — never attach across orgs.
    for wid in body.workspace_ids:
        w = ctx.db.query(Workspace).filter(Workspace.id == wid, Workspace.org_id == ctx.org_id).first()
        if not w:
            raise HTTPException(422, f"Workspace {wid} not found in this organization")
    email = body.email.lower().strip()
    if ctx.db.query(User).filter(User.email == email).first():
        raise HTTPException(409, "Email already registered")
    u = User(email=email, name=body.name, password_hash=hash_password(body.password))
    ctx.db.add(u)
    ctx.db.flush()
    ctx.db.add(Membership(user_id=u.id, org_id=ctx.org_id, role=body.role, workspace_ids=body.workspace_ids))
    ctx.db.add(AuditLog(org_id=ctx.org_id, user_id=ctx.user.id, action="create_user",
                        object_type="user", object_id=u.id, data={"role": body.role}))
    ctx.db.commit()
    return {"id": u.id, "email": u.email, "role": body.role}


@router.post("/users/{user_id}/deactivate")
def deactivate_user(user_id: int, ctx: AuthContext = Depends(require_master)):
    m = ctx.db.query(Membership).filter(Membership.user_id == user_id, Membership.org_id == ctx.org_id).first()
    if not m:
        raise HTTPException(404, "User not in this organization")
    u = ctx.db.query(User).filter(User.id == user_id).first()
    u.active = False
    ctx.db.add(AuditLog(org_id=ctx.org_id, user_id=ctx.user.id, action="deactivate_user",
                        object_type="user", object_id=user_id))
    ctx.db.commit()
    return {"ok": True}
