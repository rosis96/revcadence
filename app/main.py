"""RevCadence core API.

Boot: uvicorn app.main:app --host 0.0.0.0 --port $PORT
Docs: /docs (Swagger) — every endpoint except /healthz and login requires a
Bearer token from POST /api/auth/login.
"""
from fastapi import FastAPI

from . import config
from .db import engine, init_db
from .routers import admin, auth, crm, jobs

app = FastAPI(title=config.APP_NAME, version=config.VERSION)


@app.on_event("startup")
def _startup():
    init_db()
    print(f"[revcadence] DB backend: {engine.dialect.name.upper()}")


@app.get("/healthz")
def healthz():
    return {"ok": True, "app": config.APP_NAME, "version": config.VERSION}


app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(crm.router)
app.include_router(jobs.router)
