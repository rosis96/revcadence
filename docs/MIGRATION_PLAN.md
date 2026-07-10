# Data Migration Plan — legacy systems → RevCadence

Principle: the old systems keep running in production until each module is
migrated AND verified. Migration is additive and idempotent; nothing is deleted
from the old databases, ever.

## 1. Reply Manager DB (leads, opportunities, workspaces) — script ready

Handled by `scripts/import_legacy.py` (see NEXT_STEPS.md step 5).

| Legacy | → RevCadence | Notes |
|---|---|---|
| `workspaces.name` (string) | `Workspace.legacy_name` | Pre-create workspaces with matching `legacy_name`. Reply/follow-up twin workspaces for one client should map to ONE new workspace (set both legacy names' data to it by running the import after pointing both legacy names — or merge post-import). |
| `leads` | `Contact` (dedupe by email per workspace) + `Company` (by name) | `legacy_lead_ids` keeps every old id on the contact. |
| `leads.reply_text` / `main_reply` / `thread` | `Activity` rows (`email_in`, `email_out`/`reply_drafted`, `import`) | Full thread JSON preserved in `Activity.data`. |
| `opportunities` + `crm_stages` | `Deal` + `Stage` (matched by stage name) | `legacy_opportunity_id` prevents duplicates. |

Not migrated yet (stays live in the old system): workspace API keys, reply
formats, client profiles, app settings, proposed Calendly slots. These move only
when the reply pipeline itself moves (last).

## 2. What runs where during the transition

- Old Reply Manager keeps processing webhooks and sending replies (untouched).
- New leads flow into RevCadence via the bridge (NEXT_STEPS §7.3) once built;
  until then, re-run `import_legacy.py` periodically — it's incremental.

## 3. Client Portals (blueprints/agreements) — next script to write

Plan: `scripts/import_portals.py` reading the portals Service API
(`GET /service/clients` with `X-Service-Key`), creating:
- `Document` rows (new model: kind=blueprint|agreement, status, slug, html ref)
- executed PDFs → object storage (Railway volume or S3-compatible)
- audit arrays → `AuditLog` rows
Blocked on: adding the Document model (small) + deciding object storage.

## 4. Enrichment lists (SQLite) — migrate last

Lists/leads in the enrichment dashboard are working batches, not a system of
record. Strategy: don't migrate history; wire NEW enrichment runs to write to
`Contact`/`Company` via the `enrich_contact` job kind. Old CSV exports remain
available in the old tool.

## 5. Verification checklist (run after every migration)

- [ ] Row counts: report numbers vs `SELECT count(*)` in legacy
- [ ] Spot-check 5 contacts: email, company link, timeline shows their thread
- [ ] Spot-check 3 deals: stage, value, contact link match the old kanban
- [ ] Client-role login sees only their workspace's imported data
- [ ] Re-run the script → all "skipped_existing", zero new rows
