"""Deal Workspace extras — Tasks and Notes scoped to a Deal. The Deal is the
center of RevCadence; these back its Tasks and Notes tabs. (Overview, Conversation,
Timeline, Blueprint, Agreement, Invoice reuse existing endpoints.)"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import AuthContext, get_ctx, scoped
from ..models.crm import Activity, Deal, Note, Task

router = APIRouter(prefix="/api", tags=["deal-workspace"])


def _deal(ctx, deal_id) -> Deal:
    d = scoped(ctx.db.query(Deal), Deal, ctx).filter(Deal.id == deal_id).first()
    if not d:
        raise HTTPException(404, "Deal not found")
    return d


# ---- tasks -------------------------------------------------------------------
def _task_out(t: Task) -> dict:
    return {"id": t.id, "title": t.title, "done": bool(t.done),
            "due_at": t.due_at.isoformat() if t.due_at else None,
            "created_at": t.created_at.isoformat() if t.created_at else None}


@router.get("/deals/{deal_id}/tasks")
def list_tasks(deal_id: int, ctx: AuthContext = Depends(get_ctx)):
    _deal(ctx, deal_id)
    rows = (ctx.db.query(Task).filter(Task.deal_id == deal_id)
            .order_by(Task.done, Task.id.desc()).all())
    return [_task_out(t) for t in rows]


class TaskIn(BaseModel):
    title: str
    due_at: str | None = None


@router.post("/deals/{deal_id}/tasks")
def create_task(deal_id: int, body: TaskIn, ctx: AuthContext = Depends(get_ctx)):
    d = _deal(ctx, deal_id)
    if not body.title.strip():
        raise HTTPException(422, "title required")
    due = None
    if body.due_at:
        try:
            due = datetime.fromisoformat(body.due_at.replace("Z", ""))
        except ValueError:
            due = None
    t = Task(workspace_id=d.workspace_id, deal_id=d.id, contact_id=d.contact_id,
             title=body.title.strip(), due_at=due, assignee_user_id=ctx.user.id)
    ctx.db.add(t)
    ctx.db.flush()
    ctx.db.add(Activity(workspace_id=d.workspace_id, deal_id=d.id, contact_id=d.contact_id,
                        kind="task_created", title=f"Task: {t.title}", actor_user_id=ctx.user.id))
    ctx.db.commit()
    return _task_out(t)


class TaskPatch(BaseModel):
    done: bool | None = None
    title: str | None = None


@router.patch("/deals/{deal_id}/tasks/{task_id}")
def update_task(deal_id: int, task_id: int, body: TaskPatch, ctx: AuthContext = Depends(get_ctx)):
    d = _deal(ctx, deal_id)
    t = ctx.db.query(Task).filter(Task.id == task_id, Task.deal_id == d.id).first()
    if not t:
        raise HTTPException(404, "Task not found")
    if body.title is not None:
        t.title = body.title
    if body.done is not None:
        t.done = body.done
        if body.done:
            ctx.db.add(Activity(workspace_id=d.workspace_id, deal_id=d.id, contact_id=d.contact_id,
                                kind="task_done", title=f"Task done: {t.title}", actor_user_id=ctx.user.id))
    ctx.db.commit()
    return _task_out(t)


@router.delete("/deals/{deal_id}/tasks/{task_id}")
def delete_task(deal_id: int, task_id: int, ctx: AuthContext = Depends(get_ctx)):
    d = _deal(ctx, deal_id)
    t = ctx.db.query(Task).filter(Task.id == task_id, Task.deal_id == d.id).first()
    if not t:
        raise HTTPException(404, "Task not found")
    ctx.db.delete(t)
    ctx.db.commit()
    return {"ok": True}


# ---- notes -------------------------------------------------------------------
@router.get("/deals/{deal_id}/notes")
def list_notes(deal_id: int, ctx: AuthContext = Depends(get_ctx)):
    _deal(ctx, deal_id)
    rows = (ctx.db.query(Note).filter(Note.deal_id == deal_id).order_by(Note.id.desc()).all())
    return [{"id": n.id, "body": n.body, "author_user_id": n.author_user_id,
             "created_at": n.created_at.isoformat() if n.created_at else None} for n in rows]


class NoteIn(BaseModel):
    body: str


@router.post("/deals/{deal_id}/notes")
def create_note(deal_id: int, body: NoteIn, ctx: AuthContext = Depends(get_ctx)):
    d = _deal(ctx, deal_id)
    if not body.body.strip():
        raise HTTPException(422, "note body required")
    n = Note(workspace_id=d.workspace_id, deal_id=d.id, contact_id=d.contact_id,
             company_id=d.company_id, body=body.body.strip(), author_user_id=ctx.user.id)
    ctx.db.add(n)
    ctx.db.flush()
    ctx.db.add(Activity(workspace_id=d.workspace_id, deal_id=d.id, contact_id=d.contact_id,
                        company_id=d.company_id, kind="note", title="Note added",
                        body=body.body.strip()[:500], actor_user_id=ctx.user.id))
    ctx.db.commit()
    return {"id": n.id, "body": n.body, "created_at": n.created_at.isoformat() if n.created_at else None}
