"""RevCadence core API.

Boot: uvicorn app.main:app --host 0.0.0.0 --port $PORT
Docs: /docs (Swagger) — every endpoint except /healthz and login requires a
Bearer token from POST /api/auth/login.
"""
from fastapi import FastAPI

from . import config
from .db import engine, init_db
from .routers import (admin, agreements, auth, billing, client, crm, deal_workspace, devapi, enrich,
                      enrich_lists, inbound, invoices, jobs, mailbox, oauth, onboarding, public, reply, search)

app = FastAPI(title=config.APP_NAME, version=config.VERSION)


@app.on_event("startup")
def _startup():
    init_db()
    print(f"[revcadence] DB backend: {engine.dialect.name.upper()}")
    from .bootstrap import bootstrap_from_env, maybe_reset_admin
    from .db import SessionLocal
    db = SessionLocal()
    try:
        bootstrap_from_env(db)
        maybe_reset_admin(db)  # ADMIN_FORCE_RESET=1 recovery path
        from .provision import backfill_all
        backfill_all(db)  # existing workspaces gain any missing package pieces
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
app.include_router(search.router)
app.include_router(devapi.router)
app.include_router(admin.router)
app.include_router(billing.router)
app.include_router(crm.router)
app.include_router(jobs.router)
app.include_router(enrich.router)
app.include_router(enrich_lists.router)
app.include_router(inbound.router)
app.include_router(reply.router)
app.include_router(onboarding.router)
app.include_router(client.router)
app.include_router(agreements.router)
app.include_router(invoices.router)
app.include_router(mailbox.router)
app.include_router(oauth.router)
app.include_router(deal_workspace.router)
app.include_router(public.router)

# ---------------------------------------------------------------- blueprint host
# On a `blueprint.<domain>` host, serve the bare `/{slug}` as the client's
# published Growth Blueprint (blueprint.revcadence.com/acme-inc). Everything else
# (api, assets, healthz, the /p/ route) passes through untouched. Extra hosts can
# be listed in BLUEPRINT_HOSTS (comma-separated).
import os as _os  # noqa: E402

_BLUEPRINT_HOSTS = tuple(h.strip().lower() for h in _os.getenv("BLUEPRINT_HOSTS", "").split(",") if h.strip())
_AGREEMENT_HOSTS = tuple(h.strip().lower() for h in _os.getenv("AGREEMENT_HOSTS", "").split(",") if h.strip())
_INVOICE_HOSTS = tuple(h.strip().lower() for h in _os.getenv("INVOICE_HOSTS", "").split(",") if h.strip())
_RESERVED_SEG = {"", "api", "assets", "healthz", "docs", "redoc", "openapi.json",
                 "p", "agreement", "invoice", "favicon.ico", "robots.txt", "sitemap.xml",
                 "favicon-16x16.png", "favicon-32x32.png", "apple-touch-icon.png",
                 "android-chrome-192x192.png", "android-chrome-512x512.png", "site.webmanifest"}


@app.middleware("http")
async def _public_host_router(request, call_next):
    """On a bare public host (blueprint./agreement./invoice.<domain>), serve the
    client's document at `/{slug}` (and `/{slug}/pdf` for agreements/invoices).
    The internal app is never exposed at these hosts' root. Everything else
    (api, assets, healthz) passes through."""
    host = (request.headers.get("host") or "").split(":")[0].lower()
    from .routers import public as _pub

    def _is(kind_prefix, extra):
        return host.startswith(kind_prefix) or host in extra

    if request.method in ("GET", "HEAD"):
        path = request.url.path.strip("/")
        segs = path.split("/") if path else []
        if _is("agreement.", _AGREEMENT_HOSTS):
            if not path:
                return _pub._404
            if len(segs) == 1 and segs[0] not in _RESERVED_SEG:
                return _pub._render_agreement(segs[0])
            if len(segs) == 2 and segs[1] == "pdf":
                return _pub.public_agreement_pdf(segs[0])
        elif _is("invoice.", _INVOICE_HOSTS):
            if not path:
                return _pub._404
            if len(segs) == 1 and segs[0] not in _RESERVED_SEG:
                return _pub._render_invoice(segs[0])
            if len(segs) == 2 and segs[1] == "pdf":
                return _pub.public_invoice_pdf(segs[0])
        elif _is("blueprint.", _BLUEPRINT_HOSTS):
            if path and "/" not in path and path not in _RESERVED_SEG:
                return _pub._render_blueprint(path)
            if not path:
                return _pub._404
    # POST to a signing endpoint on the agreement host must still reach the router
    if _is("agreement.", _AGREEMENT_HOSTS) and request.method == "POST":
        return await call_next(request)
    return await call_next(request)

# ---------------------------------------------------------------- frontend
# The React app (frontend/dist, committed) is served by this same service —
# same origin as the API, so no CORS and no second Railway service.
import os  # noqa: E402

from fastapi.responses import FileResponse, RedirectResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

# Client-facing external API: its own app so /api/v1/docs + /api/v1/openapi.json
# document ONLY the public surface (internal Swagger stays at /docs).
from .extapi.routes import extapp  # noqa: E402

app.mount("/api/v1", extapp)

_DIST = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")

_ICON_FILES = {
    "favicon.ico": "image/x-icon",
    "favicon-16x16.png": "image/png",
    "favicon-32x32.png": "image/png",
    "apple-touch-icon.png": "image/png",
    "android-chrome-192x192.png": "image/png",
    "android-chrome-512x512.png": "image/png",
    "site.webmanifest": "application/manifest+json",
}


def _icon_route(fname: str, media: str):
    async def _serve():
        p = os.path.join(_DIST, fname)
        if os.path.isfile(p):
            return FileResponse(p, media_type=media,
                                headers={"Cache-Control": "public, max-age=86400"})
        return RedirectResponse("/")
    return _serve


for _fname, _media in _ICON_FILES.items():
    app.get(f"/{_fname}", include_in_schema=False)(_icon_route(_fname, _media))

if os.path.isdir(_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(_DIST, "assets")), name="assets")

    @app.get("/", include_in_schema=False)
    def _index():
        return FileResponse(os.path.join(_DIST, "index.html"))
else:
    @app.get("/", include_in_schema=False)
    def _index():
        return RedirectResponse("/docs")
