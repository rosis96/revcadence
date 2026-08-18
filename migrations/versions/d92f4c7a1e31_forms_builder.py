"""invite-only reusable form builder

Revision ID: d92f4c7a1e31
Revises: c8f2a1d64b70
Create Date: 2026-08-17

Additive only. SQLite may already have these tables through ``db.migrate()``;
the guarded creates keep adoption safe.
"""
from alembic import op
import sqlalchemy as sa


revision = "d92f4c7a1e31"
down_revision = "c8f2a1d64b70"
branch_labels = None
depends_on = None


def _has(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def upgrade() -> None:
    if not _has("forms"):
        op.create_table(
            "forms",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("org_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text()),
            sa.Column("duplicated_from_id", sa.Integer(), sa.ForeignKey("forms.id")),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("created_at", sa.DateTime()),
            sa.Column("updated_at", sa.DateTime()),
        )
        op.create_index("ix_forms_org_id", "forms", ["org_id"])
        op.create_index("ix_forms_duplicated_from_id", "forms", ["duplicated_from_id"])
        op.create_index("ix_forms_status", "forms", ["status"])

    if not _has("form_sections"):
        op.create_table(
            "form_sections",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("form_id", sa.Integer(), sa.ForeignKey("forms.id"), nullable=False),
            sa.Column("position", sa.Integer()),
            sa.Column("title", sa.String(512)),
            sa.Column("description", sa.Text()),
        )
        op.create_index("ix_form_sections_form_id", "form_sections", ["form_id"])

    if not _has("form_questions"):
        op.create_table(
            "form_questions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("form_id", sa.Integer(), sa.ForeignKey("forms.id"), nullable=False),
            sa.Column("section_id", sa.Integer(), sa.ForeignKey("form_sections.id")),
            sa.Column("position", sa.Integer()),
            sa.Column("type", sa.String(30), nullable=False),
            sa.Column("label", sa.String(1000)),
            sa.Column("help_text", sa.Text()),
            sa.Column("required", sa.Boolean()),
            sa.Column("options", sa.JSON()),
            sa.Column("maps_to", sa.String(80)),
            sa.Column("prefill_source", sa.String(80)),
            sa.Column("display_mode", sa.String(20)),
            sa.Column("created_at", sa.DateTime()),
        )
        op.create_index("ix_form_questions_form_id", "form_questions", ["form_id"])
        op.create_index("ix_form_questions_section_id", "form_questions", ["section_id"])

    if not _has("form_versions"):
        op.create_table(
            "form_versions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("form_id", sa.Integer(), sa.ForeignKey("forms.id"), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("schema", sa.JSON(), nullable=False),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("created_at", sa.DateTime()),
            sa.UniqueConstraint("form_id", "version", name="uq_form_version"),
        )
        op.create_index("ix_form_versions_form_id", "form_versions", ["form_id"])

    if not _has("form_invites"):
        op.create_table(
            "form_invites",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("form_id", sa.Integer(), sa.ForeignKey("forms.id"), nullable=False),
            sa.Column("form_version", sa.Integer(), nullable=False),
            sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=False),
            sa.Column("recipient_email", sa.String(255), nullable=False),
            sa.Column("recipient_name", sa.String(255)),
            sa.Column("known_context", sa.JSON()),
            sa.Column("token", sa.String(128), nullable=False, unique=True),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("sent_at", sa.DateTime()),
            sa.Column("opened_at", sa.DateTime()),
            sa.Column("submitted_at", sa.DateTime()),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("reminder_count", sa.Integer()),
        )
        op.create_index("ix_form_invites_form_id", "form_invites", ["form_id"])
        op.create_index("ix_form_invites_workspace_id", "form_invites", ["workspace_id"])
        op.create_index("ix_form_invites_recipient_email", "form_invites", ["recipient_email"])
        op.create_index("ix_form_invites_token", "form_invites", ["token"], unique=True)
        op.create_index("ix_form_invites_status", "form_invites", ["status"])
        op.create_index("ix_form_invites_expires_at", "form_invites", ["expires_at"])

    if not _has("form_responses"):
        op.create_table(
            "form_responses",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("form_id", sa.Integer(), sa.ForeignKey("forms.id"), nullable=False),
            sa.Column("form_version", sa.Integer(), nullable=False),
            sa.Column("invite_id", sa.Integer(), sa.ForeignKey("form_invites.id"), nullable=False),
            sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=False),
            sa.Column("response_version", sa.Integer(), nullable=False),
            sa.Column("supersedes_id", sa.Integer(), sa.ForeignKey("form_responses.id")),
            sa.Column("contact_details", sa.JSON()),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("submitted_at", sa.DateTime()),
            sa.Column("ip_hash", sa.String(64)),
            sa.Column("created_at", sa.DateTime()),
            sa.Column("updated_at", sa.DateTime()),
        )
        op.create_index("ix_form_responses_form_id", "form_responses", ["form_id"])
        op.create_index("ix_form_responses_invite_id", "form_responses", ["invite_id"])
        op.create_index("ix_form_responses_workspace_id", "form_responses", ["workspace_id"])
        op.create_index("ix_form_responses_supersedes_id", "form_responses", ["supersedes_id"])
        op.create_index("ix_form_responses_status", "form_responses", ["status"])

    if not _has("form_answers"):
        op.create_table(
            "form_answers",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("response_id", sa.Integer(), sa.ForeignKey("form_responses.id"), nullable=False),
            sa.Column("question_id", sa.Integer(), nullable=False),
            sa.Column("value", sa.JSON()),
            sa.Column("source", sa.String(40), nullable=False),
            sa.Column("prefill_value", sa.JSON()),
            sa.Column("was_edited", sa.Boolean()),
            sa.UniqueConstraint("response_id", "question_id", name="uq_form_answer"),
        )
        op.create_index("ix_form_answers_response_id", "form_answers", ["response_id"])
        op.create_index("ix_form_answers_question_id", "form_answers", ["question_id"])

    if not _has("form_uploads"):
        op.create_table(
            "form_uploads",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("invite_id", sa.Integer(), sa.ForeignKey("form_invites.id"), nullable=False),
            sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=False),
            sa.Column("question_id", sa.Integer(), nullable=False),
            sa.Column("storage_key", sa.String(255), nullable=False, unique=True),
            sa.Column("original_name", sa.String(255)),
            sa.Column("extension", sa.String(12), nullable=False),
            sa.Column("content_type", sa.String(120)),
            sa.Column("size", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime()),
        )
        op.create_index("ix_form_uploads_invite_id", "form_uploads", ["invite_id"])
        op.create_index("ix_form_uploads_workspace_id", "form_uploads", ["workspace_id"])
        op.create_index("ix_form_uploads_question_id", "form_uploads", ["question_id"])


def downgrade() -> None:
    for table in ("form_uploads", "form_answers", "form_responses", "form_invites",
                  "form_versions", "form_questions", "form_sections", "forms"):
        if _has(table):
            op.drop_table(table)
