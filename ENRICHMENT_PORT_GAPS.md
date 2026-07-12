# Prompt: finish porting the enrichment system into revcadence

**You are working in the `revcadence` codebase** (FastAPI `app/` + React `frontend/`).
There is a second, older but more-complete reference codebase called the **Ascendly
Enrichment Dashboard** (FastAPI + vanilla JS). The enrichment logic in revcadence was
**ported from it**, and the port is good — but it is **incomplete**. Your job is to
close the gaps listed below so revcadence matches the reference behavior exactly.

**Ground rules (do not violate):**
- The reference codebase is the **source of truth** for behavior. Match it.
- **Do not reorder the funnel.** The order is: free verify → Reoon → title gate + ICP
  (one scrape + one extraction) → write copy. It is deliberate.
- **Match revcadence's existing patterns** — SQLAlchemy models in `app/models`,
  routers in `app/routers`, the worker/job pattern in `app/workers`, React pages in
  `frontend/src/pages`. Do not introduce a new style.
- **Migrations are additive only.** Never drop columns or delete data.
- Models must be **env-configurable** — never hardcode a model name in a call path.
- Compile-check everything before you finish (`python -m py_compile`, build the React
  app) and confirm the app still boots.

---

## What is ALREADY ported and working (do NOT redo these)

- The Verify → Enrich funnel — `app/enrichment/pipeline.py::process_lead`.
- Free email verifier with **DNS-over-HTTPS fallback** — `app/enrichment/verify_free.py`.
- Reoon verification — `app/enrichment/reoon.py`.
- Terminal-status model (`invalid/unsafe/skipped/error/done`) + resume semantics —
  `app/models/enrich.py`.
- The three verification fields `free_status`, `email_status`, `verify_source`, and the
  **two-column display** ("System check" + "Reoon") — `frontend/src/pages/EnrichListDetail.jsx`.
- List views (`all, processed, verified, enriched, nonicp, no_website, invalid, unsafe,
  notrun, title_rejected`) + `clear-results` + `clear-verification` —
  `app/routers/enrich_lists.py`.
- Per-workspace config (profile / icp_definition / formats / rules) — `EnrichConfig`.
- Double-extract elimination (one scrape + one extraction reused by the writer) —
  `pipeline.py::_icp_and_facts` → `_write_copy(ctx)`.

Leave all of the above intact. The gaps below are what's missing.

---

## GAP 1 — Split the writer model (biggest quality+cost gap)

**Problem:** `app/enrichment/ai.py::_call_openai` uses a single `OPENAI_MODEL`
(default `gpt-4o-mini`) for **both** fact-extraction **and** cold-email copywriting. In
the reference system these are split, and the writer was recently upgraded.

**Do this:**
- Introduce two env-configurable models:
  - `EXTRACT_MODEL` (default `gpt-4o-mini`) — used for ICP/extraction calls.
  - `WRITER_MODEL` (default `gpt-4.1-mini`) — used for the copywriting call.
- `_call_openai` should accept a `model` argument (default `EXTRACT_MODEL`); the copy
  step in `pipeline.py::_write_copy` must call it with `WRITER_MODEL`.
- Keep `COMPETITOR_MODEL` (default `gpt-4o-mini`) for GAP 3.

**Why:** `gpt-4.1-mini` writes materially better copy than `gpt-4o-mini` at ~mini cost,
and input tokens dominate the bill — so the writer must be independently switchable
(`WRITER_MODEL=gpt-4.1` for higher quality, `gpt-4o` to revert) without touching code.

**Acceptance:** extraction and writing can use different models via env; defaults are
`gpt-4o-mini` / `gpt-4.1-mini`.

---

## GAP 2 — Content-budget env caps (cost lever)

**Problem:** `pipeline.py`/`ai.py` hardcode content slices (`[:8000]`, `[:6000]`).
Input tokens are ~10:1 vs output and are the main cost driver, so these must be tunable.

**Do this:** read these env vars (with the given defaults) and apply them where content
is sliced:
- `EXTRACT_CONTENT_CHARS` (default `8000`) — site text sent to the extractor/ICP call.
- `WRITER_CONTENT_CHARS` (default `6000`) — site excerpt sent to the writer.
- `MAX_TOTAL_CONTENT_CHARS` (default `10000`) — cap on total crawled text kept.
- `ENRICH_MAX_PAGES` (default `4`) — pages the crawler visits per company.

**Acceptance:** lowering these env vars measurably reduces prompt size with no code
change. (Reference incident: a 22000-char extract budget caused runaway spend — keep
defaults modest.)

---

## GAP 3 — Competitor finder (only the DB column exists)

**Problem:** `EnrichLead.competitors` column exists, but there is **no finder logic, no
endpoint, no UI**. In the reference system this is a full on-demand feature.

**Do this (port from the reference):**
- **Backend logic:** add `find_competitors(lead) -> (list[{name, why}], cost)` to
  `app/enrichment/ai.py` (or a small `competitors.py`). One cheap OpenAI call using
  `COMPETITOR_MODEL`, grounded in the company name + industry + services we already
  have. **Anti-fabrication instruction is mandatory:** "only name companies you are
  confident genuinely exist; never invent a name to fill a slot; return fewer/none if
  unsure." Demo-mode fallback when no API key, same as the other AI calls here.
- **Endpoint:** `POST /enrich-lists/{list_id}/find-competitors` accepting a selection
  or a `view` (mirror how `clear-verification` already takes `view`), running as a
  background job via the existing worker pattern, writing `lead.competitors`.
  Skip leads that already have competitors.
- **Frontend (`EnrichListDetail.jsx`):** add a **"Competitors"** column (show the 3
  names; the reason as a tooltip) and a **"Find competitors"** action next to the
  existing Clear buttons (works on selection / current view). Add it to the CSV export
  as a `Top Competitors` column formatted `Name (why); Name (why)`.

**Note:** this is the **model-knowledge** version (no web search) — cheap, a fraction of
a cent per lead. Do NOT add web search; the client chose the cheap version on purpose.

**Acceptance:** you can run "Find competitors" on a view, see 3 real companies per lead
in a Competitors column, and they appear in the export.

---

## GAP 4 — DNS diagnostics endpoints

**Problem:** there's no way to confirm the free MX layer is actually live on the host
(if the host blocks DNS and DoH, the free layer silently fails open and rejects
nothing). The reference system exposes diagnostics.

**Do this:** add two GET endpoints (an admin/enrich router is fine):
- `GET /enrich/diag/dns` — runs the MX check on a few known-good and known-dead domains
  and returns `{dns_working: bool, results: {...}, verdict: str}`. `dns_working` is true
  only if a real domain resolves True **and** a nonsense domain resolves False.
- `GET /enrich/diag/email?e=…` — returns `verify_free.check(e)` for one address.

**Acceptance:** hitting `/enrich/diag/dns` in production tells you definitively whether
the MX layer is rejecting dead domains or failing open.

---

## GAP 5 — Align the Reoon "safe" strictness + remove dead code

**Problem:** `pipeline.py` step 2 proceeds to enrich on `catch_all` and `unknown`
(only stops on hard-invalid), and contains a half-finished/no-op block
(`if r["status"] in ("catch_all", "unknown") ... and r["status"] == "invalid": pass`).

**Do this:** make the "safe to proceed" rule explicit and match the reference:
- Treat **only `safe`/`valid`** as deliverable → proceed.
- When the workspace's **Only Safe** setting is on (default on), `catch_all` and
  `unknown` should mark the lead **`unsafe`** and STOP (no ICP, no copy). When Only Safe
  is off, they may proceed. Make this a clear, single decision.
- Delete the dead `pass` block.

**Acceptance:** with Only Safe on, catch-all/unknown emails end as `unsafe` and never
consume writer tokens; the code path is clean and readable.

---

## GAP 6 — Confirm chip counts are LIVE FULL-LIST (not page-local)

**Verify:** the `GET /enrich-lists/{list_id}/leads` response must return counts for
every view computed over the **whole list** (cheap `COUNT` queries per view), not just
the current page — the reference `_list_counts` returns
`all/processed/verified/enriched/nonicp/no_website/invalid/unsafe/notrun/title_rejected`.
The chips in `EnrichLists`/`EnrichListDetail` must show these live numbers and filter
the whole list server-side, with pagination and a "select all N in view" that drives
export/clear/delete/find-competitors across the entire view.

**Acceptance:** on a 50k-lead list, every chip shows the true full-list count and
"select all N" acts on all N, not the visible page.

---

## Optional / nice-to-have (only if time)

- **Title gate:** revcadence uses a keyword list (`SENIOR_TITLES`). The reference uses a
  small AI title-gate call for nuance. Keyword is cheaper and fine — leave it unless the
  client asks for better title filtering.
- **Prompt caching:** confirm the writer's **static prefix** (client profile + rules +
  format specs) is sent FIRST and per-lead content LAST, byte-stable, so OpenAI caches
  the prefix (~90% cheaper input on repeats). `_write_copy` already does this — keep it.

---

## Definition of done

1. Extraction and writing use separate, env-configurable models (`gpt-4o-mini` /
   `gpt-4.1-mini` defaults).
2. Content budgets are env-tunable.
3. "Find competitors" works end-to-end (finder → endpoint → column → export).
4. `/enrich/diag/dns` proves the free MX layer's status.
5. Reoon safe-strictness is explicit and the dead code is gone.
6. Chip counts are live full-list with working "select all in view".
7. Everything compiles, the app boots, and no existing behavior regressed.

When unsure how something should behave, open the **Ascendly Enrichment Dashboard**
reference and copy its logic — it is the source of truth. Do not redesign; port
faithfully.
