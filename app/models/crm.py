"""The unified object model. Every record carries workspace_id — that is the
isolation boundary. Activity is the universal timeline event (the spine)."""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text

from ..db import Base


class WorkspaceScoped:
    """Mixin: every business object belongs to exactly one workspace."""
    @classmethod
    def __declare_last__(cls):
        pass


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    domain = Column(String(255), default="", index=True)
    website = Column(Text, default="")
    industry = Column(String(255), default="")
    linkedin_url = Column(Text, default="")
    location = Column(String(255), default="")
    employee_count = Column(Integer)
    revenue_range = Column(String(120), default="")
    # Enrichment output lands here with provenance: {field: {value, source, at}}
    enrichment = Column(JSON, default=dict)
    icp_fit = Column(String(40), default="")       # e.g. strict / loose / no
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), index=True)
    email = Column(String(255), default="", index=True)
    first_name = Column(String(255), default="")
    last_name = Column(String(255), default="")
    title = Column(String(255), default="")
    linkedin_url = Column(Text, default="")
    location = Column(String(255), default="")
    timezone = Column(String(64), default="")
    buying_role = Column(String(60), default="")    # champion / decision maker / ...
    email_status = Column(String(30), default="")   # valid / risky / invalid (Reoon)
    enrichment = Column(JSON, default=dict)
    revenue_score = Column(Float)                   # AI Revenue Score (0-100)
    # Legacy linkage for migration/dedup
    legacy_lead_ids = Column(JSON, default=list)    # old reply-manager leads.id values
    source = Column(String(120), default="")        # cold_email / import / form / manual
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Stage(Base):
    __tablename__ = "stages"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    name = Column(String(80), nullable=False)
    color = Column(String(20), default="#64748b")
    sort_order = Column(Integer, default=0)
    is_won = Column(Boolean, default=False)
    is_lost = Column(Boolean, default=False)
    # Phase 2: required actions / exit criteria live here
    exit_criteria = Column(JSON, default=list)


DEFAULT_STAGES = [
    ("Opportunity", "#64748b", 1, False, False),
    ("Meeting Booked", "#3b82f6", 2, False, False),
    ("Meeting Completed", "#8b5cf6", 3, False, False),
    ("No Show", "#f59e0b", 4, False, False),
    ("Follow-up", "#f97316", 5, False, False),
    ("Won", "#22c55e", 6, True, False),
    ("Lost", "#ef4444", 7, False, True),
]


class Deal(Base):
    __tablename__ = "deals"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), index=True)
    stage_id = Column(Integer, ForeignKey("stages.id"), index=True)
    name = Column(String(255), default="")
    value = Column(Float, default=0.0)
    owner_user_id = Column(Integer, ForeignKey("users.id"))
    status_label = Column(String(120), default="")
    source = Column(String(120), default="")
    lead_intent = Column(String(120), default="")
    next_step = Column(Text, default="")
    next_action_date = Column(String(40), default="")
    close_date = Column(String(40), default="")
    meeting_outcome = Column(String(60), default="")
    tags = Column(JSON, default=list)
    description = Column(Text, default="")
    legacy_opportunity_id = Column(Integer, index=True)  # old crm opportunities.id
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    stage_changed_at = Column(DateTime, default=datetime.utcnow)


class Activity(Base):
    """Universal timeline event. Everything that happens to a record is one of
    these; record pages render the merged stream."""
    __tablename__ = "activities"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    # Polymorphic link: exactly one of these is normally set (deal activities
    # may also set contact_id so both timelines show them).
    company_id = Column(Integer, ForeignKey("companies.id"), index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), index=True)
    deal_id = Column(Integer, ForeignKey("deals.id"), index=True)
    kind = Column(String(60), nullable=False, index=True)
    # kinds: email_in, email_out, reply_drafted, stage_change, note, task_done,
    #        meeting_booked, meeting_held, doc_viewed, doc_signed, enriched, import
    title = Column(String(512), default="")
    body = Column(Text, default="")
    data = Column(JSON, default=dict)      # structured payload (thread msg, old ids, ...)
    actor_user_id = Column(Integer, ForeignKey("users.id"))  # null = system/AI
    occurred_at = Column(DateTime, default=datetime.utcnow, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    deal_id = Column(Integer, ForeignKey("deals.id"), index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), index=True)
    title = Column(String(512), nullable=False)
    done = Column(Boolean, default=False)
    due_at = Column(DateTime)
    assignee_user_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)


class Note(Base):
    __tablename__ = "notes"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    deal_id = Column(Integer, ForeignKey("deals.id"), index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), index=True)
    body = Column(Text, default="")
    author_user_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
