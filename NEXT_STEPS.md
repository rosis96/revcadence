# NEXT_STEPS — living document

_Updated: 2026-07-10 (session 2). This file is updated at the end of every
working session: what was done, what to do next, in order. Do the steps top to bottom._

## ✅ Done session 2 (2026-07-10) — database foundation

- **Alembic added** as the authoritative migration system for Postgres.
  Initial migration `99d538287e82` creates all 15 Phase 0 tables:
  organizations, workspaces, users, memberships (roles live as the `role`
  column here — no separate table needed), companies, contacts, deals, stages,
  activities, tasks, notes, documents, jobs, audit_log, alembic_version.
- **Documents model added** (blueprints/agreements/proposals with signing state
  + view tracking — ready for the portals migration).
- **Deploy runs migrations automatically**: web start command is now
  `alembic upgrade head && uvicorn ...` (railway.json + Procfile). The worker
  does NOT migrate (avoids races); it simply restarts until the web has migrated.
- **`/healthz` now reports the truth**: `db` (postgresql vs sqlite), `migration`
  (applied revision), `tables` (count). If `db` says `sqlite` on Railway, that
  service is missing `DATABASE_URL` — the silent-fallback bug.
- Verified: fresh-DB upgrade creates all 15 tables, re-run is a no-op,
  autogenerate parity check shows zero drift, 16/16 smoke checks still pass.

## 🔧 Deploy-failure fix (2026-07-10, session 2b)

The first migration deploy failed healthcheck. Root cause: `alembic.ini` was
missing `prepend_sys_path = .`, so the `alembic` binary couldn't import the
`app` package (`ModuleNotFoundError: No module named 'app'`) — migrations
crashed before uvicorn ever started. Fixed by adding `prepend_sys_path = .`
and switching start commands to `python -m alembic upgrade head`. Reproduced
and verified locally with the exact Railway invocation.

If a deploy ever fails healthcheck again: check the **Deploy Logs** (not build
logs) — the crash traceback is printed there before the healthcheck retries.

## 🔧 Deploy-failure fix #2 (2026-07-10, session 2c)

Second failure: `DuplicateTable: relation "organizations" already exists`.
Root cause: the FIRST deploy (pre-Alembic code) had already run `create_all`
once `DATABASE_URL` reached the service — so Postgres had the old tables but
no `alembic_version` stamp, and the initial migration collided with them.

Fix: `scripts/premigrate.py` now runs before Alembic on every boot and handles
all three DB states automatically:
- fresh DB → no-op (Alembic creates everything)
- Alembic-managed → no-op (Alembic applies pending migrations)
- pre-Alembic tables → adopts them: creates missing tables/columns
  (e.g. `documents`), then `alembic stamp head`

Verified locally against a simulation of the exact Railway state. No manual
SQL needed — just push.

## ▶ Do now: get the schema onto Railway (5 min) — YOU

1. Push:
   ```bash
   cd ~/Desktop/revcadence && git push
   ```
2. Railway auto-deploys. Watch the web service deploy logs — you should see
   `Running upgrade  -> 99d538287e82, phase 0 initial schema`.
3. Open `https://<your-domain>/healthz`. Expected:
   ```json
   {"ok": true, "db": "postgresql", "migration": "99d538287e82", "tables": 15}
   ```
   - If `db` is `"sqlite"`: the web service has no `DATABASE_URL`. Fix: web
     service → Variables → add `DATABASE_URL = ${{Postgres.DATABASE_URL}}`,
     redeploy. **Do the same check on the worker service.**
4. Confirm in Postgres directly (Railway → Postgres → Data): 15 tables.
5. Then continue with the original steps 3–6 below (seed → workspaces →
   migrate legacy data → first client login).

## How migrations work from now on (for every schema change)

1. Edit/add models in `app/models/`.
2. `DATABASE_URL="sqlite:////tmp/fresh.db" python3 -m alembic upgrade head` then
   `... alembic revision --autogenerate -m "describe change"` — review the
   generated file in `migrations/versions/`.
3. Run `python -m tests.test_smoke`.
4. Commit + push. Railway applies it on deploy automatically. Never edit an
   already-deployed migration; add a new one.

## ✅ Done session 1 (2026-07-10)

- Platform audit + full design doc (RevCadence-Audit-and-Platform-Design.docx)
- New unified repo scaffolded: identity (org/workspace/user/roles), JWT auth,
  hard workspace isolation, unified CRM object model, DB-backed job queue,
  audit log, admin API, kanban board API, client dashboard summary API
- Legacy migration script (`scripts/import_legacy.py`) with dry-run mode
- 16/16 end-to-end smoke checks passing (incl. client-isolation tests)
- Git repo initialized with first commit

## 1. Push to GitHub (5 min) — YOU

```bash
cd ~/Desktop/revcadence
# create a PRIVATE repo named revcadence on github.com, then:
git remote add origin git@github.com:<your-username>/revcadence.git
git push -u origin main
```

## 2. Deploy on Railway (10 min) — YOU

1. Railway → New Project → **Deploy from GitHub repo** → `revcadence`
2. In the project: **+ New → Database → PostgreSQL**
3. On the web service → Variables:
   - `DATABASE_URL` = `${{Postgres.DATABASE_URL}}`
   - `JWT_SECRET` = output of `python3 -c "import secrets; print(secrets.token_hex(32))"`
4. **+ New → Service from the same repo**, set start command
   `python -m app.workers.runner`, add the same two variables. (This is the worker.)
5. Web service → Settings → Networking → add a domain (e.g. `api.revcadence.…`
   or a Railway-generated one for now).
6. Verify: open `https://<domain>/healthz` → `{"ok": true}` and `/docs` loads.

## 3. Seed the master account (2 min) — YOU

Railway web service → ⋯ → **Shell** (or locally with the Railway DATABASE_URL):

```bash
python -m scripts.seed --org "Ascendly" --email rosis_s@ascendly.one --password <STRONG-PASSWORD>
```

Then test: `POST /docs → /api/auth/login`. Keep this password in a manager —
there is no reset flow yet (step 7).

## 4. Create workspaces matching your existing clients (5 min)

Via `/docs → POST /api/admin/workspaces` (logged in as owner). **Important:**
set `legacy_name` to the exact `workspace_name` string used in the old Reply
Manager (e.g. "Ascendly", "Webaholics") — the migration matches on it.

## 5. Migrate the legacy data — TOGETHER

1. Get the old Reply Manager `DATABASE_URL` from Railway (Postgres service → Connect).
2. Dry run first (writes nothing, prints a report):
   ```bash
   python -m scripts.import_legacy --legacy-db-url "postgresql://..."
   ```
3. Review the report: `unmapped_workspaces` should be empty (fix via step 4),
   counts should look right.
4. Apply: add `--apply` (add `--create-missing --org-id 1` only if you want
   unmapped workspaces auto-created).
5. Spot-check in `/docs`: `/api/contacts`, `/api/deals`, a contact's `/timeline`.

The script is idempotent — safe to re-run; it skips already-imported records.

## 6. Create the first client login and verify isolation (5 min)

`POST /api/admin/users` with `role: "client"` and their single workspace id.
Log in as them; confirm `/api/auth/me` shows one workspace and `/api/deals`
shows only their data. This is the account you hand to a client.

## 7. Next build session (in order)

1. **Web UI shell** — React app: GHL-style dark sidebar, workspace switcher
   (masters only), login page, deals board, contacts list, the client Revenue
   Dashboard (renders `/api/dashboard/summary`). This is the client-shareable surface.
2. **Password reset + invite emails** (needs an email sender — reuse an
   Instantly mailbox or Resend).
3. **Reply Manager bridge**: webhook/API so new "Meeting Booked" leads create
   Deals here in real time (same pattern as the old CRM hook) — keeps both
   systems in sync during the transition.
4. **Wire enrichment as a job kind** (`enrich_contact` in workers/registry.py)
   using the run.py pipeline.
5. **Portals data migration** (client JSONs → Documents tables) per
   docs/MIGRATION_PLAN.md §3.

## Parked (from the design doc, in priority order)

Meeting System v1 → proposal open-tracking → automation recipes → daily briefing.

## Hygiene reminders (from the audit — do when touching the old systems)

- Rotate any API keys that appeared in screenshots/chats.
- Old reply manager: set a strong DASHBOARD_PASSWORD (no "changeme").
- Portals service: confirm the Railway volume is attached (CLIENTS_DIR=/data)
  so signed agreements survive redeploys.
