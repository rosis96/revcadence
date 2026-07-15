"""Engine, session, and the additive-migration pattern used across Ascendly
services: create_all for new tables, ALTER TABLE for new columns (safe on both
Postgres and SQLite)."""
from contextlib import contextmanager

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from . import config


class Base(DeclarativeBase):
    pass


_is_sqlite = config.DATABASE_URL.startswith("sqlite")
engine = create_engine(
    config.DATABASE_URL,
    pool_pre_ping=True,
    # Headroom for the enrichment worker pool: a run with N concurrent workers
    # opens N sessions at once. Postgres only — SQLite uses a single connection.
    **({} if _is_sqlite else {"pool_size": 30, "max_overflow": 20}),
    # timeout: let concurrent workers wait for the write lock (dev/SQLite) rather
    # than erroring "database is locked". Postgres handles concurrency natively.
    connect_args={"check_same_thread": False, "timeout": 30} if _is_sqlite else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    """FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    """SQLite (local dev): create/patch tables directly, no Alembic needed.
    Postgres (production): do NOTHING — Alembic owns the schema. Migrations run
    via `alembic upgrade head` in the deploy start command; doing create_all here
    would mask missing migrations."""
    from . import models  # noqa: F401  (register all models)
    if engine.dialect.name == "sqlite":
        Base.metadata.create_all(engine)
        migrate()


def migrate():
    """Additive migration: create any brand-new tables (create_all is
    checkfirst — only makes missing tables, never alters existing ones), then for
    every mapped column missing from a live table, ALTER TABLE ... ADD COLUMN.
    Never drops or rewrites anything, so it's safe on every deploy."""
    from . import models  # noqa: F401  (ensure all models are registered on Base)
    Base.metadata.create_all(engine)   # create missing tables (e.g. client_profiles)
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                coltype = col.type.compile(engine.dialect)
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {coltype}'))
