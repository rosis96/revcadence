"""DB-backed job queue. Replaces in-memory BackgroundTasks sleeps: jobs survive
redeploys, are visible, and power future automations (nudges, enrichment runs,
proposal follow-ups)."""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text

from ..db import Base


class Heartbeat(Base):
    """Worker liveness. The worker upserts its row every poll loop; /healthz
    reports the worker alive iff the beat is fresh. Turns 'jobs are stuck'
    mysteries into an immediate red flag."""
    __tablename__ = "heartbeats"

    name = Column(String(80), primary_key=True)      # e.g. "worker"
    at = Column(DateTime, default=datetime.utcnow)
    info = Column(JSON, default=dict)                # {db, handlers, pid, host}


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), index=True)
    kind = Column(String(120), nullable=False, index=True)   # registered handler name
    payload = Column(JSON, default=dict)
    status = Column(String(20), default="pending", index=True)  # pending/running/done/failed/cancelled
    run_at = Column(DateTime, default=datetime.utcnow, index=True)  # schedule for the future
    attempts = Column(Integer, default=0)
    max_attempts = Column(Integer, default=3)
    progress = Column(Integer, default=0)          # 0–100, updated live by handlers
    progress_note = Column(String(255), default="")  # e.g. "crawling site", "extracting facts"
    result = Column(JSON, default=dict)
    error = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime)
    # Bumped every time a handler reports progress. Lets the worker tell a live
    # run (progress advancing) from an orphaned "running" job (a worker died or
    # redeployed mid-run) so the latter can be requeued instead of spinning forever.
    progressed_at = Column(DateTime)
    finished_at = Column(DateTime)
