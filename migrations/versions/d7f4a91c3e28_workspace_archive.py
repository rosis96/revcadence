"""workspace archive (soft delete)

Deleting a workspace from the admin screen now archives it instead of
destroying it: `archived_at` stamps when, and `auth.allowed_workspace_ids` —
the one gate every scoped query already passes through — filters on it, so an
archived workspace leaves every list, switcher and query at once. Purging is a
separate, explicit action, so nothing here needs a data backfill: every
existing workspace is live and `archived_at` is NULL for all of them.

The column is guarded. The legacy additive sync (`app.db.migrate`) runs on
every deploy from `scripts.premigrate`, BEFORE `alembic upgrade head`, and it
adds any mapped column that is missing — so by the time Alembic reaches this
revision the column is usually already there, and an unguarded add_column
would abort the upgrade. Same reasoning as c9a4d1e60b73, and the case
tests/test_migration_safety.py pins.

Revision ID: d7f4a91c3e28
Revises: c9a4d1e60b73
Create Date: 2026-08-18
"""
from alembic import op
import sqlalchemy as sa


revision = "d7f4a91c3e28"
down_revision = "c9a4d1e60b73"
branch_labels = None
depends_on = None

TABLE = "workspaces"
COLUMN = "archived_at"
INDEX = "ix_workspaces_archived_at"


def _columns() -> set:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(TABLE)}


def _indexes() -> set:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(TABLE)}


def upgrade() -> None:
    if COLUMN not in _columns():
        op.add_column(TABLE, sa.Column(COLUMN, sa.DateTime(), nullable=True))
    # The additive sync adds columns but never their indexes, so this is
    # checked separately rather than inside the branch above.
    if INDEX not in _indexes():
        op.create_index(INDEX, TABLE, [COLUMN], unique=False)


def downgrade() -> None:
    if INDEX in _indexes():
        op.drop_index(INDEX, table_name=TABLE)
    if COLUMN in _columns():
        op.drop_column(TABLE, COLUMN)
