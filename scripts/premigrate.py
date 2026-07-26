"""Pre-migration bootstrap — runs before `alembic upgrade head` on every deploy.

Handles the three possible database states:
1. Fresh/empty DB            → do nothing; Alembic creates the whole schema.
2. Alembic-managed DB        → do nothing; Alembic applies pending migrations.
3. Pre-Alembic DB (tables created by the old startup create_all, no
   alembic_version) → ADOPT it: create any tables/columns added since
   (e.g. documents), then `alembic stamp head` so Alembic takes over.

Idempotent and safe to run on every boot. Never drops or modifies data.
"""
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app import models  # noqa: F401 — register every model on Base.metadata
from app.db import Base, engine, migrate


def main():
    insp = inspect(engine)
    tables = set(insp.get_table_names())

    if "alembic_version" in tables:
        print("[premigrate] alembic_version found — normal migration path")
        # Keep the legacy additive *column* sync for mapped tables, but never
        # create missing tables here. Pending Alembic migrations own new tables;
        # creating them before `alembic upgrade head` causes duplicate-table
        # failures during deployment.
        migrate(create_missing_tables=False)
        print("[premigrate] additive column sync complete")
        return
    if "organizations" not in tables:
        print("[premigrate] fresh database — Alembic will create the schema")
        return

    print("[premigrate] pre-Alembic schema detected — adopting it")
    Base.metadata.create_all(engine)   # add tables that didn't exist back then
    migrate()                          # add columns that didn't exist back then
    command.stamp(Config("alembic.ini"), "head")
    print("[premigrate] created missing tables/columns and stamped head")


if __name__ == "__main__":
    main()
