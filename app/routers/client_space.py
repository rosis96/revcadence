"""Client Space API — the screens we share with the client.

Everything here is workspace-scoped through `ctx.workspace_ids_for_query()`, and
every write goes through `_operator()`. Three rules worth stating once:

- **Writes are ours.** A client reads their launch; they do not edit it. The same
  gate refuses writes while "Preview as client" is on, so the preview is genuinely
  read-only rather than a costume an operator can still act through.
- **`hidden_from_client` is computed for the operator, not for the view.** It
  deliberately ignores `sees_as_client`, because the whole point of that number
  is to keep working while the preview is on.
- **The plan is derived in one place.** Timeline, List, Board and the Overview's
  stage rail all render `client_space.plan.build()`. None of them recompute
  blocked-ness, slippage or the critical path for themselves.
"""
import csv
import io
from datetime import date, datetime, timedelta

from fastapi import (APIRouter, Depends, File, Form as FastForm, HTTPException,
                     Response, UploadFile)
from pydantic import BaseModel, Field
from sqlalchemy import func

from .. import forms_fill
from ..auth import AuthContext, get_ctx, scoped
from ..client_space import plan as planner
from ..models.client_space import (DONE, LAUNCH_PHASES, STAGE_KEYS, STAGE_LABELS,
                                   TASK_OWNERS, TASK_STATUSES, ClientLaunch, LaunchTask)
from ..models.crm import Activity, Company, Contact, Deal, Stage
from ..models.enrich import EnrichLead
from ..models.forms import Form, FormAnswer, FormInvite, FormQuestion, FormResponse
from ..models.identity import MASTER_ROLES, Membership, User, Workspace
from ..models.sequences import EmailSequence
from ..models.workspace_docs import Block, Page
from .workspace_docs import _next_position, _pages

router = APIRouter(prefix="/api/client-space", tags=["client-space"])

TABLE_FOLDER_TITLE = "Boards & Tables"
TABLE_BLOCK_TYPES = ("table", "view")
MEETING_KINDS = ("meeting_booked", "meeting_held")
MEETING_QUALITIES = ("qualified", "no_show", "no_update")


# ---------------------------------------------------------------- helpers
def _operator(ctx: AuthContext) -> AuthContext:
    """Writes are ours. Clients read; previewing operators read."""
    if ctx.sees_as_client:
        raise HTTPException(403, "Client Space is read-only from the client's side")
    return ctx


def _internal(ctx: AuthContext) -> AuthContext:
    """Internal zone. Same rule as an internal page inside Docs.

    Client Space is not uniformly client-visible: it has a shared zone and an
    internal one, and the Setup group is the internal one. The sidebar does not
    render these items for a client, and this refuses them the URL — the nav is
    a convenience, this is the boundary.
    """
    if ctx.role not in MASTER_ROLES:
        raise HTTPException(404, "Not found")
    return ctx


def _operator_may_not_answer(ctx: AuthContext) -> AuthContext:
    """Only the recipient fills the form in.

    An operator previewing as the client is looking, not answering — a preview
    that could write would put our words in the client's mouth on a record that
    exists to be exactly what they said.
    """
    if ctx.preview_as_client:
        raise HTTPException(403, "The preview is read-only")
    return ctx


def _one_workspace(ctx: AuthContext, workspace_id: int | None) -> int | None:
    """Client Space is per-client by definition. `None` means "no client picked
    yet" — the switcher's All-workspaces position — which is a real state the
    screens render, not an error."""
    allowed = ctx.workspace_ids_for_query(workspace_id)
    if workspace_id is not None:
        return workspace_id
    return allowed[0] if len(allowed) == 1 else None


def _require_workspace(ctx: AuthContext, workspace_id: int | None) -> int:
    resolved = _one_workspace(ctx, workspace_id)
    if resolved is None:
        raise HTTPException(422, "Choose a client workspace first")
    return resolved


def _parse_when(value: str | None) -> datetime | None:
    """Accepts an ISO date or datetime; empty string clears the field."""
    if value is None or not str(value).strip():
        return None
    raw = str(value).strip().replace("Z", "")
    for parse in (datetime.fromisoformat,
                  lambda v: datetime.combine(date.fromisoformat(v), datetime.min.time())):
        try:
            return parse(raw)
        except ValueError:
            continue
    raise HTTPException(422, "Dates must be ISO format (YYYY-MM-DD)")


def _launch(ctx: AuthContext, workspace_id: int) -> ClientLaunch | None:
    return ctx.db.query(ClientLaunch).filter(ClientLaunch.workspace_id == workspace_id).first()


def _ensure_launch(ctx: AuthContext, workspace_id: int) -> ClientLaunch:
    row = _launch(ctx, workspace_id)
    if row is None:
        row = ClientLaunch(workspace_id=workspace_id, stage="intake", created_by=ctx.user.id)
        ctx.db.add(row)
        ctx.db.flush()
    return row


def _tasks(ctx: AuthContext, workspace_id: int) -> list[LaunchTask]:
    return (ctx.db.query(LaunchTask)
            .filter(LaunchTask.workspace_id == workspace_id)
            .order_by(LaunchTask.position, LaunchTask.id).all())


def _iso(value):
    return value.isoformat() if value else None


def _days_to(when: datetime | None) -> int | None:
    if when is None:
        return None
    return (when.date() - datetime.utcnow().date()).days


def _pretty(value) -> str:
    """"Aug 16". Built without `%-d`/`%#d`, which are platform-specific strftime
    extensions — the POSIX form raises on Windows and vice-versa."""
    if value is None:
        return ""
    day = value.date() if isinstance(value, datetime) else value
    return f"{day:%b} {day.day}"


def _client_label(ctx: AuthContext, workspace_id: int) -> str:
    """A client task is owned by the client — and on screen that should read as
    their name, not the word "Client". `Bond Media` in the Owner column is the
    difference between a plan about them and a plan for them."""
    ws = ctx.db.get(Workspace, workspace_id)
    return (ws.name if ws else "") or "Client"


def _built(ctx: AuthContext, workspace_id: int, launch: ClientLaunch | None) -> dict:
    return planner.build(_tasks(ctx, workspace_id), launch=launch,
                         client_label=_client_label(ctx, workspace_id))


def _health(launch: ClientLaunch | None, built: dict) -> str:
    """One word for the state of an account, ordered by what an operator needs to
    act on first — so a blocked launch never reads as "at risk" and gets skipped."""
    if launch is None:
        return "not_started"
    counts, filters = built["counts"], built["filters"]
    open_tasks = counts["total"] - counts["done"]
    if filters["blocked"]:
        return "blocked"
    if launch.stage == "live" and not open_tasks:
        return "live"
    if filters["overdue"]:
        return "at_risk"
    today = datetime.utcnow().date()
    if launch.first_send_at and launch.first_send_at.date() < today and launch.stage != "live":
        return "at_risk"
    return "live" if launch.stage == "live" else "on_track"


def _blocked_side(built: dict) -> str | None:
    sides = {t["owner"] for t in built["tasks"] if t["blocked"] and t["status"] != DONE}
    sides = {"client" if s == "client" else "us" for s in sides}
    if not sides:
        return None
    return "both" if len(sides) > 1 else sides.pop()


def _critical_note(built: dict) -> str:
    """The one line the Overview shows under its status pill: the next unfinished
    thing on the critical path, and when it lands. Anything else on that line is
    a number nobody can act on."""
    ids = set(built["critical_path"])
    upcoming = [t for t in built["tasks"] if t["id"] in ids and t["status"] != DONE]
    if not upcoming:
        return ""
    nxt = min(upcoming, key=lambda t: (t["due_at"] or "9999", t["phase_index"]))
    when = _pretty(date.fromisoformat(nxt["due_at"][:10])) if nxt["due_at"] else ""
    return f"Critical path: {nxt['title'].lower()}{f' completes {when}' if when else ''}"


def _hidden_from_client(ctx: AuthContext, workspace_id: int) -> dict | None:
    """How much of this workspace the client cannot see. Runs outside `_pages()`
    on purpose: it is the operator's number, and it has to survive the preview
    toggle that hides those very rows from every other query on the screen."""
    if ctx.role == "client":
        return None
    rows = (scoped(ctx.db.query(Page.id), Page, ctx, workspace_id)
            .filter(Page.archived_at.is_(None), Page.visibility != "shared").all())
    ids = [r[0] for r in rows]
    if not ids:
        return {"total": 0, "docs": 0, "whiteboards": 0}
    boards = (ctx.db.query(func.count(func.distinct(Block.page_id)))
              .filter(Block.page_id.in_(ids), Block.type == "whiteboard").scalar() or 0)
    return {"total": len(ids), "docs": len(ids) - boards, "whiteboards": boards}


def _shared_counts(ctx: AuthContext, workspace_id: int) -> dict:
    page_ids = [p.id for p in _pages(ctx, workspace_id).filter(Page.archived_at.is_(None)).all()]
    boards = tables = 0
    if page_ids:
        boards = (ctx.db.query(func.count(func.distinct(Block.page_id)))
                  .filter(Block.page_id.in_(page_ids), Block.type == "whiteboard").scalar() or 0)
        tables = (ctx.db.query(func.count(func.distinct(Block.page_id)))
                  .filter(Block.page_id.in_(page_ids), Block.type.in_(TABLE_BLOCK_TYPES)).scalar() or 0)
    sequences = (ctx.db.query(func.count(EmailSequence.id))
                 .filter(EmailSequence.workspace_id == workspace_id,
                         EmailSequence.status != "archived").scalar() or 0)
    return {"docs": len(page_ids) - boards, "whiteboards": boards,
            "tables": tables, "sequences": sequences}


def _workspace_choices(ctx: AuthContext) -> list[dict]:
    rows = (ctx.db.query(Workspace).filter(Workspace.id.in_(ctx.allowed_workspace_ids()))
            .order_by(Workspace.name).all())
    return [{"id": w.id, "name": w.name} for w in rows]


def _onboarding_state(ctx: AuthContext, workspace_id: int) -> dict:
    """For us, the workspace's latest invite. For the client, only their own.

    A client seeing "sent to <colleague's address>" would be reading someone
    else's row off their own dashboard, so their side is narrowed to the invite
    addressed to them and carries no recipient at all.
    """
    q = ctx.db.query(FormInvite).filter(FormInvite.workspace_id == workspace_id)
    mine_only = ctx.sees_as_client
    if mine_only:
        q = q.filter(func.lower(FormInvite.recipient_email) == (ctx.user.email or "").lower())
    invite = q.order_by(FormInvite.id.desc()).first()
    if invite is None:
        return {"status": "not_sent", "invite_id": None, "recipient": "",
                "submitted_at": None, "response_id": None}
    response = (ctx.db.query(FormResponse).filter(FormResponse.invite_id == invite.id)
                .order_by(FormResponse.id.desc()).first())
    status = "submitted" if response and response.submitted_at else (
        "partial" if response else "opened" if invite.opened_at else "sent")
    return {"status": status, "invite_id": None if mine_only else invite.id,
            "recipient": "" if mine_only else invite.recipient_email,
            "submitted_at": _iso(response.submitted_at) if response else None,
            "response_id": None if mine_only else (response.id if response else None)}


def _launch_out(launch: ClientLaunch | None, workspace_name: str) -> dict:
    if launch is None:
        return {"started": False, "name": "Outbound Launch Plan", "stage": None,
                "kickoff_at": None, "first_send_at": None, "days_to_first_send": None,
                "note": "", "prospect_target": 0, "baseline_at": None, "instantiated_at": None}
    return {
        "started": True,
        "name": launch.name or "Outbound Launch Plan",
        "subtitle": (f"Standard RevCadence launch, instantiated for {workspace_name}"
                     f"{' on ' + _pretty(launch.created_at) if launch.created_at else ''}."
                     + (f" Target first send: {_pretty(launch.first_send_at)}."
                        if launch.first_send_at else "")),
        "stage": launch.stage,
        "stage_label": STAGE_LABELS.get(launch.stage, launch.stage),
        "kickoff_at": _iso(launch.kickoff_at),
        "first_send_at": _iso(launch.first_send_at),
        "days_to_first_send": _days_to(launch.first_send_at),
        "note": launch.note or "",
        "prospect_target": launch.prospect_target or 0,
        "baseline_at": _iso(launch.baseline_at),
        "instantiated_at": _iso(launch.created_at),
    }


# ---------------------------------------------------------------- overview
@router.get("/overview")
def overview(workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    """The module's landing screen, in one request."""
    resolved = _one_workspace(ctx, workspace_id)
    if resolved is None:
        return {"workspace": None, "workspaces": _workspace_choices(ctx)}
    ws = ctx.db.get(Workspace, resolved)
    launch = _launch(ctx, resolved)
    built = _built(ctx, resolved, launch)
    stage = launch.stage if launch else None
    tasks = built["tasks"]
    open_tasks = [t for t in tasks if t["status"] != DONE]

    def _phase_state(key: str) -> dict:
        """What the stage rail says under each stop. Read from the tasks, so a
        phase reports what actually happened rather than what stage the launch
        row claims to be in."""
        rows = [t for t in tasks if t["stage"] == key]
        done = [t for t in rows if t["status"] == DONE]
        if rows and len(done) == len(rows):
            last = max((d["completed_at"] or d["due_at"] or "" for d in done), default="")
            when = _pretty(date.fromisoformat(last[:10])) if last else ""
            return {"state": "done", "note": f"Done {when}" if when else "Done"}
        if key == stage:
            waiting = [t for t in rows if t["owner"] == "client" and t["status"] != DONE]
            if waiting:
                return {"state": "now", "note": "In review — you"}
            return {"state": "now", "note": f"{len(done)}/{len(rows)} done" if rows else "In progress"}
        starts = sorted(t["start_at"] for t in rows if t["start_at"] and t["status"] != DONE)
        when = _pretty(date.fromisoformat(starts[0][:10])) if starts else ""
        return {"state": "next", "note": f"Starts {when}" if when else ""}

    return {
        "workspace": {"id": resolved, "name": ws.name if ws else ""},
        "launch": _launch_out(launch, ws.name if ws else ""),
        "stages": [{"key": key, "label": label, "short": short, **_phase_state(key)}
                   for key, label, short in LAUNCH_PHASES],
        "stage": stage,
        "stage_label": STAGE_LABELS.get(stage, "") if stage else "",
        "health": _health(launch, built),
        "blocked_side": _blocked_side(built),
        "critical_note": _critical_note(built),
        # "On track — 1 risk" needs the count, not just the word. A risk is
        # anything actively threatening the date: blocked or already late.
        "risks": built["filters"]["blocked"] + built["filters"]["overdue"],
        "first_send_at": _iso(launch.first_send_at) if launch else None,
        "days_to_first_send": _days_to(launch.first_send_at) if launch else None,
        "counts": built["counts"],
        "blocked": [t for t in open_tasks if t["blocked"]][:6],
        "waiting_on_us": [t for t in open_tasks
                          if t["owner"] in ("us", "system", "both") and not t["blocked"]][:6],
        "waiting_on_client": [t for t in open_tasks
                              if t["owner"] == "client" and not t["blocked"]][:6],
        "shared": _shared_counts(ctx, resolved),
        "hidden_from_client": _hidden_from_client(ctx, resolved),
        "onboarding": _onboarding_state(ctx, resolved),
        "can_edit": not ctx.sees_as_client,
    }


# ---------------------------------------------------------------- launch plan
class LaunchPatch(BaseModel):
    workspace_id: int | None = None
    name: str | None = None
    stage: str | None = None
    kickoff_at: str | None = None
    first_send_at: str | None = None
    note: str | None = None
    prospect_target: int | None = Field(default=None, ge=0)


class TaskIn(BaseModel):
    workspace_id: int | None = None
    title: str
    detail: str = ""
    stage: str = "intake"
    owner: str = "us"
    status: str = "backlog"
    start_at: str | None = None
    due_at: str | None = None
    is_milestone: bool = False
    depends_on: list[int] | None = None


class TaskPatch(BaseModel):
    title: str | None = None
    detail: str | None = None
    stage: str | None = None
    owner: str | None = None
    status: str | None = None
    blocked_note: str | None = None
    start_at: str | None = None
    due_at: str | None = None
    is_milestone: bool | None = None
    depends_on: list[int] | None = None
    position: int | None = Field(default=None, ge=0)


def _plan_payload(ctx: AuthContext, workspace_id: int) -> dict:
    ws = ctx.db.get(Workspace, workspace_id)
    launch = _launch(ctx, workspace_id)
    built = _built(ctx, workspace_id, launch)
    return {
        "workspace": {"id": workspace_id, "name": ws.name if ws else ""},
        "launch": _launch_out(launch, ws.name if ws else ""),
        "health": _health(launch, built),
        "phase_options": [{"key": k, "label": lbl, "short": s} for k, lbl, s in LAUNCH_PHASES],
        "can_edit": not ctx.sees_as_client,
        **built,
    }


@router.get("/plan")
def get_plan(workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    resolved = _one_workspace(ctx, workspace_id)
    if resolved is None:
        return {"workspace": None, "workspaces": _workspace_choices(ctx)}
    return _plan_payload(ctx, resolved)


@router.put("/plan")
def update_plan(body: LaunchPatch, ctx: AuthContext = Depends(get_ctx)):
    _operator(ctx)
    workspace_id = _require_workspace(ctx, body.workspace_id)
    launch = _ensure_launch(ctx, workspace_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("stage") is not None:
        if data["stage"] not in STAGE_KEYS:
            raise HTTPException(422, f"stage must be one of {STAGE_KEYS}")
        launch.stage = data["stage"]
    if data.get("name") is not None and data["name"].strip():
        launch.name = data["name"].strip()[:255]
    if "kickoff_at" in data:
        launch.kickoff_at = _parse_when(data["kickoff_at"])
    if "first_send_at" in data:
        launch.first_send_at = _parse_when(data["first_send_at"])
    if data.get("note") is not None:
        launch.note = data["note"].strip()
    if data.get("prospect_target") is not None:
        launch.prospect_target = data["prospect_target"]
    ctx.db.commit()
    return _plan_payload(ctx, workspace_id)


@router.post("/plan/schedule")
def schedule_plan(body: LaunchPatch, ctx: AuthContext = Depends(get_ctx)):
    """Date the tasks that have none, so they can appear on the Timeline.

    A plan created before the schedule columns existed has phases and owners but
    no dates, and undated tasks cannot be drawn. This lays them out from the
    kickoff, after whatever they depend on — and leaves every hand-set date
    alone.
    """
    _operator(ctx)
    workspace_id = _require_workspace(ctx, body.workspace_id)
    launch = _ensure_launch(ctx, workspace_id)
    kickoff = (_parse_when(body.kickoff_at) or launch.kickoff_at
               or datetime.combine(datetime.utcnow().date(), datetime.min.time()))
    launch.kickoff_at = kickoff
    rows = _tasks(ctx, workspace_id)
    if not rows:
        raise HTTPException(409, "There is no plan to schedule yet")
    changed = planner.schedule_missing(rows, kickoff)
    if not launch.first_send_at:
        finals = [t.due_at for t in rows if t.is_milestone and t.due_at] or \
                 [t.due_at for t in rows if t.due_at]
        if finals:
            launch.first_send_at = max(finals)
    ctx.db.commit()
    return {**_plan_payload(ctx, workspace_id), "scheduled": changed}


@router.post("/plan/baseline")
def set_baseline(body: LaunchPatch, ctx: AuthContext = Depends(get_ctx)):
    """Freeze today's dates as what we agreed to. Everything after this is
    measured against it, which is the only honest way to answer "are we late, or
    did we always intend it this way"."""
    _operator(ctx)
    workspace_id = _require_workspace(ctx, body.workspace_id)
    launch = _ensure_launch(ctx, workspace_id)
    rows = _tasks(ctx, workspace_id)
    if not rows:
        raise HTTPException(409, "There is no plan to baseline yet")
    for task in rows:
        task.baseline_start_at = task.start_at
        task.baseline_due_at = task.due_at
    launch.baseline_at = datetime.utcnow()
    ctx.db.commit()
    return _plan_payload(ctx, workspace_id)


@router.get("/plan/export")
def export_plan(workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    """The plan as CSV — the format every client already has a tool for."""
    resolved = _require_workspace(ctx, workspace_id)
    built = _built(ctx, resolved, _launch(ctx, resolved))
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Phase", "Task", "Owner", "Status", "Start", "Due",
                     "Milestone", "Blocked", "Blocks", "On critical path", "Days late"])
    for t in built["tasks"]:
        writer.writerow([
            t["phase_label"], t["title"], t["owner_label"], t["status_label"],
            (t["start_at"] or "")[:10], (t["due_at"] or "")[:10],
            "yes" if t["is_milestone"] else "", "yes" if t["blocked"] else "",
            ", ".join(t["blocks"]), "yes" if t["critical"] else "",
            t["overdue_days"] or "",
        ])
    name = (ctx.db.get(Workspace, resolved).name if ctx.db.get(Workspace, resolved) else "launch")
    slug = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-") or "launch"
    return Response(buf.getvalue(), media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="{slug}-launch-plan.csv"'})


def _validate_deps(ctx: AuthContext, task: LaunchTask, deps: list[int],
                   workspace_id: int) -> list[int]:
    """Dependencies must exist, live in the same workspace, and not close a loop.

    A cycle would make the critical path non-terminating and the Timeline
    unreadable, so it is refused at the boundary rather than defended against in
    four different renderers.
    """
    clean = []
    for raw in deps:
        dep = ctx.db.get(LaunchTask, int(raw))
        if dep is None or dep.workspace_id != workspace_id:
            raise HTTPException(422, "A dependency must be a task in the same launch plan")
        if dep.id != task.id:
            clean.append(dep.id)
    clean = sorted(set(clean))

    rows = {t.id: list(t.depends_on or []) for t in _tasks(ctx, workspace_id)}
    rows[task.id] = clean
    seen, stack = set(), set()

    def walks(node: int) -> bool:
        if node in stack:
            return True
        if node in seen:
            return False
        seen.add(node); stack.add(node)
        for nxt in rows.get(node, []):
            if walks(nxt):
                return True
        stack.discard(node)
        return False

    if any(walks(node) for node in list(rows)):
        raise HTTPException(422, "That dependency would create a loop")
    return clean


@router.post("/plan/tasks")
def create_task(body: TaskIn, ctx: AuthContext = Depends(get_ctx)):
    _operator(ctx)
    workspace_id = _require_workspace(ctx, body.workspace_id)
    title = body.title.strip()
    if not title:
        raise HTTPException(422, "A task needs a title")
    if body.stage not in STAGE_KEYS:
        raise HTTPException(422, f"stage must be one of {STAGE_KEYS}")
    if body.owner not in TASK_OWNERS:
        raise HTTPException(422, f"owner must be one of {TASK_OWNERS}")
    if body.status not in TASK_STATUSES:
        raise HTTPException(422, f"status must be one of {TASK_STATUSES}")
    _ensure_launch(ctx, workspace_id)
    last = (ctx.db.query(func.max(LaunchTask.position))
            .filter(LaunchTask.workspace_id == workspace_id).scalar() or 0)
    task = LaunchTask(workspace_id=workspace_id, stage=body.stage, owner=body.owner,
                      title=title[:512], detail=body.detail.strip(), status=body.status,
                      start_at=_parse_when(body.start_at), due_at=_parse_when(body.due_at),
                      is_milestone=bool(body.is_milestone), depends_on=[],
                      position=last + 1, created_by=ctx.user.id)
    ctx.db.add(task)
    ctx.db.flush()
    if body.depends_on:
        task.depends_on = _validate_deps(ctx, task, body.depends_on, workspace_id)
    ctx.db.commit()
    return _plan_payload(ctx, workspace_id)


def _task(ctx: AuthContext, task_id: int) -> LaunchTask:
    task = ctx.db.get(LaunchTask, task_id)
    if task is None or task.workspace_id not in ctx.allowed_workspace_ids():
        raise HTTPException(404, "Task not found")
    return task


@router.patch("/plan/tasks/{task_id}")
def patch_task(task_id: int, body: TaskPatch, ctx: AuthContext = Depends(get_ctx)):
    _operator(ctx)
    task = _task(ctx, task_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("stage") is not None:
        if data["stage"] not in STAGE_KEYS:
            raise HTTPException(422, f"stage must be one of {STAGE_KEYS}")
        task.stage = data["stage"]
    if data.get("owner") is not None:
        if data["owner"] not in TASK_OWNERS:
            raise HTTPException(422, f"owner must be one of {TASK_OWNERS}")
        task.owner = data["owner"]
    if data.get("status") is not None:
        if data["status"] not in TASK_STATUSES:
            raise HTTPException(422, f"status must be one of {TASK_STATUSES}")
        task.status = data["status"]
        task.completed_at = datetime.utcnow() if data["status"] == DONE else None
    if data.get("title") is not None:
        title = data["title"].strip()
        if not title:
            raise HTTPException(422, "A task needs a title")
        task.title = title[:512]
    if data.get("detail") is not None:
        task.detail = data["detail"].strip()
    if data.get("blocked_note") is not None:
        task.blocked_note = data["blocked_note"].strip()
    if "start_at" in data:
        task.start_at = _parse_when(data["start_at"])
    if "due_at" in data:
        task.due_at = _parse_when(data["due_at"])
    if data.get("is_milestone") is not None:
        task.is_milestone = bool(data["is_milestone"])
    if data.get("position") is not None:
        task.position = data["position"]
    if data.get("depends_on") is not None:
        task.depends_on = _validate_deps(ctx, task, data["depends_on"], task.workspace_id)
    ctx.db.commit()
    return _plan_payload(ctx, task.workspace_id)


@router.delete("/plan/tasks/{task_id}")
def delete_task(task_id: int, ctx: AuthContext = Depends(get_ctx)):
    _operator(ctx)
    task = _task(ctx, task_id)
    workspace_id = task.workspace_id
    # Leave no dangling edges behind: a dependency on a deleted task would render
    # as a blocker nobody can find or finish.
    for other in _tasks(ctx, workspace_id):
        if task.id in (other.depends_on or []):
            other.depends_on = [d for d in other.depends_on if d != task.id]
    ctx.db.delete(task)
    ctx.db.commit()
    return _plan_payload(ctx, workspace_id)


# ---------------------------------------------------------------- master rollup
@router.get("/launches")
def launches(ctx: AuthContext = Depends(get_ctx)):
    """Client launches across every workspace this operator can reach."""
    _operator(ctx)
    ws_ids = ctx.allowed_workspace_ids()
    if not ws_ids:
        return {"launches": []}
    names = dict(ctx.db.query(Workspace.id, Workspace.name)
                 .filter(Workspace.id.in_(ws_ids)).all())
    rows = ctx.db.query(ClientLaunch).filter(ClientLaunch.workspace_id.in_(ws_ids)).all()
    by_ws: dict[int, list[LaunchTask]] = {}
    for task in ctx.db.query(LaunchTask).filter(LaunchTask.workspace_id.in_(ws_ids)).all():
        by_ws.setdefault(task.workspace_id, []).append(task)
    out = []
    for launch in rows:
        built = planner.build(by_ws.get(launch.workspace_id, []), launch=launch,
                              client_label=names.get(launch.workspace_id, "Client"))
        out.append({
            "workspace_id": launch.workspace_id,
            "workspace_name": names.get(launch.workspace_id, ""),
            "stage": launch.stage, "stage_label": STAGE_LABELS.get(launch.stage, launch.stage),
            "health": _health(launch, built),
            "blocked_side": _blocked_side(built),
            "blocked_count": built["filters"]["blocked"],
            "open_count": built["counts"]["total"] - built["counts"]["done"],
            "first_send_at": _iso(launch.first_send_at),
            "days_to_first_send": _days_to(launch.first_send_at),
        })
    rank = {"blocked": 0, "at_risk": 1, "on_track": 2, "not_started": 3, "live": 4}
    out.sort(key=lambda r: (rank.get(r["health"], 9),
                            r["days_to_first_send"] if r["days_to_first_send"] is not None else 9999))
    return {"launches": out}


# ------------------------------------------------------- fixed boards & tables
#
# This is intentionally not a user-authored database. The client gets three
# useful projections over records the engine already owns. If we ever add more
# renderers, they should render these same rows rather than introduce a second
# store that can drift away from enrichment, Calendly and the CRM.
def _contact_name(contact: Contact | None) -> str:
    if contact is None:
        return ""
    return f"{contact.first_name or ''} {contact.last_name or ''}".strip()


def _meeting_quality(activity: Activity, deal: Deal | None) -> str:
    data = activity.data if isinstance(activity.data, dict) else {}
    raw = str(data.get("quality") or (deal.meeting_outcome if deal else "") or "")
    key = raw.strip().lower().replace("-", "_").replace(" ", "_")
    if key in ("qualified", "positive"):
        return "qualified"
    if key in ("no_show", "noshow"):
        return "no_show"
    return "no_update"


def _meeting_at(activity: Activity) -> str | None:
    data = activity.data if isinstance(activity.data, dict) else {}
    # Webhooks do not all name this field the same way. The first three are the
    # scheduled start; occurred_at remains the migration-safe fallback.
    value = (data.get("scheduled_at") or data.get("start_time")
             or data.get("start_at") or data.get("event_start"))
    return str(value) if value else _iso(activity.occurred_at)


@router.get("/boards")
def fixed_boards(workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    resolved = _one_workspace(ctx, workspace_id)
    if resolved is None:
        return {"workspace": None, "prospects": [], "meetings": [], "deals": [],
                "can_update_meetings": False}

    workspace = ctx.db.get(Workspace, resolved)
    leads = (ctx.db.query(EnrichLead).filter(EnrichLead.workspace_id == resolved)
             .order_by(EnrichLead.updated_at.desc(), EnrichLead.id.desc()).limit(1000).all())
    contacts = (ctx.db.query(Contact).filter(Contact.workspace_id == resolved)
                .order_by(Contact.id).all())
    companies = ctx.db.query(Company).filter(Company.workspace_id == resolved).all()
    stages = ctx.db.query(Stage).filter(Stage.workspace_id == resolved).all()
    deal_rows = (ctx.db.query(Deal).filter(Deal.workspace_id == resolved)
                 .order_by(Deal.updated_at.desc(), Deal.id.desc()).limit(500).all())
    meeting_rows = (ctx.db.query(Activity)
                    .filter(Activity.workspace_id == resolved, Activity.kind.in_(MEETING_KINDS))
                    .order_by(Activity.occurred_at.desc(), Activity.id.desc()).limit(500).all())

    contact_by_id = {row.id: row for row in contacts}
    company_by_id = {row.id: row for row in companies}
    deal_by_id = {row.id: row for row in deal_rows}
    stage_by_id = {row.id: row for row in stages}
    contact_by_email = {(row.email or "").strip().lower(): row for row in contacts if row.email}
    meeting_count_by_deal: dict[int, int] = {}
    for meeting in meeting_rows:
        if meeting.deal_id:
            meeting_count_by_deal[meeting.deal_id] = meeting_count_by_deal.get(meeting.deal_id, 0) + 1

    contacted_ids = {row[0] for row in (ctx.db.query(Activity.contact_id)
                     .filter(Activity.workspace_id == resolved,
                             Activity.kind == "email_out", Activity.contact_id.isnot(None))
                     .distinct().all())}

    prospects = []
    for lead in leads:
        email = (lead.email or "").strip().lower()
        contact = contact_by_email.get(email)
        verified = ((lead.email_status or "").lower() in
                    ("safe", "valid", "verified", "deliverable")
                    or (lead.free_status or "").lower() == "ok")
        researched = bool(lead.result) or (lead.status or "").lower() in (
            "done", "enriched", "needs_review", "insufficient")
        contacted = bool(contact and contact.id in contacted_ids)
        prospects.append({
            "id": lead.id, "company": lead.company or "", "website": lead.website or "",
            "contact": f"{lead.first_name or ''} {lead.last_name or ''}".strip(),
            "title": lead.title or "", "email": lead.email or "",
            "verified": verified, "researched": researched, "contacted": contacted,
            "verification": lead.email_status or lead.free_status or "pending",
            "research_status": lead.status or "pending", "updated_at": _iso(lead.updated_at),
        })

    # A meeting may predate its CRM deal. We still show it, and keep the human
    # fields on the activity itself so a later second meeting on the same deal
    # does not inherit the first meeting's outcome.
    lead_by_email = {(row.email or "").strip().lower(): row for row in leads if row.email}
    meetings = []
    for activity in meeting_rows:
        deal = deal_by_id.get(activity.deal_id)
        contact = contact_by_id.get(activity.contact_id or (deal.contact_id if deal else None))
        company = company_by_id.get(activity.company_id or (deal.company_id if deal else None)
                                    or (contact.company_id if contact else None))
        lead = lead_by_email.get((contact.email or "").strip().lower()) if contact else None
        source_verified = bool(
            contact and (contact.email_status or "").lower() in
            ("safe", "valid", "verified", "deliverable")
        ) or bool(lead and ((lead.email_status or "").lower() in
                           ("safe", "valid", "verified", "deliverable")
                           or (lead.free_status or "").lower() == "ok"))
        meetings.append({
            "id": activity.id, "deal_id": deal.id if deal else None,
            "company": company.name if company else (deal.name if deal else activity.title or "Meeting"),
            "website": (company.website or company.domain) if company else "",
            "contact": _contact_name(contact), "email": contact.email if contact else "",
            "meeting_at": _meeting_at(activity),
            # One old meeting may still keep its outcome on Deal. Once a deal
            # has multiple meetings, only the activity-local value is safe — a
            # new call must not inherit the last call's verdict.
            "quality": _meeting_quality(
                activity, deal if meeting_count_by_deal.get(activity.deal_id, 0) == 1 else None),
            "source": "verified" if source_verified else "system",
            "remarks": activity.body or "", "kind": activity.kind,
        })

    deals = []
    for deal in deal_rows:
        contact = contact_by_id.get(deal.contact_id)
        company = company_by_id.get(deal.company_id)
        stage = stage_by_id.get(deal.stage_id)
        deals.append({
            "id": deal.id, "name": deal.name or (company.name if company else "Untitled deal"),
            "company": company.name if company else "", "contact": _contact_name(contact),
            "email": contact.email if contact else "", "stage": stage.name if stage else "Unassigned",
            "stage_color": stage.color if stage else "#64748b",
            "stage_state": "won" if stage and stage.is_won else "lost" if stage and stage.is_lost else "open",
            "value": float(deal.value or 0), "next_step": deal.next_step or "",
            "updated_at": _iso(deal.updated_at),
        })

    return {
        "workspace": {"id": resolved, "name": workspace.name if workspace else "Workspace"},
        "prospects": prospects, "meetings": meetings, "deals": deals,
        # A real client is the person this field is for. Preview remains a
        # costume with no write path.
        "can_update_meetings": not ctx.preview_as_client,
    }


class MeetingUpdateIn(BaseModel):
    quality: str | None = None
    remarks: str | None = Field(default=None, max_length=4000)


@router.patch("/boards/meetings/{activity_id}")
def update_meeting(activity_id: int, body: MeetingUpdateIn,
                   ctx: AuthContext = Depends(get_ctx)):
    if ctx.preview_as_client:
        raise HTTPException(403, "The preview is read-only")
    activity = (scoped(ctx.db.query(Activity), Activity, ctx)
                .filter(Activity.id == activity_id, Activity.kind.in_(MEETING_KINDS)).first())
    if activity is None:
        raise HTTPException(404, "Meeting not found")
    if body.quality is not None:
        quality = body.quality.strip().lower()
        if quality not in MEETING_QUALITIES:
            raise HTTPException(422, "Quality must be qualified, no_show, or no_update")
        activity.data = {**(activity.data if isinstance(activity.data, dict) else {}),
                         "quality": quality}
        deal = ctx.db.get(Deal, activity.deal_id) if activity.deal_id else None
        if deal and deal.workspace_id == activity.workspace_id:
            deal.meeting_outcome = quality
    if body.remarks is not None:
        activity.body = body.remarks.strip()
    ctx.db.commit()
    return {"id": activity.id, "quality": _meeting_quality(
        activity, ctx.db.get(Deal, activity.deal_id) if activity.deal_id else None),
            "remarks": activity.body or ""}


# ------------------------------------------------ legacy document tables API
# Kept for existing document blocks and links. The client-facing Boards & Tables
# screen above no longer exposes creation, view builders or column configuration.
def _table_card(page: Page, blocks: list[Block]) -> dict:
    first = blocks[0].content or {}
    return {"page_id": page.id, "title": page.title or "Untitled",
            "icon": page.icon or "", "visibility": page.visibility, "status": page.status,
            "table_count": len(blocks),
            "columns": [str(c) for c in (first.get("columns") or [])][:6],
            "row_count": len(first.get("rows") or []),
            "updated_at": _iso(page.updated_at)}


@router.get("/tables")
def list_tables(workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    resolved = _one_workspace(ctx, workspace_id)
    if resolved is None:
        return {"tables": [], "workspace": None, "can_edit": not ctx.sees_as_client}
    pages = {p.id: p for p in _pages(ctx, resolved).filter(Page.archived_at.is_(None)).all()}
    grouped: dict[int, list[Block]] = {}
    if pages:
        for block in (ctx.db.query(Block)
                      .filter(Block.page_id.in_(pages.keys()), Block.type.in_(TABLE_BLOCK_TYPES))
                      .order_by(Block.position, Block.id).all()):
            grouped.setdefault(block.page_id, []).append(block)
    cards = [_table_card(pages[pid], blocks) for pid, blocks in grouped.items()]
    cards.sort(key=lambda c: (c["updated_at"] or "", c["page_id"]), reverse=True)
    return {"tables": cards, "workspace": {"id": resolved}, "can_edit": not ctx.sees_as_client}


class TableIn(BaseModel):
    workspace_id: int | None = None
    title: str = "Untitled table"


@router.post("/tables")
def create_table(body: TableIn, ctx: AuthContext = Depends(get_ctx)):
    _operator(ctx)
    workspace_id = _require_workspace(ctx, body.workspace_id)
    section = "operations"
    folder = (_pages(ctx, workspace_id)
              .filter(Page.archived_at.is_(None), Page.kind == "folder",
                      Page.section == section, Page.title == TABLE_FOLDER_TITLE)
              .order_by(Page.id).first())
    if folder is None:
        folder = Page(workspace_id=workspace_id, kind="folder", title=TABLE_FOLDER_TITLE,
                      icon="Grid3x3", section=section, visibility="internal", status="draft",
                      owner_role="us", position=_next_position(ctx, workspace_id, section, None),
                      created_by=ctx.user.id)
        ctx.db.add(folder)
        ctx.db.flush()
    page = Page(workspace_id=workspace_id, parent_id=folder.id, kind="page",
                title=(body.title or "Untitled table").strip()[:512] or "Untitled table",
                icon="Grid3x3", section=section, visibility="internal", status="draft",
                owner_role="us", position=_next_position(ctx, workspace_id, section, folder.id),
                created_by=ctx.user.id)
    ctx.db.add(page)
    ctx.db.flush()
    ctx.db.add(Block(page_id=page.id, position=1, type="table",
                     content={"columns": ["Column 1", "Column 2", "Column 3"], "rows": []}))
    ctx.db.commit()
    return {"page_id": page.id, "title": page.title}


# ---------------------------------------------------------------- onboarding form
@router.get("/onboarding-form")
def onboarding_form(workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    """Send the form to this client, and read their answers. Nothing more —
    building forms is org-level work and lives under SYSTEM.

    Internal, like an internal page inside Docs: this is the operator's side of
    the Setup group. A client never sees these items in their sidebar and cannot
    reach this endpoint by typing the URL either. Their side of the same form is
    `/onboarding-form/fill` below."""
    _internal(ctx)
    resolved = _one_workspace(ctx, workspace_id)
    if resolved is None:
        return {"workspace": None, "forms": [], "invites": [],
                "can_send": not ctx.preview_as_client}
    forms = (ctx.db.query(Form)
             .filter(Form.org_id == ctx.org_id, Form.status == "published")
             .order_by(Form.updated_at.desc(), Form.id.desc()).all())
    counts = dict(ctx.db.query(FormQuestion.form_id, func.count(FormQuestion.id))
                  .filter(FormQuestion.form_id.in_([f.id for f in forms]))
                  .group_by(FormQuestion.form_id).all()) if forms else {}
    invite_q = (ctx.db.query(FormInvite).filter(FormInvite.workspace_id == resolved)
                .order_by(FormInvite.id.desc()))
    names = {f.id: f.name for f in forms}
    invites = []
    for invite in invite_q.all():
        response = (ctx.db.query(FormResponse).filter(FormResponse.invite_id == invite.id)
                    .order_by(FormResponse.id.desc()).first())
        answered = (ctx.db.query(func.count(FormAnswer.id))
                    .filter(FormAnswer.response_id == response.id).scalar() or 0) if response else 0
        invites.append({
            "id": invite.id, "form_id": invite.form_id,
            "form_name": names.get(invite.form_id, "Onboarding form"),
            "recipient_email": invite.recipient_email,
            "recipient_name": invite.recipient_name or "",
            "status": ("submitted" if response and response.submitted_at
                       else "opened" if invite.opened_at else invite.status),
            "sent_at": _iso(invite.sent_at), "opened_at": _iso(invite.opened_at),
            "submitted_at": _iso(response.submitted_at) if response else None,
            "expires_at": _iso(invite.expires_at), "answered": answered,
            "response_id": response.id if response else None,
        })
    return {
        "workspace": {"id": resolved},
        "forms": [{"id": f.id, "name": f.name, "status": f.status,
                   "question_count": counts.get(f.id, 0)} for f in forms],
        "invites": invites,
        "can_send": not ctx.preview_as_client,
    }


# ------------------------------------------------- the client's side of the form
#
# The same form the emailed token opens, resolved from the session instead.
#
# It exists because we send the invite days before the client has an account. By
# the time they do, the link is buried in their inbox — so the half-finished form
# has to be waiting in their dashboard as an open task. Both routes resolve a
# `FormInvite` and hand it to the one fill pipeline, so continuing here picks up
# the same response the token started rather than opening a second one.
def _my_invite(ctx: AuthContext) -> FormInvite:
    """The invite addressed to whoever is signed in.

    Matched on the recipient address, scoped to workspaces this account can
    already reach. Expiry is deliberately not applied: expiry protects the
    token, and this request is not carrying one — locking someone out of a task
    on their own dashboard would punish them for a credential they no longer
    need.
    """
    email = (ctx.user.email or "").strip().lower()
    allowed = ctx.allowed_workspace_ids()
    invite = None
    if email and allowed:
        invite = (ctx.db.query(FormInvite)
                  .filter(FormInvite.workspace_id.in_(allowed),
                          func.lower(FormInvite.recipient_email) == email)
                  .order_by(FormInvite.id.desc()).first())
    if invite is None:
        raise HTTPException(404, "There is no onboarding form waiting for you.")
    return invite


@router.get("/onboarding-form/fill")
def fill_load(ctx: AuthContext = Depends(get_ctx)):
    try:
        return forms_fill.load(ctx.db, _my_invite(ctx))
    except forms_fill.InvalidLink:
        raise HTTPException(404, "There is no onboarding form waiting for you.")


@router.post("/onboarding-form/fill/save")
def fill_save(body: forms_fill.FillPayload, ctx: AuthContext = Depends(get_ctx)):
    _operator_may_not_answer(ctx)
    return forms_fill.save(ctx.db, _my_invite(ctx), body)


@router.post("/onboarding-form/fill/submit")
def fill_submit(body: forms_fill.FillPayload, ctx: AuthContext = Depends(get_ctx)):
    _operator_may_not_answer(ctx)
    return forms_fill.submit(ctx.db, _my_invite(ctx), body)


@router.post("/onboarding-form/fill/upload")
async def fill_upload(question_id: int = FastForm(...), file: UploadFile = File(...),
                      ctx: AuthContext = Depends(get_ctx)):
    _operator_may_not_answer(ctx)
    return await forms_fill.store_upload(ctx.db, _my_invite(ctx), question_id, file)


# ---------------------------------------------------------------- sharing & access
@router.get("/sharing")
def sharing(workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    """Who can open this workspace, and what of it is shared."""
    resolved = _one_workspace(ctx, workspace_id)
    if resolved is None:
        return {"workspace": None, "people": [], "team_count": 0, "pages": [], "shared": {},
                "hidden_from_client": None, "can_manage": not ctx.sees_as_client}
    memberships = ctx.db.query(Membership).filter(Membership.org_id == ctx.org_id).all()
    reachable = [m for m in memberships
                 if m.role in MASTER_ROLES or resolved in (m.workspace_ids or [])]
    users = {u.id: u for u in ctx.db.query(User)
             .filter(User.id.in_([m.user_id for m in reachable]), User.active.is_(True)).all()}
    people, team_count = [], 0
    for m in reachable:
        user = users.get(m.user_id)
        if user is None:
            continue
        if m.role != "client" and ctx.sees_as_client:
            team_count += 1
            continue
        people.append({"id": user.id, "name": user.name or "", "email": user.email,
                       "role": m.role, "last_login_at": _iso(user.last_login_at)})
    people.sort(key=lambda p: (p["role"] != "client", p["name"] or p["email"]))
    pages = (_pages(ctx, resolved).filter(Page.archived_at.is_(None))
             .order_by(Page.section, Page.position, Page.id).all())
    return {
        "workspace": {"id": resolved},
        "people": people,
        "team_count": team_count,
        "pages": [{"id": p.id, "title": p.title or "Untitled", "section": p.section,
                   "kind": p.kind or "page", "visibility": p.visibility, "status": p.status,
                   "updated_at": _iso(p.updated_at)} for p in pages],
        "shared": _shared_counts(ctx, resolved),
        "hidden_from_client": _hidden_from_client(ctx, resolved),
        "can_manage": not ctx.sees_as_client,
    }
