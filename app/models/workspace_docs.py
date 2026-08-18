"""Shared Documents — the client workspace's page system.

Deliberately NOT `documents.py`. That module is the portals object (blueprint /
agreement / proposal): one rendered HTML blob per record, with signing state and
view tracking. This is a different object with a different lifecycle — a tree of
pages built from ordered blocks, written by both sides, commented on, versioned.

Two rules are enforced by the shape of the data, not by the UI:

- `visibility` starts at `internal`. A page reaches a client only through the
  explicit share endpoint, and the client query filters on this column — so a
  forgotten UI check cannot leak an internal page.
- No CRDT, no real-time merge. Last write wins per block, and `PageVersion`
  keeps the history that actually answers "what did it say before".

`Block.entity_type / entity_id / field_path` are the live-block binding columns.
They are created here and left null on purpose: the resolver that turns a
pointer into a live value is a later step, and adding the columns now means that
step needs no migration.
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint

from ..db import Base

# The page tree's top-level grouping. `internal` pages are never shared.
SECTIONS = ("strategy", "operations", "reference", "internal")

# internal = us only · shared = the client sees it too.
VISIBILITIES = ("internal", "shared")

# `approved` and `changes_requested` are reachable by the approval flow, which is
# a later step. Share moves draft → in_review; nothing here writes the other two.
STATUSES = ("draft", "in_review", "changes_requested", "approved")

OWNER_ROLES = ("us", "client")

# A folder is a Page that holds other pages and has no blocks of its own.
# Explicit rather than inferred from "has children and no blocks" — that would
# make an empty folder indistinguishable from an empty page.
#
# `whiteboard` is the workspace's single canvas. Exactly one such page exists per
# workspace, it is created on first visit rather than by anyone, and it is kept
# out of the page tree — the Whiteboards nav entry opens it directly, so there is
# no board to name, create, or choose between. It is still a Page holding one
# Block, so comments, versions, and the audit trail work on it unchanged.
PAGE_KINDS = ("page", "folder", "whiteboard")

# A block type outside this tuple is rejected at the router. Whiteboards remain
# ordinary document blocks, so they inherit the page tree, permissions,
# comments, version history, and sharing rules instead of creating a second
# content system.
BLOCK_TYPES = (
    "heading",    # {level: 1|2|3, text}
    "text",       # {html}
    "list",       # {ordered: bool, items: [str]}
    "checklist",  # {items: [{text, done}]}
    "callout",    # {tone: info|warn|bad, text}
    "table",      # {columns: [str], rows: [[str]]}
    "file",       # {upload_id, name, size}
    "divider",    # {}
    "embed",      # {url, provider}
    "live",       # {display} — renders a placeholder until the binding resolver lands
    "view",       # {view_id} — renders a placeholder until saved views land
    "whiteboard", # {grid, shapes, connectors} — coordinates are unbounded (pan/zoom canvas)
)

# Duplicating with sanitize=True keeps the shape of the document and drops what
# was written about a specific client. Headings, callouts and dividers survive
# whole; tables keep their column headers and lose every row.
SANITIZE_KEEP_WHOLE = ("heading", "callout", "divider")


class Page(Base):
    __tablename__ = "pages"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    parent_id = Column(Integer, ForeignKey("pages.id"), index=True)   # null = top of its section

    kind = Column(String(20), default="page")             # one of PAGE_KINDS
    title = Column(String(512), default="")
    icon = Column(String(40), default="")                 # lucide icon name, rendered by the UI
    section = Column(String(20), default="strategy")      # one of SECTIONS
    visibility = Column(String(20), default="internal")   # one of VISIBILITIES
    status = Column(String(30), default="draft")          # one of STATUSES
    owner_role = Column(String(20), default="us")         # one of OWNER_ROLES
    position = Column(Integer, default=0)                 # order within (section, parent_id)

    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    archived_at = Column(DateTime)                        # soft delete — never hard-deleted


class Block(Base):
    """One editable region. The document is a list of these, not a single
    ProseMirror doc, so a save touches one row and comments can anchor to a
    stable id."""
    __tablename__ = "blocks"

    id = Column(Integer, primary_key=True)
    page_id = Column(Integer, ForeignKey("pages.id"), nullable=False, index=True)
    position = Column(Integer, default=0)
    type = Column(String(20), nullable=False, default="text")   # one of BLOCK_TYPES
    content = Column(JSON, default=dict)

    # Live-block binding. A bound block stores a POINTER and never a copy of the
    # value — one brain per client. Null until the resolver step wires it.
    entity_type = Column(String(40))
    entity_id = Column(Integer)
    field_path = Column(String(255))

    # Whiteboards use this for optimistic concurrency. Other blocks may omit
    # base_revision and retain the existing last-write-wins behavior.
    revision = Column(Integer, default=1, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PageVersion(Base):
    """An immutable snapshot of the full ordered block tree. Restoring writes a
    fresh snapshot first, so a restore is itself undoable."""
    __tablename__ = "page_versions"

    id = Column(Integer, primary_key=True)
    page_id = Column(Integer, ForeignKey("pages.id"), nullable=False, index=True)
    version_no = Column(Integer, nullable=False)
    snapshot = Column(JSON, nullable=False)     # {title, icon, section, blocks: [...]}
    note = Column(String(500), default="")
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class Comment(Base):
    """Threaded, anchored to a block (or to the page when block_id is null).
    Carries workspace_id directly so it scopes through `scoped()` like every
    other business object, without a join."""
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    page_id = Column(Integer, ForeignKey("pages.id"), nullable=False, index=True)
    block_id = Column(Integer, ForeignKey("blocks.id"), index=True)   # null = page-level
    parent_id = Column(Integer, ForeignKey("comments.id"), index=True)  # null = thread root

    author_user_id = Column(Integer, ForeignKey("users.id"))
    body = Column(Text, default="")
    mentions = Column(JSON, default=list)      # [user_id]

    resolved_at = Column(DateTime)
    resolved_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class PageTemplate(Base):
    """Org-scoped page skeleton. Templates cross workspace boundaries by design,
    which is exactly why saving one drops `entity_id` from every bound block —
    a template must never point at one client's records."""
    __tablename__ = "page_templates"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, default="")
    section = Column(String(20), default="strategy")
    icon = Column(String(40), default="")
    default_visibility = Column(String(20), default="internal")
    blocks = Column(JSON, default=list)        # [{type, content, entity_type, field_path}]
    created_from_page_id = Column(Integer, ForeignKey("pages.id"))
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)


class BoardPresence(Base):
    """Short-lived viewing heartbeat; stale rows are ignored, not scheduled."""
    __tablename__ = "board_presence"
    __table_args__ = (UniqueConstraint("block_id", "user_id", name="uq_board_presence_user"),)

    id = Column(Integer, primary_key=True)
    block_id = Column(Integer, ForeignKey("blocks.id"), nullable=False, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    last_seen = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class BoardAsset(Base):
    """Private pasted image stored outside the web root."""
    __tablename__ = "board_assets"

    id = Column(Integer, primary_key=True)
    block_id = Column(Integer, ForeignKey("blocks.id"), nullable=False, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    storage_key = Column(String(255), nullable=False, unique=True)
    content_type = Column(String(80), nullable=False)
    size = Column(Integer, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)


class WhiteboardPromotion(Base):
    """Stable record identity for a note promoted into workspace knowledge."""
    __tablename__ = "whiteboard_promotions"
    __table_args__ = (UniqueConstraint("block_id", "shape_id", name="uq_whiteboard_promotion_shape"),)

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    block_id = Column(Integer, ForeignKey("blocks.id"), nullable=False, index=True)
    shape_id = Column(String(80), nullable=False)
    kind = Column(String(30), nullable=False, index=True)
    value = Column(Text, nullable=False)
    data = Column(JSON, default=dict)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
