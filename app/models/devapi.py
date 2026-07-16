"""External API + CRM sync foundation: API keys (hashed), request logs,
idempotency, webhook subscriptions + deliveries, CRM sync connections + mappings.
All rows are workspace-scoped; nothing here ever stores a raw secret."""
from datetime import datetime

from sqlalchemy import (JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer,
                        String, Text, UniqueConstraint)

from ..db import Base

API_SCOPES = [
    "companies:read", "companies:write", "contacts:read", "contacts:write",
    "deals:read", "deals:write", "activities:read", "activities:write",
    "replies:read", "meetings:read", "blueprints:read", "agreements:read",
    "invoices:read", "webhooks:manage", "sync:manage",
]

WEBHOOK_EVENTS = [
    "company.created", "company.updated", "contact.created", "contact.updated",
    "reply.positive", "reply.needs_review", "meeting.booked", "meeting.completed",
    "deal.created", "deal.updated", "deal.stage_changed",
    "blueprint.published", "agreement.sent", "agreement.viewed",
    "agreement.client_signed", "agreement.executed",
    "invoice.issued", "invoice.paid", "client.onboarding_started",
]


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False, default="")
    prefix = Column(String(24), nullable=False, unique=True, index=True)  # public key id, e.g. rck_ab12cd34
    key_hash = Column(String(128), nullable=False)                        # HMAC-SHA256(pepper, full key)
    scopes = Column(JSON, default=list)
    expires_at = Column(DateTime)
    revoked_at = Column(DateTime)
    last_used_at = Column(DateTime)
    created_by_user_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)


class ApiRequestLog(Base):
    __tablename__ = "api_request_logs"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), index=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), index=True)
    method = Column(String(8), default="")
    path = Column(String(255), default="")          # path only — never query strings with data
    status = Column(Integer, default=0)
    latency_ms = Column(Float, default=0.0)
    at = Column(DateTime, default=datetime.utcnow, index=True)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("api_key_id", "idem_key", name="uq_idem_key"),)

    id = Column(Integer, primary_key=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=False, index=True)
    idem_key = Column(String(255), nullable=False)
    method = Column(String(8), default="")
    path = Column(String(255), default="")
    status = Column(Integer, default=0)
    response = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)


class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoints"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    url = Column(Text, nullable=False)
    events = Column(JSON, default=list)             # subset of WEBHOOK_EVENTS
    secret = Column(String(128), default="")        # HMAC signing secret (shown once at creation)
    active = Column(Boolean, default=True)
    failure_count = Column(Integer, default=0)
    last_delivery_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), index=True)
    endpoint_id = Column(Integer, ForeignKey("webhook_endpoints.id"), nullable=False, index=True)
    event_id = Column(String(48), nullable=False, index=True)   # idempotent event id (evt_...)
    event_type = Column(String(80), nullable=False, index=True)
    payload = Column(JSON, default=dict)
    status = Column(String(20), default="pending", index=True)  # pending/delivered/failed/dead
    attempts = Column(Integer, default=0)
    next_attempt_at = Column(DateTime, default=datetime.utcnow, index=True)
    response_status = Column(Integer)
    error = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    delivered_at = Column(DateTime)


class SyncConnection(Base):
    __tablename__ = "sync_connections"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    provider = Column(String(40), nullable=False, default="generic")  # generic/hubspot/salesforce/gohighlevel/pipedrive/zoho
    name = Column(String(255), default="")
    config_encrypted = Column(Text, default="")     # Fernet(CREDENTIAL_ENCRYPTION_KEY) of JSON creds/config
    direction = Column(String(20), default="outbound")  # outbound / inbound / two_way
    conflict_policy = Column(String(30), default="newest_wins")  # revcadence_wins/external_wins/newest_wins/flag_review
    entities = Column(JSON, default=list)           # ["companies","contacts","deals","activities"]
    field_mappings = Column(JSON, default=dict)     # {entity: {local_field: external_field}}
    stage_mappings = Column(JSON, default=dict)     # {local_stage_name: external_stage}
    owner_mappings = Column(JSON, default=dict)
    active = Column(Boolean, default=True)
    last_sync_at = Column(DateTime)
    last_error = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SyncMapping(Base):
    __tablename__ = "sync_mappings"
    __table_args__ = (UniqueConstraint("workspace_id", "provider", "local_entity_type",
                                       "local_entity_id", name="uq_sync_local"),)

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    provider = Column(String(40), nullable=False)
    local_entity_type = Column(String(30), nullable=False)   # company/contact/deal/activity
    local_entity_id = Column(Integer, nullable=False, index=True)
    external_entity_id = Column(String(255), default="", index=True)
    external_updated_at = Column(DateTime)
    last_synced_at = Column(DateTime)
    sync_status = Column(String(20), default="pending")     # pending/synced/failed/conflict
    last_error = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
