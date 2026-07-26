# RevCadence

The unified Revenue Operating System. This repo is **Phase 0 — Foundation** from
the platform design doc: real identity (orgs → workspaces → users with roles),
hard workspace isolation, the unified CRM object model, and a DB-backed job queue.
The existing Reply Manager, Client Portals, and Enrichment services keep running
untouched; they migrate into this platform module by module.

## The master/client model (why this repo exists)

- **Master users** (owner/admin of the Ascendly org) see every workspace and get
  the workspace switcher.
- **Client users** are hard-locked to exactly one workspace. A client logging in
  with the username you issue can never see — or query — another client's data.
  Enforcement is in the data layer (`app/auth.py: workspace_ids_for_query`), not the UI.

## Run locally

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m scripts.seed --org "Ascendly" --email you@ascendly.one --password <pw>
uvicorn app.main:app --reload
# open http://localhost:8000/docs
```

No DATABASE_URL → SQLite file (dev). Set DATABASE_URL for Postgres.

## Test

```bash
python -m tests.test_smoke   # 16 end-to-end checks incl. workspace isolation
```

## Layout

```
app/
  main.py            FastAPI app + routers
  config.py          env config (DATABASE_URL, JWT_SECRET)
  db.py              engine, sessions, additive migrations (create_all + ALTER ADD)
  auth.py            passwords, JWT, AuthContext, workspace scoping  ← the security core
  models/
    identity.py      Organization, Workspace, User, Membership (roles)
    crm.py           Company, Contact, Deal, Stage, Activity, Task, Note
    jobs.py          Job queue table
    audit.py         org-wide audit log
  routers/
    auth.py          /api/auth/login, /api/auth/me
    admin.py         /api/admin/* — workspaces + users (master only)
    crm.py           /api/companies|contacts|deals|deals/board|dashboard/summary
    jobs.py          /api/jobs — enqueue/list/cancel
  workers/
    registry.py      job-kind registry (register new capabilities here)
    runner.py        worker loop (2nd Railway service: python -m app.workers.runner)
scripts/
  seed.py            create master org + first owner
  import_legacy.py   migrate old Reply Manager DB → this schema (dry-run first)
tests/test_smoke.py  end-to-end checks
docs/                MIGRATION_PLAN.md and future docs
NEXT_STEPS.md        ← the living to-do; updated every working session
```

## Deploy (Railway) — see NEXT_STEPS.md for the full checklist

The web service uses `railway.web.json`; the worker uses
`railway.worker.json`. Both share the same Postgres `DATABASE_URL`,
`JWT_SECRET`, and enrichment credentials. The neutral `railway.json`
intentionally has no start command so it cannot override either service.
