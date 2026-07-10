"""Org-wide audit log: who did what, where. Generalizes the audit-trail pattern
already used in the client portals."""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String

from ..db import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    action = Column(String(120), nullable=False)   # login, create_deal, move_stage, ...
    object_type = Column(String(60), default="")
    object_id = Column(Integer)
    data = Column(JSON, default=dict)
    at = Column(DateTime, default=datetime.utcnow, index=True)
