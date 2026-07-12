# NEXT_STEPS — living document

## ✅ Session 14 (2026-07-12) — correct IA + Reply Management module + enrichment parity

**Fixed the structure you asked for.** The sidebar mode switch now has four
self-contained sections (dropdown), each showing ONLY its own screens:
- **Outbound**: Lists · Database · Client Profile · ICP/Non-ICP · Formats ·
  Rules · Blueprints
- **Reply Management**: Inbox (review console) · Workspaces
- **Inbound (Visitors)**: website-visitor capture ONLY — no reply data
- **CRM**: Pipeline · Companies · Contacts · Activity
- **Master Dashboard** (always on): one rollup across all four sections.

**Reply Management module built** (was entirely missing):
- ReplyWorkspace model with **secrets encrypted at rest** (app/crypto.py) —
  API keys / Calendly tokens are Fernet-encrypted; the editor is write-only.
- Webhooks `POST /api/reply/webhooks/bison` and `/instantly` with faithful
  routing incl. **strict isolation** (unmatched → "Unrouted", never another
  workspace).
- Engine port: decision logic (send/skip_enrich/stop, stop-intents never
  drafted), per-workspace AI provider + fallback, JSON-tolerant parsing,
  exactly-one-signature, follow-up loop guard, Bison variable-merge (no
  wiping), Instantly reply-to-prospect threading.
- **AUTO_SEND kill-switch**: auto-send is OFF until `AUTO_SEND_ENABLED=1`;
  until then every would-be auto-send lands in Needs Review as `would_send`.
  This lets you point real webhooks at RevCadence with zero send risk.
- Review console (Inbox): Needs Review / Replied / Booked / Stopped, drawer
  with editable draft + **Approve & Send** (both platforms), mark booked,
  follow-ups. Workspaces page: full config editor + duplicate.

**Enrichment parity gaps closed**: ICP/Non-ICP as its own structured-JSON
section (procedure/categories/hard_non_icp/default parsed into the prompt),
output-variable selection (choose which variables to write), ESP column
(Microsoft/Google/Other from MX), Database view (all leads across lists,
filterable), split-by-industry tool.

Verified: engine guards (stop-intent, dedupe, isolation, kill-switch,
encrypted-at-rest), master dashboard aggregation, 40/40 smoke checks, build.

### Railway env to add (all optional/safe)
- Reply: `AUTO_SEND_ENABLED=1` ONLY when you're ready to let it auto-send
  (leave unset to keep everything in Needs Review). `REPLY_OPENAI_MODEL`
  (default gpt-4.1), `GEMINI_API_KEY` if using Gemini.
- Inbound: `INBOUND_WEBHOOK_KEY` (any random string) to enable the visitor
  webhook.

### Reply webhooks (point your platforms here after deploy)
- Bison: `https://<app>/api/reply/webhooks/bison?reply_workspace=<name>&fup_workspace=<name>`
- Instantly (per account): `https://<app>/api/reply/webhooks/instantly?workspace_name=<name>`
- Create the matching reply workspaces first (Reply Management → Workspaces),
  names must match the `?workspace_name=` / `?reply_workspace=` params.

### Still to port (next sessions, from REPLY_PORT_SPEC.md)
Calendly scheduling + anti-double-booking + diagnostic page (GAP A.6),
CRM-enrichment-from-payload + booked sync (GAP D), Ascendly Studio /
revenue module (GAP E), cutover migration (GAP F). Test-thread sandbox (GAP C)
for validating decisions on real threads before enabling auto-send.

## ✅ Session 13 (2026-07-12) — enrichment gaps 1–6 closed · reply-port spec filed

Enrichment now matches the reference dashboard (commit bb42a4f):
- **Model split**: `EXTRACT_MODEL` (gpt-4o-mini) / `WRITER_MODEL`
  (gpt-4.1-mini) / `COMPETITOR_MODEL` (gpt-4o-mini) — all env-switchable, no
  code change to upgrade/revert the writer.
- **Cost levers**: `EXTRACT_CONTENT_CHARS` (8000) / `WRITER_CONTENT_CHARS`
  (6000) / `MAX_TOTAL_CONTENT_CHARS` (10000) / `ENRICH_MAX_PAGES` (4).
- **Competitor finder**: select leads (or a whole view) → Find competitors →
  3 real companies per lead (anti-fabrication enforced; never invents),
  Competitors column with why-tooltips, `Top Competitors` in exports,
  skips leads that already have results.
- **Diagnostics**: `GET /api/enrich-lists/diag/dns` tells you definitively
  whether the free MX layer is rejecting dead domains or failing open (run it
  once on Railway after deploy); `/diag/email?e=…` tests one address.
- **Only Safe** (default ON, per workspace, in Client Profile): catch-all /
  unknown emails stop as `unsafe` and never spend writer tokens; turn it off
  to enrich them anyway. Dead code removed.
- **Sidebar**: the 3-button mode row is now a clean dropdown, matching the
  workspace switcher.
- Chips confirmed live full-list; select-all-in-view drives run / clear /
  export / find-competitors. 40/40 checks.

**Railway note:** no new required vars. Optional: `WRITER_MODEL`,
`REOON_API_KEY`, and the content-budget vars above.

## ▶ NEXT: the Reply Management port — docs/REPLY_PORT_SPEC.md

The full gap inventory (engine, workspace config, review console, CRM
enrichment, Ascendly Studio, cutover plan) is now committed as
`docs/REPLY_PORT_SPEC.md` with a 7-step build order. It's a multi-session
build touching live-inbox behavior — next session starts with step 1
(workspace model + encrypted secrets + editor). Say "start the reply port".

## ✅ Session 12 (2026-07-12) — mode switcher + full enrichment port

Read both uploaded handoffs (enrichment SYSTEM_HANDOFF + reply-manager
CLAUDE_HANDOFF — the latter is filed for the reply-module port).

**Mode switcher:** under the workspace switcher there's now an
Outbound / Inbound / CRM toggle — the sidebar shows ONLY the active mode's
screens (plus Dashboard and System). Persisted per user.

**Enrichment is now list-based** (commits 05f7927 + a8a4853) — the old
dashboard's system, ported faithfully per its handoff's hard rules:
- Funnel order preserved: FREE verify → Reoon → title gate + ICP (one
  scrape+extraction) → write copy reusing that context. Terminal statuses
  invalid/unsafe/skipped/error/done; resume never re-charges finished leads.
- Free verifier: syntax / MX via DNS-over-HTTPS / disposable / role-flag,
  SAFE-rejections-only, fails open to Reoon. Reoon real with REOON_API_KEY
  (demo verdict without it). Two-column display (System check + Reoon) kept.
- Old sections, new UI: Lists (import CSV → grid with live full-list chips,
  select-all-in-view, test-first-N cap, hard Stop, per-view export),
  Client Profile + ICP definition, Formats (accepts the same Format JSON),
  Rules (one line each, injected into the writer).

### To activate on Railway — YOU
`git push`, then add to BOTH services: `REOON_API_KEY` (real verification)
— `OPENAI_API_KEY` should already be set for real ICP/writing.
Then: pick a workspace → Outbound → Lists → New list (import a small CSV)
→ set Test first = 10 → **Verify → Enrich**.

### Seed the config from the old system (10 min, per workspace)
Old dashboard → copy Client Profile JSON → paste fields into Outbound →
Client Profile. Copy each Format JSON → Formats → "Paste Format JSON" →
Fill → Save. Copy Rules text → Rules. (Old files also in
outbound_personalization_v3 2/variable_sets/ + client_profiles/.)

### Still open from this request (next sessions, in order)
1. Reply-module port (per CLAUDE_HANDOFF): formats/response types/rules/
   auto-send as workspace settings + live reply bridge → Inbound mode.
2. Enrichment extras from the old system not yet ported: competitor finder,
   ESP column, split-by-industry, Database faceted view, import-field
   mapping UI (auto-map only today), industry taxonomy.
3. Inbound visitor pipeline (visitor webhook → enrich → draft in 10 min).

## ✅ Session 11 (2026-07-12) — full-width UI, grouped nav, Replies, CSV in/out

Shipped from your feedback:
- **Full-width layout** — removed the 1280px content cap; board and tables now
  use the whole screen.
- **Grouped sidebar** (Studio-style categories): Dashboard · OUTBOUND
  (Enrichment, Blueprints) · INBOUND (Replies) · CRM (Pipeline, Companies,
  Contacts, Activity) · SYSTEM (Jobs, Settings) · Admin.
- **Inbound → Replies page** (client-visible reporting): total/positive
  replies + meetings booked, intent filter, reply table with body previews —
  built on the reply activities imported from the Reply Manager.
- **Clay-style CSV import/export in Enrichment**: Import CSV (auto header
  mapping: first/last name, email, title, company, website; dedupes by email;
  optional auto-enrich of every row) and Export CSV (campaign-ready file with
  enrichment columns — upload straight to Instantly/Bison).

## 🔎 Re-sweep of legacy folders (2026-07-12) — see MIGRATION_GAP_REPORT §2b

Nothing lost, three things now on the record:
1. Portals production client JSONs live on the **Railway volume, not git** —
   the blueprint repo's git copies are stale (shimahara only exists in an old
   nested duplicate). `import_portals.py` must use the live Service API.
2. The enrichment dashboard has a **live production DB** (~69k leads at
   enrichment.ascendly.one). Its custom variables / formats / rules are config
   and must be exported into the RevCadence Clay-grid build; lead history stays.
3. `intelligence/examples/revcadence_full.json` + `variable_sets/*.json` are
   ready-made seed configs for the Clay-grid and intelligence engine builds.

## ▶ The three big builds you asked for (in order — next sessions)

1. **Reply module port (Inbound completeness).** Bring reply formats, response
   types, AI rules, and auto-send config into RevCadence as per-workspace,
   DB-backed settings (they're currently live in the Reply Manager — see
   MIGRATION_GAP_REPORT §2). Plus the live bridge: Reply Manager webhook →
   RevCadence activities/deals in real time, so Replies/Pipeline update without
   re-imports. This is what makes RevCadence the single pane your clients log
   into.
2. **Clay-grade enrichment grid (Outbound).** Named lists, column-per-
   enrichment view, run/verify per selection with credit caps, Reoon email
   verification, push-to-campaign (Instantly API) instead of CSV round-trips.
   The engine + jobs already exist; this is a UI + list-model build.
3. **Inbound visitor pipeline.** Visitor identification (RB2B/similar webhook)
   → auto-create company/contact → auto-enrich → alert + drafted email within
   10 minutes (job queue makes the SLA real). New but all plumbing exists.

## ✅ Session 10 (2026-07-11) — password reset script

Passwords are PBKDF2-hashed and unrecoverable (by design). If locked out:
1. First check Railway web service → Variables → `ADMIN_PASSWORD` (the value
   used at bootstrap is probably still correct).
2. Otherwise reset from the Railway **web** service shell:
   ```bash
   /opt/venv/bin/python -m scripts.reset_password --email rosis_s@ascendly.one --generate
   ```
   It prints the new password once — store it in a password manager. Or pass
   `--password "YourChosenPassword"` (min 12 chars) instead of `--generate`.
   Also reactivates deactivated users; audit-logged.

## ✅ Session 9 (2026-07-10) — the RevCadence web UI

React app (Vite, HashRouter) in `frontend/`, **served by the FastAPI web
service itself** — same origin, no CORS, no extra Railway service. The built
`frontend/dist` is committed, so deploys stay pure-Python (no Node needed on
Railway). Swagger remains at `/docs`.

Built (all wired to production APIs, no fake data):
- Login + persistent JWT auth, auto-logout on token expiry, protected routes
- Dark GHL-style sidebar; workspace switcher (masters only — client users are
  pinned to their single workspace); topbar with live api/worker status dots
- Dashboard: open pipeline, companies, contacts, active deals, meetings
  booked, replies, positive replies, stalled deals, jobs running; pipeline-by-
  stage bars; latest activity
- Pipeline: kanban by stage, drag & drop between columns, deal drawer with
  stage change, relations, timeline
- Companies: search/filter/create; detail page with enrichment provenance,
  ICP fit, contacts, deals, timeline, Enrich + Generate blueprint buttons
- Contacts: search table with company/title/email/source/score + drawer
- Enrichment: pick workspace → add/select companies → Enrich (no manual IDs),
  live job progress, links to results and blueprints
- Blueprints: list + sandboxed HTML preview
- Activity feed, Jobs (with cancel), Settings (system health), Admin
  (workspaces, users incl. client creation, aliases CRUD)
- Backend additions that power it (same commit series): richer board/summary/
  detail responses, /api/activities, static serving

### Local preview
```bash
cd ~/Desktop/revcadence
source venv/bin/activate 2>/dev/null || (python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt)
uvicorn app.main:app --reload      # http://localhost:8000 = the full UI
```
Frontend dev loop (optional): `cd frontend && npm install && npm run dev`
(proxies /api to localhost:8000; set VITE_API_BASE to point elsewhere).
**After changing frontend code:** `cd frontend && npm run build`, commit dist.

### Deploy
`git push` — no new Railway settings required (same web service serves the UI).

### Single next step after deployment
Open your Railway web URL, log in with your owner account, and switch
workspaces — then create your first client user in Admin and log in as them
in a private window to see the client-locked view.

## ✅ Session 8 (2026-07-10) — per-service Railway start commands

`railway.json` no longer defines any startCommand or healthcheck (it kept
overriding both services). The Procfile is deleted too (Nixpacks reads it and
becomes a second source of start-command ambiguity). Start commands now live in
per-service config files:

- `railway.web.json` — premigrate → alembic upgrade → uvicorn, healthcheck /healthz
- `railway.worker.json` — `python -m app.workers.runner`, NO healthcheck

### Set once in Railway (after push)
- **web service** → Settings → Config-as-code → set config file path to
  `railway.web.json`
- **worker service** → Settings → Config-as-code → set config file path to
  `railway.worker.json` (then remove the manually pasted start command so the
  file is the single source of truth)

Alternative if you prefer no config-as-code: leave the file paths unset and put
the two start commands in each service's Settings → Deploy → Start Command —
the neutral `railway.json` no longer fights you either way.

## ✅ Session 7 (2026-07-10) — worker heartbeat + stuck-job diagnosis

Jobs stayed `pending` because the worker service isn't processing the shared
Postgres queue. Code side (committed): worker now upserts a `heartbeats` row
every poll loop (migration `929417ea2ebf`); `/healthz` reports
`worker.alive/last_beat/info` (info includes which DB the worker sees and its
registered handlers); worker prints a LOUD warning if it boots on SQLite
(= missing DATABASE_URL on Railway); poll-loop exceptions no longer kill the
worker. Verified: heartbeat → /healthz, pending enrich job claimed and
processed to done/100%.

### Railway worker checklist (do in order, stop when fixed)
1. Worker service → **Variables**: `DATABASE_URL = ${{Postgres.DATABASE_URL}}`
   (this is the #1 suspect), plus `OPENAI_API_KEY` for real extraction.
2. Worker service → Settings → Deploy → **Custom Start Command** =
   `python -m app.workers.runner` (it must NOT run the uvicorn command from
   railway.json), and **clear the Healthcheck Path** (a worker serves no HTTP;
   an inherited /healthz check kills the deployment).
3. Redeploy the worker, open its Deploy Logs: expect
   `[worker] started · db=postgresql · handlers=[...]` — if it says
   `db=sqlite` or shows the WARNING banner, step 1 wasn't applied.

### One-glance verification
`GET /healthz` → `"worker": {"alive": true, ...}` and job 1 flips
pending → done with `progress: 100` (workers pick up old pending jobs
automatically; no re-enqueue needed).

## ✅ Session 6 (2026-07-10) — first-admin bootstrap (deadlock fix)

Fresh deployments could never create the first admin (admin API needs a token,
login needs a user). Fixed with two equivalent paths, both active ONLY while
the users table is empty and permanently disabled afterwards:

1. **Env vars (recommended for Railway):** set `ADMIN_EMAIL` + `ADMIN_PASSWORD`
   (optional `ADMIN_NAME`, `ADMIN_ORG` — default "RevCadence") on the web
   service → the owner is created automatically at startup. You can remove the
   vars after first boot; they do nothing once a user exists.
2. **One-time endpoint:** `POST /api/auth/bootstrap` {org, email, password
   (min 12 chars), name} — hard-403 the moment any user exists.

`scripts/seed.py` still works as a third option. Security unchanged after
bootstrap: all admin endpoints still require an owner/admin token.
Verified both paths + permanent lockout; 40/40 checks.

## ✅ Session 5 (2026-07-10) — migration accepted · gap audit · Enrichment Engine

**Migration:** production Reply Manager data imported and accepted. Gap audit in
`docs/MIGRATION_GAP_REPORT.md` — short version: all record types migrated;
all configuration (reply formats, prompts, client profiles, workspace/campaign
config, ai_rules) intentionally stays in the still-live legacy system until the
reply module moves. Knowledge base and sequences never existed as data — build
new. Blueprints = separate portals migration (planned). CRM tags: recreate by
hand when wanted.

**Enrichment Engine shipped** (commits 160d56e + this one):
- `app/enrichment/`: crawler (homepage + about/services/pricing pages),
  AI extraction via OpenAI (`OPENAI_API_KEY`; deterministic demo mode without
  it — full pipeline runs at zero cost), engine writing enrichment with
  per-field provenance, ICP fit, AI Revenue Score v1, timeline Activities
- Blueprint generation: enrichment → draft `Document` (kind=blueprint) with
  clean HTML — the portals blueprint flow, now native
- Jobs: progress % + note on every job (migration `7df433f3bf3c`), retry with
  exponential backoff, partial-write rollback
- API: `POST /api/enrich` (specific records), `POST /api/enrich/workspace`
  (bulk, capped, only-unenriched by default), `POST /api/blueprints/generate`,
  `GET /api/jobs/{id}/status`, company/contact/document create+detail endpoints
- 37/37 E2E checks

### To activate real AI enrichment on Railway (2 min) — YOU
Add `OPENAI_API_KEY` (and optionally `OPENAI_MODEL`, default gpt-4o-mini) to
BOTH the web and worker services → redeploy. Without it, enrichment runs in
demo mode (works, but heuristic-only extraction).

### Try it (after push + deploy)
1. `/docs` → POST `/api/companies` {workspace_id, name, website}
2. POST `/api/enrich` {workspace_id, company_ids: [id]}
3. GET `/api/jobs/{job_id}/status` → watch progress
4. GET `/api/companies/{id}` → enrichment with provenance
5. POST `/api/blueprints/generate` → GET `/api/documents/{id}` → open the HTML

### Next build priorities (in order)
1. **Web UI shell** — GHL-style sidebar, login, deals board, contacts with
   scores, blueprint preview, client Revenue Dashboard (the shareable surface)
2. **Reply Manager live bridge** — new booked meetings → Deals in real time
3. **Meeting System v1** (design doc Stage 7)
4. **Portals data migration** (`import_portals.py`, Document model is ready)


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

## 🔧 Swagger auth fix (2026-07-10, session 2d)

`/api/auth/me` used a raw `Header` param, which Swagger doesn't send — every
"Try it out" returned `401 Missing bearer token`. `get_ctx` now uses FastAPI's
`HTTPBearer` security scheme. Token format and all behavior unchanged.

**How to use /docs now:** POST `/api/auth/login` → copy the `token` value →
click the green **Authorize** button (top right) → paste the token (no "Bearer"
prefix needed) → Authorize. Every protected endpoint then works from Swagger.
Verified: OpenAPI declares HTTPBearer; auth/admin/CRM/jobs endpoints all
enforce it; 16/16 smoke checks pass.

## ✅ Session 3 (2026-07-10) — workspace alias system (pre-import fix)

Problem found before import: the same client has different workspace names per
source system (e.g. 'Ascendly: mainreplybison' in Reply Manager vs 'Ascendly'
in Enrichment), so a single `legacy_name` field couldn't map them.

Built:
- `WorkspaceAlias` table (workspace_id, source_system, external_name,
  external_id) with unique (source_system, external_name). Sources:
  reply_manager / enrichment / client_portals. Migration `fa785bd597ff`.
- Admin API: GET/POST/PATCH/DELETE `/api/admin/aliases` (master only).
- Importer resolves via aliases (exact match only — similar names are NEVER
  guessed). `legacy_name` kept as a fallback for backward compat only.
- Pre-flight mapping review: the importer prints every legacy name as
  MAPPED/UNMAPPED *before* writing; `--apply` ABORTS if anything is unmapped.
  Dry run = your explicit mapping review step.
- Importer bug fixed en route: legacy SQLite timestamps arrive as strings —
  now coerced safely.
- Tests: 30/30 (alias CRUD, multi-alias → one workspace, source separation,
  no-guessing, abort-writes-nothing, full fixture import, idempotent re-run).

### New import procedure (replaces old step 5 mapping note)

1. Create canonical workspaces (step 4) — `legacy_name` no longer required.
2. Create aliases for every legacy name, e.g. via /docs:
   - POST /api/admin/aliases {workspace_id: <Ascendly id>, source_system:
     "reply_manager", external_name: "Ascendly: mainreplybison"}
   - POST /api/admin/aliases {workspace_id: <Ascendly id>, source_system:
     "enrichment", external_name: "Ascendly"}
   - ...one per (source, name) pair. Don't know all the legacy names? Just run
     the dry-run first — the mapping review lists every name it found.
3. Dry run: `python -m scripts.import_legacy --legacy-db-url "..."` → review
   the MAPPED/UNMAPPED report.
4. Fix any UNMAPPED by adding aliases; repeat until the review is clean.
5. Apply: add `--apply`. It aborts (writing nothing) if anything is unmapped.

## ✅ Session 4 (2026-07-10) — production dry-run prep

Findings:
- The local Reply Manager DB copy is a stale dev snapshot: workspaces
  Ascendly / Insight Media Labs / Maildoso / Webaholics, ZERO leads, and no
  opportunities/crm_stages tables. **All real data is only in production
  Postgres**, so the authoritative mapping report must run on Railway.
- Importer hardened for that run: missing legacy tables are reported in the
  dry-run output (notes) instead of crashing; duplicate notes deduped.
  30/30 tests pass.

## ▶ NEXT ACTION: run the production dry run (10 min) — YOU

Nothing is written by this — it's read-only against legacy and rolls back on
the new DB. Two steps:

1. Get the LEGACY database URL: old Reply Manager Railway project → Postgres
   service → **Connect** tab → copy the **Public Network** connection string
   (`postgresql://postgres:...@...proxy.rlwy.net:PORT/railway`).
   ⚠ Must be the PUBLIC URL — the new project cannot resolve the old project's
   private `postgres.railway.internal` hostname (private networking is
   per-project).

2. NEW RevCadence project → web service → Shell:
   ```bash
   /opt/venv/bin/python -m scripts.import_legacy \
     --legacy-db-url "postgresql://postgres:<pw>@<host>.proxy.rlwy.net:<port>/railway"
   ```
   (`DATABASE_URL` for the new DB is already injected into that shell; do not
   pass it. `--apply` is intentionally absent.)

3. Read the `WORKSPACE MAPPING REVIEW` block it prints:
   - Every production legacy workspace name is listed as MAPPED or UNMAPPED.
   - Expected UNMAPPED on first run (from your examples):
     `Ascendly: mainreplybison`, `Revcadence`, `Insight Media Labs`, likely
     `Webaholics`, `Maildoso`.
   - For each one, create the alias via /docs →
     POST /api/admin/aliases {workspace_id, source_system: "reply_manager",
     external_name: "<exact name from the report>"}.
   - Also check `notes` in the JSON report for missing-table warnings.

4. Re-run the same command until the review shows every name MAPPED and
   `unmapped_workspaces` is `[]`. Paste the final report back to Claude.

**Only after that**: we run `--apply` together (still never touches the legacy
DB) and spot-check per the verification checklist in docs/MIGRATION_PLAN.md §5.

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

**Important — use the app's venv interpreter.** Railway's shell does NOT
auto-activate `/opt/venv`, so plain `python` is the bare system Python and fails
with `ModuleNotFoundError: No module named 'jwt'` (PyJWT and everything else
live only inside the venv). Correct command in the Railway service shell:

```bash
/opt/venv/bin/python -m scripts.seed --org "RevCadence" --email rosis_s@ascendly.one --password <STRONG-PASSWORD>
```

Running locally instead? Use the project venv with the Railway DATABASE_URL:

```bash
cd ~/Desktop/revcadence
python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt
DATABASE_URL="<railway-postgres-url>" python -m scripts.seed --org "RevCadence" --email rosis_s@ascendly.one --password <STRONG-PASSWORD>
```

The script is idempotent (safe to re-run) and now prints exactly this guidance
if run with the wrong interpreter. Verify: POST /api/auth/login on /docs →
expect a token and `"role": "owner"`.

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
