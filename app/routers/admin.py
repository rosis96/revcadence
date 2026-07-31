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
    # The workspace is a PACKAGE: pipeline + enrichment config + reply space
    # are all provisioned together — no separate "create reply space" step.
    from ..provision import provision_workspace
    provision_workspace(ctx.db, w)
    ctx.db.add(AuditLog(org_id=ctx.org_id, workspace_id=w.id, user_id=ctx.user.id,
                        action="create_workspace", object_type="workspace", object_id=w.id))
    ctx.db.commit()
    return {"id": w.id, "name": w.name, "slug": w.slug}


class WorkspacePatch(BaseModel):
    name: str | None = None
    active: bool | None = None


@router.patch("/workspaces/{workspace_id}")
def update_workspace(workspace_id: int, body: WorkspacePatch, ctx: AuthContext = Depends(require_master)):
    """Rename a workspace and/or toggle its active flag. Deactivating is the safe
    way to 'remove' a workspace that still holds data — nothing is destroyed."""
    w = _org_workspace(ctx, workspace_id)
    if body.name is not None:
        nm = body.name.strip()
        if not nm:
            raise HTTPException(422, "Name is required")
        w.name = nm
    if body.active is not None:
        w.active = body.active
    ctx.db.add(AuditLog(org_id=ctx.org_id, workspace_id=w.id, user_id=ctx.user.id,
                        action="update_workspace", object_type="workspace", object_id=w.id,
                        data={"name": w.name, "active": w.active}))
    ctx.db.commit()
    return {"id": w.id, "name": w.name, "slug": w.slug, "active": w.active}


@router.delete("/workspaces/{workspace_id}")
def delete_workspace(workspace_id: int, ctx: AuthContext = Depends(require_master)):
    """Hard-delete a workspace, but ONLY when it holds no business data. If it has
    contacts, companies, deals, or leads, we refuse and tell the caller to
    deactivate instead — so a populated client workspace can never be wiped by
    accident. Empty workspaces are removed with an FK-safe cascade of their
    provisioned config rows."""
    from ..db import Base
    from ..models.crm import Company, Contact, Deal
    from ..models.enrich import EnrichLead
    from ..models.reply import ReplyLead

    w = _org_workspace(ctx, workspace_id)

    counts = {}
    for label, Model in [("companies", Company), ("contacts", Contact), ("deals", Deal),
                         ("reply leads", ReplyLead), ("enrich leads", EnrichLead)]:
        n = ctx.db.query(Model).filter(Model.workspace_id == workspace_id).count()
        if n:
            counts[label] = n
    if counts:
        detail = ", ".join(f"{n} {label}" for label, n in counts.items())
        raise HTTPException(409, f"This workspace still holds data ({detail}). "
                                 f"Deactivate it instead of deleting.")

    # A client locked to this workspace would be orphaned — block and explain.
    for m in ctx.db.query(Membership).filter(Membership.org_id == ctx.org_id).all():
        if m.role == "client" and (m.workspace_ids or []) == [workspace_id]:
            raise HTTPException(409, "A client user is locked to this workspace. "
                                     "Reassign or deactivate that user first.")

    # Drop this workspace id from any member's workspace list.
    for m in ctx.db.query(Membership).filter(Membership.org_id == ctx.org_id).all():
        if m.workspace_ids and workspace_id in m.workspace_ids:
            m.workspace_ids = [x for x in m.workspace_ids if x != workspace_id]
    ctx.db.flush()

    # Delete every child row that points at this workspace, children before
    # parents (reversed FK order), then the workspace row itself.
    for tbl in reversed(Base.metadata.sorted_tables):
        if tbl.name == "workspaces":
            continue
        if "workspace_id" in tbl.c:
            ctx.db.execute(tbl.delete().where(tbl.c.workspace_id == workspace_id))
    ctx.db.execute(Workspace.__table__.delete().where(Workspace.__table__.c.id == workspace_id))
    ctx.db.commit()
    return {"ok": True}


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


@router.post("/users/{user_id}/reset-link")
def reset_link(user_id: int, ctx: AuthContext = Depends(require_master)):
    """Owner-generated password reset: returns a one-time link to hand to the user
    (works today without email delivery). Valid 1 hour."""
    from ..routers.auth import make_reset_token
    m = ctx.db.query(Membership).filter(Membership.user_id == user_id, Membership.org_id == ctx.org_id).first()
    if not m:
        raise HTTPException(404, "User not in this organization")
    u = ctx.db.query(User).filter(User.id == user_id).first()
    raw = make_reset_token(ctx.db, u)
    ctx.db.add(AuditLog(org_id=ctx.org_id, user_id=ctx.user.id, action="reset_link",
                        object_type="user", object_id=user_id))
    ctx.db.commit()
    return {"ok": True, "email": u.email, "reset_path": f"/#/reset/{raw}"}
