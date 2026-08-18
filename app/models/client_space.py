"""Client Space — the launch a client can see.

Two objects, and the smallness is deliberate:

- `ClientLaunch` is one row per workspace: which phase the launch is in, the date
  it is aimed at, and what it is called.
- `LaunchTask` is the work between today and that date.

Three properties of a task are NOT stored, because storing them means storing a
value that goes stale the moment something else changes:

- **overdue** is `due_at < today and not done`.
- **blocked** is "something this depends on is not finished yet" (or an operator
  wrote down why). Deriving it from the dependency graph means a task unblocks
  itself the moment its blocker is ticked off — nobody has to remember to.
- **critical path** is computed over that same graph. See client_space/plan.py.

Which is why `depends_on` is the load-bearing column here. It is what lets the
Overview say "blocked on the client", the List fill its Blocks column, and the
Timeline draw an arrow and a red bar — three features, one edge list.
"""
from datetime import datetime

from sqlalchemy import (Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text,
                        UniqueConstraint)

from ..db import Base

# The launch, start to first send. (key, full label, short label) — the short one
# is for dense surfaces like board cards, where "ICP & Targeting" is noise and
# "Targeting" is the same word doing the same job. Order is progress order: the
# Overview reads position in this tuple, and the Timeline numbers its phases by it.
LAUNCH_PHASES = (
    ("intake", "Kickoff & Intake", "Intake"),
    ("brain", "Client Brain", "Brain"),
    ("icp", "ICP & Targeting", "Targeting"),
    ("infrastructure", "Infrastructure", "Infrastructure"),
    ("copy", "Angles & Copy", "Copy"),
    ("list_build", "List Build", "List Build"),
    ("live", "Live Ops", "Live Ops"),
)
STAGE_KEYS = tuple(key for key, _, _ in LAUNCH_PHASES)
STAGE_LABELS = {key: label for key, label, _ in LAUNCH_PHASES}
STAGE_SHORT = {key: short for key, _, short in LAUNCH_PHASES}
STAGE_INDEX = {key: i for i, key in enumerate(STAGE_KEYS)}

# Who has to move. `both` is a real answer for work done together in a call, not
# a hedge — but it is the rarest, and a plan full of `both` is a plan nobody owns.
# `system` is work the engine does unattended: crawls, research runs, warm-up.
TASK_OWNERS = ("us", "client", "system", "both")
OWNER_LABELS = {"us": "RevCadence", "client": "Client", "system": "System", "both": "Both"}

# The board's lanes, in order. `blocked` is absent on purpose — see the module
# note: it is derived, so a lane for it would be a lane nothing can be dragged
# into. A blocked task sits in the lane describing what it is *waiting to do*.
TASK_STATUSES = ("backlog", "waiting_client", "in_progress", "review", "done")
STATUS_LABELS = {
    "backlog": "Backlog", "waiting_client": "Waiting on client",
    "in_progress": "In progress", "review": "Review", "done": "Done",
}
DONE = "done"


class ClientLaunch(Base):
    """One per workspace, created on first write. Absent means "not started",
    which the Overview renders as an empty state rather than as phase zero."""

    __tablename__ = "client_launches"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    name = Column(String(255), default="Outbound Launch Plan")
    stage = Column(String(30), nullable=False, default="intake")   # one of STAGE_KEYS
    kickoff_at = Column(DateTime)
    first_send_at = Column(DateTime)
    note = Column(Text, default="")
    # How many researched prospects this launch is aiming for. Without it the
    # Overview can say "1,284 researched" but not whether that is nearly done or
    # barely started, which is the only version of that number worth showing.
    prospect_target = Column(Integer, default=0)
    # Set when the plan is first agreed. "Baseline vs actual" compares today's
    # dates against these, which is the only honest way to answer "are we late,
    # or did we always intend it this way".
    baseline_at = Column(DateTime)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("workspace_id", name="uq_client_launch_workspace"),)


class LaunchTask(Base):
    __tablename__ = "launch_tasks"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    stage = Column(String(30), nullable=False, default="intake")   # one of STAGE_KEYS
    title = Column(String(512), nullable=False)
    detail = Column(Text, default="")
    owner = Column(String(20), nullable=False, default="us")       # one of TASK_OWNERS
    status = Column(String(20), nullable=False, default="backlog")  # one of TASK_STATUSES
    # An operator's reason this cannot move, when the reason is not a dependency
    # the system can see ("their legal is reviewing it"). Set = blocked.
    blocked_note = Column(Text, default="")
    start_at = Column(DateTime)
    due_at = Column(DateTime)
    # A milestone is a moment, not a span — the kickoff call, the approval, the
    # first send. It draws as a diamond and ignores its own duration.
    is_milestone = Column(Boolean, default=False, nullable=False, server_default="0")
    # Task ids this one waits for. The edge list behind blocked-ness, the Blocks
    # column, and the critical path.
    depends_on = Column(JSON, default=list)
    # What we agreed to at baseline, so slippage is visible rather than silently
    # absorbed by moving the dates.
    baseline_start_at = Column(DateTime)
    baseline_due_at = Column(DateTime)
    position = Column(Integer, default=0)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime)
