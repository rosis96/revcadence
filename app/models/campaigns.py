"""Live campaign snapshots — what the sending platform says is actually going out.

The client-facing sequence view is deliberately NOT rendered from our own
`email_sequences` tables. Instantly/Bison is what actually sends, so it is the
only honest answer to "what will this prospect receive". A step added directly
in Instantly, a variant paused there, a delay edited there — none of that reaches
our tables, and a client looking at a page that disagrees with their inbox has
been told something false.

So we mirror instead of assert: fetch the campaign from the platform, normalize
it, store it here, render it read-only. `payload` holds the normalized shape from
`app/reply/campaigns.py` (never the raw vendor JSON — that lives in `raw` for
debugging and is not what the UI reads).

One row per (reply workspace, external campaign). Refreshed on a worker tick and
on demand; a stale row still renders, with its age shown, because a third-party
outage should degrade the page's freshness and nothing else.
"""
from datetime import datetime

from sqlalchemy import (Column, DateTime, ForeignKey, Integer, JSON, String,
                        Text, UniqueConstraint)

from ..db import Base


class CampaignSnapshot(Base):
    __tablename__ = "campaign_snapshots"
    __table_args__ = (UniqueConstraint("reply_workspace_id", "external_id",
                                       name="uq_campaign_snapshot_external"),)

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    reply_workspace_id = Column(Integer, ForeignKey("reply_workspaces.id"), nullable=False, index=True)

    platform = Column(String(20), default="")        # instantly | bison
    external_id = Column(String(255), default="", index=True)
    name = Column(String(500), default="")
    status = Column(String(40), default="")          # normalized: live | paused | draft | completed

    payload = Column(JSON, default=dict)             # normalized {steps:[...], stats:{...}}
    raw = Column(JSON, default=dict)                 # vendor response, for diagnosing a bad mapping

    fetch_status = Column(String(20), default="ok")  # ok | error
    fetch_error = Column(Text, default="")
    fetched_at = Column(DateTime)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
