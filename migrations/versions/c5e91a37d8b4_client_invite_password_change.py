"""client invite: forced first-login password change

Revision ID: c5e91a37d8b4
Revises: a7c3e1f90b52
Create Date: 2026-08-17

Additive only: one boolean on users. Existing accounts default to 0, so nobody
already signed in is asked to change anything.
"""
from alembic import op
import sqlalchemy as sa


revision = "c5e91a37d8b4"
down_revision = "a7c3e1f90b52"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "must_change_password" not in _columns("users"):
        op.add_column("users", sa.Column("must_change_password", sa.Boolean(),
                                         nullable=False, server_default="0"))


def downgrade() -> None:
    if "must_change_password" in _columns("users"):
        op.drop_column("users", "must_change_password")
