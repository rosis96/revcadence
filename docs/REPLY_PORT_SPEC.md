# Reply Management port — full gap inventory (WORKING SPEC)

_Source of truth: the live legacy system in `~/Desktop/reply management`
(main.py, dashboard.py, db.py, crm.py, revenue.py) at reply.ascendly.one, plus
its CLAUDE_HANDOFF.md (§4 explains WHY each behavior exists). This doc lists
WHAT must exist in RevCadence. Port behavior faithfully; match RevCadence
patterns (app/models, app/routers, app/workers, React pages). The legacy
system keeps running until cutover. Client Portals stays a separate service —
talk to it only via the Service API (X-Service-Key), like revenue.py::svc()._

## Already in RevCadence (do not redo)
Read-only Replies reporting · CRM records migrated + aliases · enrichment
engine/lists (gaps closed 2026-07-12) · jobs/worker · auth/users/admin.

## GAP A — the live reply engine (every item was a fixed production bug)
1. Webhooks: POST /bison-reply (?reply_workspace/&fup_workspace combined,
   TAG_ATTACHED trigger-tag routing, LEAD_INTERESTED via deep_find_lead_id);
   POST /instantly-reply (?workspace_name, resolve_instantly_workspace, key
   scan across active Instantly workspaces). Unmatched-lead attribution: by
   campaign ownership probe → URL hint → literal "Unrouted" — NEVER another
   workspace's view.
2. decide_reply_action: send / skip_enrich / stop; STOP intents never drafted
   or enriched; auto-send ONLY response_types[].auto_send (legacy keyword
   fallback).
3. LLM: per-workspace provider + key overrides → global fallback
   (build_ai_cfg); ai_fallback provider auto-switch; model-id lowercasing;
   _parse_llm_json tolerance; detectable _LLM_FALLBACK sentinel (never sent).
4. Reply-format fidelity: response_types[] schema + FUP1..6; STEP 0 faithful
   template fill; strip_existing_signature + add_signature = exactly one
   signature.
5. Operator AI rules injected into EVERY prompt — rebuild per-workspace.
6. Calendly: per-ws token+URL, timezone_from_location, prospect-tz weekday
   slots spread across days, proposed_slots anti-double-booking (6 distinct
   for follow-ups), /dashboard/calendly diagnostic page.
7. Follow-up loop guard: lead_already_handled + _scan_for_campaign_id
   backstop (reply mode only; followup-mode workspaces exempt).
8. Bison variable merge: fetch existing vars → merge → drop-unknown retry
   (PUT replaces ALL vars otherwise).
9. Instantly threading: reply to prospect's latest INBOUND (not own sent),
   sender = that email's eaccount; build_reply_quote; _clean_name_token.
10. reply_delay_seconds. 11. record_lead incl. full lead_data JSON.

## GAP B — workspace model + management UI
platform/mode/api_key/base_url/campaign id/calendly fields/ai provider+keys/
sender fields/client_profile/reply_format/active; structured format editor
(paste JSON → fill; auto-migrate old single-main_reply formats); duplicate
workspace.

## GAP C — leads console + review workflow
Needs Review queue; drawer w/ editable draft + Approve & Send (both
platforms); stages; mark-booked (single/bulk) → CRM sync; delete; filters w/
full-list counts; CSV export. Test-thread sandbox: paste thread → exact
engine run, ZERO side effects, detects model-didn't-run fallback.

## GAP D — CRM enrichment from platform payloads (2026-07, not in handoff)
extract_lead_enrichment (company/location/LinkedIns/website from raw
payloads) → deal fields; backfill_opportunities_from_booked + Sync button;
fields on the deal form; carried into Studio promotion.

## GAP E — Ascendly Studio / revenue module (revenue.py ~1200 lines)
svc() Service API client (PORTALS_API_URL/KEY) — Studio is a thin stateless
UI over portals. Home command center (stage chips, MRR, awaiting-countersign,
activity). Client workspace tabs: Overview / Blueprint / Agreement /
Sales Intel (INTERNAL ONLY) / Timeline / Notes. Transcript intake → skipAI
upsert → forced AI regen → pricing-applied / MISMATCH banners. Blueprint:
preview/Present(?present=1)/links/publish/regenerate/AI content review/
readiness checklist/custom-HTML upload + revert. Agreement: signature state,
countersign link, resend executed, terms editor (locked once executed), PDF.
Promotion /promote?opp_id= → DRAFT portals client (manual only, never auto).
Embedded AI assistant (tool loop over Service API). Timeline w/ EVENT_LABELS.
Settings via /service/info. Boundary: clients only ever see
blueprint./agreement.ascendly.one; no inbox data in Studio.

## GAP F — cutover migration
Workspace config columns (ENCRYPT secrets on arrival), reply_format JSONs
(+7 file seeds), client_profiles, ai_rules → per-workspace, trigger tags,
campaign ids. Repoint Bison + every Instantly webhook (?workspace_name=) to
RevCadence. Parallel-run days before legacy goes read-only. proposed_slots
ephemeral — recreate, don't migrate.

## Definition of done
1. Webhook reply → auto-sent / Needs Review / stopped with exact legacy
   decisions (validated via Test-thread sandbox on real threads).
2. Approve & Send works on both platforms; no variable wiping; no
   reply-to-self.
3. Calendly: timezone-correct, real, never double-booked; diagnostic page.
4. Strict workspace isolation incl. "Unrouted".
5. Studio E2E against live portals API: promote → transcript → generate →
   review → present → publish → sign → countersign → executed (+ custom
   blueprint upload/revert).
6. GAP F migrated; legacy untouched until cutover.

## Suggested build order (each independently shippable)
1. GAP B workspace model + encrypted secrets + editor (foundation).
2. GAP A engine: webhooks → decision → generation → guards (behind
   inactive-until-configured workspaces; validated with the sandbox).
3. GAP C console (review/approve-send) + test-thread sandbox.
4. GAP A.6 Calendly + diagnostics.
5. GAP D CRM enrichment + booked sync.
6. GAP E Studio (vertical slices: svc client + Home → client tabs →
   transcript/regen → Sales Intel → assistant).
7. GAP F cutover, parallel-run, webhook repoint.
