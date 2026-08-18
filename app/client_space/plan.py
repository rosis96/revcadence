"""The launch plan, derived.

Timeline, List and Board are three arrangements of one answer, and the Overview's
stage rail is a fourth. Computing that answer in three components would give you
three subtly different plans — a task the board calls blocked that the Gantt
draws in blue. So it is computed once, here, and every surface renders what it
returns.

What gets derived rather than stored:

- **overdue** — `due_at` is in the past and the task is not done.
- **blocked** — something it depends on is unfinished, or an operator wrote down
  a reason. A task unblocks itself the moment its blocker is ticked.
- **blocks** — the inverse edge, which is what the List's Blocks column shows.
- **critical path** — the longest dependency chain reaching the final milestone.
  Move anything on it and the launch date moves; move anything off it and the
  launch date does not. That is the whole reason the plan has dependencies.
"""
from datetime import date, datetime, timedelta

from ..models.client_space import (DONE, LAUNCH_PHASES, OWNER_LABELS, STAGE_INDEX, STAGE_LABELS,
                                   STAGE_SHORT, STATUS_LABELS, TASK_OWNERS, TASK_STATUSES)


def _iso(value):
    return value.isoformat() if value else None


def _day(value):
    return value.date() if isinstance(value, datetime) else value


def _duration_days(task) -> int:
    """A milestone is a moment, so it costs nothing. Everything else spans at
    least a day — a zero-length bar is invisible, and an invisible bar reads as
    a missing task rather than a short one."""
    if task.is_milestone:
        return 0
    if task.start_at and task.due_at:
        return max(1, (_day(task.due_at) - _day(task.start_at)).days)
    return 1


# ---------------------------------------------------------------- graph
def _edges(tasks: list) -> tuple[dict, dict]:
    """(depends_on, blocks) as id → [id], with dangling ids dropped.

    A dependency on a deleted task is not an error worth refusing the whole
    screen over; it is an edge that no longer exists.
    """
    ids = {t.id for t in tasks}
    depends, blocks = {}, {t.id: [] for t in tasks}
    for t in tasks:
        deps = [int(d) for d in (t.depends_on or []) if int(d) in ids and int(d) != t.id]
        depends[t.id] = deps
        for d in deps:
            blocks[d].append(t.id)
    return depends, blocks


def _topological(ids: list, depends: dict) -> list | None:
    """Kahn's algorithm. Returns None on a cycle rather than raising — a cycle is
    a plan somebody mis-linked, and the right response is to draw the plan
    without a critical path, not to refuse to draw the plan."""
    indegree = {i: len(depends.get(i, [])) for i in ids}
    ready = [i for i in ids if indegree[i] == 0]
    order = []
    while ready:
        node = ready.pop()
        order.append(node)
        for other in ids:
            if node in depends.get(other, []):
                indegree[other] -= 1
                if indegree[other] == 0:
                    ready.append(other)
    return order if len(order) == len(ids) else None


def critical_path(tasks: list) -> list:
    """The longest chain of dependencies, in days, ending at the last thing that
    happens. Ids in order; empty when the plan has no dependencies to chain."""
    if not tasks:
        return []
    by_id = {t.id: t for t in tasks}
    depends, _ = _edges(tasks)
    order = _topological(list(by_id), depends)
    if order is None:
        return []                      # mis-linked plan: draw it, just not this
    longest, previous = {}, {}
    for node in order:
        best, best_from = 0, None
        for dep in depends.get(node, []):
            if longest.get(dep, 0) > best:
                best, best_from = longest[dep], dep
        longest[node] = best + max(1, _duration_days(by_id[node]))
        previous[node] = best_from
    # End at the final milestone if the plan has one — that is the launch, and a
    # path to anything else is not the path anybody means.
    finals = [t.id for t in tasks if t.is_milestone] or list(by_id)
    end = max(finals, key=lambda i: (longest.get(i, 0), _day(by_id[i].due_at) or date.min))
    chain, node = [], end
    while node is not None:
        chain.append(node)
        node = previous.get(node)
    return list(reversed(chain))


# ---------------------------------------------------------------- serialize
def task_out(task, *, depends: dict, blocks: dict, by_id: dict, critical: set,
             today: date, client_label: str) -> dict:
    deps = depends.get(task.id, [])
    open_blockers = [by_id[d] for d in deps if by_id[d].status != DONE]
    overdue_days = 0
    if task.due_at and task.status != DONE:
        overdue_days = max(0, (today - _day(task.due_at)).days)
    return {
        "id": task.id,
        "stage": task.stage,
        "phase_label": STAGE_LABELS.get(task.stage, task.stage),
        "phase_short": STAGE_SHORT.get(task.stage, task.stage),
        "phase_index": STAGE_INDEX.get(task.stage, 99),
        "title": task.title,
        "detail": task.detail or "",
        "owner": task.owner,
        "owner_label": client_label if task.owner == "client" else OWNER_LABELS.get(task.owner, task.owner),
        "status": task.status,
        "status_label": STATUS_LABELS.get(task.status, task.status),
        "start_at": _iso(task.start_at),
        "due_at": _iso(task.due_at),
        "duration_days": _duration_days(task),
        "is_milestone": bool(task.is_milestone),
        "position": task.position or 0,
        "completed_at": _iso(task.completed_at),
        "depends_on": deps,
        "blocked_note": task.blocked_note or "",
        # Derived — see the module note. None of these are stored.
        "overdue": overdue_days > 0,
        "overdue_days": overdue_days,
        "blocked": bool(task.blocked_note) or bool(open_blockers),
        "blocked_by": [{"id": b.id, "title": b.title, "owner": b.owner} for b in open_blockers],
        "blocks": sorted({STAGE_SHORT.get(by_id[b].stage, by_id[b].stage)
                          for b in blocks.get(task.id, [])}),
        "blocks_tasks": blocks.get(task.id, []),
        "critical": task.id in critical,
        "baseline_start_at": _iso(task.baseline_start_at),
        "baseline_due_at": _iso(task.baseline_due_at),
        "slipped_days": (
            (_day(task.due_at) - _day(task.baseline_due_at)).days
            if task.due_at and task.baseline_due_at else 0
        ),
    }


def _date_range(rows: list) -> dict:
    """The window the Timeline draws. Padded by a day at each end so the first
    bar does not start flush against the axis.

    An undated plan still gets a real window rather than an empty one. Returning
    no days collapsed the whole grid — the Timeline drew task names against a
    blank rectangle, which reads as "broken" when the truth is "these tasks have
    no dates yet".
    """
    stamps = [d for r in rows for d in (r["start_at"], r["due_at"]) if d]
    if not stamps:
        start = date.today() - timedelta(days=1)
        end = start + timedelta(days=21)
        return {"start": start.isoformat(), "end": end.isoformat(),
                "days": [(start + timedelta(days=i)).isoformat()
                         for i in range((end - start).days + 1)]}
    start = min(date.fromisoformat(s[:10]) for s in stamps) - timedelta(days=1)
    end = max(date.fromisoformat(s[:10]) for s in stamps) + timedelta(days=1)
    # A plan spanning years would render a column per day and melt the browser.
    end = min(end, start + timedelta(days=180))
    return {
        "start": start.isoformat(), "end": end.isoformat(),
        "days": [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)],
    }


def schedule_missing(tasks: list, kickoff: datetime, *, default_days: int = 2) -> int:
    """Give dates to tasks that have none, and return how many were changed.

    Needed because a plan can predate the schedule columns — the first version of
    the standard plan had owners and phases but no dates at all, and those tasks
    are invisible on a Timeline. Rather than making the operator type twenty
    dates, this lays them out the way the plan already implies:

    - a task starts after everything it depends on has finished, and
    - no earlier than its phase's turn, so an unlinked task still lands in
      roughly the right week instead of all of them stacking on day one.

    Tasks that already carry dates are left exactly as they are. Rescheduling
    somebody's hand-set dates would be a worse bug than the one being fixed.
    """
    by_id = {t.id: t for t in tasks}
    depends, _ = _edges(tasks)
    order = _topological(list(by_id), depends) or [t.id for t in tasks]
    rank = {tid: i for i, tid in enumerate(order)}
    changed = 0
    for task in sorted(tasks, key=lambda t: rank.get(t.id, 0)):
        if task.start_at and task.due_at:
            continue
        phase_turn = kickoff + timedelta(days=STAGE_INDEX.get(task.stage, 0) * 3)
        earliest = phase_turn
        for dep_id in depends.get(task.id, []):
            dep = by_id[dep_id]
            if dep.due_at and dep.due_at > earliest:
                earliest = dep.due_at
        task.start_at = task.start_at or earliest
        span = 0 if task.is_milestone else default_days
        task.due_at = task.due_at or (task.start_at + timedelta(days=span))
        changed += 1
    return changed


def build(tasks: list, *, launch=None, client_label: str = "Client",
          today: date | None = None) -> dict:
    """Everything all four surfaces need, computed once."""
    today = today or datetime.utcnow().date()
    tasks = sorted(tasks, key=lambda t: (STAGE_INDEX.get(t.stage, 99), t.position or 0, t.id))
    by_id = {t.id: t for t in tasks}
    depends, blocks = _edges(tasks)
    critical = set(critical_path(tasks))
    rows = [task_out(t, depends=depends, blocks=blocks, by_id=by_id, critical=critical,
                     today=today, client_label=client_label) for t in tasks]

    week_end = today + timedelta(days=7)
    def _due_within(r):
        return r["due_at"] and today <= date.fromisoformat(r["due_at"][:10]) <= week_end

    phases = []
    for index, (key, label, short) in enumerate(LAUNCH_PHASES):
        in_phase = [r for r in rows if r["stage"] == key]
        if not in_phase and launch is None:
            continue
        phases.append({
            "key": key, "label": label, "short": short, "index": index,
            "total": len(in_phase),
            "done": sum(1 for r in in_phase if r["status"] == DONE),
            "task_ids": [r["id"] for r in in_phase],
        })

    open_rows = [r for r in rows if r["status"] != DONE]
    return {
        "tasks": rows,
        # A task with no dates cannot be drawn on a time axis. Counting them lets
        # the Timeline say so and offer to fix it, instead of rendering a blank
        # grid and leaving the reader to guess.
        "undated": sum(1 for r in rows if not r["start_at"] or not r["due_at"]),
        "phases": phases,
        "range": _date_range(rows),
        "critical_path": [i for i in critical_path(tasks)],
        "lanes": [{"key": key, "label": STATUS_LABELS[key],
                   "count": sum(1 for r in rows if r["status"] == key)}
                  for key in TASK_STATUSES],
        "filters": {
            "all": len(rows),
            "waiting_client": sum(1 for r in open_rows if r["owner"] == "client"),
            "blocked": sum(1 for r in open_rows if r["blocked"]),
            "overdue": sum(1 for r in open_rows if r["overdue"]),
            "this_week": sum(1 for r in open_rows if _due_within(r)),
        },
        "owners": [{"key": k, "label": client_label if k == "client" else OWNER_LABELS[k]}
                   for k in TASK_OWNERS],
        "statuses": [{"key": k, "label": STATUS_LABELS[k]} for k in TASK_STATUSES],
        "counts": {
            "total": len(rows),
            "done": len(rows) - len(open_rows),
            "blocked": sum(1 for r in open_rows if r["blocked"]),
            "ours": sum(1 for r in open_rows if r["owner"] in ("us", "system")),
            "theirs": sum(1 for r in open_rows if r["owner"] == "client"),
        },
    }
