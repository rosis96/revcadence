"""List-based enrichment (port of the Ascendly Enrichment Dashboard data model,
workspace_id replaces variable_set as the tenancy key).

Funnel statuses (terminal, drive counts + resume):
  invalid · unsafe · skipped · error · insufficient · generation_failed ·
  needs_review · done. Failed/held research is terminal to prevent an unattended
  rerun from spending repeatedly; Clear results explicitly reopens it.
Anything else ("", pending, running) = not finished; the pipeline resumes it.
Completed work is never re-charged."""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text

from ..db import Base

TERMINAL_STATUSES = (
    "invalid", "unsafe", "skipped", "error", "insufficient",
    "generation_failed", "needs_review", "done",
)


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
    esp = Column(String(20), default="")            # Microsoft | Google | Other (MX-based)
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
    skip_icp = Column(Integer, default=0)       # 1: don't reject Non-ICP — enrich all verified leads
    only_safe = Column(Integer, default=1)      # 1: catch_all/unknown stop as unsafe (default on)
    reoon_api_key_enc = Column(Text, default="")  # per-workspace Reoon key (encrypted); env fallback
    reading_level = Column(String(40), default="b2 business")  # default: clear natural B2 business English
    writer_model = Column(String(60), default="")    # override the OpenAI writer model (else env default)
    research_depth = Column(String(20), default="standard")  # standard | deep (crawl pages + content budget)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WorkspaceTrainingRevision(Base):
    """Immutable, sanitized workspace-training snapshot used for audit/rollback.

    Snapshots contain enrichment configuration and golden evaluation cases only.
    They never contain leads, mailbox data, credentials, or encrypted API keys.
    """
    __tablename__ = "workspace_training_revisions"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    action = Column(String(30), default="apply")
    note = Column(String(500), default="")
    revision_hash = Column(String(64), nullable=False, index=True)
    snapshot = Column(JSON, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class WorkspaceEvaluationCase(Base):
    """A sanitized golden case for repeatable writer evaluation."""
    __tablename__ = "workspace_evaluation_cases"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    company = Column(String(255), default="")
    website = Column(Text, default="")
    facts = Column(JSON, default=dict)
    expected_outputs = Column(JSON, default=dict)
    notes = Column(Text, default="")
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
