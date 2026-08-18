"""Shared Documents API — the client workspace's page system.

Security shape, in one place so it cannot drift:

- `_pages(ctx, workspace_id)` is the ONLY way a page query starts. It applies
  the workspace filter through `scoped()` and, for client users, an additional
  `visibility == 'shared'` filter. Every read and every write goes through it,
  so an internal page is invisible in the data layer rather than hidden by the
  UI, and a client asking for one gets 404 (never 403 — a 403 would confirm the
  id exists in a workspace they can see).
- Blocks carry no `workspace_id`; `_block(...)` resolves them through their page
  so a block write inherits the exact same check.
- Templates are org-scoped, not workspace-scoped, so they filter on `ctx.org_id`
  directly — `scoped()` does not apply.

Every mutation writes an `AuditLog` row before the commit.
"""
import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func

from ..auth import AuthContext, get_ctx, scoped
from ..models.audit import AuditLog
from ..models.workspace_docs import (BLOCK_TYPES, PAGE_KINDS, SANITIZE_KEEP_WHOLE, SECTIONS,
                                     Block, BoardAsset, BoardPresence, Comment, Page,
                                     PageTemplate, PageVersion, WhiteboardPromotion)
from ..models.identity import User

router = APIRouter(prefix="/api/workspace", tags=["workspace-docs"])


# ---------------------------------------------------------------- access helpers
def _is_client(ctx: AuthContext) -> bool:
    """Client users only ever see shared pages.

    `ctx.sees_as_client` is `role == "client"` and not `not ctx.is_master`: a
    `member` is an internal operator scoped to a subset of workspaces, and must
    keep seeing internal pages. It is also true while an operator has "Preview
    as client" on, so the preview hides internal pages in the data layer — the
    same filter, not a second one the UI could get wrong.
    """
    return ctx.sees_as_client


def _pages(ctx: AuthContext, workspace_id: int | None = None):
    """The only sanctioned starting point for a page query."""
    q = scoped(ctx.db.query(Page), Page, ctx, workspace_id)
    if _is_client(ctx):
        q = q.filter(Page.visibility == "shared")
    return q


def _page(ctx: AuthContext, page_id: int, *, include_archived: bool = False) -> Page:
    q = _pages(ctx).filter(Page.id == page_id)
    if not include_archived:
        q = q.filter(Page.archived_at.is_(None))
    page = q.first()
    if page is None:
        raise HTTPException(404, "Page not found")
    return page


def _block(ctx: AuthContext, block_id: int) -> tuple[Block, Page]:
    """Resolve a block through its page so block writes inherit page access."""
    block = ctx.db.get(Block, block_id)
    if block is None:
        raise HTTPException(404, "Block not found")
    return block, _page(ctx, block.page_id)


def _audit(ctx: AuthContext, workspace_id: int, action: str, object_type: str,
           object_id: int, data: dict | None = None) -> None:
    ctx.db.add(AuditLog(org_id=ctx.org_id, workspace_id=workspace_id, user_id=ctx.user.id,
                        action=action, object_type=object_type, object_id=object_id,
                        data=data or {}))


def _target_workspace(ctx: AuthContext, workspace_id: int | None) -> int:
    """The workspace a new object belongs to. A client has exactly one; a master
    must say which, unless the org has only one visible."""
    allowed = ctx.workspace_ids_for_query(workspace_id)
    if len(allowed) != 1:
        raise HTTPException(422, "workspace_id is required")
    return allowed[0]


def _next_position(ctx: AuthContext, workspace_id: int, section: str, parent_id: int | None) -> int:
    current = (ctx.db.query(func.max(Page.position))
               .filter(Page.workspace_id == workspace_id, Page.section == section,
                       Page.parent_id == parent_id).scalar())
    return (current or 0) + 1


def _stamp(value) -> str:
    """One aggregate value as a comparable string.

    `func.max()` over a DateTime hands back a datetime on Postgres and, depending
    on the driver, a plain string on SQLite. A poll only ever compares stamps for
    equality, so both are normalised to text here rather than parsed.
    """
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value) if value else ""


# ---------------------------------------------------------------- serializers
def _block_out(b: Block) -> dict:
    return {"id": b.id, "page_id": b.page_id, "position": b.position, "type": b.type,
            "content": b.content or {}, "entity_type": b.entity_type,
            "entity_id": b.entity_id, "field_path": b.field_path,
            "revision": b.revision or 1,
            "updated_at": b.updated_at.isoformat() if b.updated_at else None}


def _page_out(p: Page, *, version_no: int = 0, editor: str = "") -> dict:
    return {"id": p.id, "workspace_id": p.workspace_id, "parent_id": p.parent_id,
            "kind": p.kind or "page",
            "title": p.title or "", "icon": p.icon or "", "section": p.section,
            "visibility": p.visibility, "status": p.status, "owner_role": p.owner_role,
            "position": p.position or 0, "version_no": version_no, "edited_by": editor,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
            "archived_at": p.archived_at.isoformat() if p.archived_at else None}


def _comment_out(c: Comment, names: dict) -> dict:
    return {"id": c.id, "page_id": c.page_id, "block_id": c.block_id, "parent_id": c.parent_id,
            "author_user_id": c.author_user_id, "author": names.get(c.author_user_id, "Someone"),
            "body": c.body or "", "mentions": c.mentions or [],
            "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
            "resolved_by": c.resolved_by,
            "created_at": c.created_at.isoformat() if c.created_at else None}


def _template_out(t: PageTemplate) -> dict:
    return {"id": t.id, "name": t.name, "description": t.description or "",
            "section": t.section, "icon": t.icon or "",
            "default_visibility": t.default_visibility, "version": t.version or 1,
            "block_count": len(t.blocks or []),
            "created_at": t.created_at.isoformat() if t.created_at else None}


def _names(ctx: AuthContext, user_ids: set) -> dict:
    ids = {i for i in user_ids if i}
    if not ids:
        return {}
    rows = ctx.db.query(User.id, User.name, User.email).filter(User.id.in_(ids)).all()
    return {r[0]: (r[1] or r[2] or "").strip() for r in rows}


# ---------------------------------------------------------------- pages
class PageIn(BaseModel):
    workspace_id: int | None = None
    template_id: int | None = None
    parent_id: int | None = None
    section: str = "strategy"
    title: str = "Untitled"
    icon: str = ""
    kind: str = "page"


class PagePatch(BaseModel):
    title: str | None = None
    icon: str | None = None
    section: str | None = None
    position: int | None = None
    parent_id: int | None = None


def _folder(ctx: AuthContext, parent_id: int) -> Page:
    """A page nests inside a folder, not inside another document. Enforced here
    so the tree can never contain a document that secretly holds children."""
    parent = _page(ctx, parent_id)
    if (parent.kind or "page") != "folder":
        raise HTTPException(422, "Pages can only be nested inside a folder")
    return parent


class DuplicateIn(BaseModel):
    sanitize: bool = False


@router.get("/pages/tree")
def page_tree(workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    """Flat, ordered list — the sidebar groups it by section and nests by
    parent_id. One query beats N recursive ones for a tree this size.

    The workspace whiteboard is excluded: it has its own nav entry, and a page
    the tree cannot nest or reorder does not belong in the tree. `coalesce` because
    `kind` predates this value and is null on the oldest rows, which SQL would
    otherwise drop from a `!=` comparison.
    """
    rows = (_pages(ctx, workspace_id)
            .filter(Page.archived_at.is_(None),
                    func.coalesce(Page.kind, "page") != "whiteboard")
            .order_by(Page.section, Page.position, Page.id).all())
    return {"pages": [_page_out(p) for p in rows],
            "sections": list(SECTIONS),
            "can_share": not _is_client(ctx)}


@router.get("/pulse")
def pulse(workspace_id: int | None = None, page_id: int | None = None,
          ctx: AuthContext = Depends(get_ctx)):
    """A cheap change-stamp, polled by both shells so the operator's copy of a
    document and the client's copy converge without either side reloading.

    Two stamps, because the two halves of the screen move for different reasons.
    `tree` covers the sidebar: a page created, renamed, reordered, archived, or
    shared — sharing is the event that makes a page exist for a client at all.
    `page` covers the document that is open. A caller compares each against the
    last one it saw and refetches only the half that moved; the strings are
    opaque and are never parsed.

    Both go through `_pages()`, so a client's stamp is computed over the pages a
    client can see. That is load-bearing: a stamp built over every page would
    tell a client that *something* changed each time we edited an internal one.

    Whiteboard blocks are left out of the page stamp deliberately. They carry
    their own revision protocol and their own refresh (see WhiteboardBlock), and
    a page-wide refetch driven by someone else's brush stroke would re-import the
    canvas under their pen.
    """
    # Digested from the columns the sidebar actually draws, rather than from
    # `max(updated_at)`: writing a block bumps its page's `updated_at`, so a
    # timestamp would make every keystroke's autosave order a full tree refetch
    # on both sides. This moves when — and only when — the sidebar would look
    # different. It reads the same handful of small rows the tree endpoint reads,
    # which is the cheap half of that request; the payload is what it saves.
    rows = (_pages(ctx, workspace_id)
            .filter(Page.archived_at.is_(None),
                    func.coalesce(Page.kind, "page") != "whiteboard")
            .with_entities(Page.id, Page.parent_id, Page.section, Page.position,
                           Page.kind, Page.title, Page.icon, Page.visibility)
            .order_by(Page.section, Page.position, Page.id).all())
    digest = hashlib.sha256(repr([tuple(r) for r in rows]).encode()).hexdigest()
    out = {"tree": digest[:16], "page": None}

    if page_id:
        # Not `_page()`: on a poll, a page that has been archived or moved out of
        # reach is not an error. It is a null the caller answers by reloading,
        # which is also what shows the reader that it is gone.
        page = _pages(ctx).filter(Page.id == page_id,
                                  Page.archived_at.is_(None)).first()
        if page is not None:
            blocks = (ctx.db.query(func.count(Block.id), func.max(Block.updated_at),
                                   func.sum(Block.revision))
                      .filter(Block.page_id == page.id,
                              func.coalesce(Block.type, "text") != "whiteboard").one())
            # `count()` over a nullable column counts the non-nulls, so the third
            # figure moves when a thread is resolved or reopened.
            comments = (ctx.db.query(func.count(Comment.id), func.max(Comment.created_at),
                                     func.count(Comment.resolved_at))
                        .filter(Comment.page_id == page.id).one())
            out["page"] = ".".join(str(part) for part in (
                _stamp(page.updated_at), page.visibility, page.status,
                blocks[0], _stamp(blocks[1]), blocks[2] or 0,
                comments[0], _stamp(comments[1]), comments[2]))
    return out


@router.post("/pages")
def create_page(body: PageIn, ctx: AuthContext = Depends(get_ctx)):
    """Blank, from a template, or (via /duplicate) from another page.

    A client-created page is born shared and owned by the client — a client
    cannot create an internal page, so there is no path to a hidden client page.
    """
    if body.section not in SECTIONS:
        raise HTTPException(422, f"section must be one of {SECTIONS}")
    if body.kind not in PAGE_KINDS:
        raise HTTPException(422, f"kind must be one of {PAGE_KINDS}")
    if body.kind == "whiteboard":
        # The workspace's one canvas is created by opening it, never from here —
        # otherwise this endpoint is a way to end up with two of them.
        raise HTTPException(422, "The workspace whiteboard is opened, not created")
    workspace_id = _target_workspace(ctx, body.workspace_id)
    client = _is_client(ctx)
    if client and body.section == "internal":
        raise HTTPException(403, "Clients cannot create internal pages")

    template = None
    if body.template_id:
        if body.kind == "folder":
            raise HTTPException(422, "A folder holds pages; it has no blocks to fill from a template")
        template = (ctx.db.query(PageTemplate)
                    .filter(PageTemplate.id == body.template_id,
                            PageTemplate.org_id == ctx.org_id).first())
        if template is None:
            raise HTTPException(404, "Template not found")

    # A document always lives in a folder; only folders sit at the root of a
    # section. Enforced here rather than in the UI, so the tree cannot be given a
    # shape the sidebar has no way to draw.
    if body.kind == "page" and body.parent_id is None:
        raise HTTPException(422, "A page must be created inside a folder")
    if body.parent_id is not None:
        if body.kind == "folder":
            raise HTTPException(422, "Folders sit at the root of a section")
        # 404s if out of reach, 422 if it is a document rather than a folder.
        _folder(ctx, body.parent_id)

    section = template.section if template else body.section
    page = Page(
        workspace_id=workspace_id,
        parent_id=body.parent_id,
        kind=body.kind,
        title=(body.title or "Untitled").strip()[:512],
        icon=(body.icon or (template.icon if template else "")).strip()[:40],
        section=section,
        visibility="shared" if client else (template.default_visibility if template else "internal"),
        status="draft",
        owner_role="client" if client else "us",
        position=_next_position(ctx, workspace_id, section, body.parent_id),
        created_by=ctx.user.id,
    )
    ctx.db.add(page)
    ctx.db.flush()

    if body.kind == "folder":
        pass                       # a folder holds pages; it has no blocks
    elif template:
        for i, spec in enumerate(template.blocks or [], start=1):
            btype = spec.get("type")
            if btype not in BLOCK_TYPES:
                continue
            ctx.db.add(Block(page_id=page.id, position=i, type=btype,
                             content=spec.get("content") or {},
                             entity_type=spec.get("entity_type"),
                             field_path=spec.get("field_path")))
    else:
        # A blank page still gets one block so the editor has somewhere to land.
        ctx.db.add(Block(page_id=page.id, position=1, type="text", content={"html": ""}))

    _audit(ctx, workspace_id, "create_page", "page", page.id,
           {"section": section, "kind": body.kind, "template_id": body.template_id})
    ctx.db.commit()
    return _page_out(page)


@router.get("/pages/{page_id}")
def get_page(page_id: int, ctx: AuthContext = Depends(get_ctx)):
    page = _page(ctx, page_id)
    blocks = (ctx.db.query(Block).filter(Block.page_id == page.id)
              .order_by(Block.position, Block.id).all())
    latest = (ctx.db.query(PageVersion)
              .filter(PageVersion.page_id == page.id)
              .order_by(PageVersion.version_no.desc()).first())
    open_comments = (ctx.db.query(func.count(Comment.id))
                     .filter(Comment.page_id == page.id, Comment.resolved_at.is_(None))
                     .scalar()) or 0
    editor = _names(ctx, {page.created_by}).get(page.created_by, "")
    return {"page": _page_out(page, version_no=(latest.version_no if latest else 0), editor=editor),
            "blocks": [_block_out(b) for b in blocks],
            "open_comments": open_comments,
            "can_share": not _is_client(ctx)}


@router.patch("/pages/{page_id}")
def update_page(page_id: int, body: PagePatch, ctx: AuthContext = Depends(get_ctx)):
    page = _page(ctx, page_id)
    if body.section is not None:
        if body.section not in SECTIONS:
            raise HTTPException(422, f"section must be one of {SECTIONS}")
        if _is_client(ctx) and body.section == "internal":
            raise HTTPException(403, "Clients cannot move a page into the internal section")
        page.section = body.section
    if body.title is not None:
        page.title = body.title.strip()[:512]
    if body.icon is not None:
        page.icon = body.icon.strip()[:40]
    if body.position is not None:
        page.position = int(body.position)
    if body.parent_id is not None:
        if body.parent_id == page.id:
            raise HTTPException(422, "A page cannot be its own parent")
        _folder(ctx, body.parent_id)
        page.parent_id = body.parent_id
    _audit(ctx, page.workspace_id, "update_page", "page", page.id,
           {"title": page.title, "section": page.section})
    ctx.db.commit()
    return _page_out(page)


@router.post("/pages/{page_id}/share")
def share_page(page_id: int, ctx: AuthContext = Depends(get_ctx)):
    """The only path from internal to shared. Clients cannot call it — they have
    nothing to share, since every page they can see is already shared."""
    if _is_client(ctx):
        raise HTTPException(403, "Only the RevCadence team can share a page")
    page = _page(ctx, page_id)
    if page.section == "internal":
        raise HTTPException(422, "Move the page out of the internal section before sharing it")
    page.visibility = "shared"
    page.status = "in_review"
    _audit(ctx, page.workspace_id, "share_page", "page", page.id, {"status": page.status})
    ctx.db.commit()
    return _page_out(page)


@router.post("/pages/{page_id}/archive")
def archive_page(page_id: int, ctx: AuthContext = Depends(get_ctx)):
    """Soft delete — the blocks, comments and versions stay. Nothing in this
    module hard-deletes a page.

    Archiving a folder archives what it holds, otherwise its pages would be left
    pointing at a parent that is no longer in the tree.
    """
    page = _page(ctx, page_id)
    now = datetime.utcnow()
    page.archived_at = now
    children = 0
    if (page.kind or "page") == "folder":
        children = (_pages(ctx).filter(Page.parent_id == page.id, Page.archived_at.is_(None))
                    .update({Page.archived_at: now}, synchronize_session=False))
    _audit(ctx, page.workspace_id, "archive_page", "page", page.id, {"children": children})
    ctx.db.commit()
    return {"ok": True, "id": page.id, "archived_children": children}


def _sanitize_content(btype: str, content: dict) -> dict:
    """Keep the shape, drop what was written about a specific client."""
    if btype in SANITIZE_KEEP_WHOLE:
        return content or {}
    if btype == "table":
        return {"columns": (content or {}).get("columns") or [], "rows": []}
    if btype == "text":
        return {"html": ""}
    if btype == "list":
        return {"ordered": bool((content or {}).get("ordered")), "items": []}
    if btype == "checklist":
        return {"items": []}
    if btype == "whiteboard":
        return _empty_board()
    return content or {}


@router.post("/pages/{page_id}/duplicate")
def duplicate_page(page_id: int, body: DuplicateIn, ctx: AuthContext = Depends(get_ctx)):
    source = _page(ctx, page_id)
    client = _is_client(ctx)
    copy = Page(
        workspace_id=source.workspace_id,
        parent_id=source.parent_id,
        kind=source.kind or "page",
        title=f"{source.title or 'Untitled'} (copy)"[:512],
        icon=source.icon,
        section=source.section,
        visibility="shared" if client else "internal",
        status="draft",
        owner_role="client" if client else "us",
        position=_next_position(ctx, source.workspace_id, source.section, source.parent_id),
        created_by=ctx.user.id,
    )
    ctx.db.add(copy)
    ctx.db.flush()

    blocks = (ctx.db.query(Block).filter(Block.page_id == source.id)
              .order_by(Block.position, Block.id).all())
    for i, b in enumerate(blocks, start=1):
        ctx.db.add(Block(
            page_id=copy.id, position=i, type=b.type,
            content=_sanitize_content(b.type, b.content) if body.sanitize else (b.content or {}),
            entity_type=b.entity_type,
            # A sanitized copy keeps the binding shape but not the record it pointed at.
            entity_id=None if body.sanitize else b.entity_id,
            field_path=b.field_path,
        ))
    _audit(ctx, copy.workspace_id, "duplicate_page", "page", copy.id,
           {"source_page_id": source.id, "sanitize": body.sanitize})
    ctx.db.commit()
    return _page_out(copy)


# ---------------------------------------------------------------- blocks
class BlockIn(BaseModel):
    type: str
    position: int | None = None
    content: dict = Field(default_factory=dict)


class BlockPatch(BaseModel):
    content: dict | None = None
    position: int | None = None
    base_revision: int | None = None
    force: bool = False


class ReorderIn(BaseModel):
    ordered_ids: list[int]


# The board is a tldraw document, stored as tldraw's own store snapshot:
#
#     {"kind": "tldraw", "snapshot": {"store": {<id>: <record>}, "schema": {...}}}
#
# Deliberately tldraw's format rather than a shape schema of our own. A canvas is
# not a small problem — bound arrows that follow the shapes they connect, groups,
# frames, undo, multiplayer-shaped records, and a migration system for all of it.
# Re-deriving a private format from it would mean reimplementing that migration
# system, and would put us one tldraw release behind forever.
#
# What we store is the *document* snapshot, never the editor snapshot: session
# state holds the camera and the selection, which are per-person. Persisting them
# would mean one person scrolling moved everyone else's view.
#
# The consequence is that this file cannot validate a board field by field the
# way it validated the old one — the record schema belongs to tldraw. So the
# trust boundary moves to what actually carries risk: size, and where an image
# is allowed to point. Everything else is opaque JSON that only tldraw reads.
_BOARD_MAX_RECORDS = 20_000
_BOARD_MAX_BYTES = 6 * 1024 * 1024

# The note types that can graduate into workspace knowledge. On a tldraw board
# this lives in a shape's `meta`, which is the field tldraw reserves for exactly
# this: application data that rides along with a shape and survives its edits.
_BOARD_NOTE_TYPES = {"segment", "trigger", "proof", "reject", "angle", "question"}

# tldraw ids look like `shape:aBc123`, so the old identifier pattern would reject
# every one of them.
_BOARD_ID = re.compile(r"^[A-Za-z0-9_:-]{1,120}$")

# Where a board image may point. Anything else — a `data:` URL that would inline
# megabytes into this row, or an external host that would leak a client's board
# contents through a referer and break when it 404s — is refused, and the editor
# is wired to upload through our own endpoint instead.
_BOARD_ASSET_SRC = re.compile(r"^/api/workspace/whiteboard/assets/\d+$")


def _empty_board() -> dict:
    """A board nobody has drawn on. `None` rather than an empty snapshot: tldraw
    builds its own initial document, and inventing one here would hard-code a
    schema version that goes stale on the next upgrade."""
    return {"kind": "tldraw", "snapshot": None}


def _validate_whiteboard(ctx: AuthContext, block: Block, raw: dict) -> dict:
    """Check the board document at the trust boundary.

    Not a field-by-field validation and not pretending to be one — see the note
    above. This bounds what a board may cost us and refuses an image that points
    anywhere but our own asset store.
    """
    if not isinstance(raw, dict):
        raise HTTPException(422, "Whiteboard content must be an object")
    if raw.get("kind") != "tldraw":
        raise HTTPException(422, "Unknown whiteboard format")
    snapshot = raw.get("snapshot")
    if snapshot is None:
        return _empty_board()
    if not isinstance(snapshot, dict):
        raise HTTPException(422, "Whiteboard snapshot must be an object")
    store = snapshot.get("store")
    schema = snapshot.get("schema")
    if not isinstance(store, dict) or not isinstance(schema, dict):
        raise HTTPException(422, "Whiteboard snapshot must carry a store and a schema")
    if len(store) > _BOARD_MAX_RECORDS:
        raise HTTPException(422, "This board has grown too large to save")
    encoded = json.dumps(snapshot, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > _BOARD_MAX_BYTES:
        raise HTTPException(413, "This board has grown too large to save")

    page = _page(ctx, block.page_id)
    assets = {asset.id for asset in ctx.db.query(BoardAsset.id)
              .filter(BoardAsset.workspace_id == page.workspace_id).all()}
    for record in store.values():
        if not isinstance(record, dict):
            raise HTTPException(422, "Every whiteboard record must be an object")
        if record.get("typeName") != "asset":
            continue
        source = ((record.get("props") or {}) if isinstance(record.get("props"), dict) else {}).get("src")
        if source in (None, ""):
            continue
        if not isinstance(source, str) or not _BOARD_ASSET_SRC.match(source):
            raise HTTPException(422, "A board image must be uploaded to this workspace")
        if int(source.rsplit("/", 1)[1]) not in assets:
            raise HTTPException(422, "That board image is not in this workspace")
    return {"kind": "tldraw", "snapshot": {"store": store, "schema": schema}}


# ---------------------------------------------------------------- reading a board
# The board is tldraw's document, but two features have to read meaning out of
# it: promoting a note into workspace knowledge, and generating a page from what
# the team decided. Both go through the helpers below so there is exactly one
# place that knows how a tldraw record is shaped.
def _board_store(content) -> dict:
    if not isinstance(content, dict):
        return {}
    snapshot = content.get("snapshot")
    store = snapshot.get("store") if isinstance(snapshot, dict) else None
    return store if isinstance(store, dict) else {}


def _rich_text(value) -> str:
    """Flatten tldraw's rich text into a plain string.

    Text is a ProseMirror document, so the text lives in `text` leaves at an
    arbitrary depth. Walking for those leaves is version-proof in the way that
    reaching into `content[0].content[0]` is not.
    """
    out: list[str] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("text"), str):
                out.append(node["text"])
            children = node.get("content")
            if isinstance(children, list):
                for child in children:
                    walk(child)
            if node.get("type") in ("paragraph", "heading") and out and out[-1] != "\n":
                out.append("\n")
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return "".join(out).strip()


def _shape_text(record: dict) -> str:
    props = record.get("props") if isinstance(record.get("props"), dict) else {}
    if isinstance(props.get("richText"), (dict, list)):
        return _rich_text(props["richText"])
    return str(props.get("text") or "").strip()


def _board_shapes(store: dict) -> dict:
    return {key: record for key, record in store.items()
            if isinstance(record, dict) and record.get("typeName") == "shape"}


def _board_note(record: dict) -> str | None:
    """The note type an operator tagged this shape with, if any."""
    meta = record.get("meta") if isinstance(record.get("meta"), dict) else {}
    note_type = str(meta.get("note_type") or "").lower()
    return note_type if note_type in _BOARD_NOTE_TYPES else None


def _board_links(store: dict) -> list[tuple[str, str]]:
    """Which shape an arrow leaves and which it lands on.

    tldraw keeps this in binding records rather than on the arrow: one row per
    end, `fromId` the arrow and `toId` the shape it is stuck to. An arrow bound
    at only one end connects nothing and is skipped.
    """
    ends: dict[str, dict[str, str]] = {}
    for record in store.values():
        if not isinstance(record, dict) or record.get("typeName") != "binding":
            continue
        if record.get("type") != "arrow":
            continue
        props = record.get("props") if isinstance(record.get("props"), dict) else {}
        arrow, target = record.get("fromId"), record.get("toId")
        terminal = props.get("terminal")
        if not isinstance(arrow, str) or not isinstance(target, str):
            continue
        if terminal in ("start", "end"):
            ends.setdefault(arrow, {})[terminal] = target
    return [(pair["start"], pair["end"]) for pair in ends.values()
            if "start" in pair and "end" in pair and pair["start"] != pair["end"]]


@router.post("/pages/{page_id}/blocks")
def create_block(page_id: int, body: BlockIn, ctx: AuthContext = Depends(get_ctx)):
    if body.type not in BLOCK_TYPES:
        raise HTTPException(422, f"type must be one of {BLOCK_TYPES}")
    page = _page(ctx, page_id)
    position = body.position
    if position is None:
        last = (ctx.db.query(func.max(Block.position)).filter(Block.page_id == page.id).scalar())
        position = (last or 0) + 1
    else:
        # Inserting mid-document: push everything at or after this slot down one.
        (ctx.db.query(Block)
         .filter(Block.page_id == page.id, Block.position >= position)
         .update({Block.position: Block.position + 1}, synchronize_session=False))
    content = body.content or {}
    block = Block(page_id=page.id, position=position, type=body.type, content={})
    ctx.db.add(block)
    ctx.db.flush()
    block.content = (_validate_whiteboard(ctx, block, content)
                     if body.type == "whiteboard" else content)
    page.updated_at = datetime.utcnow()
    _audit(ctx, page.workspace_id, "create_block", "block", page.id, {"type": body.type})
    ctx.db.commit()
    return _block_out(block)


@router.patch("/blocks/{block_id}")
def update_block(block_id: int, body: BlockPatch, ctx: AuthContext = Depends(get_ctx)):
    """Ordinary blocks retain last-write-wins; whiteboards send a revision and
    fail with 409 rather than silently erasing another viewer's changes."""
    block, page = _block(ctx, block_id)
    if body.content is not None:
        if (body.base_revision is not None and body.base_revision != (block.revision or 1)
                and not body.force):
            raise HTTPException(409, {"message": "This board changed in another session.",
                                      "current": _block_out(block)})
        block.content = (_validate_whiteboard(ctx, block, body.content)
                         if block.type == "whiteboard" else body.content)
        block.revision = (block.revision or 1) + 1
    if body.position is not None:
        block.position = int(body.position)
    page.updated_at = datetime.utcnow()
    _audit(ctx, page.workspace_id, "update_block", "block", block.id,
           {"page_id": page.id, "revision": block.revision, "forced": bool(body.force)})
    ctx.db.commit()
    return _block_out(block)


# ---------------------------------------------------------------- whiteboards
def _whiteboard(ctx: AuthContext, block_id: int) -> tuple[Block, Page]:
    block, page = _block(ctx, block_id)
    if block.type != "whiteboard":
        raise HTTPException(422, "This block is not a whiteboard")
    return block, page


# A workspace has exactly one board. Not a collection of one — a collection is
# what this deliberately is not. There is no index, no title, and no create
# action, because a second board would immediately raise the question the single
# canvas answers by construction: which one is the client's?
#
# It is still a Page holding one Block, so comments, version history, sharing and
# the audit trail keep working on it exactly as they do on a document. What marks
# it is `kind == "whiteboard"`, which also keeps it out of the page tree: the
# board is reached from its own nav entry, not by finding it among documents.
BOARD_PAGE_TITLE = "Whiteboard"

# Pages generated *from* the board are ordinary documents and do go in the tree,
# so they need a folder to live in. Found by title rather than a flag column — it
# is a normal folder the team can rename, move, or fill.
BOARD_FOLDER_TITLE = "Whiteboards"


def _board_folder(ctx: AuthContext, workspace_id: int) -> Page:
    """Where documents generated from the board land.

    Shared, matching the board itself: a page generated from a canvas both sides
    draw on has no reason to be hidden from one of them.
    """
    section = "strategy"
    folder = (_pages(ctx, workspace_id)
              .filter(Page.archived_at.is_(None), Page.kind == "folder",
                      Page.section == section, Page.title == BOARD_FOLDER_TITLE)
              .order_by(Page.id).first())
    if folder is None:
        folder = Page(workspace_id=workspace_id, kind="folder", title=BOARD_FOLDER_TITLE,
                      icon="Layers", section=section, visibility="shared",
                      status="draft", owner_role="client" if _is_client(ctx) else "us",
                      position=_next_position(ctx, workspace_id, section, None),
                      created_by=ctx.user.id)
        ctx.db.add(folder)
        ctx.db.flush()
        _audit(ctx, workspace_id, "create_page", "page", folder.id,
               {"section": section, "kind": "folder", "for": "whiteboards"})
    return folder


def _workspace_board(ctx: AuthContext, workspace_id: int | None = None) -> tuple[Block, Page]:
    """The workspace's canvas, brought into being by the first visit to it.

    Born `shared`, always — this is the point of the whole design. An internal
    board would be invisible to the client, who would then silently get a second
    canvas of their own, and "one whiteboard per workspace" would be true only
    from one side of it. Ownership follows the same reasoning: the board belongs
    to the workspace, not to whoever happened to open it first.

    Two people opening the section for the first time in the same moment can each
    insert a page. Rather than take a lock for a row written once in a
    workspace's lifetime, the lowest id wins on every later read and the losers
    are archived here — so the race heals itself on the next request.
    """
    target = _target_workspace(ctx, workspace_id)
    pages = (_pages(ctx, target)
             .filter(Page.archived_at.is_(None), Page.kind == "whiteboard")
             .order_by(Page.id).all())
    page = pages[0] if pages else None
    if len(pages) > 1:
        now = datetime.utcnow()
        for duplicate in pages[1:]:
            duplicate.archived_at = now
        _audit(ctx, target, "archive_duplicate_whiteboard", "page", page.id,
               {"archived": [duplicate.id for duplicate in pages[1:]]})
        ctx.db.commit()
    if page is None:
        page = Page(workspace_id=target, kind="whiteboard", title=BOARD_PAGE_TITLE,
                    icon="Columns2", section="strategy", visibility="shared",
                    status="draft", owner_role="us",
                    position=_next_position(ctx, target, "strategy", None),
                    created_by=ctx.user.id)
        ctx.db.add(page)
        ctx.db.flush()
        _audit(ctx, target, "create_workspace_whiteboard", "page", page.id, {})
        ctx.db.commit()

    block = (ctx.db.query(Block)
             .filter(Block.page_id == page.id, Block.type == "whiteboard")
             .order_by(Block.position, Block.id).first())
    if block is None:
        block = Block(page_id=page.id, position=1, type="whiteboard", content=_empty_board())
        ctx.db.add(block)
        ctx.db.commit()
    return block, page


@router.get("/whiteboard")
def get_workspace_whiteboard(workspace_id: int | None = None,
                             ctx: AuthContext = Depends(get_ctx)):
    """Open the workspace's canvas. There is only one, so there is nothing to pick."""
    block, page = _workspace_board(ctx, workspace_id)
    return {"board": _block_out(block), "page_id": page.id,
            "workspace_id": page.workspace_id, "can_share": not _is_client(ctx)}


def _board_asset_root() -> Path:
    configured = os.getenv("WHITEBOARD_ASSET_DIR", "").strip()
    root = (Path(configured).resolve() if configured else
            (Path(__file__).resolve().parents[2] / "var" / "whiteboard_assets").resolve())
    root.mkdir(parents=True, exist_ok=True)
    return root


def _image_type(first: bytes) -> tuple[str, str] | None:
    if first.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if first.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if len(first) >= 12 and first[:4] == b"RIFF" and first[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return None


@router.post("/blocks/{block_id}/whiteboard/images")
async def upload_whiteboard_image(block_id: int, file: UploadFile = File(...),
                                  ctx: AuthContext = Depends(get_ctx)):
    block, page = _whiteboard(ctx, block_id)
    root = _board_asset_root()
    temporary = root / (secrets.token_hex(24) + ".upload")
    total, first = 0, b""
    try:
        with temporary.open("xb") as output:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                if not first:
                    first = chunk[:16]
                total += len(chunk)
                if total > 8 * 1024 * 1024:
                    raise HTTPException(413, "Whiteboard images must be 8MB or smaller")
                output.write(chunk)
        detected = _image_type(first)
        if not detected:
            raise HTTPException(422, "Paste a PNG, JPG, or WebP image")
        content_type, extension = detected
        storage_key = secrets.token_hex(24) + extension
        destination = root / storage_key
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    if total == 0:
        temporary.unlink(missing_ok=True)
        raise HTTPException(422, "The pasted image is empty")
    asset = BoardAsset(block_id=block.id, workspace_id=page.workspace_id,
                       storage_key=storage_key, content_type=content_type, size=total,
                       created_by=ctx.user.id)
    ctx.db.add(asset)
    ctx.db.flush()
    _audit(ctx, page.workspace_id, "upload_whiteboard_image", "board_asset", asset.id,
           {"block_id": block.id, "size": total})
    ctx.db.commit()
    # `src` is the only value a board is allowed to store for an image, and it is
    # a path into our own private store rather than a data blob or a foreign URL.
    return {"id": asset.id, "content_type": asset.content_type, "size": asset.size,
            "src": f"/api/workspace/whiteboard/assets/{asset.id}"}


@router.get("/whiteboard/assets/{asset_id}")
def get_whiteboard_image(asset_id: int, ctx: AuthContext = Depends(get_ctx)):
    asset = ctx.db.get(BoardAsset, asset_id)
    if asset is None:
        raise HTTPException(404, "Image not found")
    # Resolve through the owning block/page to inherit both workspace and client
    # visibility rules. A duplicated board may reference an asset from another
    # block, but only inside the same authorized workspace.
    _, page = _block(ctx, asset.block_id)
    if page.workspace_id != asset.workspace_id:
        raise HTTPException(404, "Image not found")
    path = _board_asset_root() / asset.storage_key
    if not path.is_file():
        raise HTTPException(404, "Image not found")
    return FileResponse(path, media_type=asset.content_type,
                        headers={"Cache-Control": "private, max-age=3600"})


@router.post("/blocks/{block_id}/whiteboard/presence")
def heartbeat_whiteboard(block_id: int, ctx: AuthContext = Depends(get_ctx)):
    block, page = _whiteboard(ctx, block_id)
    now = datetime.utcnow()
    row = (ctx.db.query(BoardPresence)
           .filter(BoardPresence.block_id == block.id,
                   BoardPresence.user_id == ctx.user.id).first())
    if row is None:
        row = BoardPresence(block_id=block.id, workspace_id=page.workspace_id,
                            user_id=ctx.user.id)
        ctx.db.add(row)
    row.last_seen = now
    ctx.db.flush()
    (ctx.db.query(BoardPresence)
     .filter(BoardPresence.last_seen < now - timedelta(days=1))
     .delete(synchronize_session=False))
    active = (ctx.db.query(BoardPresence)
              .filter(BoardPresence.block_id == block.id,
                      BoardPresence.last_seen >= now - timedelta(seconds=45))
              .order_by(BoardPresence.last_seen.desc()).all())
    names = _names(ctx, {presence.user_id for presence in active})
    ctx.db.commit()
    return {"viewers": [{"user_id": presence.user_id,
                          "name": names.get(presence.user_id, "Someone"),
                          "is_you": presence.user_id == ctx.user.id}
                         for presence in active]}


class PromoteNoteIn(BaseModel):
    shape_id: str
    base_revision: int


def _icp_add(cfg, key: str, value: str) -> None:
    raw = (cfg.icp_definition or "").strip()
    try:
        current = json.loads(raw) if raw else {}
    except Exception:
        current = None
    if isinstance(current, dict):
        values = [str(item).strip() for item in (current.get(key) or []) if str(item).strip()]
        if value.casefold() not in {item.casefold() for item in values}:
            values.append(value)
        current[key] = values
        current.setdefault("default", "Needs Review")
        cfg.icp_definition = json.dumps(current, ensure_ascii=False, indent=2)
    else:
        label = "Fit segment" if key == "icp_categories" else "Reject signal"
        line = f"{label} (from whiteboard): {value}"
        if line.casefold() not in raw.casefold():
            cfg.icp_definition = (raw + "\n\n" + line).strip()


@router.post("/blocks/{block_id}/whiteboard/promote")
def promote_whiteboard_note(block_id: int, body: PromoteNoteIn,
                            ctx: AuthContext = Depends(get_ctx)):
    from ..models.enrich import EnrichConfig

    block, page = _whiteboard(ctx, block_id)
    if body.base_revision != (block.revision or 1):
        raise HTTPException(409, {"message": "Save or reload the newest board before promoting.",
                                  "current": _block_out(block)})
    if not _BOARD_ID.match(body.shape_id or ""):
        raise HTTPException(404, "Note not found")
    content = _validate_whiteboard(ctx, block, block.content or {})
    store = _board_store(content)
    shape = _board_shapes(store).get(body.shape_id)
    if shape is None:
        raise HTTPException(404, "Note not found")
    note_type = _board_note(shape)
    promotion_kind = {"segment": "segment", "proof": "case_study",
                      "reject": "exclusion"}.get(note_type)
    value = _shape_text(shape)
    if promotion_kind is None:
        raise HTTPException(422, "Only Segment, Proof, and Reject notes can become records")
    if not value:
        raise HTTPException(422, "Write the note before promoting it")
    existing = (ctx.db.query(WhiteboardPromotion)
                .filter(WhiteboardPromotion.block_id == block.id,
                        WhiteboardPromotion.shape_id == body.shape_id).first())
    if existing:
        return {"promotion": {"id": existing.id, "kind": existing.kind,
                              "value": existing.value}, "block": _block_out(block)}

    promotion = WhiteboardPromotion(
        workspace_id=page.workspace_id, block_id=block.id, shape_id=body.shape_id,
        kind=promotion_kind, value=value[:2000], data={"source": "whiteboard"},
        created_by=ctx.user.id)
    ctx.db.add(promotion)
    ctx.db.flush()
    cfg = (ctx.db.query(EnrichConfig)
           .filter(EnrichConfig.workspace_id == page.workspace_id).first())
    if cfg is None:
        cfg = EnrichConfig(workspace_id=page.workspace_id, profile={}, icp_definition="")
        ctx.db.add(cfg)
        ctx.db.flush()
    if promotion_kind == "segment":
        _icp_add(cfg, "icp_categories", value)
    elif promotion_kind == "exclusion":
        _icp_add(cfg, "hard_non_icp", value)
    else:
        # A promoted proof note becomes a Library record, not another entry in the
        # brain's JSON. A sticky note is somebody's shorthand from a workshop, so
        # it lands as `operator` — usable as background, and not nameable in an
        # email until a human verifies it and adds the link.
        from ..library import store as _library
        try:
            _library.add_case_study(
                ctx.db, page.workspace_id, client_name=value[:200],
                outcome=value, source="operator", user_id=ctx.user.id,
                note=f"Promoted from a whiteboard note (record {promotion.id}).")
        except _library.LibraryError:
            pass  # already in the Library — the promotion record is still the link
    # Stamp the link into the shape's own meta, so the board shows what has
    # already graduated without a second lookup — and so a duplicated board
    # carries the provenance with it.
    meta = dict(shape.get("meta") or {})
    meta["promotion"] = {"id": promotion.id, "kind": promotion.kind}
    store[body.shape_id] = {**shape, "meta": meta}
    block.content = content
    block.revision = (block.revision or 1) + 1
    page.updated_at = datetime.utcnow()
    _audit(ctx, page.workspace_id, "promote_whiteboard_note", promotion.kind,
           promotion.id, {"block_id": block.id, "shape_id": shape["id"]})
    ctx.db.commit()
    return {"promotion": {"id": promotion.id, "kind": promotion.kind,
                          "value": promotion.value}, "block": _block_out(block)}


class GenerateBoardPageIn(BaseModel):
    title: str = ""


def _board_notes(notes: dict, note_type: str) -> list[dict]:
    """Tagged notes of one type, read top-to-bottom then left-to-right — the
    order someone would read them off the board."""
    return sorted([note for note in notes.values()
                   if note["note_type"] == note_type and note["text"]],
                  key=lambda note: (note["y"], note["x"], note["id"]))


@router.post("/blocks/{block_id}/whiteboard/generate-page")
def generate_page_from_whiteboard(block_id: int, body: GenerateBoardPageIn,
                                  ctx: AuthContext = Depends(get_ctx)):
    block, source = _whiteboard(ctx, block_id)
    content = _validate_whiteboard(ctx, block, block.content or {})
    store = _board_store(content)
    # Only tagged shapes carry meaning we can group. Everything else on the board
    # is drawing, and a generator that guessed at it would produce a document the
    # team did not decide.
    notes = {}
    for shape_id, record in _board_shapes(store).items():
        note_type = _board_note(record)
        text = _shape_text(record)
        if note_type and text:
            notes[shape_id] = {"id": shape_id, "note_type": note_type, "text": text,
                               "x": record.get("x") or 0, "y": record.get("y") or 0}
    if not notes:
        raise HTTPException(422, "Tag some notes on the board before generating a page")
    neighbors: dict[str, list[dict]] = {shape_id: [] for shape_id in notes}
    reasoning = []
    for start, end in _board_links(store):
        left, right = notes.get(start), notes.get(end)
        if left is None or right is None:
            continue                    # an arrow to an untagged shape says nothing
        neighbors[left["id"]].append(right)
        neighbors[right["id"]].append(left)
        reasoning.append(f"{left['text']} → {right['text']}")

    title = (body.title or f"{source.title} — board decisions").strip()[:512]
    # The workspace board sits outside the tree and has no parent to inherit, so
    # what it generates goes to the Whiteboards folder. A board embedded in a
    # document keeps landing beside that document, where its author expects it.
    parent_id = (_board_folder(ctx, source.workspace_id).id
                 if (source.kind or "page") == "whiteboard" else source.parent_id)
    generated = Page(workspace_id=source.workspace_id, parent_id=parent_id,
                     kind="page", title=title, icon=source.icon, section=source.section,
                     visibility=source.visibility, status="draft",
                     owner_role="client" if _is_client(ctx) else "us",
                     position=_next_position(ctx, source.workspace_id, source.section, parent_id),
                     created_by=ctx.user.id)
    ctx.db.add(generated)
    ctx.db.flush()
    specs = [{"type": "heading", "content": {"level": 1, "text": "Decisions from the board"}},
             {"type": "callout", "content": {"tone": "info", "text":
              "This editable draft groups only what the team placed and connected on the whiteboard."}}]
    segments = _board_notes(notes, "segment")
    if segments:
        rows = []
        for segment in segments:
            connected = neighbors.get(segment["id"], [])
            by_type = lambda kind: ", ".join(item["text"] for item in connected
                                              if item["note_type"] == kind)
            rows.append([segment["text"], by_type("trigger"), by_type("proof"), by_type("angle")])
        specs += [{"type": "heading", "content": {"level": 2, "text": "Segments"}},
                  {"type": "table", "content": {"columns":
                   ["Segment", "Connected triggers", "Connected proof", "Connected angles"],
                   "rows": rows}}]
    for note_type, heading in (("trigger", "Fit signals"), ("reject", "Reject criteria"),
                               ("proof", "Proof library"), ("angle", "Angles")):
        values = [note["text"] for note in _board_notes(notes, note_type)]
        if values:
            specs += [{"type": "heading", "content": {"level": 2, "text": heading}},
                      {"type": "list", "content": {"ordered": False, "items": values}}]
    questions = [note["text"] for note in _board_notes(notes, "question")]
    if questions:
        specs += [{"type": "heading", "content": {"level": 2, "text": "Open questions"}},
                  {"type": "checklist", "content": {"items":
                   [{"text": value, "done": False} for value in questions]}}]
    if reasoning:
        specs += [{"type": "heading", "content": {"level": 2, "text": "Reasoning captured"}},
                  {"type": "list", "content": {"ordered": False, "items": reasoning}}]
    for position, spec in enumerate(specs, 1):
        ctx.db.add(Block(page_id=generated.id, position=position, type=spec["type"],
                         content=spec["content"]))
    _audit(ctx, source.workspace_id, "generate_page_from_whiteboard", "page", generated.id,
           {"source_page_id": source.id, "block_id": block.id,
            "notes": len(notes), "links": len(reasoning)})
    ctx.db.commit()
    return _page_out(generated)


@router.delete("/blocks/{block_id}")
def delete_block(block_id: int, ctx: AuthContext = Depends(get_ctx)):
    block, page = _block(ctx, block_id)
    ctx.db.query(Comment).filter(Comment.block_id == block.id).update(
        {Comment.block_id: None}, synchronize_session=False)
    ctx.db.delete(block)
    page.updated_at = datetime.utcnow()
    _audit(ctx, page.workspace_id, "delete_block", "block", block_id, {"page_id": page.id})
    ctx.db.commit()
    return {"ok": True, "id": block_id}


@router.post("/pages/{page_id}/blocks/reorder")
def reorder_blocks(page_id: int, body: ReorderIn, ctx: AuthContext = Depends(get_ctx)):
    page = _page(ctx, page_id)
    owned = {b.id: b for b in ctx.db.query(Block).filter(Block.page_id == page.id).all()}
    unknown = [i for i in body.ordered_ids if i not in owned]
    if unknown:
        raise HTTPException(422, f"Blocks not on this page: {unknown}")
    for i, bid in enumerate(body.ordered_ids, start=1):
        owned[bid].position = i
    page.updated_at = datetime.utcnow()
    _audit(ctx, page.workspace_id, "reorder_blocks", "page", page.id,
           {"count": len(body.ordered_ids)})
    ctx.db.commit()
    return {"ok": True, "ordered_ids": body.ordered_ids}


# ---------------------------------------------------------------- versions
class VersionIn(BaseModel):
    note: str = ""


def _snapshot(ctx: AuthContext, page: Page) -> dict:
    blocks = (ctx.db.query(Block).filter(Block.page_id == page.id)
              .order_by(Block.position, Block.id).all())
    return {"title": page.title or "", "icon": page.icon or "", "section": page.section,
            "blocks": [{"type": b.type, "position": b.position, "content": b.content or {},
                        "entity_type": b.entity_type, "entity_id": b.entity_id,
                        "field_path": b.field_path} for b in blocks]}


def _save_version(ctx: AuthContext, page: Page, note: str) -> PageVersion:
    latest = (ctx.db.query(func.max(PageVersion.version_no))
              .filter(PageVersion.page_id == page.id).scalar()) or 0
    version = PageVersion(page_id=page.id, version_no=latest + 1, snapshot=_snapshot(ctx, page),
                          note=(note or "")[:500], created_by=ctx.user.id)
    ctx.db.add(version)
    ctx.db.flush()
    return version


@router.get("/pages/{page_id}/versions")
def list_versions(page_id: int, ctx: AuthContext = Depends(get_ctx)):
    page = _page(ctx, page_id)
    rows = (ctx.db.query(PageVersion).filter(PageVersion.page_id == page.id)
            .order_by(PageVersion.version_no.desc()).all())
    names = _names(ctx, {r.created_by for r in rows})
    return [{"id": r.id, "version": r.version_no, "note": r.note or "",
             "author": names.get(r.created_by, ""), "block_count": len(r.snapshot.get("blocks", [])),
             "at": r.created_at.isoformat() if r.created_at else None} for r in rows]


@router.post("/pages/{page_id}/versions")
def create_version(page_id: int, body: VersionIn, ctx: AuthContext = Depends(get_ctx)):
    page = _page(ctx, page_id)
    version = _save_version(ctx, page, body.note)
    _audit(ctx, page.workspace_id, "create_page_version", "page_version", version.id,
           {"page_id": page.id, "version": version.version_no})
    ctx.db.commit()
    return {"id": version.id, "version": version.version_no, "note": version.note}


@router.post("/pages/{page_id}/restore/{version_id}")
def restore_version(page_id: int, version_id: int, ctx: AuthContext = Depends(get_ctx)):
    """Snapshot the current state first, so a restore is itself undoable."""
    page = _page(ctx, page_id)
    version = (ctx.db.query(PageVersion)
               .filter(PageVersion.id == version_id, PageVersion.page_id == page.id).first())
    if version is None:
        raise HTTPException(404, "Version not found")

    _save_version(ctx, page, f"before restoring v{version.version_no}")

    ctx.db.query(Comment).filter(Comment.page_id == page.id).update(
        {Comment.block_id: None}, synchronize_session=False)
    ctx.db.query(Block).filter(Block.page_id == page.id).delete(synchronize_session=False)
    snap = version.snapshot or {}
    for i, spec in enumerate(snap.get("blocks") or [], start=1):
        if spec.get("type") not in BLOCK_TYPES:
            continue
        ctx.db.add(Block(page_id=page.id, position=i, type=spec["type"],
                         content=spec.get("content") or {}, entity_type=spec.get("entity_type"),
                         entity_id=spec.get("entity_id"), field_path=spec.get("field_path")))
    page.title = snap.get("title", page.title)
    page.icon = snap.get("icon", page.icon)
    page.updated_at = datetime.utcnow()
    _audit(ctx, page.workspace_id, "restore_page_version", "page_version", version.id,
           {"page_id": page.id, "version": version.version_no})
    ctx.db.commit()
    return {"ok": True, "restored_version": version.version_no}


# ---------------------------------------------------------------- comments
class CommentIn(BaseModel):
    page_id: int
    block_id: int | None = None
    parent_id: int | None = None
    body: str
    mentions: list[int] = Field(default_factory=list)


@router.get("/comments")
def list_comments(page_id: int, block_id: int | None = None,
                  ctx: AuthContext = Depends(get_ctx)):
    page = _page(ctx, page_id)          # 404s before any comment is read
    q = scoped(ctx.db.query(Comment), Comment, ctx).filter(Comment.page_id == page.id)
    if block_id is not None:
        q = q.filter(Comment.block_id == block_id)
    rows = q.order_by(Comment.created_at, Comment.id).all()
    names = _names(ctx, {r.author_user_id for r in rows})
    return [_comment_out(c, names) for c in rows]


@router.post("/comments")
def create_comment(body: CommentIn, ctx: AuthContext = Depends(get_ctx)):
    page = _page(ctx, body.page_id)
    text = (body.body or "").strip()
    if not text:
        raise HTTPException(422, "A comment needs a body")
    if body.block_id is not None:
        block = ctx.db.get(Block, body.block_id)
        if block is None or block.page_id != page.id:
            raise HTTPException(404, "Block not found on this page")
    if body.parent_id is not None:
        parent = (scoped(ctx.db.query(Comment), Comment, ctx)
                  .filter(Comment.id == body.parent_id, Comment.page_id == page.id).first())
        if parent is None:
            raise HTTPException(404, "Parent comment not found")
    comment = Comment(workspace_id=page.workspace_id, page_id=page.id, block_id=body.block_id,
                      parent_id=body.parent_id, author_user_id=ctx.user.id, body=text,
                      mentions=body.mentions or [])
    ctx.db.add(comment)
    ctx.db.flush()
    _audit(ctx, page.workspace_id, "create_comment", "comment", comment.id, {"page_id": page.id})
    ctx.db.commit()
    return _comment_out(comment, _names(ctx, {ctx.user.id}))


@router.post("/comments/{comment_id}/resolve")
def resolve_comment(comment_id: int, ctx: AuthContext = Depends(get_ctx)):
    comment = scoped(ctx.db.query(Comment), Comment, ctx).filter(Comment.id == comment_id).first()
    if comment is None:
        raise HTTPException(404, "Comment not found")
    _page(ctx, comment.page_id)          # a client must not resolve on an internal page
    comment.resolved_at = datetime.utcnow()
    comment.resolved_by = ctx.user.id
    _audit(ctx, comment.workspace_id, "resolve_comment", "comment", comment.id)
    ctx.db.commit()
    return _comment_out(comment, _names(ctx, {comment.author_user_id}))


@router.delete("/comments/{comment_id}")
def delete_comment(comment_id: int, ctx: AuthContext = Depends(get_ctx)):
    comment = scoped(ctx.db.query(Comment), Comment, ctx).filter(Comment.id == comment_id).first()
    if comment is None:
        raise HTTPException(404, "Comment not found")
    _page(ctx, comment.page_id)
    if comment.author_user_id != ctx.user.id:
        raise HTTPException(403, "Only the author can delete a comment")
    ctx.db.query(Comment).filter(Comment.parent_id == comment.id).delete(synchronize_session=False)
    workspace_id = comment.workspace_id
    ctx.db.delete(comment)
    _audit(ctx, workspace_id, "delete_comment", "comment", comment_id)
    ctx.db.commit()
    return {"ok": True, "id": comment_id}


# ---------------------------------------------------------------- templates
class TemplateIn(BaseModel):
    from_page_id: int
    name: str
    description: str = ""
    keep_text_block_ids: list[int] = Field(default_factory=list)


@router.get("/page-templates")
def list_templates(ctx: AuthContext = Depends(get_ctx)):
    rows = (ctx.db.query(PageTemplate).filter(PageTemplate.org_id == ctx.org_id)
            .order_by(PageTemplate.name).all())
    return [_template_out(t) for t in rows]


@router.post("/page-templates")
def create_template(body: TemplateIn, ctx: AuthContext = Depends(get_ctx)):
    """Keep the structure; keep text only for the blocks explicitly ticked.

    Bound blocks keep `entity_type` and `field_path` but lose `entity_id` —
    templates are org-scoped, so a retained id would point one workspace's page
    at another workspace's record.
    """
    if _is_client(ctx):
        raise HTTPException(403, "Only the RevCadence team can save templates")
    page = _page(ctx, body.from_page_id)
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(422, "A template needs a name")

    keep = set(body.keep_text_block_ids or [])
    blocks = (ctx.db.query(Block).filter(Block.page_id == page.id)
              .order_by(Block.position, Block.id).all())
    skeleton = [{
        "type": b.type,
        "content": (b.content or {}) if b.id in keep else _sanitize_content(b.type, b.content),
        "entity_type": b.entity_type,
        "field_path": b.field_path,
    } for b in blocks]

    template = PageTemplate(org_id=ctx.org_id, name=name[:255], description=body.description or "",
                            section=page.section, icon=page.icon or "",
                            default_visibility=page.visibility, blocks=skeleton,
                            created_from_page_id=page.id, version=1)
    ctx.db.add(template)
    ctx.db.flush()
    _audit(ctx, page.workspace_id, "create_page_template", "page_template", template.id,
           {"from_page_id": page.id, "kept": len(keep)})
    ctx.db.commit()
    return _template_out(template)
