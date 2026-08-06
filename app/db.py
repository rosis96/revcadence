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
    # Headroom for the enrichment worker pool: the runner can process several
    # jobs at once (JOB_CONCURRENCY), and each job fans leads across N worker
    # threads — so peak sessions ≈ JOB_CONCURRENCY × per-job workers. Keep this
    # comfortably above that. Postgres only — SQLite uses a single connection.
    **({} if _is_sqlite else {"pool_size": 30, "max_overflow": 40}),
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


def migrate(*, create_missing_tables: bool = True):
    """Apply the legacy additive schema sync.

    ``create_missing_tables`` remains enabled for local SQLite setup and
    pre-Alembic database adoption. Alembic-managed production databases disable
    it so a pending Alembic migration remains the sole owner of new tables.

    Existing mapped tables still receive missing columns. Nothing is dropped or
    rewritten.
    """
    from . import models  # noqa: F401  (ensure all models are registered on Base)
    if create_missing_tables:
        Base.metadata.create_all(engine)
    insp = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        existing = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing:
                continue
            coltype = col.type.compile(engine.dialect)
            # Each ADD COLUMN runs in its OWN transaction so a single failure (e.g.
            # an incompatible type on one column) can't roll back every other add and
            # break boot. Columns are added nullable (compile() emits no NOT NULL), so
            # this is safe on populated tables; app-side defaults apply to new rows.
            try:
                with engine.begin() as conn:
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {coltype}'))
            except Exception as e:  # noqa: BLE001
                print(f"[migrate] skipped {table.name}.{col.name}: {str(e)[:160]}")
