# Prompt: port the Reply Management system into revcadence — the FULL gap list

**You are working in the `revcadence` codebase** (FastAPI `app/` + React `frontend/`).
The **source of truth** is the live production system in the `reply management` folder
(`main.py`, `dashboard.py`, `db.py`, `crm.py`, `revenue.py`), running at
`reply.ascendly.one` against real client inboxes.

**Read `reply management/CLAUDE_HANDOFF.md` fully first.** It documents the reply
engine's hard-won behaviors (§4). **But it is incomplete** — it does not cover the
Studio/revenue module or the newest fixes. This document is the complete inventory:
everything the legacy system does that revcadence does not. Your existing
`docs/MIGRATION_GAP_REPORT.md` deferred all of this "with the reply module" — this IS
that list.

**Ground rules (do not violate):**
- The legacy code is the behavioral source of truth. Port behavior, not code style —
  match revcadence patterns (`app/models`, `app/routers`, `app/workers`, React pages).
- **Never break the live legacy system while porting.** It keeps running until cutover.
- **The Client Portals service stays a separate Railway project.** revcadence talks to
  it via the Service API (`X-Service-Key`), exactly as legacy `revenue.py::svc()` does.
  Do NOT absorb portals into revcadence.
- Migrations additive only. Secrets (workspace API keys, Calendly tokens) must be
  encrypted at rest on arrival. Compile + boot-check before claiming done.

---

## What revcadence ALREADY has (do NOT redo)

- Read-only **Replies reporting** (`frontend/src/pages/Replies.jsx` over migrated
  `activities` kind=email_in with intents) — this is reporting, not the engine.
- CRM: contacts/companies/deals/stages migrated; workspace aliases.
- Enrichment engine + lists (see `ENRICHMENT_PORT_GAPS.md`).
- Jobs/worker pattern, auth/users, admin.

Everything below is missing.

---

## GAP A — The live reply engine (the heart; nothing of it exists here)

Port from `main.py`. Every item below was a production bug fixed at least once —
losing any of them reintroduces a known incident.

1. **Webhooks.**
   - `POST /bison-reply` — supports `?reply_workspace=&fup_workspace=` (one combined
     webhook to avoid double-sends), `TAG_ATTACHED` routing by trigger tag,
     `LEAD_INTERESTED` via `deep_find_lead_id`, legacy Make.com shape.
   - `POST /instantly-reply` — explicit `?workspace_name=` routing;
     `resolve_instantly_workspace(payload)` (payload name → single-active-workspace →
     **None**, never a hardcoded default); `find_instantly_lead` tries every active
     Instantly workspace's API key to find the owning account.
   - **Workspace isolation (fixed 2026-07-12):** when a lead can't be matched to any
     key, attribute the record via `find_instantly_workspace_by_campaign(campaign_id)`
     (GET the campaign with each workspace's key — ownership is factual), else the
     explicit URL hint, else literal `"Unrouted"`. NEVER dump unmatched leads into
     another workspace's view. Workspaces are strictly individual.
2. **Decision logic** — `decide_reply_action`: classify → `send` / `skip_enrich` /
   `stop`. STOP intents (out_of_office, automated/auto-reply, opt-out, wrong person)
   are never drafted or enriched, by design. Auto-send ONLY reply-format
   `response_types[].auto_send` types (legacy keyword fallback for old formats);
   everything else lands in **Needs Review**.
3. **LLM generation** — `generate_ai_reply` + `_call_llm/_call_openai/_call_gemini`:
   per-workspace provider (`ai_provider`) with per-workspace key overrides falling back
   to global keys (`build_ai_cfg`); `ai_fallback` auto-switch on provider failure;
   model-id lowercasing (capitalized model strings silently failed); `_parse_llm_json`
   fence/noise tolerance; `_LLM_FALLBACK` sentinel is detectable, never silently sent.
4. **Reply-format fidelity** — the category schema (`REPLY_FORMAT_SCHEMA.md`):
   `response_types[]` with examples/intent/auto_send/template/rules + `followups`
   FUP1..6. STEP 0 faithful-template-fill (keep structure, only fill placeholders).
   Signature dedupe: AI told to omit sign-off; `strip_existing_signature` +
   `add_signature` guarantee exactly one.
5. **Operator AI Rules** — free-text rules (legacy: `app_settings.ai_rules`) injected
   into EVERY prompt as mandatory. Rebuild per-workspace (legacy is global-only);
   copy the existing text at cutover.
6. **Calendly scheduling** — per-workspace token + scheduling URL (read-only scopes);
   `timezone_from_location`; `get_calendly_slots` (prospect-timezone, weekday windows,
   spread across days); **`proposed_slots` anti-double-booking** (reserve every
   proposed time; follow-ups get 6 distinct times); the `/dashboard/calendly`
   diagnostic page (shows event types, raw slot count, errors) — "same time to
   everyone" was a real incident diagnosed with it.
7. **Follow-up loop guard** — `lead_already_handled` (reply-mode only) +
   `_scan_for_campaign_id` backstop, applied to both platforms; follow-up-mode
   workspaces exempt. Without this, the follow-up campaign re-triggers auto-replies.
8. **Bison custom-variable merge** — Bison PUT replaces ALL variables; read existing
   vars first (`fetch_bison_lead_custom_vars`), merge ours on top, keep the
   drop-unknown-variable retry. Without this, company/#employees/etc. get wiped.
9. **Instantly threading** — `find_instantly_reply_target`: reply to the PROSPECT's
   latest inbound email (not our own last sent — replies went to self) and use its
   `eaccount` as sender; `build_reply_quote` natural quoting; `_clean_name_token`
   ("From:" artifact fix).
10. **Reply delay** — configurable `reply_delay_seconds` before processing.
11. **Lead recording** — `record_lead` with statuses/intents/actions AND `lead_data`
    (the full raw platform payload JSON — the CRM enrichment below depends on it).

## GAP B — Workspace model + management UI

- Full workspace config: `platform` (bison/instantly), `mode` (reply/followup),
  `api_key`, `base_url` (Bison), `reply_followup_campaign_id`, `calendly_token`,
  `calendly_scheduling_url`, `ai_provider`, `ai_fallback`, per-ws AI keys, sender
  name/email fields, `client_profile` JSON, `reply_format` JSON, `active`.
- The structured workspace editor (response types + follow-ups as sections, advanced
  JSON, **"Paste JSON → auto-fill"**, auto-migration of old single-main_reply formats).
- **Duplicate workspace** (`db.duplicate_workspace`): copies every config column,
  auto-numbers name collisions — used to spin up new clients fast.

## GAP C — Leads console + human review workflow

- Needs Review queue; drawer with editable draft + live **Approve & Send** (sends via
  the right platform); stages (New/Replied/Meeting Booked/Stopped/Done); mark-booked
  (single + bulk) triggering CRM sync; delete (single/bulk); filters with full-list
  counts; CSV export.
- **Test thread sandbox** (`/dashboard/test`): paste a thread → exact engine run
  (profile, format, rules, provider) → decision + drafts, with ZERO side effects (no
  sends, no writes, no Calendly reservations). Detects "model didn't run" fallback.

## GAP D — CRM enrichment from platform data (built 2026-07, not in the handoff)

- `db.extract_lead_enrichment(lead_data_json)` — tolerant parser pulling company,
  location, contact LinkedIn, company LinkedIn, website from raw Bison/Instantly
  payloads → `opportunities.location / contact_linkedin / company_linkedin`.
- `backfill_opportunities_from_booked` (idempotent, workspace-scoped) + the
  "Sync booked leads" button.
- Opportunity form fields for location/LinkedIns; enrichment carried into Studio
  promotion notes.

## GAP E — Ascendly Studio / revenue module (`revenue.py`, ~1,200 lines — entirely absent, newest work, in no handoff)

The internal cockpit for the client-portals document system (blueprints + agreements).
revcadence has `Blueprints.jsx`/`documents` stubs — the real module is this:

1. **Service API client** — `svc(method, path, body)` → portals service with
   `X-Service-Key` (`PORTALS_API_URL`/`PORTALS_API_KEY` env pair). All document state
   lives in portals; Studio is a thin, stateless UI over it.
2. **Home command center** — stage-chip pipeline (Draft → Published → Client signed →
   Executed → Active) + MRR, awaiting-countersign, ready-to-onboard, drafts, live,
   activity feed (portals audit events).
3. **Client workspaces** — `/clients/{slug}`: stage strip, next-action bar, tabs:
   Overview / Blueprint / Agreement / **Sales Intel** / Timeline / Notes.
4. **Transcript intake** → `/clients/{slug}/transcript`: saves transcript (skipAI
   upsert) then forces AI regeneration; result banner reports "Call pricing applied:
   $X" or "no pricing found — defaults kept"; **MISMATCH banner** when the AI flags the
   transcript is about a different company.
5. **Blueprint tab**: preview / **Present** (`?present=1` presentation mode) / copy
   link / publish–unpublish / Regenerate AI; AI content review (bottleneck, focus,
   call pricing, notes, **whatWeSee**, **theirWords** pull quotes); publish-readiness
   checklist; **custom blueprint upload** (paste/upload full HTML → portals
   `POST /service/clients/{slug}/blueprint-html`, revert via DELETE — replaces the
   generated page at the same client link, `{{vars}}` still render).
6. **Agreement tab**: signature status, countersign link, resend executed email,
   commercial terms editor (locked once executed), download executed PDF.
7. **Sales Intel tab** (INTERNAL ONLY — never client-visible): opportunityScore
   (overall/budget/authority/urgency/fit, close probability, revenue potential),
   salesCoach (biggest objection + response, questions, emphasize/avoid, next step,
   pricing confidence), missingInfo.
8. **CRM → Studio promotion** — `/promote?opp_id=` creates a DRAFT portals client
   prefilled from the opportunity (incl. GAP D enrichment). **Manual only** — no
   auto-promotion, ever.
9. **Embedded AI assistant** — per-workspace chat (`/assistant/chat`) with an OpenAI
   tool loop over the Service API; current client slug injected as default context.
10. **Timeline** — portals audit events with human labels (`EVENT_LABELS`), including
    blueprint_viewed / client_signed / executed / custom-blueprint events.
11. **Studio settings** — portals connection status via `/service/info` (version +
    generation model), Studio chat model, defaults, notifications.
12. **Boundary rules (non-negotiable):** clients only ever see
    `blueprint.ascendly.one` / `agreement.ascendly.one`; Studio is internal; no
    reply-inbox data leaks into Studio; the two codebases stay separate services.

## GAP F — Cutover data migration (deferred items from MIGRATION_GAP_REPORT §2)

At the moment the reply module goes live in revcadence:
- Migrate `workspaces` config columns (encrypt secrets), `reply_format` JSON per
  workspace (+ the 7 `reply_formats/*.json` seeds), `client_profile` JSON
  (+ `client_profiles/`), `app_settings.ai_rules` → per-workspace rules, trigger tags,
  `reply_followup_campaign_id`.
- Repoint the Bison webhook and every Instantly account's webhook
  (`?workspace_name=` per workspace) to the revcadence URLs.
- Parallel-run: keep legacy receiving until revcadence has processed real webhooks
  correctly for several days; then legacy goes read-only.
- `proposed_slots` is ephemeral — do not migrate; recreate the table.

---

## Definition of done

1. A reply arrives by webhook and ends as auto-sent / Needs Review / stopped with the
   exact legacy decision behavior (verify with the Test-thread sandbox on real threads).
2. Approve & Send works against both platforms; follow-ups write back; no variable
   wiping (Bison) and no reply-to-self (Instantly).
3. Calendly proposals are timezone-correct, real, and never double-booked; diagnostic
   page exists.
4. Workspaces are fully isolated — including unmatched-lead attribution ("Unrouted").
5. Studio module works end-to-end against the live portals Service API: promote →
   transcript → generate → review (incl. Sales Intel) → present → publish → sign →
   countersign → executed, plus custom-blueprint upload/revert.
6. All cutover data migrated per GAP F; legacy runs untouched until then.

When unsure how anything should behave: open the `reply management` folder and read
the actual implementation — it is the source of truth. `CLAUDE_HANDOFF.md` §4 explains
WHY each behavior exists; this document lists WHAT must exist. Port faithfully.
