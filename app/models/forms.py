"""Invite-only onboarding forms.

The editable ``FormSection``/``FormQuestion`` rows are the current draft.  Every
published revision is also frozen into ``FormVersion.schema`` so an invite can
keep rendering exactly what was sent even after the operator edits the form.

There is no template system, deliberately.  Duplicate does the same job for a
fraction of the machinery: build the form once for the first client, copy it and
tweak it for the next.  A template library would add a second kind of form, a
sync question ("the template changed — do these forms?"), and a place for one
client's questions to reach another's workspace.
"""
from datetime import datetime

from sqlalchemy import (JSON, Boolean, Column, DateTime, ForeignKey, Integer,
                        String, Text, UniqueConstraint)

from ..db import Base


FORM_STATUSES = ("draft", "published", "archived")
QUESTION_TYPES = (
    "short_text", "long_text", "single_choice", "multi_choice", "dropdown",
    "yes_no", "number", "date", "email", "url", "file_upload",
)
DISPLAY_MODES = ("ask", "confirm", "readonly")
PREFILL_SOURCES = (
    "invite.contact_name", "invite.contact_email", "invite.company_name",
    "invite.website_url", "crawl.positioning", "crawl.offers", "crawl.case_studies",
)
MAP_TARGETS = (
    "workspace.name", "client.website_url", "client.contact_name",
    "client.contact_email", "client.role", "client.timezone", "brain.offers",
    "brain.positioning", "icp.titles", "icp.geo", "icp.company_size",
    "icp.reject_signals", "library.do_not_contact", "library.case_study",
    "approval.copy_approver", "infra.booking_link", "infra.has_domains",
)


class Form(Base):
    """A form belongs to the organization, not to a client.

    The builder is our tool; a client is chosen when an invite is sent, not when
    the form is written.  ``duplicated_from_id`` is provenance only — the copy is
    independent from the moment it is made, and nothing propagates between them.
    """
    __tablename__ = "forms"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, default="")
    duplicated_from_id = Column(Integer, ForeignKey("forms.id"), index=True)
    version = Column(Integer, default=1, nullable=False)
    status = Column(String(20), default="draft", nullable=False, index=True)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FormSection(Base):
    __tablename__ = "form_sections"

    id = Column(Integer, primary_key=True)
    form_id = Column(Integer, ForeignKey("forms.id"), nullable=False, index=True)
    position = Column(Integer, default=0)
    title = Column(String(512), default="")
    description = Column(Text, default="")


class FormQuestion(Base):
    __tablename__ = "form_questions"

    id = Column(Integer, primary_key=True)
    form_id = Column(Integer, ForeignKey("forms.id"), nullable=False, index=True)
    section_id = Column(Integer, ForeignKey("form_sections.id"), index=True)
    position = Column(Integer, default=0)
    type = Column(String(30), nullable=False)
    label = Column(String(1000), default="")
    help_text = Column(Text, default="")
    required = Column(Boolean, default=False)
    options = Column(JSON, default=dict)
    maps_to = Column(String(80))
    prefill_source = Column(String(80))
    display_mode = Column(String(20), default="ask")
    created_at = Column(DateTime, default=datetime.utcnow)


class FormVersion(Base):
    """Immutable public-render snapshot for one published form version."""
    __tablename__ = "form_versions"
    __table_args__ = (UniqueConstraint("form_id", "version", name="uq_form_version"),)

    id = Column(Integer, primary_key=True)
    form_id = Column(Integer, ForeignKey("forms.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    schema = Column(JSON, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)


class FormInvite(Base):
    __tablename__ = "form_invites"

    id = Column(Integer, primary_key=True)
    form_id = Column(Integer, ForeignKey("forms.id"), nullable=False, index=True)
    form_version = Column(Integer, nullable=False, default=1)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    recipient_email = Column(String(255), nullable=False, index=True)
    recipient_name = Column(String(255), default="")
    known_context = Column(JSON, default=dict)
    token = Column(String(128), unique=True, nullable=False, index=True)
    status = Column(String(20), default="sent", nullable=False, index=True)
    sent_at = Column(DateTime)
    opened_at = Column(DateTime)
    submitted_at = Column(DateTime)
    expires_at = Column(DateTime, nullable=False, index=True)
    reminder_count = Column(Integer, default=0)


class FormResponse(Base):
    __tablename__ = "form_responses"

    id = Column(Integer, primary_key=True)
    form_id = Column(Integer, ForeignKey("forms.id"), nullable=False, index=True)
    form_version = Column(Integer, nullable=False)
    invite_id = Column(Integer, ForeignKey("form_invites.id"), nullable=False, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    response_version = Column(Integer, default=1, nullable=False)
    supersedes_id = Column(Integer, ForeignKey("form_responses.id"), index=True)
    contact_details = Column(JSON, default=dict)
    status = Column(String(20), default="partial", nullable=False, index=True)
    submitted_at = Column(DateTime)
    ip_hash = Column(String(64), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FormAnswer(Base):
    __tablename__ = "form_answers"
    __table_args__ = (UniqueConstraint("response_id", "question_id", name="uq_form_answer"),)

    id = Column(Integer, primary_key=True)
    response_id = Column(Integer, ForeignKey("form_responses.id"), nullable=False, index=True)
    question_id = Column(Integer, nullable=False, index=True)
    value = Column(JSON)
    source = Column(String(40), default="client_supplied", nullable=False)
    prefill_value = Column(JSON)
    was_edited = Column(Boolean, default=False)


class FormUpload(Base):
    """Private upload metadata. ``storage_key`` is generated server-side."""
    __tablename__ = "form_uploads"

    id = Column(Integer, primary_key=True)
    invite_id = Column(Integer, ForeignKey("form_invites.id"), nullable=False, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    question_id = Column(Integer, nullable=False, index=True)
    storage_key = Column(String(255), nullable=False, unique=True)
    original_name = Column(String(255), default="")
    extension = Column(String(12), nullable=False)
    content_type = Column(String(120), default="")
    size = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
