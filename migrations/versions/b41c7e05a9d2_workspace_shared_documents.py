"""workspace shared documents

Revision ID: b41c7e05a9d2
Revises: 6d2bc12dbf30
Create Date: 2026-08-16

Purely additive: five new tables, no changes to existing ones. Written
defensively for the same reason as the training-bridge revision — a SQLite dev
database has already had these created by `db.migrate()`, so every create is
guarded and the deployment accepts that safe pre-existing state.
"""
from alembic import op
import sqlalchemy as sa


revision = "b41c7e05a9d2"
down_revision = "6d2bc12dbf30"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _index_names(table_name: str) -> set[str]:
    return {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
        if index.get("name")
    }


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if index_name not in _index_names(table_name):
        op.create_index(index_name, table_name, columns, unique=False)


def upgrade() -> None:
    tables = _table_names()

    if "pages" not in tables:
        op.create_table(
            "pages",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("workspace_id", sa.Integer(), nullable=False),
            sa.Column("parent_id", sa.Integer(), nullable=True),
            sa.Column("title", sa.String(length=512), nullable=True),
            sa.Column("icon", sa.String(length=40), nullable=True),
            sa.Column("section", sa.String(length=20), nullable=True),
            sa.Column("visibility", sa.String(length=20), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=True),
            sa.Column("owner_role", sa.String(length=20), nullable=True),
            sa.Column("position", sa.Integer(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("archived_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["parent_id"], ["pages.id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing(op.f("ix_pages_workspace_id"), "pages", ["workspace_id"])
    _create_index_if_missing(op.f("ix_pages_parent_id"), "pages", ["parent_id"])

    if "blocks" not in tables:
        op.create_table(
            "blocks",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("page_id", sa.Integer(), nullable=False),
            sa.Column("position", sa.Integer(), nullable=True),
            sa.Column("type", sa.String(length=20), nullable=False),
            sa.Column("content", sa.JSON(), nullable=True),
            sa.Column("entity_type", sa.String(length=40), nullable=True),
            sa.Column("entity_id", sa.Integer(), nullable=True),
            sa.Column("field_path", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["page_id"], ["pages.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing(op.f("ix_blocks_page_id"), "blocks", ["page_id"])

    if "page_versions" not in tables:
        op.create_table(
            "page_versions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("page_id", sa.Integer(), nullable=False),
            sa.Column("version_no", sa.Integer(), nullable=False),
            sa.Column("snapshot", sa.JSON(), nullable=False),
            sa.Column("note", sa.String(length=500), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["page_id"], ["pages.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing(op.f("ix_page_versions_page_id"), "page_versions", ["page_id"])
    _create_index_if_missing(op.f("ix_page_versions_created_at"), "page_versions", ["created_at"])

    if "comments" not in tables:
        op.create_table(
            "comments",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("workspace_id", sa.Integer(), nullable=False),
            sa.Column("page_id", sa.Integer(), nullable=False),
            sa.Column("block_id", sa.Integer(), nullable=True),
            sa.Column("parent_id", sa.Integer(), nullable=True),
            sa.Column("author_user_id", sa.Integer(), nullable=True),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column("mentions", sa.JSON(), nullable=True),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
            sa.Column("resolved_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["author_user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["block_id"], ["blocks.id"]),
            sa.ForeignKeyConstraint(["page_id"], ["pages.id"]),
            sa.ForeignKeyConstraint(["parent_id"], ["comments.id"]),
            sa.ForeignKeyConstraint(["resolved_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing(op.f("ix_comments_workspace_id"), "comments", ["workspace_id"])
    _create_index_if_missing(op.f("ix_comments_page_id"), "comments", ["page_id"])
    _create_index_if_missing(op.f("ix_comments_block_id"), "comments", ["block_id"])
    _create_index_if_missing(op.f("ix_comments_parent_id"), "comments", ["parent_id"])
    _create_index_if_missing(op.f("ix_comments_created_at"), "comments", ["created_at"])

    if "page_templates" not in tables:
        op.create_table(
            "page_templates",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("org_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("section", sa.String(length=20), nullable=True),
            sa.Column("icon", sa.String(length=40), nullable=True),
            sa.Column("default_visibility", sa.String(length=20), nullable=True),
            sa.Column("blocks", sa.JSON(), nullable=True),
            sa.Column("created_from_page_id", sa.Integer(), nullable=True),
            sa.Column("version", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["created_from_page_id"], ["pages.id"]),
            sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing(op.f("ix_page_templates_org_id"), "page_templates", ["org_id"])


def downgrade() -> None:
    op.drop_table("page_templates")
    op.drop_table("comments")
    op.drop_table("page_versions")
    op.drop_table("blocks")
    op.drop_table("pages")
