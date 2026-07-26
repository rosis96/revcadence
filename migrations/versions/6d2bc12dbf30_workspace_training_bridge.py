"""workspace training bridge

Revision ID: 6d2bc12dbf30
Revises: 120b8ef2c964
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa


revision = "6d2bc12dbf30"
down_revision = "120b8ef2c964"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_training_revisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("revision_hash", sa.String(length=64), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_workspace_training_revisions_workspace_id"),
        "workspace_training_revisions", ["workspace_id"], unique=False,
    )
    op.create_index(
        op.f("ix_workspace_training_revisions_revision_hash"),
        "workspace_training_revisions", ["revision_hash"], unique=False,
    )
    op.create_index(
        op.f("ix_workspace_training_revisions_created_at"),
        "workspace_training_revisions", ["created_at"], unique=False,
    )
    op.create_table(
        "workspace_evaluation_cases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("company", sa.String(length=255), nullable=True),
        sa.Column("website", sa.Text(), nullable=True),
        sa.Column("facts", sa.JSON(), nullable=True),
        sa.Column("expected_outputs", sa.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_workspace_evaluation_cases_workspace_id"),
        "workspace_evaluation_cases", ["workspace_id"], unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_workspace_evaluation_cases_workspace_id"),
        table_name="workspace_evaluation_cases",
    )
    op.drop_table("workspace_evaluation_cases")
    op.drop_index(
        op.f("ix_workspace_training_revisions_created_at"),
        table_name="workspace_training_revisions",
    )
    op.drop_index(
        op.f("ix_workspace_training_revisions_revision_hash"),
        table_name="workspace_training_revisions",
    )
    op.drop_index(
        op.f("ix_workspace_training_revisions_workspace_id"),
        table_name="workspace_training_revisions",
    )
    op.drop_table("workspace_training_revisions")
