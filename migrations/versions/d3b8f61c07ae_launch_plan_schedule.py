"""launch plan: schedule, dependencies, milestones, baseline

Revision ID: d3b8f61c07ae
Revises: c5e91a37d8b4
Create Date: 2026-08-17

Additive only. The columns behind the Timeline/List/Board views: a start date so
a task is a span rather than a due date, a dependency edge list so blocked-ness
and the critical path can be derived, a milestone flag, and the baseline the
"baseline vs actual" toggle compares against.
"""
from alembic import op
import sqlalchemy as sa


revision = "d3b8f61c07ae"
down_revision = "c5e91a37d8b4"
branch_labels = None
depends_on = None

_TASK_COLUMNS = (
    ("start_at", sa.DateTime()),
    ("is_milestone", sa.Boolean(), "0"),
    ("depends_on", sa.JSON()),
    ("baseline_start_at", sa.DateTime()),
    ("baseline_due_at", sa.DateTime()),
)
_LAUNCH_COLUMNS = (
    ("name", sa.String(255)),
    ("prospect_target", sa.Integer(), "0"),
    ("baseline_at", sa.DateTime()),
)


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    existing = _columns("launch_tasks")
    for name, kind, *default in _TASK_COLUMNS:
        if name not in existing:
            op.add_column("launch_tasks", sa.Column(
                name, kind, server_default=(default[0] if default else None)))
    existing = _columns("client_launches")
    for name, kind, *default in _LAUNCH_COLUMNS:
        if name not in existing:
            op.add_column("client_launches", sa.Column(
                name, kind, server_default=(default[0] if default else None)))


def downgrade() -> None:
    existing = _columns("launch_tasks")
    for name, *_ in _TASK_COLUMNS:
        if name in existing:
            op.drop_column("launch_tasks", name)
    existing = _columns("client_launches")
    for name, *_ in _LAUNCH_COLUMNS:
        if name in existing:
            op.drop_column("client_launches", name)
