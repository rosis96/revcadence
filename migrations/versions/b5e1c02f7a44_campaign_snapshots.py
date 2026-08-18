"""campaign snapshots + mirrored campaign ids

Mirrors the live outbound ladder from Instantly/Bison so the client-facing
sequence screen renders what actually sends, without calling a third party
inline.

Additive only. Both steps are guarded by an existence check because the legacy
additive sync (`app.db.migrate`) can create a mapped table or column before
Alembic reaches this revision — the Railway recovery path that
tests/test_migration_safety.py pins. An unguarded create_table would abort the
upgrade on exactly the deploy that most needs it to succeed.

Revision ID: b5e1c02f7a44
Revises: a7c3f19d8b52
Create Date: 2026-08-18
"""
from alembic import op
import sqlalchemy as sa


revision = 'b5e1c02f7a44'
down_revision = 'a7c3f19d8b52'
branch_labels = None
depends_on = None


def _tables() -> set:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "campaign_snapshots" not in _tables():
        op.create_table(
            "campaign_snapshots",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"),
                      nullable=False, index=True),
            sa.Column("reply_workspace_id", sa.Integer(), sa.ForeignKey("reply_workspaces.id"),
                      nullable=False, index=True),
            sa.Column("platform", sa.String(20)),
            sa.Column("external_id", sa.String(255), index=True),
            sa.Column("name", sa.String(500)),
            sa.Column("status", sa.String(40)),
            # The normalized ladder the UI reads. `raw` keeps the vendor response
            # so a wrong field mapping is diagnosable without a second API call.
            sa.Column("payload", sa.JSON()),
            sa.Column("raw", sa.JSON()),
            sa.Column("fetch_status", sa.String(20)),
            sa.Column("fetch_error", sa.Text()),
            sa.Column("fetched_at", sa.DateTime()),
            sa.Column("created_at", sa.DateTime()),
            sa.Column("updated_at", sa.DateTime()),
            sa.UniqueConstraint("reply_workspace_id", "external_id",
                                name="uq_campaign_snapshot_external"),
        )

    if "mirror_campaign_ids" not in _columns("reply_workspaces"):
        op.add_column("reply_workspaces", sa.Column("mirror_campaign_ids", sa.JSON()))


def downgrade() -> None:
    if "mirror_campaign_ids" in _columns("reply_workspaces"):
        op.drop_column("reply_workspaces", "mirror_campaign_ids")
    if "campaign_snapshots" in _tables():
        op.drop_table("campaign_snapshots")
