"""page kind (folders)

Revision ID: c8f2a1d64b70
Revises: b41c7e05a9d2
Create Date: 2026-08-17

Additive: one nullable column. Existing rows read as `page` through the model
default, so nothing needs backfilling and nothing changes behaviour on deploy.
"""
from alembic import op
import sqlalchemy as sa


revision = "c8f2a1d64b70"
down_revision = "b41c7e05a9d2"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    # The SQLite dev path may already have added this via db.migrate(); accept
    # that safe pre-existing state rather than failing the deployment.
    if "kind" not in _columns("pages"):
        op.add_column("pages", sa.Column("kind", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("pages", "kind")
