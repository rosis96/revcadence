"""Deal Conversation (Revenue Inbox v1) — same-thread relationship management.

A workspace connects ONE mailbox. Every message RevCadence sends goes out through
that mailbox, and every reply returns into the SAME email thread (via RFC
In-Reply-To / References headers), so Gmail/Outlook keep it as one conversation.
Each Deal owns exactly one Conversation that continues until the Deal is Won/Lost.

v1 transport: SMTP (send) + IMAP (receive) with an app password, encrypted at rest.
The provider field lets us swap in OAuth/aggregator transports later without a
data-model change.
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from ..db import Base

MAILBOX_PROVIDERS = ("gmail", "outlook", "smtp")
CONVERSATION_STATES = ("active", "paused", "won", "lost", "stopped")
MESSAGE_STATES = ("draft", "scheduled", "sent", "received", "failed", "cancelled")

# NOTE: the mailbox row itself is `onboarding.MailboxConnection` (table
# `mailbox_connections`), scaffolded earlier for the Unibox/follow-up. We reuse it
# and reference it by table name below rather than redefining the table.


class DealConversation(Base):
    __tablename__ = "deal_conversations"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    deal_id = Column(Integer, ForeignKey("deals.id"), unique=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), index=True)
    mailbox_id = Column(Integer, ForeignKey("mailbox_connections.id"))

    subject = Column(String(512), default="")                  # the thread subject ("Re: …")
    prospect_email = Column(String(255), default="", index=True)
    thread_refs = Column(Text, default="")                     # accumulated References header
    provider_thread_id = Column(String(255), default="")       # optional (gmail threadId)

    state = Column(String(20), default="active")               # CONVERSATION_STATES
    last_inbound_at = Column(DateTime)
    last_outbound_at = Column(DateTime)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("deal_conversations.id"), index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), index=True)
    deal_id = Column(Integer, ForeignKey("deals.id"), index=True)

    direction = Column(String(4), default="out")               # out | in
    from_email = Column(String(255), default="")
    to_email = Column(String(255), default="")
    subject = Column(String(512), default="")
    body_text = Column(Text, default="")
    body_html = Column(Text, default="")

    # RFC threading — what keeps it in the SAME email thread
    rfc_message_id = Column(String(512), default="", index=True)
    in_reply_to = Column(String(512), default="")
    references = Column(Text, default="")

    status = Column(String(20), default="sent")                # MESSAGE_STATES
    scheduled_at = Column(DateTime)                            # for AI follow-up cadence
    sent_at = Column(DateTime)
    ai_generated = Column(Boolean, default=False)
    approved_by = Column(Integer, ForeignKey("users.id"))

    created_at = Column(DateTime, default=datetime.utcnow)
