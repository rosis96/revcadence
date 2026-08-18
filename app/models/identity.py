"""Identity: the master/client model.

Organization (master, e.g. Ascendly)
  └── Workspace (one per client: Webaholics, Shimahara, ...)
        └── Users attach via Membership with a role:
            owner / admin  → all workspaces in the org (master users)
            member         → the workspaces listed in Membership.workspace_ids
            client         → hard-locked to exactly ONE workspace
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint

from ..db import Base

ROLES = ("owner", "admin", "member", "client")
MASTER_ROLES = ("owner", "admin")


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(120), unique=True, nullable=False)
    settings = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(120), nullable=False)
    active = Column(Boolean, default=True)
    # White-label / client-portal options
    logo_url = Column(Text, default="")
    domain = Column(String(255), default="")
    # Legacy linkage: the workspace_name string used in the old reply-manager DB
    legacy_name = Column(String(255), default="", index=True)
    # Per-workspace public inbound capture key (form + visitor webhooks route by it)
    inbound_key = Column(String(64), default="", index=True)
    settings = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    # Soft delete. "Delete" in the admin screen sets this: the workspace leaves
    # every list, switcher and query at once (auth.allowed_workspace_ids is the
    # single gate), but not one row is destroyed. Restoring puts it back exactly
    # as it was; only an explicit purge removes it for good.
    archived_at = Column(DateTime, index=True)

    __table_args__ = (UniqueConstraint("org_id", "slug", name="uq_workspace_org_slug"),)


ALIAS_SOURCES = ("reply_manager", "enrichment", "client_portals")


class WorkspaceAlias(Base):
    """Source-specific legacy workspace names. One canonical workspace can carry
    many aliases (e.g. Ascendly ← 'Ascendly: mainreplybison' in reply_manager,
    'Ascendly' in enrichment). Aliases are the source of truth for every
    importer; Workspace.legacy_name remains only for backward compatibility."""
    __tablename__ = "workspace_aliases"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)
    source_system = Column(String(40), nullable=False)      # one of ALIAS_SOURCES
    external_name = Column(String(255), nullable=False)     # exact name in the source system
    external_id = Column(String(255))                       # optional stable id in the source
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("source_system", "external_name", name="uq_alias_source_name"),)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), default="")
    password_hash = Column(Text, nullable=False)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login_at = Column(DateTime)
    # password reset (token hashed at rest; expires)
    reset_token_hash = Column(String(128), default="")
    reset_expires_at = Column(DateTime)
    # Set when an operator issues a temporary password (a client invite). While
    # true the account can do nothing but read /me and change its password —
    # enforced in auth.get_ctx, so a temporary password cannot be left in place
    # by a client who simply avoids the screen that asks them to change it.
    must_change_password = Column(Boolean, default=False, nullable=False,
                                  server_default="0")


class Membership(Base):
    __tablename__ = "memberships"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    role = Column(String(20), nullable=False, default="member")  # one of ROLES
    # member: list of workspace ids they may access. owner/admin: ignored (all).
    # client: exactly one id — enforced in auth layer.
    workspace_ids = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("user_id", "org_id", name="uq_membership_user_org"),)
