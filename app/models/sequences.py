"""Workspace email sequences, their immutable approvals, and reusable templates.

Copy stays as plain text.  Enrichment placeholders are references to
``EnrichConfig.formats``; their definitions are never copied into these rows.
"""
from datetime import datetime

from sqlalchemy import (JSON, Boolean, Column, DateTime, ForeignKey, Integer,
                        String, Text, UniqueConstraint)

from ..db import Base


SEQUENCE_STATUSES = ("draft", "in_review", "changes_requested", "approved", "archived")
VARIANT_LABELS = tuple("ABCDEFG")


class EmailAngle(Base):
    __tablename__ = "email_angles"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    hypothesis = Column(Text, default="")
    proof_key = Column(String(160), default="")
    proof_label = Column(String(500), default="")
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EmailSequence(Base):
    __tablename__ = "email_sequences"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    angle_id = Column(Integer, ForeignKey("email_angles.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, default="")
    status = Column(String(30), nullable=False, default="draft", index=True)
    version = Column(Integer, nullable=False, default=1)
    current_list_id = Column(Integer, ForeignKey("enrich_lists.id"), index=True)
    template_source_id = Column(Integer, ForeignKey("email_sequence_templates.id"), index=True)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EmailSequenceStep(Base):
    __tablename__ = "email_sequence_steps"

    id = Column(Integer, primary_key=True)
    sequence_id = Column(Integer, ForeignKey("email_sequences.id"), nullable=False, index=True)
    position = Column(Integer, nullable=False, default=0)
    name = Column(String(255), nullable=False)
    purpose = Column(String(40), default="opener")
    wait_days = Column(Integer, nullable=False, default=0)
    rotation_cursor = Column(Integer, nullable=False, default=0)
    archived_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EmailSequenceVariant(Base):
    __tablename__ = "email_sequence_variants"
    __table_args__ = (UniqueConstraint("step_id", "label", name="uq_email_step_variant_label"),)

    id = Column(Integer, primary_key=True)
    step_id = Column(Integer, ForeignKey("email_sequence_steps.id"), nullable=False, index=True)
    label = Column(String(1), nullable=False)
    subject = Column(Text, default="")
    body = Column(Text, default="")
    change_note = Column(String(500), default="")
    enabled = Column(Boolean, default=False, nullable=False, index=True)
    promoted = Column(Boolean, default=False, nullable=False)
    quality = Column(JSON, default=dict)
    revision = Column(Integer, default=1, nullable=False)
    sent_count = Column(Integer, default=0, nullable=False)
    reply_count = Column(Integer, default=0, nullable=False)
    positive_count = Column(Integer, default=0, nullable=False)
    meeting_count = Column(Integer, default=0, nullable=False)
    archived_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EmailSequenceApproval(Base):
    __tablename__ = "email_sequence_approvals"

    id = Column(Integer, primary_key=True)
    sequence_id = Column(Integer, ForeignKey("email_sequences.id"), nullable=False, index=True)
    sequence_version = Column(Integer, nullable=False)
    status = Column(String(30), nullable=False, default="pending", index=True)
    snapshot = Column(JSON, nullable=False)
    note = Column(Text, default="")
    requested_by = Column(Integer, ForeignKey("users.id"))
    requested_at = Column(DateTime, default=datetime.utcnow)
    decided_by = Column(Integer, ForeignKey("users.id"))
    decided_at = Column(DateTime)


class EmailSequenceTemplate(Base):
    __tablename__ = "email_sequence_templates"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, default="")
    structure = Column(JSON, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"))
    archived_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

