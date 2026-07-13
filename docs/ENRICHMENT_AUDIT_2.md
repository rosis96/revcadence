# Enrichment audit vs legacy dashboard (2026-07-13)

Full endpoint-by-endpoint comparison of RevCadence enrichment against the
Ascendly Enrichment Dashboard reference. Legend: ✅ present · ➕ added this pass.

## At parity (already built, verified)
Lists CRUD · CSV import · leads grid + live full-list chips (all/processed/
verified/enriched/nonicp/no_website/invalid/unsafe/notrun/title_rejected) ·
Verify · Verify→Enrich · test-first-N cap · Only Safe · select-all-in-view ·
Find competitors · Split by industry · Clear results · Clear verification ·
Export · per-workspace config (profile/ICP/formats/rules) · DNS + email
diagnostics · ESP column · Database view · funnel statuses + resume · model
split + content budgets.

## Fixed / added this pass
- ➕ **Uploaded columns preserved** — import kept only 6 standard fields and
  dropped the rest; now every uploaded column survives import and returns on
  export (+ shown in the lead drawer). (commit c650f83)
- ➕ **Stop persists across reload** — `GET /{list}/active-job`: the grid
  reconnects to a run already in progress, so the Stop button + live progress
  survive a page refresh (previously the UI only knew about jobs it launched
  itself). 
- ➕ **Delete leads** — `POST /{list}/delete-leads` (selection or whole view) +
  a Delete button. (legacy DELETE /lists/{id}/leads)
- ➕ **Reoon balance chip** — `GET /reoon/balance` shows remaining credits (or
  "demo" without a key).

## Intentionally not ported (config lives elsewhere or low value)
- Standalone `esp-check` / `title-check` / `classify` tools — we compute ESP as
  a free-verify byproduct and title-gate + ICP inside the pipeline; separate
  one-off tools aren't needed.
- Custom-variable CRUD / import-field mapping UI — handled by the Formats
  config (paste Format JSON) and the now-preserved uploaded columns.
- `dedupe`, `reclassify`, `run-all` workspace-level batch tools — can be added
  if you want them; not core to a single-list flow.
- Multi-worker concurrency knob — our worker processes a list job sequentially
  with mid-run Stop; concurrency can be added later if throughput needs it.
