"""reply settings per workspace

Reply Settings became a client-facing screen, and every value it held was an
org-wide `app_settings` row — one value for the whole org. A client editing the
model or the API key there would have edited it for every other client, which is
the cross-tenant write rule 2 exists to prevent.

Four of the nine values already had per-space homes (`openai_key_enc`,
`gemini_key_enc`, `base_url`, `reply_delay_seconds`). This adds the other five as
columns on `reply_workspaces` so the screen can be scoped instead of shared. The
org row is untouched and still serves a master editing "All workspaces".

Additive only, and each column is guarded: the legacy additive sync
(`app.db.migrate`) can add a mapped column before Alembic reaches this revision —
the Railway recovery path that tests/test_migration_safety.py pins — and an
unguarded add_column would abort the upgrade on exactly the deploy that most
needs it to succeed.

Revision ID: c9a4d1e60b73
Revises: b5e1c02f7a44
Create Date: 2026-08-18
"""
from alembic import op
import sqlalchemy as sa


revision = 'c9a4d1e60b73'
down_revision = 'b5e1c02f7a44'
branch_labels = None
depends_on = None

TABLE = "reply_workspaces"
COLUMNS = (
    ("openai_model", sa.String(length=120)),
    ("gemini_model", sa.String(length=120)),
    ("review_webhook_url", sa.Text()),
    ("reply_trigger_tag", sa.String(length=120)),
    ("followup_trigger_tag", sa.String(length=120)),
)


def _columns() -> set:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(TABLE)}


def upgrade() -> None:
    existing = _columns()
    for name, type_ in COLUMNS:
        if name not in existing:
            # Nullable with a server-side empty default: existing rows inherit
            # (blank means "fall back to env", see reply/engine.build_ai_cfg), so
            # no workspace changes behaviour by being migrated.
            op.add_column(TABLE, sa.Column(name, type_, nullable=True, server_default=""))


def downgrade() -> None:
    existing = _columns()
    for name, _ in reversed(COLUMNS):
        if name in existing:
            op.drop_column(TABLE, name)
