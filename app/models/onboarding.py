"""Client onboarding — a premium intake form per client workspace. Filled once
by the client (public token link, save-draft or submit); on submit it auto-wires
the profile / ICP / mailbox / feature toggles so the team never sets those up by
hand. `MailboxConnection` is the one mailbox that powers both the Unibox and
automated follow-up sending."""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text

from ..db import Base


class Onboarding(Base):
    __tablename__ = "onboardings"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    token = Column(String(64), unique=True, nullable=False, index=True)  # public form link
    status = Column(String(20), default="draft")   # draft / submitted
    data = Column(JSON, default=dict)              # all form answers (secrets stored separately)
    submitted_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MailboxConnection(Base):
    """A connected sending/reading mailbox for a workspace (IMAP read + SMTP
    send). Powers the Unibox and post-meeting follow-up. App password encrypted."""
    __tablename__ = "mailbox_connections"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))          # who connected it
    email = Column(String(255), default="")
    from_name = Column(String(255), default="")                # display name on outgoing mail
    username = Column(String(255), default="")                 # SMTP/IMAP login (usually == email)
    app_password_enc = Column(Text, default="")                # encrypted app password
    imap_host = Column(String(120), default="imap.gmail.com")
    imap_port = Column(Integer, default=993)
    smtp_host = Column(String(120), default="smtp.gmail.com")
    smtp_port = Column(Integer, default=587)
    provider = Column(String(30), default="gmail")
    active = Column(Boolean, default=True)
    status = Column(String(20), default="pending")             # pending | connected | error
    last_error = Column(Text, default="")
    last_checked_at = Column(DateTime)
    last_sync_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
