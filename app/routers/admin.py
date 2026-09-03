"""Master-only administration: workspaces and users. This is where you create a
client login: POST /api/admin/users with role="client" and their workspace, or
POST /api/admin/workspaces/{id}/invite-client to do it and mail them the details
in one step."""
from datetime import datetime
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import config
from ..auth import AuthContext, hash_password, require_master, verify_password
from ..models.audit import AuditLog
from ..models.crm import DEFAULT_STAGES, Stage
from ..models.identity import (ALIAS_SOURCES, MASTER_ROLES, ROLES, Membership, User, Workspace,
                               WorkspaceAlias)

router = APIRouter(prefix="/api/admin", tags=["admin"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Ambiguous characters are left out on purpose. This password gets read off a
# screen or retyped out of an email, and "was that a 1 or an l" is how an invite
# turns into a support conversation.
_PW_LOWER = "abcdefghijkmnopqrstuvwxyz"
_PW_UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"
_PW_DIGITS = "23456789"
_PW_ALPHABET = _PW_LOWER + _PW_UPPER + _PW_DIGITS


def _temp_password() -> str:
    """A readable eight-character temporary password with mixed character types."""
    raw = [secrets.choice(_PW_LOWER), secrets.choice(_PW_UPPER), secrets.choice(_PW_DIGITS)]
    raw.extend(secrets.choice(_PW_ALPHABET) for _ in range(5))
    secrets.SystemRandom().shuffle(raw)
    return "".join(raw)


def _slugify(v: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in v.lower()).strip("-")


# ---------------------------------------------------------------- workspaces
class WorkspaceIn(BaseModel):
    name: str
    slug: str = ""
    legacy_name: str = ""
    # The client's website. Stored as a bare domain on the workspace so the
    # switcher can show the company's favicon with no upload.
    website: str = ""
    # Who this workspace is being made for, if the operator already knows. It
    # creates NO account and sends NO mail — it is remembered so the invite,
    # which happens later and separately, opens with the address already typed
    # instead of asking for it a second time.
    client_email: str = ""
    # Archived workspaces this one replaces. Purged, in the same transaction,
    # immediately before the new workspace is written — see create_workspace.
    replace_ids: list[int] = []


def _grouped_counts(db, model, workspace_ids: list[int]) -> dict[int, int]:
    """{workspace_id: row count} for one model, in a single grouped query. The
    admin table shows five of these across every workspace — done per row it is
    a screenful of queries, so it is done once per model instead."""
    if not workspace_ids:
        return {}
    rows = (db.query(model.workspace_id, func.count(model.id))
            .filter(model.workspace_id.in_(workspace_ids))
            .group_by(model.workspace_id).all())
    return {wid: n for wid, n in rows}


def _workspace_payload(ctx, ws: list) -> list[dict]:
    """The admin table's row shape for a set of workspaces: who the client is,
    how many people can reach it, what it holds, and when it was last touched.

    Every aggregate is a grouped query rather than a per-row lookup, and it is
    shared by the live list, the archive list and the duplicate check — so the
    three screens can never disagree about what a workspace contains."""
    from ..models.crm import Company, Contact, Deal

    ids = [w.id for w in ws]
    companies = _grouped_counts(ctx.db, Company, ids)
    contacts = _grouped_counts(ctx.db, Contact, ids)
    deals = _grouped_counts(ctx.db, Deal, ids)

    last_activity: dict[int, object] = {}
    if ids:
        for wid, at in (ctx.db.query(AuditLog.workspace_id, func.max(AuditLog.at))
                        .filter(AuditLog.workspace_id.in_(ids))
                        .group_by(AuditLog.workspace_id).all()):
            last_activity[wid] = at

    # One pass over the org's memberships: who is attached where, and which
    # client account each workspace was handed to.
    members: dict[int, int] = {}
    client_of: dict[int, dict] = {}
    # A workspace usually has one client login, but nothing enforces that — and
    # the row can only show one. Every address is collected separately, because
    # the duplicate check reads this payload: matching only the first one found
    # let a second client's address through as if the workspace had never seen
    # it, and the collision surfaced later as an unexplained refusal to invite.
    client_emails: dict[int, list[str]] = {}
    rows = (ctx.db.query(Membership, User)
            .join(User, User.id == Membership.user_id)
            .filter(Membership.org_id == ctx.org_id).all())
    for m, u in rows:
        if m.role in MASTER_ROLES:
            continue                       # masters reach every workspace; not a per-row fact
        for wid in (m.workspace_ids or []):
            members[wid] = members.get(wid, 0) + 1
            if m.role == "client":
                if wid not in client_of:
                    client_of[wid] = {"id": u.id, "name": u.name or "", "email": u.email,
                                      "active": bool(u.active)}
                client_emails.setdefault(wid, []).append(u.email)

    return [{
        "id": w.id, "name": w.name, "slug": w.slug, "active": w.active,
        "legacy_name": w.legacy_name,
        "client": client_of.get(w.id),
        "client_emails": sorted(client_emails.get(w.id, [])),
        # The address typed at creation, kept only until an invite makes it a
        # real client account. `client` is the fact; this is the intention.
        "pending_client_email": (w.settings or {}).get("client_email") or "",
        "members": members.get(w.id, 0),
        "counts": {"companies": companies.get(w.id, 0), "contacts": contacts.get(w.id, 0),
                   "deals": deals.get(w.id, 0)},
        "created_at": w.created_at.isoformat() if w.created_at else None,
        "archived_at": w.archived_at.isoformat() if w.archived_at else None,
        "last_activity_at": last_activity[w.id].isoformat() if last_activity.get(w.id) else None,
    } for w in ws]


@router.get("/workspaces")
def list_workspaces(archived: int = 0, ctx: AuthContext = Depends(require_master)):
    """The live workspaces, or — with `archived=1` — the archive.

    Two calls rather than one list the screen filters itself, because the admin
    page shows them as two different things: a table you work in, and a bin you
    restore from."""
    q = ctx.db.query(Workspace).filter(Workspace.org_id == ctx.org_id)
    q = q.filter(Workspace.archived_at.isnot(None)) if archived else q.filter(Workspace.archived_at.is_(None))
    return _workspace_payload(ctx, q.order_by(Workspace.name).all())


def _client_users_locked_to(ctx, workspace_id: int) -> list:
    """Client accounts whose ONLY destination is this workspace."""
    rows = (ctx.db.query(Membership, User)
            .join(User, User.id == Membership.user_id)
            .filter(Membership.org_id == ctx.org_id).all())
    return [u for m, u in rows
            if m.role == "client" and (m.workspace_ids or []) == [workspace_id]]


def _address_taken_detail(ctx, membership):
    """Why this address cannot be used here, in terms the operator can act on.

    "That email already belongs to another account" is true and useless. The
    account it belongs to is nearly always this same client's own login for a
    workspace that was deleted — and a deleted workspace is invisible, so the
    operator is told their address is taken by something they cannot see, and
    has no way to find out what.

    When the blocker IS an archived workspace, this returns the workspaces
    themselves rather than a sentence about them, so the UI can offer the same
    two doors the create screen offers — restore it, or delete it for good —
    instead of a dead-end message. Every other case has nothing to act on from
    here, and stays a plain string."""
    ids = (membership.workspace_ids or []) if membership is not None else []
    held = ((ctx.db.query(Workspace)
             .filter(Workspace.org_id == ctx.org_id, Workspace.id.in_(ids))
             .order_by(Workspace.name).all())
            if ids and membership.role == "client" else [])

    if not held:
        # Another org, an operator account, or a client attached to nothing —
        # nothing here for this operator to go and undo.
        return ("That email already belongs to another account. Use a different "
                "address for this workspace.")

    names = ", ".join(f"“{w.name}”" for w in held)
    if all(w.archived_at is not None for w in held):
        many = len(held) > 1
        return {
            "code": "address_in_archive",
            "message": (f"That email is the client login for {names}, "
                        f"{'which are' if many else 'which is'} in the archive."),
            "workspaces": _workspace_payload(ctx, held),
        }
    return (f"That email is already the client login for {names}. A client account "
            f"reaches one workspace, so use a different address here.")


def _live_holder_of_email(ctx, email: str, exclude_id: int | None = None):
    """The LIVE workspace already using this address, if any.

    An address reaches exactly one workspace — that is what a client login is —
    so two workspaces claiming the same one is not a state worth reaching. It
    counts as claimed whether an invite has gone out or not: the address typed
    at creation is a promise to send there, and letting a second workspace take
    the same promise means one of them silently loses it at invite time.

    LIVE only. An archived match is a different answer (restore it, or replace
    it) handled by the duplicate screen, and must not read as "taken"."""
    email = (email or "").lower().strip()
    if not email:
        return None
    live = (ctx.db.query(Workspace)
            .filter(Workspace.org_id == ctx.org_id, Workspace.archived_at.is_(None))
            .order_by(Workspace.name).all())
    for row in _workspace_payload(ctx, live):
        if row["id"] == exclude_id:
            continue
        known = {e.lower() for e in row["client_emails"]}
        known.add((row["pending_client_email"] or "").lower())
        if email in (known - {""}):
            return row
    return None


# ---------------------------------------------------------------- duplicates
class ConflictCheckIn(BaseModel):
    name: str
    email: str = ""


@router.post("/workspaces/check-conflicts")
def check_workspace_conflicts(body: ConflictCheckIn, ctx: AuthContext = Depends(require_master)):
    """Does an ARCHIVED workspace already hold this name, address or client
    email? Asked BEFORE a workspace is created, so the answer can be an offer
    to restore the client's own history rather than an error afterwards.

    Archived only. A live duplicate is a different conversation — the address
    check in create refuses it, and the workspace is right there in the table —
    whereas an archived match is nearly always the same client coming back, and
    the operator cannot see it to know that."""
    name = (body.name or "").strip()
    email = (body.email or "").lower().strip()
    slug = _slugify(name)

    archived = (ctx.db.query(Workspace)
                .filter(Workspace.org_id == ctx.org_id, Workspace.archived_at.isnot(None))
                .order_by(Workspace.name).all())

    out = []
    for row in _workspace_payload(ctx, archived):
        matched = []
        # The slug is the name's address, so a slug hit IS a name hit — it is
        # what makes "Acme Inc" and "acme  inc" the same answer.
        if name and ((row["name"] or "").strip().lower() == name.lower() or row["slug"] == slug):
            matched.append("name")
        # Every client login the workspace has, plus the address pencilled in at
        # creation — an archived workspace made for this person but never
        # invited is still this person's workspace.
        known = {e.lower() for e in row["client_emails"]}
        known.add((row["pending_client_email"] or "").lower())
        if email and email in (known - {""}):
            matched.append("email")
        if matched:
            out.append({**row, "matched": matched})
    # A LIVE workspace holding the address is not an offer, it is a refusal —
    # returned alongside so the create form can say so on the field itself
    # rather than opening a screen with nothing to choose.
    return {"conflicts": out,
            "email_in_use": _live_holder_of_email(ctx, email) is not None}


# ---------------------------------------------------------------- create
@router.post("/workspaces")
def create_workspace(body: WorkspaceIn, ctx: AuthContext = Depends(require_master)):
    """Create a workspace, first destroying any archived ones it replaces.

    `replace_ids` is the second half of the duplicate flow: the operator was
    shown the archived workspace holding this name or this client's email,
    chose "Create new" over "Restore", and confirmed that the old one goes for
    good. The purge runs BEFORE the address check because the archived
    workspace is usually the thing holding the address — and inside the same
    transaction, so "replace" either happens completely or not at all."""
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Name is required")
    slug = body.slug or _slugify(name)

    # Refused BEFORE the replace purge, so a rejected create destroys nothing.
    client_email = (body.client_email or "").lower().strip()
    if _live_holder_of_email(ctx, client_email) is not None:
        raise HTTPException(409, {"code": "email_in_use", "field": "client_email",
                                  "message": "Email already in use"})

    for wid in body.replace_ids:
        victim = _org_workspace(ctx, wid, allow_archived=True)
        if victim.archived_at is None:
            raise HTTPException(409, f"“{victim.name}” is not archived — only an "
                                     f"archived workspace can be replaced.")
        _purge_workspace(ctx, victim)

    clash = ctx.db.query(Workspace).filter(Workspace.org_id == ctx.org_id,
                                           Workspace.slug == slug).first()
    if clash is not None:
        if clash.archived_at is not None:
            raise HTTPException(409, f"An archived workspace (“{clash.name}”) already uses "
                                     f"the address “{slug}”. Restore it, or delete it "
                                     f"permanently first.")
        raise HTTPException(409, "Workspace slug already exists")

    # Bare domain from the website, e.g. "https://www.acme.com/x" -> "acme.com".
    from urllib.parse import urlsplit
    _raw = (body.website or "").strip()
    if _raw and "//" not in _raw:
        _raw = "https://" + _raw
    _host = (urlsplit(_raw).hostname or "").lower() if _raw else ""
    domain = _host[4:] if _host.startswith("www.") else _host

    w = Workspace(org_id=ctx.org_id, name=name, slug=slug, legacy_name=body.legacy_name,
                  domain=domain,
                  settings={"client_email": client_email} if client_email else {})
    ctx.db.add(w)
    ctx.db.flush()
    # The workspace is a PACKAGE: pipeline + enrichment config + reply space
    # are all provisioned together — no separate "create reply space" step.
    from ..provision import provision_workspace
    provision_workspace(ctx.db, w)
    ctx.db.add(AuditLog(org_id=ctx.org_id, workspace_id=w.id, user_id=ctx.user.id,
                        action="create_workspace", object_type="workspace", object_id=w.id,
                        data={"replaced": body.replace_ids} if body.replace_ids else {}))
    ctx.db.commit()
    return {"id": w.id, "name": w.name, "slug": w.slug,
            "pending_client_email": client_email}


class WorkspacePatch(BaseModel):
    name: str | None = None
    active: bool | None = None


@router.patch("/workspaces/{workspace_id}")
def update_workspace(workspace_id: int, body: WorkspacePatch, ctx: AuthContext = Depends(require_master)):
    """Rename a workspace and/or toggle its active flag. Deactivating keeps it
    in the table and reachable by operators; archiving is the one that takes it
    out of everywhere."""
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


# ---------------------------------------------------------------- archive
class WorkspaceArchiveIn(BaseModel):
    """Both confirmations, checked on the server.

    The typed name proves the operator means THIS workspace; the password
    proves it is still the operator at the keyboard. A UI-only check proves
    neither — it is a courtesy to the person clicking, not a control, and
    anything holding a session token could skip it entirely."""
    confirm_name: str = ""
    password: str = ""


# POST, not DELETE, because this call carries a body and a DELETE body is not
# dependably delivered — proxies, CDNs and several HTTP clients drop it. A
# password that silently goes missing in transit reads to the operator as
# "wrong password" and to us as a support ticket.
@router.post("/workspaces/{workspace_id}/archive")
def archive_workspace(workspace_id: int, body: WorkspaceArchiveIn,
                      ctx: AuthContext = Depends(require_master)):
    """Delete a workspace after re-confirming its name and the operator's
    password. It leaves every list, switcher and query — its client's included
    — and not one row is destroyed, so it can be brought back whole.

    What it does NOT do is refuse. The delete this replaces turned any
    workspace holding companies, contacts, deals or leads away, which made
    every workspace worth having impossible to remove and left "deactivate" as
    a permanent limbo. Keeping the data is what makes an unconditional delete
    safe; the guard against losing it moved to `purge`."""
    # allow_archived so a repeated submit is a no-op rather than an error.
    w = _org_workspace(ctx, workspace_id, allow_archived=True)

    # 1 — the name, exactly. Compared against the workspace found BY ID, so a
    # near-duplicate name two rows down can never be what gets deleted.
    if body.confirm_name.strip() != (w.name or "").strip():
        raise HTTPException(422, f"Type the workspace name exactly — “{w.name}” — to confirm.")

    # 2 — the operator's own password, verified against their stored hash.
    if not body.password or not verify_password(body.password, ctx.user.password_hash):
        # Recorded whether or not it succeeds: repeated failures here are worth
        # being able to see after the fact.
        ctx.db.add(AuditLog(org_id=ctx.org_id, workspace_id=workspace_id, user_id=ctx.user.id,
                            action="archive_workspace_denied", object_type="workspace",
                            object_id=workspace_id, data={"reason": "bad_password"}))
        ctx.db.commit()
        raise HTTPException(403, "That password is not correct.")

    if w.archived_at is not None:
        return {"id": w.id, "name": w.name, "archived_at": w.archived_at.isoformat(),
                "suspended_users": 0}

    # A client locked to this workspace would otherwise sign in to an app with
    # nothing in it. Their account is suspended alongside it, and the ids are
    # recorded so restoring gives back exactly what archiving took — an account
    # that was already deactivated stays deactivated.
    suspended = []
    for u in _client_users_locked_to(ctx, workspace_id):
        if u.active:
            u.active = False
            suspended.append(u.id)

    at = datetime.utcnow()
    w.archived_at = at
    w.settings = {**(w.settings or {}), "archive": {
        "at": at.isoformat(), "by_user_id": ctx.user.id,
        "was_active": bool(w.active), "suspended_user_ids": suspended,
    }}
    w.active = False
    ctx.db.add(AuditLog(org_id=ctx.org_id, workspace_id=w.id, user_id=ctx.user.id,
                        action="archive_workspace", object_type="workspace", object_id=w.id,
                        data={"name": w.name, "suspended_user_ids": suspended}))
    ctx.db.commit()
    return {"id": w.id, "name": w.name, "archived_at": at.isoformat(),
            "suspended_users": len(suspended)}


@router.post("/workspaces/{workspace_id}/restore")
def restore_workspace(workspace_id: int, ctx: AuthContext = Depends(require_master)):
    """Put an archived workspace back exactly as it was, client login included."""
    w = _org_workspace(ctx, workspace_id, allow_archived=True)
    if w.archived_at is None:
        raise HTTPException(409, f"“{w.name}” is not archived.")

    # Its address may have been taken while it was away, and two live
    # workspaces cannot share one.
    clash = (ctx.db.query(Workspace)
             .filter(Workspace.org_id == ctx.org_id, Workspace.slug == w.slug,
                     Workspace.id != w.id, Workspace.archived_at.is_(None)).first())
    if clash is not None:
        raise HTTPException(409, f"“{clash.name}” now uses the address "
                                 f"“{w.slug}”. Rename it before restoring this one.")

    meta = (w.settings or {}).get("archive") or {}
    restored_users = 0
    for uid in meta.get("suspended_user_ids") or []:
        u = ctx.db.query(User).filter(User.id == uid).first()
        if u is not None and not u.active:
            u.active = True
            restored_users += 1
    w.active = bool(meta.get("was_active", True))
    w.archived_at = None
    w.settings = {k: v for k, v in (w.settings or {}).items() if k != "archive"}
    ctx.db.add(AuditLog(org_id=ctx.org_id, workspace_id=w.id, user_id=ctx.user.id,
                        action="restore_workspace", object_type="workspace", object_id=w.id,
                        data={"name": w.name}))
    ctx.db.commit()
    return {"id": w.id, "name": w.name, "slug": w.slug, "active": w.active,
            "restored_users": restored_users}


def _erase_user(ctx, user_id: int) -> None:
    """Remove an account and every reference to it.

    Every nullable users.id foreign key in the schema is cleared first, driven
    by the metadata rather than a hand-kept list — a table added next year is
    covered the day it is added, and a dangling reference is a constraint
    violation on Postgres, not a cosmetic problem. Memberships are deleted
    instead of cleared: their user_id is NOT NULL, and a membership with no
    user is not a thing."""
    from ..db import Base

    ctx.db.query(Membership).filter(Membership.user_id == user_id).delete(synchronize_session=False)
    ctx.db.flush()
    for tbl in Base.metadata.sorted_tables:
        if tbl.name == "users":
            continue
        for col in tbl.columns:
            if col.nullable and any(fk.target_fullname == "users.id" for fk in col.foreign_keys):
                ctx.db.execute(tbl.update().where(col == user_id).values({col.name: None}))
    ctx.db.execute(User.__table__.delete().where(User.__table__.c.id == user_id))
    ctx.db.flush()


def _purge_workspace(ctx, w: Workspace) -> None:
    """Destroy a workspace and everything that belonged to it.

    No commit: the caller owns the transaction, so "replace this archived
    workspace with a new one" is a single step that either happens completely
    or not at all."""
    from ..db import Base

    workspace_id = w.id
    # Read before anything is deleted — it is derived from the memberships this
    # purge is about to rewrite.
    orphans = _client_users_locked_to(ctx, workspace_id)

    # The trace has to outlive its subject, so it is written with no
    # workspace_id — the cascade below removes every row that carries one,
    # which would otherwise include the record of this deletion.
    ctx.db.add(AuditLog(org_id=ctx.org_id, workspace_id=None, user_id=ctx.user.id,
                        action="purge_workspace", object_type="workspace",
                        object_id=workspace_id,
                        data={"name": w.name, "slug": w.slug,
                              "client_emails": [u.email for u in orphans]}))

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
    ctx.db.flush()

    # A client login whose only destination no longer exists is an orphan — and
    # leaving it behind also keeps its email address permanently unusable,
    # which is exactly the address about to be re-invited when an operator
    # replaces an archived workspace with a new one for the same client.
    for u in orphans:
        _erase_user(ctx, u.id)


@router.post("/workspaces/{workspace_id}/purge")
def purge_workspace(workspace_id: int, ctx: AuthContext = Depends(require_master)):
    """Permanent deletion — the workspace, everything in it, and the client
    login that existed only to reach it.

    Reachable only from the archive. That two-step path (delete → archive
    → delete permanently) is the whole reason the first step can be
    unconditional: nothing is destroyed until somebody comes back for it."""
    w = _org_workspace(ctx, workspace_id, allow_archived=True)
    if w.archived_at is None:
        raise HTTPException(409, f"Delete “{w.name}” first — only an archived "
                                 f"workspace can be deleted permanently.")
    name = w.name
    _purge_workspace(ctx, w)
    ctx.db.commit()
    return {"ok": True, "name": name}


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


def _org_workspace(ctx, workspace_id: int, *, allow_archived: bool = False) -> Workspace:
    """The workspace, if it belongs to this org and is not archived.

    Archived workspaces are invisible by default so that every ordinary admin
    action — rename, invite, alias — behaves as if they were gone. Only the
    three that exist to act ON the archive (restore, purge, and the replace
    step of create) pass `allow_archived`."""
    w = ctx.db.query(Workspace).filter(Workspace.id == workspace_id, Workspace.org_id == ctx.org_id).first()
    if not w:
        raise HTTPException(422, f"Workspace {workspace_id} not found in this organization")
    if w.archived_at is not None and not allow_archived:
        raise HTTPException(409, f"“{w.name}” is archived. Restore it first.")
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
    # Treat `password` as temporary: the account can do nothing but change it.
    # Defaults off so this endpoint keeps behaving exactly as it always has.
    must_change_password: bool = False


@router.get("/users")
def list_users(ctx: AuthContext = Depends(require_master)):
    """Every account in the org that is still somebody's to manage.

    A client locked to an archived workspace is left out. Their account was
    suspended by the delete and comes back with the restore, so there is
    nothing to do to it here — and listing it means listing a workspace id with
    no workspace behind it. The archive row carries that client's address
    instead, next to the workspace they belong to.

    Everyone else stays, with archived ids filtered out of what they can reach:
    an operator attached to four workspaces should not appear to have lost
    their account because one of them was deleted."""
    archived = {r[0] for r in
                ctx.db.query(Workspace.id)
                .filter(Workspace.org_id == ctx.org_id, Workspace.archived_at.isnot(None)).all()}
    rows = (
        ctx.db.query(User, Membership)
        .join(Membership, Membership.user_id == User.id)
        .filter(Membership.org_id == ctx.org_id)
        .all()
    )
    out = []
    for u, m in rows:
        ids = list(m.workspace_ids or [])
        live = [i for i in ids if i not in archived]
        if m.role == "client" and ids and not live:
            continue
        out.append({"id": u.id, "email": u.email, "name": u.name, "role": m.role,
                    "workspace_ids": live, "active": u.active})
    return out


@router.post("/users")
def create_user(body: UserIn, ctx: AuthContext = Depends(require_master)):
    if body.role not in ROLES:
        raise HTTPException(422, f"role must be one of {ROLES}")
    if body.role == "client" and len(body.workspace_ids) != 1:
        raise HTTPException(422, "A client user must be locked to exactly one workspace")
    if body.role == "member" and not body.workspace_ids:
        raise HTTPException(422, "A member needs at least one workspace")
    # Verify the workspaces belong to this org — never attach across orgs, and
    # never to an archived workspace: the account would sign in to nothing.
    for wid in body.workspace_ids:
        _org_workspace(ctx, wid)
    email = body.email.lower().strip()
    if ctx.db.query(User).filter(User.email == email).first():
        raise HTTPException(409, "Email already registered")
    u = User(email=email, name=body.name, password_hash=hash_password(body.password),
             must_change_password=bool(body.must_change_password))
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


# ---------------------------------------------------------------- client invites
class InviteClientIn(BaseModel):
    email: str
    name: str = ""


@router.post("/workspaces/{workspace_id}/invite-client")
def invite_client(workspace_id: int, body: InviteClientIn, request: Request,
                  ctx: AuthContext = Depends(require_master)):
    """Create (or re-issue) this workspace's client login and email the details.

    Called as a separate, explicit step after the workspace exists, so nothing
    leaves the building until an operator has confirmed the workspace they are
    about to hand over.

    The temporary password leaves this function **only when the mail could not
    be sent**. On the happy path it exists between here and the SMTP socket and
    nowhere else — not in the response, so not in a browser's network tab, not
    in a screenshot of one, and not in anything the operator can accidentally
    forward. When delivery fails there is no other channel and the operator has
    to be able to hand it over themselves, so it is returned and the UI says so.
    It is never stored in plaintext, and never written to a job payload or log.
    """
    workspace = _org_workspace(ctx, workspace_id)
    email = body.email.lower().strip()
    if not _EMAIL_RE.match(email):
        raise HTTPException(422, "Enter a valid email address")

    user = ctx.db.query(User).filter(User.email == email).first()
    # The membership in THIS org is the one that decides; a user can carry
    # several, and taking whichever came back first is a coin toss that reads
    # as "belongs to another account" for an account sitting right here.
    membership = None
    if user is not None:
        membership = (ctx.db.query(Membership)
                      .filter(Membership.user_id == user.id,
                              Membership.org_id == ctx.org_id).first())
    if user is not None:
        # Re-inviting the workspace's own client is a resend and rotates the
        # temporary password. Anyone else with that address is a different
        # person's account, and we do not quietly repoint it at this workspace.
        if (membership is None or membership.role != "client"
                or (membership.workspace_ids or []) != [workspace_id]):
            raise HTTPException(409, _address_taken_detail(ctx, membership))

    password = _temp_password()
    if user is None:
        user = User(email=email, name=body.name.strip(),
                    password_hash=hash_password(password), must_change_password=True)
        ctx.db.add(user)
        ctx.db.flush()
        ctx.db.add(Membership(user_id=user.id, org_id=ctx.org_id, role="client",
                              workspace_ids=[workspace_id]))
        action = "invite_client"
    else:
        user.password_hash = hash_password(password)
        user.must_change_password = True
        user.active = True
        if body.name.strip():
            user.name = body.name.strip()
        # Any outstanding reset link is a second door into an account whose
        # password we just rotated. Close it.
        user.reset_token_hash = ""
        user.reset_expires_at = None
        action = "reinvite_client"

    # Whatever address was pencilled in at creation, THIS is the one the
    # workspace was handed to. Replaced rather than left behind, so a re-invite
    # never reopens with a stale guess.
    workspace.settings = {**(workspace.settings or {}), "client_email": email}

    # Commit the account BEFORE attempting delivery. If the mail fails the
    # operator still has a working login to hand over; the reverse — a sent
    # password for an account that was never written — is unrecoverable.
    ctx.db.add(AuditLog(org_id=ctx.org_id, workspace_id=workspace_id, user_id=ctx.user.id,
                        action=action, object_type="user", object_id=user.id,
                        data={"email": email}))
    ctx.db.commit()

    # The workspace slug, not the id: `app.revcadence.com/w/acme-inc` is a link a
    # client can read, and it is the address their workspace actually has. It
    # also still says which workspace the link belongs to, which is what the old
    # `?ws=` was for — an operator opening an invite lands in THAT client's space
    # rather than whichever one happened to be first in their list. Invites
    # already sent keep working: the client shell still honours `?ws=` and
    # rewrites it to the slug form.
    link = config.client_workspace_url(workspace.slug, fallback=str(request.base_url))
    from ..email_templates import LOGO_CID, client_invite_html, client_invite_text
    from ..mailer import LOGO_PATH, send_system_mail
    fields = {"app_name": config.APP_NAME, "workspace_name": workspace.name, "link": link,
              "email": email, "password": password, "name": user.name or ""}
    sent, detail = send_system_mail(
        ctx.db, to_email=email, to_name=user.name or "",
        subject=f"Your {workspace.name} workspace is ready",
        body=client_invite_text(**fields),
        html=client_invite_html(**fields),
        inline_images={LOGO_CID: LOGO_PATH},
        workspace_id=workspace_id, org_workspace_ids=ctx.allowed_workspace_ids(),
    )
    return {
        "user_id": user.id, "email": email, "name": user.name or "",
        "workspace": {"id": workspace.id, "name": workspace.name},
        "login_url": link,
        # ONLY when the mail did not go out — see the docstring. When it did, the
        # client's inbox is the single place this password exists.
        **({} if sent else {"temp_password": password}),
        "emailed": sent, "delivery": detail,
        "reissued": action == "reinvite_client",
    }


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
