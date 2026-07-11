"""DB-backed job queue. Replaces in-memory BackgroundTasks sleeps: jobs survive
redeploys, are visible, and power future automations (nudges, enrichment runs,
proposal follow-ups)."""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text

from ..db import Base


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
    finished_at = Column(DateTime)
