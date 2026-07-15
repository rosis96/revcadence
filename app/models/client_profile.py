"""Client Profile: the operational source of truth for delivery once a deal is
Closed Won. One per company. Structured, editable sections (NOT one JSON blob) —
each field carries value + provenance (source, when, who, client-visible?). The
raw onboarding submission is kept immutable; conflicting answers are flagged for
review rather than silently overwriting.
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String

from ..db import Base

SCOPE_TYPES = ("outbound", "inbound", "full")
ONBOARDING_STATUSES = ("not_started", "sent", "submitted", "in_review", "approved")


class ClientProfile(Base):
    __tablename__ = "client_profiles"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, unique=True, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), index=True)
    deal_id = Column(Integer, ForeignKey("deals.id"), index=True)
    blueprint_doc_id = Column(Integer, ForeignKey("documents.id"), index=True)
    agreement_doc_id = Column(Integer, ForeignKey("documents.id"), index=True)

    is_active_client = Column(Boolean, default=False, index=True)
    scope_type = Column(String(20), default="full")     # SCOPE_TYPES — drives onboarding form

    # Structured data: {section_key: {field_key: {value, source, at, by, visibility}}}
    data = Column(JSON, default=dict)

    # Scope-specific onboarding form spec + immutable raw submissions + review flags
    onboarding_form = Column(JSON, default=dict)         # {sections:[{key,label,fields:[...]}]}
    onboarding_submissions = Column(JSON, default=list)  # append-only raw submissions (immutable)
    onboarding_status = Column(String(20), default="not_started")
    onboarding_token = Column(String(64), default="", index=True)  # secure public form token
    review_flags = Column(JSON, default=list)            # [{field, existing, submitted, note, at}]
    completeness = Column(Integer, default=0)            # 0-100

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
