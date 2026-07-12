"""Reply Management models — port of the legacy reply-manager schema
(db.py: workspaces + leads), tenant-scoped and with secrets encrypted at rest."""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text

from ..db import Base


class ReplyWorkspace(Base):
    """One row per client × flow (legacy pattern kept: mode reply/followup)."""
    __tablename__ = "reply_workspaces"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    name = Column(String(255), unique=True, nullable=False)   # matched by webhooks
    platform = Column(String(20), default="bison")            # bison | instantly
    mode = Column(String(20), default="reply")                # reply | followup
    active = Column(Boolean, default=True)

    api_key_enc = Column(Text, default="")                    # encrypted
    base_url = Column(Text, default="")                       # Bison base URL
    reply_followup_campaign_id = Column(String(255), default="")

    website = Column(Text, default="")
    sender_name = Column(Text, default="")
    default_sender_email = Column(Text, default="")
    calendly_token_enc = Column(Text, default="")             # encrypted
    calendly_scheduling_url = Column(Text, default="")

    ai_provider = Column(String(20), default="openai")        # openai | gemini
    ai_fallback = Column(Boolean, default=False)
    openai_key_enc = Column(Text, default="")                 # per-ws override, encrypted
    gemini_key_enc = Column(Text, default="")

    client_profile = Column(JSON, default=dict)
    reply_format = Column(JSON, default=dict)                 # response_types[] + followups schema
    ai_rules = Column(Text, default="")                       # per-workspace (legacy was global)
    reply_delay_seconds = Column(Integer, default=420)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ProposedSlot(Base):
    """Anti-double-booking: every Calendly time we propose to a prospect is
    reserved here (unique by workspace + slot), so the same open slot is never
    pitched to two prospects. Past slots are pruned. Legacy proposed_slots."""
    __tablename__ = "proposed_slots"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), index=True)
    reply_workspace = Column(String(255), default="", index=True)
    prospect = Column(String(255), default="")     # email or lead id
    slot_utc = Column(String(40), default="", index=True)  # ISO-8601 UTC (the unique key)
    label = Column(Text, default="")               # human label we showed
    created_at = Column(DateTime, default=datetime.utcnow)


class ReplyLead(Base):
    """One row per processed reply (legacy `leads` table)."""
    __tablename__ = "reply_leads"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), index=True)  # tenant (may be null → Unrouted)
    reply_workspace = Column(String(255), default="", index=True)            # ReplyWorkspace.name or "Unrouted"
    platform = Column(String(20), default="")
    dedupe_key = Column(String(512), index=True)
    legacy_id = Column(Integer, index=True)     # original Reply Manager leads.id (traceability)
    external_lead_id = Column(String(255), default="")
    reply_id = Column(String(255), default="")

    name = Column(String(255), default="")
    email = Column(String(255), default="")
    company = Column(String(255), default="")
    campaign = Column(String(255), default="")
    subject = Column(String(512), default="")

    intent = Column(String(120), default="")
    confidence = Column(String(40), default="")
    conf_num = Column(Float, default=0.0)
    action = Column(String(40), default="")     # send / would_send / skip_enrich / stop / error
    replied = Column(Boolean, default=False)    # our reply actually sent
    reply_added = Column(Boolean, default=False)
    fup_added = Column(Boolean, default=False)
    reviewed = Column(Boolean, default=False)
    stage = Column(String(40), default="new")   # new/replied/booked/won/lost/stopped

    reply_text = Column(Text, default="")       # prospect's incoming reply
    main_reply = Column(Text, default="")       # our (drafted or sent) reply
    followups = Column(JSON, default=list)
    thread = Column(JSON, default=list)
    lead_data = Column(JSON, default=dict)      # full raw platform payload (CRM enrichment depends on it)
    send_meta = Column(JSON, default=dict)      # everything needed to (re)send

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
