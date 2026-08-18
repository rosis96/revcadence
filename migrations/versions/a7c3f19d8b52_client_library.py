"""client library: case studies, segments, ICP tests, exclusions

Revision ID: a7c3f19d8b52
Revises: d3b8f61c07ae
Create Date: 2026-08-17

Additive only. `source` is NOT NULL on every table on purpose: a library record
without provenance is a fact whose origin we have already lost, and the writer's
named-claim rule reads this column. There is no server_default — a row must state
where it came from rather than inheriting a guess.

Case studies previously lived in `enrich_configs.profile["case_studies"]`. That
JSON is deliberately left alone; the Library lists it as unfiled and
`POST /api/library/import-unfiled` moves it into rows when somebody chooses to.
"""
from alembic import op
import sqlalchemy as sa


revision = "a7c3f19d8b52"
down_revision = "d3b8f61c07ae"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _provenance() -> list:
    return [
        sa.Column("source", sa.String(20), nullable=False, index=True),
        sa.Column("source_url", sa.Text()),
        sa.Column("verified_at", sa.DateTime()),
        sa.Column("verified_by", sa.Integer(), sa.ForeignKey("users.id")),
    ]


def _stamps() -> list:
    return [
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
        sa.Column("archived_at", sa.DateTime()),
    ]


def upgrade() -> None:
    tables = _tables()
    if "library_case_studies" not in tables:
        op.create_table(
            "library_case_studies",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"),
                      nullable=False, index=True),
            sa.Column("client_name", sa.String(240), nullable=False),
            sa.Column("engagement", sa.String(240)),
            sa.Column("segment", sa.String(160)),
            sa.Column("year", sa.Integer()),
            sa.Column("outcome", sa.Text(), nullable=False),
            sa.Column("note", sa.Text()),
            *_provenance(), *_stamps(),
        )
    if "library_segments" not in tables:
        op.create_table(
            "library_segments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"),
                      nullable=False, index=True),
            sa.Column("name", sa.String(240), nullable=False),
            sa.Column("company_type", sa.String(240)),
            sa.Column("headcount", sa.String(80)),
            sa.Column("geography", sa.String(240)),
            sa.Column("tam_estimate", sa.Integer()),
            sa.Column("tam_note", sa.Text()),
            sa.Column("enrich_list_id", sa.Integer(), sa.ForeignKey("enrich_lists.id"), index=True),
            *_provenance(), *_stamps(),
        )
    if "library_icp_tests" not in tables:
        op.create_table(
            "library_icp_tests",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"),
                      nullable=False, index=True),
            sa.Column("hypothesis", sa.Text(), nullable=False),
            sa.Column("verdict", sa.String(20), nullable=False, server_default="testing",
                      index=True),
            sa.Column("result", sa.Text()),
            sa.Column("sample_size", sa.Integer()),
            sa.Column("segment_id", sa.Integer(), sa.ForeignKey("library_segments.id"), index=True),
            sa.Column("started_at", sa.DateTime()),
            sa.Column("decided_at", sa.DateTime()),
            *_provenance(), *_stamps(),
        )
    if "library_exclusions" not in tables:
        op.create_table(
            "library_exclusions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"),
                      nullable=False, index=True),
            sa.Column("kind", sa.String(20), nullable=False, server_default="domain"),
            sa.Column("value", sa.String(320), nullable=False, index=True),
            sa.Column("label", sa.String(240)),
            sa.Column("reason", sa.String(500)),
            sa.Column("source", sa.String(20), nullable=False, index=True),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id")),
            sa.Column("created_at", sa.DateTime()),
            sa.Column("archived_at", sa.DateTime()),
            sa.UniqueConstraint("workspace_id", "kind", "value",
                                name="uq_library_exclusion_value"),
        )


def downgrade() -> None:
    op.drop_table("library_exclusions")
    op.drop_table("library_icp_tests")
    op.drop_table("library_segments")
    op.drop_table("library_case_studies")
