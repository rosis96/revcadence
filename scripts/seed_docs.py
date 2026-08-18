"""Seed the Shared Documents space: org page templates + a starter folder and page.

Gives a workspace something real to look at — a template to start pages from, and
one written page carrying a comment thread so the review flow is visible without
anyone having to type it first.

Deliberately a script, not part of workspace provisioning: auto-instantiating a
client workspace is its own step, and seeding on boot would surprise anyone whose
workspace already has pages.

Usage:
    python -m scripts.seed_docs --workspace-slug webaholics
    python -m scripts.seed_docs --workspace-id 1 --reset

Re-running is safe: existing templates and the starter folder are left alone
unless --reset is passed, which removes only what this script created.
"""
import argparse
import sys
from datetime import datetime, timedelta

try:
    from app.db import init_db, session
    from app.models.identity import Membership, User, Workspace
    from app.models.workspace_docs import (Block, Comment, Page, PageTemplate, PageVersion)
except ModuleNotFoundError as e:  # pragma: no cover - operator convenience
    sys.exit(
        f"\nMissing dependency: {e.name!r} — wrong Python interpreter.\n"
        "Locally, use the project venv:\n"
        "    .venv/Scripts/python -m scripts.seed_docs --workspace-slug <slug>\n"
    )


# ---------------------------------------------------------------- templates
# Block skeletons in the same shape PageTemplate.blocks stores: type + content,
# plus entity_type/field_path for bound blocks (never entity_id — a template is
# org-scoped and must not point at one workspace's records).
TEMPLATES = [
    {
        "name": "ICP Definition",
        "description": "Who we target, who we skip, and the evidence behind both.",
        "section": "strategy",
        "icon": "Target",
        "blocks": [
            {"type": "callout", "content": {"tone": "info", "text":
                "This page is the single source of truth for fit decisions. Editing the "
                "ICP block below changes what the research pipeline actually uses."}},
            {"type": "heading", "content": {"level": 2, "text": "Who we target"}},
            {"type": "live", "content": {"display": "ICP definition"},
             "entity_type": "icp", "field_path": "icp_definition"},
            {"type": "heading", "content": {"level": 2, "text": "Firmographics"}},
            {"type": "table", "content": {
                "columns": ["Attribute", "Target", "Hard rule?"],
                "rows": [["Employee count", "", ""], ["Geography", "", ""], ["Industry", "", ""]]}},
            {"type": "heading", "content": {"level": 2, "text": "Who we skip"}},
            {"type": "list", "content": {"ordered": False, "items": []}},
            {"type": "divider", "content": {}},
            {"type": "heading", "content": {"level": 2, "text": "Open questions"}},
            {"type": "checklist", "content": {"items": []}},
        ],
    },
    {
        "name": "Angles & Messaging",
        "description": "The angles we lead with, the proof behind each, and what we avoid.",
        "section": "strategy",
        "icon": "Megaphone",
        "blocks": [
            {"type": "heading", "content": {"level": 2, "text": "Angle one"}},
            {"type": "text", "content": {"html": ""}},
            {"type": "heading", "content": {"level": 3, "text": "Proof we can name"}},
            {"type": "list", "content": {"ordered": False, "items": []}},
            {"type": "callout", "content": {"tone": "warn", "text":
                "Only verified case studies can be named in copy. Client-supplied facts are "
                "usable but get flagged in preview."}},
            {"type": "divider", "content": {}},
            {"type": "heading", "content": {"level": 2, "text": "Phrases to avoid"}},
            {"type": "list", "content": {"ordered": False, "items": []}},
        ],
    },
    {
        "name": "Kickoff Notes",
        "description": "What we heard on the call, what we agreed, and what we still need.",
        "section": "operations",
        "icon": "ClipboardList",
        "blocks": [
            {"type": "heading", "content": {"level": 2, "text": "What we heard"}},
            {"type": "text", "content": {"html": ""}},
            {"type": "heading", "content": {"level": 2, "text": "Agreed scope"}},
            {"type": "checklist", "content": {"items": []}},
            {"type": "heading", "content": {"level": 2, "text": "Still needed from the client"}},
            {"type": "checklist", "content": {"items": []}},
            {"type": "heading", "content": {"level": 2, "text": "Attachments"}},
            {"type": "file", "content": {"upload_id": "", "name": "", "size": 0}},
        ],
    },
]

STARTER_FOLDER = "Strategy"
STARTER_PAGE = "ICP Definition"

# The starter page ships written, not blank — an empty page teaches nothing about
# what the space is for.
STARTER_BLOCKS = [
    {"type": "callout", "content": {"tone": "info", "text":
        "This page is shared with you. Comment on any block and we will pick it up — "
        "you do not need to edit it yourself unless you want to."}},
    {"type": "heading", "content": {"level": 2, "text": "Who we target"}},
    {"type": "text", "content": {"html":
        "<p>B2B agencies and consultancies between 10 and 50 staff, in the UK and "
        "North America, who sell retained work rather than one-off projects.</p>"}},
    {"type": "heading", "content": {"level": 2, "text": "Firmographics"}},
    {"type": "table", "content": {
        "columns": ["Attribute", "Target", "Hard rule?"],
        "rows": [
            ["Employee count", "10–50", "Yes — under 10 is out"],
            ["Geography", "UK, US, Canada", "No"],
            ["Industry", "Marketing, design, dev, consulting", "No"],
            ["Model", "Retained or project-based", "Yes — no pure staffing"],
        ]}},
    {"type": "heading", "content": {"level": 2, "text": "Who we skip"}},
    {"type": "list", "content": {"ordered": False, "items": [
        "Non-profits, churches and donation-driven organisations",
        "Pure staffing and recruitment agencies",
        "Anyone under 10 staff — they buy on price and churn",
    ]}},
    {"type": "divider", "content": {}},
    {"type": "heading", "content": {"level": 2, "text": "Open questions"}},
    {"type": "checklist", "content": {"items": [
        {"text": "Confirm whether we include agencies in Ireland", "done": False},
        {"text": "Decide on a minimum retainer size", "done": True},
    ]}},
    {"type": "live", "content": {"display": "ICP definition"},
     "entity_type": "icp", "field_path": "icp_definition"},
]

# (block index the thread hangs off, author side, body). "us" = the operator,
# "client" = the client user, so the page shows a real two-sided conversation.
STARTER_COMMENTS = [
    (5, "client", "Would you include agencies in Ireland? We have two good clients there."),
    (5, "us", "Yes — adding Ireland to the geography row now. It was an oversight, not a decision."),
    (7, "us", "Once you confirm the minimum retainer we will lock this page and start the list build."),
]


def _seed_templates(db, org_id: int) -> int:
    made = 0
    for spec in TEMPLATES:
        exists = (db.query(PageTemplate)
                  .filter(PageTemplate.org_id == org_id, PageTemplate.name == spec["name"]).first())
        if exists:
            continue
        db.add(PageTemplate(
            org_id=org_id, name=spec["name"], description=spec["description"],
            section=spec["section"], icon=spec["icon"], default_visibility="internal",
            blocks=spec["blocks"], version=1,
        ))
        made += 1
    db.flush()
    return made


def _seed_page(db, workspace: Workspace, author_id: int, client_id: int | None) -> str:
    folder = (db.query(Page)
              .filter(Page.workspace_id == workspace.id, Page.kind == "folder",
                      Page.title == STARTER_FOLDER, Page.archived_at.is_(None)).first())
    if folder is None:
        folder = Page(workspace_id=workspace.id, kind="folder", title=STARTER_FOLDER,
                      icon="Target", section="strategy", visibility="shared",
                      status="draft", owner_role="us", position=1, created_by=author_id)
        db.add(folder)
        db.flush()

    if (db.query(Page).filter(Page.workspace_id == workspace.id, Page.parent_id == folder.id,
                              Page.title == STARTER_PAGE, Page.archived_at.is_(None)).first()):
        return None                     # already there; caller reports it honestly

    page = Page(workspace_id=workspace.id, parent_id=folder.id, kind="page",
                title=STARTER_PAGE, icon="Target", section="strategy",
                visibility="shared", status="in_review", owner_role="us",
                position=1, created_by=author_id)
    db.add(page)
    db.flush()

    blocks = []
    for i, spec in enumerate(STARTER_BLOCKS, start=1):
        b = Block(page_id=page.id, position=i, type=spec["type"], content=spec["content"],
                  entity_type=spec.get("entity_type"), field_path=spec.get("field_path"))
        db.add(b)
        blocks.append(b)
    db.flush()

    # One pinned version, so History is not empty on first open.
    db.add(PageVersion(
        page_id=page.id, version_no=1, note="shared for review", created_by=author_id,
        snapshot={"title": page.title, "icon": page.icon, "section": page.section,
                  "blocks": [{"type": b.type, "position": b.position, "content": b.content,
                              "entity_type": b.entity_type, "entity_id": b.entity_id,
                              "field_path": b.field_path} for b in blocks]},
    ))

    now = datetime.utcnow()
    root_by_block: dict[int, int] = {}
    for n, (idx, side, body) in enumerate(STARTER_COMMENTS):
        author = client_id if side == "client" else author_id
        if author is None:
            author = author_id
        block = blocks[idx]
        parent_id = root_by_block.get(block.id)
        c = Comment(workspace_id=workspace.id, page_id=page.id, block_id=block.id,
                    parent_id=parent_id, author_user_id=author, body=body,
                    created_at=now - timedelta(hours=len(STARTER_COMMENTS) - n))
        db.add(c)
        db.flush()
        root_by_block.setdefault(block.id, c.id)

    return f"created “{STARTER_PAGE}” in “{STARTER_FOLDER}” with {len(blocks)} blocks"


def _reset(db, workspace: Workspace) -> None:
    """Remove only what this script creates."""
    folder = (db.query(Page).filter(Page.workspace_id == workspace.id, Page.kind == "folder",
                                    Page.title == STARTER_FOLDER).first())
    if folder is None:
        return
    pages = db.query(Page).filter(Page.parent_id == folder.id).all() + [folder]
    ids = [p.id for p in pages]
    db.query(Comment).filter(Comment.page_id.in_(ids)).delete(synchronize_session=False)
    db.query(PageVersion).filter(PageVersion.page_id.in_(ids)).delete(synchronize_session=False)
    db.query(Block).filter(Block.page_id.in_(ids)).delete(synchronize_session=False)
    db.query(Page).filter(Page.id.in_(ids)).delete(synchronize_session=False)
    db.flush()


def main():
    ap = argparse.ArgumentParser(description="Seed page templates and a starter document")
    ap.add_argument("--workspace-id", type=int)
    ap.add_argument("--workspace-slug")
    ap.add_argument("--reset", action="store_true",
                    help="remove the starter folder and its pages first")
    args = ap.parse_args()

    init_db()
    with session() as db:
        q = db.query(Workspace)
        if args.workspace_id:
            q = q.filter(Workspace.id == args.workspace_id)
        elif args.workspace_slug:
            q = q.filter(Workspace.slug == args.workspace_slug)
        workspace = q.order_by(Workspace.id).first()
        if workspace is None:
            raise SystemExit("No matching workspace. Pass --workspace-id or --workspace-slug.")

        author = (db.query(User).join(Membership, Membership.user_id == User.id)
                  .filter(Membership.org_id == workspace.org_id,
                          Membership.role.in_(("owner", "admin")))
                  .order_by(User.id).first())
        if author is None:
            raise SystemExit(f"No owner/admin user in org {workspace.org_id}.")

        client = None
        for m in db.query(Membership).filter(Membership.org_id == workspace.org_id,
                                             Membership.role == "client").all():
            if workspace.id in (m.workspace_ids or []):
                client = db.query(User).filter(User.id == m.user_id).first()
                break

        if args.reset:
            _reset(db, workspace)

        made = _seed_templates(db, workspace.org_id)
        result = _seed_page(db, workspace, author.id, client.id if client else None)

    print(f"workspace: {workspace.name} (id={workspace.id})")
    print(f"templates: {made} added ({len(TEMPLATES)} defined, existing ones untouched)")
    if result is None:
        print(f"document:  “{STARTER_PAGE}” already exists — left alone (use --reset to rebuild)")
    else:
        print(f"document:  {result}")
        print(f"comments:  {len(STARTER_COMMENTS)} across 2 blocks"
              + ("" if client else "  (no client user — all authored by the operator)"))


if __name__ == "__main__":
    main()
