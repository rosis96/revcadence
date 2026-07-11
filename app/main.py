"""RevCadence core API.

Boot: uvicorn app.main:app --host 0.0.0.0 --port $PORT
Docs: /docs (Swagger) — every endpoint except /healthz and login requires a
Bearer token from POST /api/auth/login.
"""
from fastapi import FastAPI

from . import config
from .db import engine, init_db
from .routers import admin, auth, crm, enrich, jobs

app = FastAPI(title=config.APP_NAME, version=config.VERSION)


@app.on_event("startup")
def _startup():
    init_db()
    print(f"[revcadence] DB backend: {engine.dialect.name.upper()}")
    from .bootstrap import bootstrap_from_env
    from .db import SessionLocal
    db = SessionLocal()
    try:
        bootstrap_from_env(db)
    finally:
        db.close()


@app.get("/healthz")
def healthz():
    """Also reports which DB backend is live and the applied migration revision —
    if db says 'sqlite' on Railway, the service is missing DATABASE_URL (the
    silent-fallback bug from the old reply manager)."""
    info = {"ok": True, "app": config.APP_NAME, "version": config.VERSION,
            "db": engine.dialect.name, "migration": None, "tables": 0,
            "worker": {"alive": False, "last_beat": None, "info": {}}}
    try:
        from sqlalchemy import inspect, text
        info["tables"] = len(inspect(engine).get_table_names())
        with engine.connect() as conn:
            info["migration"] = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:
        pass  # alembic_version absent on sqlite dev — fine
    try:
        from datetime import datetime, timedelta
        from .db import SessionLocal
        from .models.jobs import Heartbeat
        db = SessionLocal()
        hb = db.get(Heartbeat, "worker")
        if hb is not None:
            stale_after = timedelta(seconds=max(config.WORKER_POLL_SECONDS * 4, 30))
            info["worker"] = {
                "alive": (datetime.utcnow() - hb.at) < stale_after,
                "last_beat": hb.at.isoformat(),
                "info": hb.info or {},
            }
        db.close()
    except Exception:
        pass  # heartbeats table not migrated yet
    return info


app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(crm.router)
app.include_router(jobs.router)
app.include_router(enrich.router)
