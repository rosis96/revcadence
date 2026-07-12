"""List-based enrichment (port of the Ascendly Enrichment Dashboard data model,
workspace_id replaces variable_set as the tenancy key).

Funnel statuses (terminal, drive counts + resume — DO NOT change semantics):
  invalid (free-rejected) · unsafe (Reoon-rejected) · skipped (Non-ICP or
  title-rejected) · error (no website) · done (enriched).
Anything else ("", pending, running) = not finished; the pipeline resumes it.
Completed work is never re-charged."""
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text

from ..db import Base

TERMINAL_STATUSES = ("invalid", "unsafe", "skipped", "error", "done")


class EnrichList(Base):
    __tablename__ = "enrich_lists"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class EnrichLead(Base):
    __tablename__ = "enrich_leads"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    list_id = Column(Integer, ForeignKey("enrich_lists.id"), nullable=False, index=True)
    first_name = Column(String(255), default="")
    last_name = Column(String(255), default="")
    title = Column(String(255), default="")
    company = Column(String(255), default="")
    website = Column(Text, default="")
    email = Column(String(255), default="", index=True)
    data = Column(JSON, default=dict)          # raw imported row
    result = Column(JSON, default=dict)        # {<vars>, ICP_reason, _title_gate, ...}

    # Two-column verification display (client sees who did what) — preserve.
    free_status = Column(String(40), default="")    # ok / role / no mx / disposable / bad syntax
    email_status = Column(String(40), default="")   # Reoon: safe / catch_all / unknown / invalid / skipped
    verify_source = Column(String(20), default="")  # free | reoon

    title_status = Column(String(20), default="")   # pass | rejected
    industry = Column(String(255), default="")
    icp_decision = Column(String(40), default="", index=True)  # ICP | Non-ICP | Needs Review
    icp_score = Column(Integer)
    icp_reason = Column(Text, default="")
    competitors = Column(JSON, default=list)

    status = Column(String(20), default="", index=True)  # funnel status (see module docstring)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EnrichConfig(Base):
    """Per-workspace enrichment configuration (the old Client Profile / ICP /
    Formats / Rules sections). One row per workspace."""
    __tablename__ = "enrich_configs"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), unique=True, nullable=False)
    profile = Column(JSON, default=dict)        # client profile (service brief, offer, ...)
    icp_definition = Column(Text, default="")   # single source of truth for fit decisions
    formats = Column(JSON, default=list)        # [{label,name,guidance,template,min_words,max_words,placeholders:[...]}]
    rules = Column(Text, default="")            # one correction rule per line, injected into the writer
    skip_title_gate = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
