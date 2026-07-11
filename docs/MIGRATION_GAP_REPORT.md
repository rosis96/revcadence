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

## 3. Bottom line

Every *record* type (leads, deals, stages, threads) is migrated. Every
*configuration* type is intentionally still in the legacy system **because the
legacy Reply Manager is still the live production pipeline** — its config must
stay where it runs. The migration moment for config = the moment the reply
pipeline itself moves into RevCadence (roadmap Phase 2/3).

Action items carried into NEXT_STEPS: recreate CRM tags manually (5 min, when
wanted); copy `ai_rules` text at reply-module cutover; `import_portals.py` for
blueprints.
