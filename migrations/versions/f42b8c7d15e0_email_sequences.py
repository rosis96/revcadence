"""email sequences workspace

Revision ID: f42b8c7d15e0
Revises: e31a6b9c42d0
Create Date: 2026-08-17

Additive only: the angle, sequence, step, variant, approval, and template tables.
"""
from alembic import op
import sqlalchemy as sa


revision = "f42b8c7d15e0"
down_revision = "e31a6b9c42d0"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()
    if "email_angles" not in tables:
        op.create_table(
            "email_angles",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("org_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False, index=True),
            sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=False, index=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("hypothesis", sa.Text()), sa.Column("proof_key", sa.String(160)),
            sa.Column("proof_label", sa.String(500)),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("created_at", sa.DateTime()), sa.Column("updated_at", sa.DateTime()),
        )
    if "email_sequence_templates" not in tables:
        op.create_table(
            "email_sequence_templates",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("org_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False, index=True),
            sa.Column("name", sa.String(255), nullable=False), sa.Column("description", sa.Text()),
            sa.Column("structure", sa.JSON(), nullable=False),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("archived_at", sa.DateTime()), sa.Column("created_at", sa.DateTime()),
        )
    if "email_sequences" not in tables:
        op.create_table(
            "email_sequences",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("org_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False, index=True),
            sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=False, index=True),
            sa.Column("angle_id", sa.Integer(), sa.ForeignKey("email_angles.id"), nullable=False, index=True),
            sa.Column("name", sa.String(255), nullable=False), sa.Column("description", sa.Text()),
            sa.Column("status", sa.String(30), nullable=False, server_default="draft", index=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("current_list_id", sa.Integer(), sa.ForeignKey("enrich_lists.id"), index=True),
            sa.Column("template_source_id", sa.Integer(), sa.ForeignKey("email_sequence_templates.id"), index=True),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("created_at", sa.DateTime()), sa.Column("updated_at", sa.DateTime()),
        )
    if "email_sequence_steps" not in tables:
        op.create_table(
            "email_sequence_steps",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("sequence_id", sa.Integer(), sa.ForeignKey("email_sequences.id"), nullable=False, index=True),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("name", sa.String(255), nullable=False), sa.Column("purpose", sa.String(40)),
            sa.Column("wait_days", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("rotation_cursor", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("archived_at", sa.DateTime()), sa.Column("created_at", sa.DateTime()),
            sa.Column("updated_at", sa.DateTime()),
        )
    if "email_sequence_variants" not in tables:
        op.create_table(
            "email_sequence_variants",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("step_id", sa.Integer(), sa.ForeignKey("email_sequence_steps.id"), nullable=False, index=True),
            sa.Column("label", sa.String(1), nullable=False), sa.Column("subject", sa.Text()),
            sa.Column("body", sa.Text()), sa.Column("change_note", sa.String(500)),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false(), index=True),
            sa.Column("promoted", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("quality", sa.JSON()), sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("reply_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("positive_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("meeting_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("archived_at", sa.DateTime()), sa.Column("created_at", sa.DateTime()),
            sa.Column("updated_at", sa.DateTime()),
            sa.UniqueConstraint("step_id", "label", name="uq_email_step_variant_label"),
        )
    if "email_sequence_approvals" not in tables:
        op.create_table(
            "email_sequence_approvals",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("sequence_id", sa.Integer(), sa.ForeignKey("email_sequences.id"), nullable=False, index=True),
            sa.Column("sequence_version", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="pending", index=True),
            sa.Column("snapshot", sa.JSON(), nullable=False), sa.Column("note", sa.Text()),
            sa.Column("requested_by", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("requested_at", sa.DateTime()),
            sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("decided_at", sa.DateTime()),
        )


def downgrade() -> None:
    op.drop_table("email_sequence_approvals")
    op.drop_table("email_sequence_variants")
    op.drop_table("email_sequence_steps")
    op.drop_table("email_sequences")
    op.drop_table("email_sequence_templates")
    op.drop_table("email_angles")
