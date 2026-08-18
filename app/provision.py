"""Workspace provisioning — a client workspace is a PACKAGE. The moment it
exists it has: a CRM pipeline (stages), an enrichment config, and a reply
space. No separate 'create reply workspace' step — these come together.

`provision_workspace` is idempotent; `backfill_all` runs on startup so existing
workspaces gain any package pieces they were missing."""
from .models.crm import DEFAULT_STAGES, Stage
from .models.enrich import EnrichConfig
from .models.reply import ReplyWorkspace


def provision_workspace(db, workspace) -> dict:
    created = {"stages": 0, "enrich_config": False, "reply_space": False}

    if not db.query(Stage).filter(Stage.workspace_id == workspace.id).first():
        for name, color, order, won, lost in DEFAULT_STAGES:
            db.add(Stage(workspace_id=workspace.id, name=name, color=color,
                         sort_order=order, is_won=won, is_lost=lost))
        created["stages"] = len(DEFAULT_STAGES)

    if not db.query(EnrichConfig).filter(EnrichConfig.workspace_id == workspace.id).first():
        db.add(EnrichConfig(workspace_id=workspace.id))
        created["enrich_config"] = True

    # One default reply space per workspace, named after it. Inactive until the
    # user fills in the platform + API key. Never duplicates.
    if not db.query(ReplyWorkspace).filter(ReplyWorkspace.workspace_id == workspace.id).first():
        name = workspace.name
        n = 2
        while db.query(ReplyWorkspace).filter(ReplyWorkspace.name == name).first():
            name = f"{workspace.name} ({n})"
            n += 1
        db.add(ReplyWorkspace(workspace_id=workspace.id, name=name, active=False,
                              reply_format={"response_types": [], "followups": []}))
        created["reply_space"] = True

    db.flush()
    return created


def backfill_all(db) -> int:
    from .models.identity import Workspace
    n = 0
    # Archived workspaces are on their way out, not waiting for parts.
    for w in db.query(Workspace).filter(Workspace.archived_at.is_(None)).all():
        res = provision_workspace(db, w)
        if any(res.values()):
            n += 1
    db.commit()
    return n
