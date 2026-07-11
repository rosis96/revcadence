"""Master-only administration: workspaces and users. This is where you create a
client login: POST /api/admin/users with role="client" and their workspace."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import AuthContext, hash_password, require_master
from ..models.audit import AuditLog
from ..models.crm import DEFAULT_STAGES, Stage
from ..models.identity import ALIAS_SOURCES, ROLES, Membership, User, Workspace, WorkspaceAlias

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


# ---------------------------------------------------------------- workspace aliases
class AliasIn(BaseModel):
    workspace_id: int
    source_system: str            # reply_manager / enrichment / client_portals
    external_name: str
    external_id: str = ""


class AliasPatch(BaseModel):
    workspace_id: int | None = None
    external_name: str | None = None
    external_id: str | None = None


def _alias_out(a: WorkspaceAlias):
    return {"id": a.id, "workspace_id": a.workspace_id, "source_system": a.source_system,
            "external_name": a.external_name, "external_id": a.external_id or ""}


def _org_workspace(ctx, workspace_id: int) -> Workspace:
    w = ctx.db.query(Workspace).filter(Workspace.id == workspace_id, Workspace.org_id == ctx.org_id).first()
    if not w:
        raise HTTPException(422, f"Workspace {workspace_id} not found in this organization")
    return w


@router.get("/aliases")
def list_aliases(source_system: str = "", workspace_id: int = 0, ctx: AuthContext = Depends(require_master)):
    q = (ctx.db.query(WorkspaceAlias)
         .join(Workspace, Workspace.id == WorkspaceAlias.workspace_id)
         .filter(Workspace.org_id == ctx.org_id))
    if source_system:
        q = q.filter(WorkspaceAlias.source_system == source_system)
    if workspace_id:
        q = q.filter(WorkspaceAlias.workspace_id == workspace_id)
    return [_alias_out(a) for a in q.order_by(WorkspaceAlias.source_system, WorkspaceAlias.external_name).all()]


@router.post("/aliases")
def create_alias(body: AliasIn, ctx: AuthContext = Depends(require_master)):
    if body.source_system not in ALIAS_SOURCES:
        raise HTTPException(422, f"source_system must be one of {ALIAS_SOURCES}")
    name = body.external_name.strip()
    if not name:
        raise HTTPException(422, "external_name is required")
    _org_workspace(ctx, body.workspace_id)
    if ctx.db.query(WorkspaceAlias).filter(WorkspaceAlias.source_system == body.source_system,
                                           WorkspaceAlias.external_name == name).first():
        raise HTTPException(409, f"Alias already exists for ({body.source_system}, {name!r})")
    a = WorkspaceAlias(workspace_id=body.workspace_id, source_system=body.source_system,
                       external_name=name, external_id=body.external_id or None)
    ctx.db.add(a)
    ctx.db.flush()
    ctx.db.add(AuditLog(org_id=ctx.org_id, workspace_id=body.workspace_id, user_id=ctx.user.id,
                        action="create_alias", object_type="workspace_alias", object_id=a.id,
                        data={"source": body.source_system, "name": name}))
    ctx.db.commit()
    return _alias_out(a)


@router.patch("/aliases/{alias_id}")
def edit_alias(alias_id: int, body: AliasPatch, ctx: AuthContext = Depends(require_master)):
    a = (ctx.db.query(WorkspaceAlias)
         .join(Workspace, Workspace.id == WorkspaceAlias.workspace_id)
         .filter(WorkspaceAlias.id == alias_id, Workspace.org_id == ctx.org_id).first())
    if not a:
        raise HTTPException(404, "Alias not found")
    if body.workspace_id is not None:
        _org_workspace(ctx, body.workspace_id)
        a.workspace_id = body.workspace_id
    if body.external_name is not None:
        name = body.external_name.strip()
        dup = ctx.db.query(WorkspaceAlias).filter(WorkspaceAlias.source_system == a.source_system,
                                                  WorkspaceAlias.external_name == name,
                                                  WorkspaceAlias.id != a.id).first()
        if dup:
            raise HTTPException(409, f"Alias already exists for ({a.source_system}, {name!r})")
        a.external_name = name
    if body.external_id is not None:
        a.external_id = body.external_id or None
    ctx.db.commit()
    return _alias_out(a)


@router.delete("/aliases/{alias_id}")
def delete_alias(alias_id: int, ctx: AuthContext = Depends(require_master)):
    a = (ctx.db.query(WorkspaceAlias)
         .join(Workspace, Workspace.id == WorkspaceAlias.workspace_id)
         .filter(WorkspaceAlias.id == alias_id, Workspace.org_id == ctx.org_id).first())
    if not a:
        raise HTTPException(404, "Alias not found")
    ctx.db.delete(a)
    ctx.db.commit()
    return {"ok": True}


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
