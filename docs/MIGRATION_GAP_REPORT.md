# Migration Gap Report — Reply Manager → RevCadence

_Date: 2026-07-10. Based on direct inspection of the legacy schema (db.py:
7 tables) plus file/code-based config. Not guessed._

## 1. Legacy tables — migrated or not

| Legacy table | Status | Where it went / why not |
|---|---|---|
| `leads` | ✅ MIGRATED | → `contacts` (deduped by email), `companies` (by name), `activities` (email_in / email_out / reply_drafted / full thread JSON) |
| `opportunities` | ✅ MIGRATED | → `deals` (stage matched by name, `legacy_opportunity_id` kept) |
| `crm_stages` | ✅ MIGRATED | → `stages` per workspace (used for deal stage mapping) |
| `workspaces` | ⚠ PARTIAL | Names resolved via `workspace_aliases`. **Config columns NOT migrated** (see §2) |
| `crm_tags` | ❌ NOT migrated | Tag definitions + old deals' tag assignments not carried. Minor: recreate tags by hand in RevCadence, or micro-import later if missed |
| `app_settings` | ❌ NOT migrated | Global config incl. `ai_rules` (see §2) |
| `proposed_slots` | ❌ NOT migrated | Ephemeral Calendly reservations; auto-prune by design |

## 2. Business-critical configuration — exact findings

| Item | Exists in legacy? | Where | Migrated? | Decision |
|---|---|---|---|---|
| Reply formats/templates | YES | `workspaces.reply_format` JSON column + `reply_formats/*.json` files (7 files) | NO | **Deferred — migrate with the reply module.** The live Reply Manager still consumes them; moving them now would fork the truth. When the reply pipeline moves into RevCadence, import the JSON column per workspace. |
| AI reply prompts | YES | Hardcoded in legacy `main.py` (reply prompt, `_followup_prompt`, `FOLLOWUP_SYSTEM`) | NO — it's code, not data | **Rebuild** as DB-backed prompt templates in RevCadence (per-workspace, editable) when the reply module lands. Do not port code verbatim. |
| Client profiles | YES | `workspaces.client_profile` JSON column + `client_profiles/` dirs (both repos) | NO | **Deferred — migrate with the reply module** (same reason as reply formats). Enrichment engine (below) writes profiles into `companies.enrichment` going forward. |
| Knowledge base | NO | Does not exist anywhere in legacy | n/a | **Build new** (design doc Stage 14). Nothing to migrate. |
| Email sequences | NO (not in legacy DB) | Sequences live inside Instantly/Bison platforms; legacy only stores `reply_followup_campaign_id` and writes followup variables | n/a | **Rebuild** as native sequence orchestration (Stage 5). Nothing migratable. |
| Workspace configuration | YES | `workspaces` columns: `api_key`, `base_url`, `calendly_token`, `calendly_scheduling_url`, `ai_provider`, `ai_fallback`, per-ws AI keys, sender fields | NO | **Deferred intentionally** — the legacy system is still live and depends on these. Migrating secrets now duplicates them. Move when the reply pipeline moves; encrypt at rest on arrival. |
| Campaign configuration | PARTIAL | `reply_followup_campaign_id` (workspace), trigger tags (`app_settings`) | NO | **Deferred with workspace config** (same migration moment). |
| Automation rules | YES | `app_settings.ai_rules` (global, plain-English lines) | NO | **Rebuild improved**: per-workspace rules in RevCadence (legacy is global-only). Copy the text over manually at cutover — it's one text field. |
| Blueprint data | YES — different system | Client Portals service (per-client JSON + executed PDFs), not the Reply Manager DB | NO | **Migrate later** via planned `import_portals.py` (MIGRATION_PLAN §3). `documents` table is ready for it. |
| Other: Calendly slot reservations | YES | `proposed_slots` | NO | **Deprecate** — operational/ephemeral. |
| Other: dashboard auth/session | YES | env password | NO | **Deprecated** — replaced by RevCadence users/roles. |

## 2b. Re-sweep addendum (2026-07-12) — full folder re-check

**Blueprint folder (`agreement and blueprint`):**
- The "reply management thing" is documentation, not code: `DEPLOYMENT_STEPS.md`
  covers deploying the reply-manager repo, and the portals README describes the
  Service API the Reply Manager consumes. Nothing to migrate from those.
- ⚠ **Nested duplicate repo** `ascendly-client-portals/ascendly-client-portals/`
  is an OLD copy — but it's the only place in git holding `shimahara.json` +
  `shimahara.blueprint.html`. The live repo's `clients/` has only `_example` and
  `zulu-landscaping`. Conclusion: **production client JSONs live on the Railway
  volume, not in git** — `import_portals.py` must read the live Service API
  (as planned), never the git folders. Delete the nested duplicate after that
  migration is verified.
- Loose top-level HTML (shimahara/cleo/revenue blueprints) = generated
  artifacts; superseded once portals data migrates.

**Reply management folder:**
- `reply_formats/*.json` (7) + `client_profiles/*.json` (4) + `config.json` are
  the file-based seeds of what now lives in the DB `workspaces` columns —
  `config.json` is superseded, but the reply_formats JSONs are the canonical
  input for the reply-module port (schema contract: `REPLY_FORMAT_SCHEMA.md`).
- `logs/` (processed_replies, sent payloads) — operational debris, ignore.

**Enrichment folder — new finds that matter:**
- ⚠ **There IS a production enrichment database** (Railway Postgres, previously
  Neon — see `enrichment-dashboard/migrate_from_neon.py`): workspaces, lists,
  ~69k leads with enrichment results, custom variables, correction rules,
  live at enrichment.ascendly.one. The earlier "don't migrate enrichment
  history" decision stands, BUT the **custom variables, formats, and rules** in
  that DB are configuration, not history — they must be exported when building
  the Clay-grid in RevCadence (revising the §2 'enrichment' row: config =
  migrate, lead history = leave).
- `variable_sets/*.json` (8, incl. backups) — per-client personalization
  variable definitions; direct input for the Clay-grid port.
- `intelligence/examples/revcadence_full.json` — a complete Intelligence
  Workspace config written for RevCadence itself; use it as the seed config
  when the intelligence engine is built.
- `workspace_config_template.json` — the profile+variables template.
- `run_backup_before_followup_linebreak_fix.py`, `.bak` files, 64k-file cache,
  leads.csv, Result-*.numbers — delete/gitignore (already in audit §5).

## 3. Bottom line

Every *record* type (leads, deals, stages, threads) is migrated. Every
*configuration* type is intentionally still in the legacy system **because the
legacy Reply Manager is still the live production pipeline** — its config must
stay where it runs. The migration moment for config = the moment the reply
pipeline itself moves into RevCadence (roadmap Phase 2/3).

Action items carried into NEXT_STEPS: recreate CRM tags manually (5 min, when
wanted); copy `ai_rules` text at reply-module cutover; `import_portals.py` for
blueprints.
