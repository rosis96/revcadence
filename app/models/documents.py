"""Documents: blueprints, agreements, proposals — the portals data model,
unified. Content/PDFs reference object storage; signing state and view tracking
live here so proposals get open/read analytics (design doc, Stage 9)."""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text

from ..db import Base

DOCUMENT_KINDS = ("blueprint", "agreement", "proposal", "other")
DOCUMENT_STATUSES = ("draft", "published", "viewed", "client_signed", "executed", "archived")


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), index=True)
    deal_id = Column(Integer, ForeignKey("deals.id"), index=True)

    kind = Column(String(30), nullable=False, default="other")       # DOCUMENT_KINDS
    status = Column(String(30), nullable=False, default="draft")     # DOCUMENT_STATUSES
    title = Column(String(512), default="")
    slug = Column(String(255), default="", index=True)               # public URL slug
    published = Column(Boolean, default=False)

    html = Column(Text, default="")            # rendered content (bespoke pages)
    template = Column(String(255), default="") # template name used, if any
    fields = Column(JSON, default=dict)        # {{placeholder}} values
    storage_key = Column(Text, default="")     # object-storage key for PDFs

    # Signing state (mirrors the portals flow)
    client_signed_at = Column(DateTime)
    countersigned_at = Column(DateTime)
    executed_at = Column(DateTime)
    locked = Column(Boolean, default=False)

    # View tracking (Stage 9: open/read analytics)
    first_viewed_at = Column(DateTime)
    last_viewed_at = Column(DateTime)
    view_count = Column(Integer, default=0)

    # Legacy linkage: portals client slug for migration
    legacy_slug = Column(String(255), default="", index=True)
    versions = Column(JSON, default=list)      # snapshot history

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
