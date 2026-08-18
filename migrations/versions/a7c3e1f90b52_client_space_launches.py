"""client space launches

Revision ID: a7c3e1f90b52
Revises: f42b8c7d15e0
Create Date: 2026-08-17

Additive only: the per-workspace launch row and its tasks. Nothing existing is
touched — Client Space reads the docs, sequence and form tables as they stand.
"""
from alembic import op
import sqlalchemy as sa


revision = "a7c3e1f90b52"
down_revision = "f42b8c7d15e0"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()
    if "client_launches" not in tables:
        op.create_table(
            "client_launches",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"),
                      nullable=False, index=True),
            sa.Column("stage", sa.String(30), nullable=False, server_default="intake"),
            sa.Column("kickoff_at", sa.DateTime()),
            sa.Column("first_send_at", sa.DateTime()),
            sa.Column("note", sa.Text()),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("created_at", sa.DateTime()),
            sa.Column("updated_at", sa.DateTime()),
            sa.UniqueConstraint("workspace_id", name="uq_client_launch_workspace"),
        )
    if "launch_tasks" not in tables:
        op.create_table(
            "launch_tasks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"),
                      nullable=False, index=True),
            sa.Column("stage", sa.String(30), nullable=False, server_default="intake"),
            sa.Column("title", sa.String(512), nullable=False),
            sa.Column("detail", sa.Text()),
            sa.Column("owner", sa.String(20), nullable=False, server_default="us"),
            sa.Column("status", sa.String(20), nullable=False, server_default="todo"),
            sa.Column("blocked_note", sa.Text()),
            sa.Column("due_at", sa.DateTime()),
            sa.Column("position", sa.Integer(), server_default="0"),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("created_at", sa.DateTime()),
            sa.Column("updated_at", sa.DateTime()),
            sa.Column("completed_at", sa.DateTime()),
        )


def downgrade() -> None:
    tables = _tables()
    if "launch_tasks" in tables:
        op.drop_table("launch_tasks")
    if "client_launches" in tables:
        op.drop_table("client_launches")
