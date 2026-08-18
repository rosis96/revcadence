"""document-embedded whiteboards

Revision ID: e31a6b9c42d0
Revises: d92f4c7a1e31
Create Date: 2026-08-17

Additive only: one optimistic-revision column and three supporting tables.
"""
from alembic import op
import sqlalchemy as sa


revision = "e31a6b9c42d0"
down_revision = "d92f4c7a1e31"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)
            if index.get("name")}


def _index(name: str, table: str, columns: list[str]) -> None:
    if name not in _indexes(table):
        op.create_index(name, table, columns, unique=False)


def upgrade() -> None:
    if "revision" not in _columns("blocks"):
        op.add_column("blocks", sa.Column("revision", sa.Integer(), nullable=False,
                                          server_default=sa.text("1")))
    tables = _tables()
    if "board_presence" not in tables:
        op.create_table(
            "board_presence",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("block_id", sa.Integer(), nullable=False),
            sa.Column("workspace_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("last_seen", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["block_id"], ["blocks.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("block_id", "user_id", name="uq_board_presence_user"),
        )
    _index(op.f("ix_board_presence_block_id"), "board_presence", ["block_id"])
    _index(op.f("ix_board_presence_workspace_id"), "board_presence", ["workspace_id"])
    _index(op.f("ix_board_presence_user_id"), "board_presence", ["user_id"])
    _index(op.f("ix_board_presence_last_seen"), "board_presence", ["last_seen"])

    if "board_assets" not in tables:
        op.create_table(
            "board_assets",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("block_id", sa.Integer(), nullable=False),
            sa.Column("workspace_id", sa.Integer(), nullable=False),
            sa.Column("storage_key", sa.String(length=255), nullable=False),
            sa.Column("content_type", sa.String(length=80), nullable=False),
            sa.Column("size", sa.Integer(), nullable=False),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["block_id"], ["blocks.id"]),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("storage_key"),
        )
    _index(op.f("ix_board_assets_block_id"), "board_assets", ["block_id"])
    _index(op.f("ix_board_assets_workspace_id"), "board_assets", ["workspace_id"])

    if "whiteboard_promotions" not in tables:
        op.create_table(
            "whiteboard_promotions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("workspace_id", sa.Integer(), nullable=False),
            sa.Column("block_id", sa.Integer(), nullable=False),
            sa.Column("shape_id", sa.String(length=80), nullable=False),
            sa.Column("kind", sa.String(length=30), nullable=False),
            sa.Column("value", sa.Text(), nullable=False),
            sa.Column("data", sa.JSON(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["block_id"], ["blocks.id"]),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("block_id", "shape_id", name="uq_whiteboard_promotion_shape"),
        )
    _index(op.f("ix_whiteboard_promotions_workspace_id"), "whiteboard_promotions", ["workspace_id"])
    _index(op.f("ix_whiteboard_promotions_block_id"), "whiteboard_promotions", ["block_id"])
    _index(op.f("ix_whiteboard_promotions_kind"), "whiteboard_promotions", ["kind"])


def downgrade() -> None:
    op.drop_table("whiteboard_promotions")
    op.drop_table("board_assets")
    op.drop_table("board_presence")
    op.drop_column("blocks", "revision")
