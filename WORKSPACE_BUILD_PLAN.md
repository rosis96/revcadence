# Client Workspace — Build Plan

**Companion to:** `AGENT_BRIEF.md` (the spec) · this file is the **tracker**.
**Status:** M1, M8 and M10 shipped. M0 open on D1–D5 and the bridge extraction (M0-T5);
M2–M7, M9 not started. **Track 2 (M11–M16) added — see §4b:** the client operates their own
workspace, in the operator's UI. D7–D10 decided, D11 open.
**Track 2 is being built out of order at the client's direction:** M13's screens shipped on
2026-08-18 ahead of M11 (actor trail, collision guard) and M12 (client-safe serializers).
Both are now overdue rather than upcoming — see the debt note at the head of §4b.
**Last updated:** 2026-08-18

---

## How to use this file

- Work top to bottom. Do not start a milestone before the previous one's **Exit check** passes.
- Every task has a checkbox, the files it touches, and a **Done when** condition.
- **After each task:** tick the box, add one line to §7 Progress log, and update the
  milestone's status line. If the task changed the plan (new dependency, wrong estimate,
  scope moved), edit the affected task here in the same commit — this file must never
  describe a world that no longer exists.
- New work discovered mid-milestone goes in as a numbered task in the milestone it belongs
  to, not a TODO comment in code.
- Estimates assume **one dev**, and are ± wide. They are for sequencing, not commitments.

---

## 1. Step-0 verification report

Answers to `AGENT_BRIEF.md` §1, verified against the repo on 2026-08-16.

| # | Question | Answer | Impact |
|---|---|---|---|
| 1 | Shared `DataTable`? | **Yes.** [DataTable.jsx](frontend/src/ui/DataTable.jsx) — 284 lines, TanStack Table + Virtual. Search, sort, column chooser, saved views, bulk actions, sticky header, resizable columns, pagination *or* virtual scroll, skeletons, empty state. Used by 9 pages. | Brief's "pages hand-roll tables" is **stale**. Views work is **not** blocked. Caveat: saved views + column prefs are `localStorage` only — C6 needs a server-side `View` and a controlled-views prop. |
| 2 | `Page`/`Document`/`Note` model? | **No page/block model.** [`Document`](app/models/documents.py) exists but is the portals object (blueprint/agreement/proposal — an HTML blob + signing state + view tracking). `Note` in [crm.py:155](app/models/crm.py:155) is a plain body on a deal/contact/company. | C1 is genuinely new. **Name collision:** `Document`/`documents` is taken → use `Page`/`pages`, `Block`/`page_blocks`, `PageVersion`/`page_versions`, `PageComment`/`page_comments`. |
| 3 | Campaign / sequence / step object? | **None.** Cold sending is fully delegated to Bison/Instantly ([`ReplyWorkspace.platform`](app/models/reply.py:17)). RevCadence pushes **replies and follow-ups only** — `send_bison_reply`, `send_instantly_reply`, `push_instantly_followups` in [reply/engine.py](app/reply/engine.py:650). There is no campaign/sequence **write** API. | C4 is new **and** acceptance test #6 ("toggle variant C off → next send excludes it") is **not reachable** without a new campaign-sync integration. → **Decision D1.** |
| 4 | Training Bridge reusable? | **Split.** Pure logic *is* a service: [app/enrichment/training.py](app/enrichment/training.py) (`config_state`, `workspace_state`, `revision_hash`, `export_bundle`, `normalize_bundle`, `state_diff`, `apply_config_state`). Orchestration — auth gate, revision save, apply, rollback — is **inline** in [enrich_lists.py:724-1100](app/routers/enrich_lists.py:724), and `_training_admin` **403s any non-owner/admin**. | Extract orchestration before C2. Client edits currently cannot reach it at all. Covered by [tests/test_training_bridge.py](tests/test_training_bridge.py) (230 lines) — that suite is the safety net for the extraction. |
| 5 | `formats` multi-variant? | **One definition each.** `EnrichConfig.formats` is `[{label, name, guidance, template, min_words, max_words, placeholders[]}]` — [enrich.py:77](app/models/enrich.py:77). | A–G variants are a **new object** (C4). Do not try to grow `formats` into it. |
| 6 | `Meeting` model? | **No model.** Meetings = `Deal` at stage *Meeting Booked / Meeting Completed* + `Activity` (`meeting_booked`, `meeting_held`) + Calendly webhook ([app/reply/calendly.py](app/reply/calendly.py)). **But `Deal.meeting_outcome` already exists** — [crm.py:107](app/models/crm.py:107), `String(60)`, currently unused. | Bucket B "Meeting outcome" is **smaller than the brief says**: no migration, just a write endpoint + one-click UI + the auto-set-on-Proposal rule. |
| 7 | `Membership` role enum? | **Plain string.** `role = Column(String(20))` with a Python tuple `ROLES` — [identity.py:16](app/models/identity.py:16). No DB enum, **no migration needed**. | But role is baked into the JWT (`create_token`), read by `AuthContext.is_master`, and the frontend gates on the literal `me.role === "client"` in [App.jsx:160](frontend/src/App.jsx:160) and [App.jsx:355](frontend/src/App.jsx:355). Adding `client_admin` = audit **every** `"client"` literal, backend and frontend. |
| 8 | `frontend/dist` committed + served? | **Yes.** Committed, mounted by [app/main.py](app/main.py) (`StaticFiles` on `/assets` + `index.html` at `/`). Working tree currently has an unstaged dist asset swap. | Every frontend milestone ends with a rebuilt, committed `dist`. Add it to each Exit check or it ships stale. |

### Findings beyond the eight questions

| # | Finding | Consequence |
|---|---|---|
| A | **The brief's companion files do not exist in this repo.** No `revcadence-workspace-prototype.html`, no `WORKSPACE_SPEC.md` (which holds the §8.1 launch-template table), no `EXAMPLE_PAGES.md`. Only `DESIGN_SYSTEM.md` is present. | C5's seed template, C11's seed content, and the C4/C5 UI reference have **no source**. Blocks *content*, not structure. → **Decision D2.** |
| B | **Migration rule contradiction.** Brief says "additive migrations via `db.migrate()`". Reality: [db.py:54](app/db.py:54) — `init_db()` only creates/patches on **SQLite**; Postgres is **Alembic-owned** (13 revisions in `migrations/versions/`), and doing otherwise "would mask missing migrations". | Every new table needs an **Alembic revision** or it will not exist in production. [tests/test_migration_safety.py](tests/test_migration_safety.py) guards this. Written into M0-T4 as a standing rule. |
| C | **Warm-up does not exist.** Zero matches for `warmup` in `app/` or `frontend/src`. `MailboxConnection.status` is only `pending / connected / error` — no start date, no health score. | C5's critical path `warmup_started + 14d` has **no input**. Warm-up tracking becomes a sub-build inside M4. → **Decision D3.** |
| D | **The UI kit already ships the C1/C3 primitives.** [ui/index.jsx](frontend/src/ui/index.jsx) exports `useAutoSave`, `SaveIndicator`, `VersionList`, `CommentsPanel`, `StatusSteps`, `JourneyTimeline`, `FilterPanel`, `Pager`, `EmptyState`, `Skeleton`, `ToastProvider`/`useToast`, `confirmDialog`. | Real savings on M1–M3. Wire these; do not rebuild them. |
| E | **A `visibility` vocabulary already exists**: field-level `internal` \| `client` in [app/client/schema.py](app/client/schema.py), applied via `profiles.set_field(..., visibility=...)`. | Reuse those two values for `Page.visibility` / `Block.visibility`. Do not invent a third vocabulary. |
| F | **TipTap and tldraw are not dependencies.** package.json: react 18, react-router 6 (**HashRouter**), TanStack table/virtual, framer-motion, lucide-react. `node_modules` is not installed locally. | TipTap adds ~10 packages and a build-size jump; tldraw is heavy and needs a licence check. Both are explicit gates (M1-T1, M10-T1). |
| G | **`tests/test_smoke.py` is not pytest-style** — it is a script of `check("name", bool)` calls, and already asserts *"client requesting other workspace → 403"* at [line 134](tests/test_smoke.py:134). | The brief asks for a **404** on cross-workspace page ids. Both are defensible; they must be *deliberate*: **403** where the workspace is named in the path (existing convention), **404** for a bare `page_id` so existence never leaks. Match the file's existing style, don't introduce pytest here. |
| H | **A sibling Next.js app exists** at `D:\projects\revcadence` with `app/w/[slug]/` workspace-slug routes, its own Prisma schema and docs set. | Unclear whether the client workspace is meant to live there instead of this repo's React SPA. → **Decision D4.** Everything below assumes **this repo**. |

**Net:** the brief's structure holds. Its 40/60 split is roughly right, but the *hard* parts
moved: DataTable is a gift (question 1 was the stated blocker and it is already solved),
while sequences-that-actually-send, warm-up, and the missing spec files are the real risks.

---

## 2. Decisions needed before the affected milestone

Nothing below blocks M0–M3. Each is tagged with the first milestone it blocks.

| ID | Decision | Options | Recommendation | Blocks |
|---|---|---|---|---|
| **D1** | What does "toggling a variant changes what sends" mean, given cold sending lives in Bison/Instantly? | (a) Build a campaign push/sync integration to Bison + Instantly. (b) Sequence is the **source of truth**, and enabled variants export as the campaign payload the operator loads. (c) Read-only mirror of the external campaign. | **(b) first, (a) as M6b.** (b) delivers the client-facing value — approve copy, see what will send — without betting the milestone on two third-party write APIs. Then add real push once the object model is proven. | **M6** |
| **D2** | The launch-plan template (`WORKSPACE_SPEC.md` §8.1) and seed pages (`EXAMPLE_PAGES.md`) don't exist. | (a) Locate the files. (b) Reconstruct from `RevCadence_ICP_definition.md`, `VISION_FOR_CODEX.md`, `ROADMAP_V1.md` + a working session. (c) Ship structure with a thin placeholder template. | **(a), fall back to (b).** Ask for the files first — reconstructing a launch template that the team already agreed on is wasted work and will be wrong in the details that matter (durations, owners). | **M4** content, **M9** |
| **D3** | Where does `warmup_started` come from? | (a) Operator-entered date on `MailboxConnection`. (b) Derive from the external sender's warm-up API. (c) Auto-set from first connection + a manual override. | **(c).** Cheap, always populated, correctable. Gives the countdown a real input on day one without a new integration. | **M4** |
| **D4** | Is the client workspace built in `revcadence-engine` (React SPA) or the sibling `revcadence` Next.js app (`app/w/[slug]`)? | (a) This repo. (b) Sibling. (c) Backend here, UI there. | **Confirm before M1.** This is a one-question answer with a whole-project blast radius — the data model is fine either way, but every frontend task below assumes (a). | **M1** |
| **D5** | Does `client_admin` inherit *all* client permissions plus approval, or is it a distinct role list? | (a) Superset of `client`. (b) Parallel role. | **(a) superset.** Every existing `role == "client"` check becomes `role in CLIENT_ROLES`. One audit, one helper, no behavioural surprises. | **M2** |
| **D6** | **Whiteboards is a top-level nav section** in the agreed sidebar, but `AGENT_BRIEF.md` §C9 explicitly decided *against* a separate Whiteboards area (one page tree, one comment system, one permission model). | (a) Keep the nav entry; it lists pages that contain canvas blocks. (b) Drop the entry; canvases live inside Docs. | **(a).** It satisfies both: the section is a filtered view of the page tree, not a second content store. C9's decision survives — no separate model, no second comment or approval path. The nav entry is built and routed either way; only what it lists changes. | **M10** |

---

## 3. Milestone map

> **Shipped so far:** M1 (page system), M8 (library + provenance), M10 (whiteboard block),
> plus M0-T8's client shell. M8 was pulled forward because it only depended on M6's sequence
> objects, which already existed, and because the evidence rule it enforces is what M4's
> countdown and M6's variant gates both lean on.

| # | Milestone | Covers | Exit check | Est. |
|---|---|---|---|---|
| **M0** | Ground truth & unblock | Step 0 | Report delivered; decisions logged; bridge extracted; migration + role conventions set | 2–3 d |
| **M1** | Page system | C1 | A page can be written, commented on, versioned, autosaved | 5–8 d |
| **M2** | Visibility, `client_admin`, approvals | C3 + Bucket A read | Client approves; version pins; internal pages invisible; cross-workspace page id 404s | 4–6 d |
| **M3** | Live blocks | C2 + Bucket B writes | Editing the ICP block changes `cfg.icp_definition`, writes an audit entry, is revertible | 5–7 d |
| **M4** | Launch plan | C5 (+ warm-up) | Overview shows a correct countdown and names the blocking item | 6–9 d |
| **M5** | Deep links | C8 | Every stage and task clicks through to its space | 1–2 d |
| **M6** | Email sequences | C4 | 4-step sequence, A–G variants, QC-gated, toggling changes the payload (per D1) | 6–9 d |
| **M7** | Views | C6 | One dataset renders as table / list / board / calendar / gantt | 5–7 d |
| **M8** | Library + provenance | C7 + Bucket B extras | ✅ **done** — client case study tagged `client_supplied`, flagged at the angle, refused as a named claim | 4–6 d |
| **M9** | Notifications + instantiation | C10, C11 | New client lands on a pre-filled workspace; digest sends | 4–6 d |
| **M10** | Whiteboard block | C9 | A sticky note promotes into a real Segment record | 3–5 d |

**Track 2 — the client operates their own workspace** (§4b). Track 1 makes the client a
reader; Track 2 hands them every workspace-scoped screen, in the operator's own UI.

| # | Milestone | Covers | Exit check | Est. |
|---|---|---|---|---|
| **M11** | Boundary + actor trail | D9, D10 | Client/system line is one list; every send names a human; no double-send | 3–4 d |
| **M12** | Client-safe serializers | D11 | A client token cannot read a denied field from any endpoint, per a test | 3–5 d |
| **M13** | Reply Setup, client-operated | D8 | Client connects their own Instantly and builds reply formats, unaided | 4–6 d |
| **M14** | Inbox, both operate | D7 | Both sides work one inbox; every reply names its sender | 3–5 d |
| **M15** | Profile, Brain, ICP, Formats, Rules | — | Client edits their ICP through the bridge; audit + rollback intact | 5–7 d |
| **M16** | Sending infrastructure & follow-ups | D3 | Client connects a sender, sees warm-up, sets their own cadence | 4–6 d |

**Order is load-bearing.** M11 and M12 are the boundary; mounting any screen before them
hands a client token more than it should have. M13–M16 then parallelise freely.

**Parallelisable:** M6 barely touches M1–M5 code — a second dev can start it after M0.
M7 depends only on M0 + the dataset resolver.
**Steps M1–M5 are the product.** If time runs out, ship those.

---

## 4. Tasks

### M0 — Ground truth & unblock · `in progress`

- [x] **M0-T1** Answer the eight Step-0 questions against the repo. → §1 above.
- [x] **M0-T2** Report contradictions between the brief and the repo. → §1 findings A–H.
- [ ] **M0-T3** Get decisions **D1–D5** answered and record them in §2 (replace the
      recommendation with the decision + date).
      *Done when:* every row reads `DECIDED <date>: …`.
- [ ] **M0-T4** Write the schema convention into `AGENT_BRIEF.md` §2 rule 3 and this file:
      **new table → Alembic revision + model; new column → model + Alembic**; `db.migrate()`
      is dev-only. Add one revision per milestone, not one per table.
      *Files:* `AGENT_BRIEF.md`, `migrations/versions/`.
      *Done when:* `pytest tests/test_migration_safety.py` passes with the convention documented.
- [ ] **M0-T5** Extract the training-bridge orchestration out of the router into
      `app/enrichment/bridge.py`: `preview(ctx, ws_id, package)`, `apply(...)`,
      `rollback(...)`, `save_revision(...)`. Router endpoints become thin call sites.
      *Files:* [enrich_lists.py:724-1100](app/routers/enrich_lists.py:724) → new `app/enrichment/bridge.py`.
      *Done when:* `tests/test_training_bridge.py` passes **unchanged** and the router holds no bridge logic.
- [ ] **M0-T6** Audit every `role == "client"` literal (backend + frontend) and introduce
      `CLIENT_ROLES` / `is_client()` helpers so M2 can add `client_admin` in one place.
      *Files:* [app/auth.py](app/auth.py), [app/models/identity.py](app/models/identity.py),
      [frontend/src/App.jsx:160,355](frontend/src/App.jsx:160), any router doing a role compare.
      *Done when:* zero bare `"client"` role comparisons remain; smoke tests pass.
- [ ] **M0-T7** Add a server-side-views escape hatch to `DataTable`: accept optional
      `views` / `onSaveView` / `onApplyView` props; keep `localStorage` as the default so
      the 9 existing call sites are untouched.
      *Files:* [frontend/src/ui/DataTable.jsx](frontend/src/ui/DataTable.jsx), [KitchenSink.jsx](frontend/src/pages/KitchenSink.jsx).
      *Done when:* kitchen sink shows both a local-views and a controlled-views table.
- [x] **M0-T8** **Client workspace shell.** Sidebar-only chrome (no top bar): workspace
      identity at the top, four nav groups in the middle, profile at the bottom. Admin
      tokens throughout — no new palette. All 13 routes live under `/w/*`; clients land
      there and cannot leave it, masters can open `#/w` to preview.
      *Files:* [client/ClientShell.jsx](frontend/src/client/ClientShell.jsx),
      [client/pages/Overview.jsx](frontend/src/client/pages/Overview.jsx),
      [client/pages/Sections.jsx](frontend/src/client/pages/Sections.jsx),
      [styles.css](frontend/src/styles.css), [App.jsx](frontend/src/App.jsx),
      [routers/auth.py](app/routers/auth.py) (`logo_url` on `/me`).
      *Done:* verified in a browser against a throwaway DB — client login lands on the
      workspace, `/api/reports/summary` renders real KPIs, nav/active states and the
      unknown-route fallback work, light and dark both correct.

- [x] **M0-T9** **Client host + workspace URLs.** `app.revcadence.com` serves the client app
      and `app.revcadence.com/w/<workspace-slug>` is a real path, not a hash route. The
      client routes moved from `/w` to `/w/:slug`; the engine host keeps the hash router so
      every existing bookmark and sent invite still resolves.
      *Files:* [config.py](app/config.py) (`CLIENT_BASE_URL`, `CLIENT_HOSTS`,
      `client_workspace_url`), [main.py](app/main.py) (`_public_host_router` SPA fallback),
      [admin.py](app/routers/admin.py) (invite link), [runner.py](app/workers/runner.py) +
      [crm.py](app/routers/crm.py) (digest link), [host.js](frontend/src/host.js),
      [clientUrl.js](frontend/src/clientspace/clientUrl.js), [nav.jsx](frontend/src/clientspace/nav.jsx),
      [ClientShell.jsx](frontend/src/client/ClientShell.jsx), [App.jsx](frontend/src/App.jsx).
      *Done:* smoke 307 → **308 checks** (link shape, SPA fallback, `/api` + `/assets` +
      `/healthz` not swallowed, operator host unchanged); `npm run check` covers the
      redirect's fixed-point behaviour; `dist` rebuilt, no new dependencies.

**Exit check:** Step-0 report delivered · D1–D5 decided · bridge callable as a service ·
migration + role conventions in place · DataTable ready for C6.

---

### M1 — Page system (C1) · `done — 2026-08-17`
> Built in `revcadence-engine` (D4 resolved by building here). Migration rule settled:
> new tables need an **Alembic revision**; `db.migrate()` is dev/SQLite only.

- [ ] **M1-T1** Decide and install the editor. TipTap is the brief's call; confirm the
      dependency cost (~10 packages) and bundle impact against the committed `dist` first.
      *Done when:* `npm run build` succeeds and the dist delta is recorded in §7.
- [ ] **M1-T2** Models: `Page`, `Block`, `PageVersion`, `PageComment` (+ Alembic revision).
      `Page`: workspace_id, section (`strategy|operations|reference|internal`), kind, title,
      slug, parent_id, sort_order, status, visibility, timestamps.
      `Block`: page_id, type (the **11 only**), position, content JSON, visibility.
      *Files:* new `app/models/pages.py`, `app/models/__init__.py`, `migrations/versions/`.
      *Done when:* tables create on SQLite **and** via `alembic upgrade head`.
- [ ] **M1-T3** Router `app/routers/pages.py` — page tree CRUD, block CRUD, reorder. Every
      query through `scoped()` / `workspace_ids_for_query()`. Unknown block type → 422.
      *Done when:* a page tree round-trips through the API.
- [ ] **M1-T4** Comments: threaded, anchored to `block_id`, resolvable.
      *Done when:* comment → reply → resolve round-trips; resolved threads collapse.
- [ ] **M1-T5** Versions: snapshot on demand; `PageVersion` stores the full block set.
      *Done when:* a version can be listed, opened, and restored.
- [ ] **M1-T6** Frontend: page tree nav + block editor. Wire the **existing** `useAutoSave`
      (800 ms debounce), `SaveIndicator`, `CommentsPanel`, `VersionList` — do not rebuild them.
      Optimistic UI, rollback + toast on error.
      *Files:* new `frontend/src/pages/Workspace*.jsx`, `App.jsx` routes.
      *Done when:* typing autosaves, a forced 500 rolls back and toasts.
- [ ] **M1-T7** Rebuild + commit `frontend/dist`.

**Exit check:** a page can be written, commented on, and versioned. **No CRDT, no
co-editing** — last-write-wins plus history, per brief §7.

---

### M2 — Visibility, `client_admin`, approvals (C3) · `not started`
> Gate: **D5** answered. Depends on M0-T6, M1.

- [ ] **M2-T1** Add `client_admin` to `ROLES` + `CLIENT_ROLES`; only `client_admin` approves.
      No migration (finding 7). Verify the JWT `role` claim and refresh path carry it.
      *Files:* [identity.py](app/models/identity.py), [auth.py](app/auth.py), [App.jsx](frontend/src/App.jsx).
- [ ] **M2-T2** `visibility` on `Page` and `Block` using the **existing** `internal|client`
      vocabulary (finding E). Enforce in the **data layer**, not the UI.
      *Done when:* an `internal` page is absent from a client's tree response — not merely hidden.
- [ ] **M2-T3** Approval state machine: `draft → in_review → approved`, plus
      `changes_requested` and `approved_changed_since`. Approving writes a `PageVersion`
      snapshot **with live values resolved at that moment** and pins it.
      *Done when:* "what did they approve" is answerable from the pinned version alone.
- [ ] **M2-T4** Post-approval edits set `approved_changed_since` **with a diff**; never a
      silent revert to the approved copy.
- [ ] **M2-T5** Approval gate hook: `blocks_list_build` — a pipeline step can require an
      approved page. Wire the check, leave the pipeline call site for M4.
- [ ] **M2-T6** Bucket A read-only exposure, pass 1: client-safe serializers for leads,
      segments/TAM, meetings, replies (intent + status only), deals, mailbox status,
      `/reports/summary` (cached 60 s). **Never** cost, model names, prompt internals,
      margin or delivery notes.
      *Files:* [crm.py:522](app/routers/crm.py:522), [enrich_lists.py](app/routers/enrich_lists.py), [reply/engine.py](app/reply/engine.py).
      *Done when:* a client token's response body contains no field on the deny-list — asserted by a test.
- [ ] **M2-T7** *(independent quick win, Bucket B)* Meeting outcome: write endpoint + one-click
      row control on `Deal.meeting_outcome` (**column already exists** — finding 6), auto-set
      to `Qualified` when a deal moves to Proposal.
- [ ] **M2-T8** Smoke tests, in the file's existing `check(...)` style (finding G):
      cross-workspace `page_id` → **404**; client requesting an `internal` page → **404**;
      non-`client_admin` approving → **403**.
      *Files:* [tests/test_smoke.py](tests/test_smoke.py).
- [ ] **M2-T9** Rebuild + commit `frontend/dist`.

**Exit check:** client approves · version pins · internal pages invisible in the data layer ·
cross-workspace access 404s, covered by a test.

---

### M3 — Live blocks (C2) · `not started`
> Depends on M0-T5 (bridge extracted), M2.

- [ ] **M3-T1** `app/workspace/bindings.py` — registry `entity_type → {read, write, preview}`.
      Start with `icp`, `format`, `rule`; `metric_query` **read-only**.
      *Done when:* an unregistered `entity_type` raises, never silently no-ops.
- [ ] **M3-T2** The `live` block stores **only** a pointer (`entity_type`, `entity_id`,
      `field_path`). Values resolve server-side on read.
      *Done when:* a test asserts no `EnrichConfig` value is ever persisted into a `Block`
      (brief §7: no second knowledge store).
- [ ] **M3-T3** Write path: `preview → QC → apply → audit`, routed through
      `app/enrichment/bridge.py`. Client edits get the **same** QC and banned-phrase pass —
      no relaxation (brief §7).
- [ ] **M3-T4** Rollback from the doc UI, reusing `WorkspaceTrainingRevision`.
      *Done when:* edit → apply → rollback restores the prior value **and** leaves both audit entries.
- [ ] **M3-T5** Remaining bindings: `case_study`, `segment`, `angle`, `icp_test`.
- [ ] **M3-T6** Frontend live-block editor with an inline diff preview before apply.
- [ ] **M3-T7** Rebuild + commit `frontend/dist`.

**Exit check:** editing the ICP block in a doc changes `cfg.icp_definition`, writes an audit
entry, and is revertible.

---

### M4 — Launch plan (C5) · `not started`
> Gate: **D2** (template content), **D3** (warm-up source).

- [ ] **M4-T1** Warm-up input per D3: `warmup_started_at` (+ optional health) on
      `MailboxConnection`; auto-set on connect, operator-overridable. **This does not exist
      today** (finding C) and the countdown is wrong without it.
- [ ] **M4-T2** Models: `PlanTemplate`, `PlanTemplateTask`, `Plan`, `PlanTask` (+ Alembic).
      `PlanTask` carries `owner_role` (us/client/system), `auto_source`, `baseline_*`, and
      `link_kind`/`link_id` (added now so M5 is pure wiring).
- [ ] **M4-T3** Seed the standard RevCadence template (per D2). If reconstructed, mark each
      duration `PROVISIONAL` in the seed data so wrong numbers are visible, not invisible.
- [ ] **M4-T4** Instantiate per client on workspace creation; store a **baseline** snapshot
      for baseline-vs-actual.
      *Files:* [app/provision.py](app/provision.py), [app/bootstrap.py](app/bootstrap.py).
- [ ] **M4-T5** `auto_source` event closers — **no human ticks these**: `onboarding_form`,
      `crawl_complete`, `brain_built`, `warmup_complete`, `doc_approved:<page_id>`,
      `list_researched`, `first_send`. `doc_approved` hooks the M2 approval event.
- [ ] **M4-T6** Critical path:
      `launch = max(warmup_started + 14d, angles_approved + list_build, icp_approved + list_build)`.
      Warm-up is normally binding. Overdue client task → show the **new projected date**, not a red dot.
      *Done when:* a unit test covers each of the three terms winning.
- [ ] **M4-T7** Views: Gantt (hand-built, ~200 lines), List, Board.
- [ ] **M4-T8** Overview page: countdown + the **named** blocking item.
- [ ] **M4-T9** Rebuild + commit `frontend/dist`.

**Exit check:** Overview shows a correct countdown and correctly names what is blocking.

---

### M5 — Deep links (C8) · `not started`
> Depends on M4-T2 (`link_kind`/`link_id` already on the model).

- [ ] **M5-T1** Resolver: `link_kind` + `link_id` → a frontend route. Note the app uses
      **HashRouter** (finding F) — links are `#/…`.
- [ ] **M5-T2** Render the Overview stage rail, Gantt task names and List rows as links.
      *Partly done in M0-T8:* the Overview stage rail is built and all seven phases already
      route. It carries **no status** yet — progress arrives with M4, and a fabricated
      "you are here" is worse than none.
- [ ] **M5-T3** Wire the seven phase targets from `AGENT_BRIEF.md` §C8 (Intake, Client Brain,
      ICP & Targeting, Infrastructure, Angles & Copy, List Build, Launch).
- [ ] **M5-T4** **No dead-end status:** a test asserting every phase and every seeded task
      resolves to a real route. A broken link is a failing test, not a 404 in the demo.
- [ ] **M5-T5** Rebuild + commit `frontend/dist`.

**Exit check:** every stage and task clicks through to where the thing is happening.

---

### M6 — Email sequences (C4) · `not started`
> Gate: **D1**. Can start right after M0 with a second dev.

- [ ] **M6-T1** Models: `Angle`, `Sequence`, `SequenceStep`, `Variant`, `SequenceTemplate`
      (+ Alembic). Variants **A–G**, each individually enabled; enabled variants rotate evenly.
- [ ] **M6-T2** Variant bodies use `{{placeholders}}` resolved through the **same bindings as
      M3** — editing in the doc or the sequence moves both. One resolver, not two.
- [ ] **M6-T3** `change_note` **required** on every variant. Enforce at the model/schema
      layer, not the form.
- [ ] **M6-T4** Every variant runs the existing QC + banned-phrase + evidence check before it
      can be enabled. Missing proof asset → **"needs proof"**, cannot enable.
- [ ] **M6-T5** Promote winner → copy to slot A, archive losers **with stats intact**. Never delete.
- [ ] **M6-T6** Seed three org-level 4-step templates: Standard, Case-study led, Trigger-event.
- [ ] **M6-T7** Sequences UI. (Prototype reference is missing — finding A. Build from
      `DESIGN_SYSTEM.md` tokens and confirm the layout with the team before polishing.)
- [ ] **M6-T8** **Per D1(b):** enabled variants export as the campaign payload; show exactly
      what will send. `M6b` (deferred): real push/sync to Bison + Instantly.
- [ ] **M6-T9** Rebuild + commit `frontend/dist`.

**Exit check:** a 4-step sequence with A–G variants exists; toggling a variant changes the
send payload (definition per D1).

---

### M7 — Views (C6) · `not started`
> Depends on M0-T7. Otherwise independent.

- [ ] **M7-T1** `View` model = `dataset` + `type` + `config` (filters, columns, sort, group_by),
      workspace-scoped (+ Alembic).
- [ ] **M7-T2** **Dataset resolver** — the new glue: `dataset` name → one workspace-scoped
      query with filters/sort/pagination. Datasets: meetings, leads, deals, companies,
      contacts, segments, case_studies, icp_tests, plan_tasks.
      *Done when:* every dataset goes through `scoped()`; a cross-workspace filter cannot be injected.
- [ ] **M7-T3** Five renderers over **one** `View.config`: table, list, board, calendar, gantt.
      Table = the existing `DataTable` with the M0-T7 controlled-views props. Gantt reuses M4-T7.
- [ ] **M7-T4** Saved views persist server-side per workspace.
- [ ] **M7-T5** `view` block embeds a saved view in a page.
- [ ] **M7-T6** Rebuild + commit `frontend/dist`.

**Exit check:** one dataset renders as table / list / board / calendar / gantt from a single config.

---

### M8 — Library + provenance (C7) · `done — 2026-08-17`
> Built ahead of M4–M7. It only needed M6's sequence objects (already shipped) for its
> usage counts, and it unblocks the evidence rule every later milestone leans on.

- [x] **M8-T1** `LibraryCaseStudy`, `LibrarySegment`, `LibraryIcpTest`, `LibraryExclusion`
      (+ Alembic `a7c3f19d8b52`, verified with a real `upgrade head`), each with **mandatory**
      `source: verified \| client_supplied \| operator`, plus `source_url`, `verified_at`,
      `verified_by`. `source` is `nullable=False` with **no server_default**, and
      `store.clean_source()` raises rather than guessing.
      *Files:* [app/models/library.py](app/models/library.py), [app/library/store.py](app/library/store.py),
      [app/routers/library.py](app/routers/library.py).
      *Done:* a row cannot be created without `source`; `verified` additionally cannot be
      created without a link.
- [x] **M8-T2** **Writer change:** named claims only from `verified`, enforced on both writer
      paths. (a) Sequence QC — copy containing the client name of a non-verified case study
      fails with `unverified_named_claim`, and the existing enable gate refuses the variant.
      (b) Per-lead writer — the Library reaches the prompt as
      `client_library.{nameable_proof, background_only}` plus an explicit rule, so
      unverified proof stays usable as background and cannot be named.
      *Files:* [app/routers/sequences.py](app/routers/sequences.py),
      [app/enrichment/pipeline.py](app/enrichment/pipeline.py) (`_client_packet`, `_library_rule`),
      [app/library/store.py](app/library/store.py) (`writer_packet`, `WRITER_RULE`).
      *Done:* smoke asserts the QC failure, the refused enable, and that the same copy passes
      once verified. Legacy `profile["case_studies"]` treatment is deliberately unchanged —
      see the note under M8-T1 findings below.
- [x] **M8-T3** Client "+ Add" surfaces, contextual not blank: *Add a case study* ·
      *Add an account we should not contact* · *Add an objection you hear on calls*. The last
      two open the list they write into, so their records have a home without inventing two
      more tabs. `source` is decided server-side from the token in `_source_for()` — a client
      request asking for `verified` is ignored, asserted by a test.
      *Files:* [frontend/src/client/pages/Library.jsx](frontend/src/client/pages/Library.jsx).
- [x] **M8-T4** Do-not-contact list, client-owned; **exclusions apply before research runs**.
      Checked at the top of `process_lead`, ahead of the free verify — an excluded account
      never reaches Reoon or the crawler. Matching is exact on a normalised domain, never a
      substring. Reuses the existing `skipped` / Non-ICP vocabulary, so no counter or export
      needed changing.
      *Files:* [app/enrichment/pipeline.py](app/enrichment/pipeline.py), [app/routers/forms.py](app/routers/forms.py).
- [x] **M8-T5** Rebuilt + committed `frontend/dist`. Delta: CSS 220.6 → 221.2 kB, main chunk
      +0.5 kB, `Library` chunk 19.6 kB. **No new dependencies.**

**Exit check:** ✅ a client-added case study is tagged `client_supplied`, flagged where the
angle is chosen, and refused as a named claim by QC.

**Findings this milestone raised**

| # | Finding | Consequence |
|---|---|---|
| I | **The old proof key was a content hash.** `_proof_choices` keyed each case study on `sha256(json(item))`, so editing a case study orphaned every angle pointing at it and QC then reported "missing proof" on copy nobody had touched. | Fixed by real rows with stable ids (`lib:<id>`). Legacy hash keys still resolve, and `import_unfiled` **repoints** angles as it files them — covered by a test. |
| J | **`EnrichConfig.profile["case_studies"]` was a store with no rules.** `source` was an optional free-text string ("whiteboard", "operator_supplied", absent), so rule 4 could not be enforced on it. | The table is now the source of truth. That profile key became an **inbox**: the Library lists it as unfiled with a *File it* action. The crawler and brain chat keep writing there; nothing is destroyed. |
| K | **Three writers were feeding the old store.** `/api/sequences/proof`, the whiteboard proof promotion, and the `library.case_study` form mapping all appended to the profile JSON. | All three now write Library rows. Without that, the Library would have been a nicer view over a second store — the exact drift rule 1 exists to prevent. |
| L | **`library.do_not_contact` only accepted email addresses** and wrote `ReplyBlock`, which is *inbound* reply suppression. Clients answer that question with domains and company names. | Exclusions are their own object with `kind: domain \| company \| email`; email entries are **mirrored** into `ReplyBlock` so inbound and outbound agree without conflating the two. |
| M | **The per-lead writer receives the whole brain profile**, `case_studies` included, so a named claim could come from there too. | Rule wired on that path as well (M8-T2b). Legacy profile entries keep their current treatment: client answers and client additions no longer land there, so what remains is our own crawler/operator notes, and demoting it would change copy for live workspaces to enforce a rule about facts that are not in it. |

---

### M9 — Notifications + instantiation (C10, C11) · `not started`
> Gate: **D2** (seed content).

- [ ] **M9-T1** Extend [app/digest.py](app/digest.py) (builders are already pure and testable):
      weekly client digest; immediate alert on **approval requests only**; batch comments.
- [ ] **M9-T2** The digest must say, in one sentence: *"2 things need you: approve Angles v4,
      upload 2 case studies. Launch slips to Sep 8 if not done by Friday."* Pull the slip date
      from M4-T6.
      *Done when:* a test asserts that exact sentence shape from fixture data.
- [ ] **M9-T3** Workspace instantiation: page tree + plan + default sequences from templates,
      pre-filled from the onboarding form ([app/models/onboarding.py](app/models/onboarding.py))
      and the website crawl ([app/enrichment/crawler.py](app/enrichment/crawler.py)).
- [ ] **M9-T4** Seed content per D2. Target: a new client lands on a workspace **~60% written
      about them**.
- [ ] **M9-T5** Rebuild + commit `frontend/dist`.

**Exit check:** a new client lands on a pre-filled workspace; the digest sends.

---

### M10 — Whiteboard block (C9) · `not started`

- [ ] **M10-T1** **Check tldraw's commercial licence before writing any code.** If it fails,
      stop and re-decide — do not build around it.
- [ ] **M10-T2** `whiteboard` as a **block type inside a page** — not a separate section.
      One page tree, one comment system, one permission model, one approval flow. Canvas JSON
      stored opaquely.
- [ ] **M10-T3** On approval of a page containing a canvas, the version snapshot stores a
      **rendered PNG + the canvas JSON**; approvals show before/after images (you cannot
      text-diff a drawing).
- [ ] **M10-T4** Promote a sticky note into a real `Segment` record.
- [ ] **M10-T5** Rebuild + commit `frontend/dist`.

**Exit check:** a sticky note promotes into a real Segment record.

---

## 4b. Track 2 — the client operates their own workspace (M11–M16)

**Added 2026-08-18.** Track 1 (M0–M10) makes the client a *reader* with three narrow write
paths: Library additions, doc comments, their onboarding form. Everything else is ours —
[client_space.py](app/routers/client_space.py) states it outright: *"Writes are ours. A
client reads their launch; they do not edit it."*

Track 2 reverses that for everything **workspace-scoped**. The client's sales team runs
their own reply setup, inbox, follow-ups, brain and profile. We keep the org-level machinery.

### Outstanding debt from shipping M13 first

M13 shipped on 2026-08-18 before M11 and M12, which §4b's own milestone map calls
load-bearing. Nothing below is hypothetical — it is live now:

| Owed | What is true today | Milestone |
|---|---|---|
| Client-safe reply serializer | The client's Inbox renders `intent_reason`, `confidence` and the engine's `action` verbatim. These endpoints were already reachable by a client token before the screens were mounted (that is M12-T1's finding), so the surface did not widen — but it is now on a menu instead of behind a URL nobody had. | **M12-T1/T2** |
| Actor trail | The client can send replies (`/leads/{id}/send` was always `get_ctx`). `ReplyLead` still has no `sent_by_user_id`, so a sent reply cannot name who sent it. | **M11-T3** |
| Draft collision guard | Both sides can now reach one draft through the UI. Nothing refuses a stale send. | **M11-T4** |
| `is_client()` choke point | Role checks are still bare literals. | **M11-T1** |

D11 also became urgent rather than deferrable: (a) is now a live exposure decision, not a
design question.

### Findings this track has raised

| # | Finding | Consequence |
|---|---|---|
| **N — resolved 2026-08-18** | **`/reply/settings` wrote to nothing.** The nine `AppSetting` rows under `reply.*` have exactly two writers — the settings endpoint itself and `scripts/import_reply_config.py` — and **zero readers** anywhere in `app/`. `build_ai_cfg` ([reply/engine.py](app/reply/engine.py)) takes provider keys from `ReplyWorkspace.openai_key_enc` / `gemini_key_enc` falling back to `OPENAI_API_KEY` / `GEMINI_API_KEY` in the environment, and model names from `REPLY_OPENAI_MODEL` / `OPENAI_MODEL` in the environment only. `review_webhook_url`, `default_bison_base_url`, `reply_trigger_tag` and `followup_trigger_tag` have no reader at all. | **DECIDED: the screen goes to the client, scoped per workspace.** Five columns added to `reply_workspaces` (Alembic `c9a4d1e60b73`) so the seven non-secret values have a per-space home; the two secrets already had one. `/api/reply/settings` now resolves its scope from the caller — the org row for a master on "All workspaces", the workspace's own reply space for everyone else — so one screen serves both without a client's save ever reaching the org row. `openai_model` / `gemini_model` are now **read** by `build_ai_cfg`, at the same precedence the keys already used (workspace → env → default), so that half of the screen is live. `review_webhook_url` and the two Bison trigger tags still have no reader; they persist and the screen labels them *"saved, not yet acted on"* rather than implying otherwise. Wiring those is an outbound POST in the send path — real work with real failure modes, not a side effect of moving a screen. |

| **O** | **`GET /api/enrich-lists/reoon/balance` checked nothing.** It took a `workspace_id`, loaded that workspace's `EnrichConfig`, decrypted its Reoon key and called the vendor with it — with no `require_workspace`. Any signed-in account could read any workspace's credit balance, billed against that workspace's key. It never returned the key itself, which is why it survived: the response looked harmless. | Fixed 2026-08-18 with the one missing line, plus a smoke check. Worth generalising: this endpoint was written before the client had any reason to reach it, and it is the second of its kind found in two days (the other being `update_rws` copying `workspace_id` off the body). **Every endpoint taking a `workspace_id` should be audited for a matching `require_workspace`** — that is a grep, and it belongs in M12. |

| **P** | **Absolute links are the tax on "one UI, two bases".** Mounting the CRM for the client turned up 51 hardcoded `/companies/5`-style links across 16 files. None is a build error — in the client shell they match no route, and the shell's catch-all returns the reader to their Overview, so the symptom is a link that "does nothing" rather than an error anyone can see. A further six were `#/…` hrefs, which the client host cannot follow at all. | Fixed with one helper (`appPath` + `useAppPath`) rather than 51 edits of judgement. Two traps worth knowing before the next module moves: a page with several components needs the hook in **each** one (a bare `appTo` compiles and throws only when clicked), and `DealRecord`'s `DocTab` already binds `to`, so the local is `appTo`. Both were caught by a scope checker, not by the build — **the build cannot see this class of bug**, so any future two-base mount needs the same check. |

### The governing rule: one UI, two bases

The client gets **the operator's screens**, mounted at a second base — not a client-flavoured
rewrite. This is already the pattern `clientSpaceRoutes(base)` uses for Docs, and the reason
is written at the top of [nav.jsx](frontend/src/clientspace/nav.jsx): the support call that
starts *"I can't find it"* is only answerable if both people are looking at the same screen.

Consequences, and they are the whole design:

- Differences between operator and client are **field-level, inside one component** — an
  operator-only card, an operator-only column — never a forked page.
- The **server** is the boundary. The sidebar is a convenience; a client who types the URL
  gets the same answer the rail implies. Three things must always agree: nav, route, endpoint.
- A screen that currently opens with `if (!me.is_master) return <ErrorBox …>` is not
  "protected" — it is **unported**. That guard is the work item, not the security model.

### Where the line falls: `BUILD_BY_MODE` vs `SYSTEM_NAV`

The split the client asked for already exists in [App.jsx:126-155](frontend/src/App.jsx#L126).
It is not a new taxonomy — it is the one the operator sidebar already draws.

| | Contents | Owner |
|---|---|---|
| `BUILD_BY_MODE` + per-workspace operational screens | Reply Setup, Client Profile, Brain, ICP, Formats, Rules, Email Accounts, Inbox, Lists, Pipeline, Reports | **the client** — this is their business |
| `SYSTEM_NAV` + `/admin` + `/billing` | Forms builder, Activity, Jobs, Settings, Developers, CRM Integrations, Admin, Billing | **ours** — org-level, cross-client |

**One exception, and it is misfiled today:** `/reply/settings` sits in `BUILD_BY_MODE.reply`
but writes `AppSetting` rows — org-wide OpenAI/Gemini keys, model names, the shared Bison
base URL ([ReplySettings.jsx](frontend/src/pages/ReplySettings.jsx)). It is System wearing a
Build label and it must **not** cross the line. `/reply/setup` next to it is genuinely
per-workspace and does cross.

### Decisions — recorded 2026-08-18

| ID | Decision | Blocks |
|---|---|---|
| **D7** | **DECIDED 2026-08-18: both send.** Operator and client both send replies directly. No approval queue, no draft-and-release. The cost is that two people can now act on one thread — paid for by M11-T3/T4, not by a gate. | M14 |
| **D8** | **DECIDED 2026-08-18: the client configures `/reply/setup` themselves, including their own Instantly/Bison key.** Not a read-only mirror, not an agency-held key. This *supersedes* **D1** for reply and follow-up sending: the client owns the connection. D1's mirror decision still governs the read-only **cold** campaign view at `/w/sequences` — different objects, both stay. | M13 |
| **D9** | **DECIDED 2026-08-18: everything workspace-scoped is the client's; `SYSTEM_NAV` stays ours.** Codified as the table above and enforced as one list, read by both the router and the sidebar. | M11 |
| **D10** | **DECIDED 2026-08-18: every client user is equal.** No `client_admin` for now — this *defers* **D5** rather than answering it. M11-T1 still lands the `is_client()` choke point so introducing a role later is one file, not an audit. | M11 |
| **D11** | **OPEN.** Three field-level calls inside the shared screens: (a) does the client see `intent_reason` / `confidence` on a reply? (b) can the client set `auto_send` on a response type? (c) does the client see the AI provider card? | M12 |

---

### M11 — Boundary + actor trail · `not started`
> Foundation. Nothing else in this track is safe to build first.

- [ ] **M11-T1** `is_client()` / `CLIENT_ROLES` in [auth.py](app/auth.py); replace every bare
      `role == "client"` comparison, backend and frontend. **This is M0-T6, carried in** — it
      was a prerequisite for `client_admin` and it is now a prerequisite for this whole track.
      No new role (D10); one choke point so adding one later is one file.
      *Files:* [auth.py](app/auth.py), [App.jsx](frontend/src/App.jsx#L222), every router doing a role compare.
      *Done when:* zero bare `"client"` role comparisons remain; smoke passes.
- [ ] **M11-T2** One capability list, read by the router **and** the sidebar — the
      `BUILD_BY_MODE` / `SYSTEM_NAV` split above, expressed once and never as two hand-kept copies.
      *Done when:* removing a screen from the list removes it from the client's rail **and**
      404s the endpoint, from a single edit.
- [ ] **M11-T3** Actor columns on `ReplyLead`: `drafted_by_user_id`, `sent_by_user_id`,
      `draft_updated_at` (+ Alembic revision). Every send writes an `Activity` naming the
      human. **`ReplyLead` has no actor today** ([reply.py](app/models/reply.py#L76)) — the
      moment both sides can send, "who sent this" is unanswerable without it.
      *Done when:* a sent reply reports the user who sent it, on both bases.
- [ ] **M11-T4** Draft collision guard. D7 removed the gate, so this is what pays for it:
      `POST /leads/{id}/send` carries the draft's `draft_updated_at`; a stale one is refused
      with *"<name> edited this at 14:32 — reload"*. The thread header shows who is holding it.
      *Done when:* two sessions editing one draft cannot both send; a test covers the refusal.
- [ ] **M11-T5** Smoke checks in the file's existing `check(...)` style (finding G): client
      hitting a `SYSTEM_NAV` endpoint → 404 · client hitting another workspace's reply space
      → 403 · stale send → 409.

**Exit check:** the client/system line is one list · every send names a human · two people
cannot double-send one thread.

---

### M12 — Client-safe serializers · `not started`
> Depends on M11. This is the layer every screen below mounts on.

- [ ] **M12-T1** **Close the standing gap first.** Every `/api/reply/*` lead endpoint and
      **every** `/api/mailbox/*` endpoint is `Depends(get_ctx)` today — workspace-scoped but
      otherwise unfiltered. `GET /api/reply/leads` already returns `intent_reason`,
      `confidence`, `action`, `platform` and `reply_workspace` to any token that can reach it
      ([reply.py](app/routers/reply.py#L440)). The client lockdown on these routes is
      **UI-only**; a client token reaches them today by typing the URL.
      *Done when:* a test asserts a client token's response body carries no denied field.
- [ ] **M12-T2** Answer **D11** and encode it. Deny-list floor regardless of the answer:
      `send_meta`, `lead_data`, raw vendor payloads, cost figures, model names, prompt
      internals, any `*_enc` column, other workspaces. Reuse the `internal | client`
      vocabulary from [client/schema.py](app/client/schema.py) — do not invent a third.
- [ ] **M12-T3** Keep org-level endpoints `require_master`: `GET/PUT /api/reply/settings`,
      `POST /api/reply/workspaces`, `/duplicate`, and the `GET /api/reply/workspaces` list.
      Only `/workspaces/for/{ws}` and `PUT /workspaces/{id}` open up, workspace-scoped, and
      `PUT` must refuse a changed `workspace_id`.
- [ ] **M12-T4** The deny-list test, in `tests/test_smoke.py`'s `check(...)` style.

**Exit check:** a client token cannot read a field on the deny-list from any endpoint in this
track, asserted by a test rather than by a sidebar.

---

### M13 — Reply Setup, client-operated (D8) · `not started`
> The screen the client named. Depends on M11, M12.

- [ ] **M13-T1** Mount [ReplySetup.jsx](frontend/src/pages/ReplySetup.jsx) at the client base.
      **One component** — delete `if (!me.is_master) return <ErrorBox msg="Master access
      required." />` ([ReplySetup.jsx:133](frontend/src/pages/ReplySetup.jsx#L133)) and gate
      the *AI model* card on `is_master` instead (pending D11c). The page reads `wsParam`,
      which the client shell already sets via `useActiveWorkspace` — no workspace-switcher
      dependency to unpick.
- [ ] **M13-T2** Open `GET /api/reply/workspaces/for/{workspace_id}` and
      `PUT /api/reply/workspaces/{rws_id}` from `require_master` to workspace-scoped.
      `name` is the webhook routing key and is **globally unique** — a client rename must
      refuse a collision rather than silently steal another space's webhooks.
- [ ] **M13-T3** **Fix `WebhookBox`.** It builds the URL from `window.location.origin`
      ([ReplySetup.jsx:26](frontend/src/pages/ReplySetup.jsx#L26)). On the client host that
      yields `app.revcadence.com/api/reply/webhooks/…` — the client host, not the engine host.
      A client would paste a URL into Instantly that never delivers a reply, and the failure
      mode is a permanently empty inbox with no error anywhere. Use the API origin.
      *Done when:* the copied URL is identical on both hosts, covered by `npm run check`.
- [ ] **M13-T4** Client-owned credentials: `api_key` and `calendly_token` stay write-only and
      encrypted, unchanged. The client pastes their own Instantly key. Never echoed back — the
      existing `*_set` boolean pattern already does this correctly.
- [ ] **M13-T5** `POST /workspaces/{id}/build-reply-formats` and `/calendly-probe` open to the
      client. **Keep every existing AI cap** (standing rule 6) and count the spend against the
      workspace — a client with a Build button is a new spender.
- [ ] **M13-T6** Response types, the FUP1–6 ladder and Reply Rules are client-editable, and
      run the **same** QC + banned-phrase pass as an operator edit. No relaxation (brief §7).
- [ ] **M13-T7** `auto_send` per **D11b**. If the client may set it, a self-service checkbox
      that makes the system email prospects unattended needs a confirm step naming what it does.
- [ ] **M13-T8** Rebuild + commit `frontend/dist`.

**Exit check:** a client connects their own Instantly account, pastes the webhook URL, builds
their reply formats and saves — with no operator involved, and the first real reply lands.

---

### M14 — Inbox, both operate (D7) · `not started`
> Depends on M11-T3/T4 (actor + collision), M12.

- [ ] **M14-T1** Mount [ReplyInbox.jsx](frontend/src/pages/ReplyInbox.jsx) at the client base.
      One component, client-safe serializer underneath.
- [ ] **M14-T2** Every action the operator has: edit draft, Draft with AI, Approve & Send,
      send follow-up, mark reviewed, book / push to CRM, ignore, block sender. **Both sides
      send** — no queue, no release step.
- [ ] **M14-T3** Show the actor on the row and in the thread: *"drafted by AI · sent by Priya
      (Acme) · 14:32"*. With two parties acting, this is the only way either side can read the
      history.
- [ ] **M14-T4** Block sender writes through the **M8 exclusions object**, not a second list.
      Finding L already established that `ReplyBlock` is inbound-only and mirrors from
      exclusions — keep that direction; do not fork it.
- [ ] **M14-T5** Rebuild + commit `frontend/dist`.

**Exit check:** a client rep and an operator both work the same inbox; every reply names who
sent it; a stale draft cannot be double-sent.

---

### M15 — Profile, Brain, ICP, Formats, Rules · `not started`
> Depends on **M0-T5** (bridge extraction — still open) and M12. Overlaps M3: same machinery.

- [ ] **M15-T1** Mount [EnrichConfig.jsx](frontend/src/pages/EnrichConfig.jsx) (all four tabs)
      and [BrainChat.jsx](frontend/src/pages/BrainChat.jsx) at the client base.
- [ ] **M15-T2** Every client write goes through `app/enrichment/bridge.py` —
      preview → QC → apply → audit → rollback. The same path M3 uses from inside a doc.
      **One write path, two entry points.** Standing rule 1: no second knowledge store.
- [ ] **M15-T3** Field-level `internal | client` visibility over `EnrichConfig`, reusing
      [client/schema.py](app/client/schema.py)'s vocabulary.
- [ ] **M15-T4** **Resolve the two-profile problem.** `EnrichConfig` (workspace-scoped, drives
      the writer) and `ClientProfile` (company-scoped, [client/schema.py](app/client/schema.py))
      both hold offer, ICP, messaging and case studies. Standing rule 1 is *one brain per
      client*. Exposing both to the client guarantees drift, and the client will reasonably
      expect editing one to change the other.
      *Recommendation:* the client edits `EnrichConfig` — it is what actually drives the
      pipeline; `ClientProfile` stays the internal CRM record. Confirm before building the screen.
- [ ] **M15-T5** Rebuild + commit `frontend/dist`.

**Exit check:** a client edits their ICP, sees the diff, applies it, and the change appears in
`cfg.icp_definition` with an audit entry and a working rollback.

---

### M16 — Sending infrastructure & follow-ups · `not started`
> Depends on M12. **M16-T1 is M4-T1** — build it once, both tracks need it.

- [ ] **M16-T1** `warmup_started_at` (+ optional health) on `MailboxConnection`, auto-set on
      connect, operator-overridable (**D3**). Does not exist today (finding C).
- [ ] **M16-T2** Mount [MailboxConnect.jsx](frontend/src/pages/MailboxConnect.jsx) at the
      client base: connect / disconnect / test their own sending accounts, with warm-up status.
      *Note:* `/api/mailbox/*` is already `get_ctx`, so a client token can already connect and
      **disconnect** a mailbox by URL today. M12-T1 makes that deliberate instead of accidental.
- [ ] **M16-T3** `PUT /api/mailbox/followup-defaults` client-editable.
- [ ] **M16-T4** Per-deal follow-up plans and autopilot
      ([mailbox.py](app/routers/mailbox.py#L202)) at the client base. Autopilot sends
      unattended — it gets the same confirm treatment as M13-T7's `auto_send`.
- [ ] **M16-T5** Rebuild + commit `frontend/dist`.

**Exit check:** a client connects a sending account, sees its warm-up state, and sets their
own follow-up cadence.

---

### Remainder — the rest of the workspace-scoped screens

Not milestoned yet; the same one-component-two-bases treatment, no new mechanics. Sequence
them once M11–M12 are in: Lists · Database · Pipeline · Reports · Revenue Inbox · Companies ·
Contacts · Onboarding · Invoices · Blueprints & Agreements · Reply Dashboard · Processing ·
Test Thread.

### Risks this track adds

| Risk | Impact | Mitigation |
|---|---|---|
| **`get_ctx` reply/mailbox endpoints are already open to client tokens** | A client can read model reasoning and disconnect mailboxes *today*, by URL | M12-T1 **before** any screen is mounted. This is the one item that is a live gap, not a future one |
| **Both sides send (D7)** | Double-sends and contradictory replies to one prospect | M11-T3 actor trail + M11-T4 collision guard. Neither is optional — they are what replaced the approval gate |
| **`WebhookBox` origin (M13-T3)** | Client self-serves, pastes a dead URL, inbox stays empty, no error surfaces anywhere | Fix before M13 ships; cover with `npm run check` |
| **Client-triggered AI spend** | Build-formats and Draft-with-AI become client-callable | Existing caps unchanged (standing rule 6); attribute spend to the workspace |
| **Two client profiles (M15-T4)** | Client edits one, the other silently disagrees | Decide before the screen is built, not after |
| **Everyone equal (D10)** | Any client rep can rewrite the ICP, the reply rules, or disconnect a mailbox | Accepted for now, explicitly. M11-T1 keeps the reversal to one file |

---

## 5. Standing rules (checked at every milestone exit)

From `AGENT_BRIEF.md` §2, plus what verification added:

1. **One brain per client** — pages point at `EnrichConfig`; they never copy it.
2. **Multi-tenant, fail closed** — every query through `workspace_ids_for_query()` / `scoped()`.
3. **Schema** — new table/column = model **+ Alembic revision**. `db.migrate()` is dev-only
   (finding B). Nothing destructive.
4. **Evidence first** — client facts usable but tagged; named claims only from `verified`.
5. **Accumulate, don't replace** — teaching merges, never wipes.
6. **Cost discipline** — no removing AI content caps, no new uncapped model calls.
7. **Design system** — `DESIGN_SYSTEM.md` tokens and existing components. No page invents
   its own table, button, or layout.
8. **`frontend/dist` is committed** — rebuild and commit it, or the change does not ship.

### Do NOT (brief §7)

CRDT / real-time co-editing · nested databases-in-pages · custom-fields UI · automations
builder · public share links · AI writing inside docs · extending the Blueprint editor into
the page system · a second knowledge store · client-editable computed values (metrics,
verification results, audit entries, prior approvals) · loosening QC, banned-phrase, or
research-sufficiency checks.

---

## 6. Acceptance test (the demo that proves it works)

Run end-to-end at M9. Each row names the milestone that must deliver it.

| # | Step | Milestone |
|---|---|---|
| 1 | Create a client workspace → page tree, launch plan and default sequence appear, pre-filled | M9 |
| 2 | Client logs in, sees only shared pages, comments on a format block | M1, M2 |
| 3 | Operator edits that format from inside the doc → diff → apply → audit → visible in enrich config | M3 |
| 4 | Client approves Angles → version pinned → plan task closes → list-build gate releases → countdown recalculates | M2, M4 |
| 5 | Client uploads a case study → `client_supplied` → writer preview flags it | M8 |
| 6 | Toggle variant C off in step 2 → next send rotation excludes it | M6 (scope per **D1**) |
| 7 | Click "ICP" on the Overview rail → lands on the ICP Definition page | M5 |
| 8 | Client requests another workspace's page id → 404, enforced in the data layer, covered by a test | M2 |

---

## 7. Progress log

One line per completed task. Newest last.

| Date | Task | Note |
|---|---|---|
| 2026-08-16 | M0-T1 | Eight Step-0 questions verified. DataTable already exists — the stated blocker is not a blocker. |
| 2026-08-16 | M0-T2 | Eight further findings (A–H). Three contradict the brief: missing companion files, Alembic vs `db.migrate()`, no warm-up concept. |
| 2026-08-16 | M0-T8 | Client workspace shell shipped: sidebar-only chrome, 13 routes under `/w/*`, Overview on real `/reports/summary` data, 10 sections scaffolded. Raised **D6** (Whiteboards nav vs C9). `dist` rebuilt (+2 kB CSS, no new dependencies). |
| 2026-08-17 | M1 (C1) | **Shared Documents shipped.** 5 tables + Alembic revision `b41c7e05a9d2` (verified with a real `upgrade head`), `app/routers/workspace_docs.py` with visibility enforced in the query layer, 11 block types, TipTap per-block editor, comments, versions, templates. Smoke 68 → **109 checks**. Docs mounted at `/workspace/docs*` and `/w/docs*` from one component. **D1 resolved** in favour of Alembic; `db.migrate()` documented as dev-only. |
| 2026-08-17 | M8 (C7) | **Library + provenance shipped.** 4 tables + Alembic `a7c3f19d8b52` (real `upgrade head`), `app/library/store.py` as the one write path, `app/routers/library.py`, and the three-tab client screen. `source` is mandatory and server-decided. Named claims gated on both writer paths. Do-not-contact applied *before* the first verify call. Five findings (I–M) — the old content-hash proof key was silently orphaning angles. Smoke 248 → **279 checks**. `dist` rebuilt, no new dependencies. |
| 2026-08-17 | M0-T9 | **Client host shipped.** `app.revcadence.com/w/<slug>` is the client workspace, on real paths; `engine.revcadence.com` stays the operator app on the hash router. `PUBLIC_BASE_URL` was doing two jobs — OAuth redirect URI *and* emailed client links — so the client origin became its own `CLIENT_BASE_URL` rather than repointing a setting Google and Microsoft hold a copy of. Invite links are now slug-based; `?ws=` is still honoured and rewritten, so sent invites keep working. Smoke 307 → **308 checks**, plus `npm run check`. **D4 reconfirmed:** the workspace is this repo's SPA, `revcadence.com` stays the marketing site. |
| 2026-08-18 | M13-T1/T2/T3, part of M13-T5 | **Reply Management is on the client rail.** Client sidebar gained the operator's module switcher (`clientspace/modules.jsx`); Reply Management mounts Dashboard, Inbox, Processing, Test Thread and Reply Setup at `/w/<slug>/reply/*` from the **operator's own components** — no forks. Six endpoints moved from `require_master` to workspace-scoped behind a new `_rws_scoped()`; create, duplicate, org settings, live-sequence refresh and campaign mirroring stay ours. `update_rws` now refuses a `workspace_id` change from a non-master — `_apply` copied it straight off the body, so that was a cross-tenant write through an endpoint that passed its own access check. `WebhookBox` now takes its origin from the server: it was building the URL from `window.location.origin`, which is the Vite dev server locally and the client host in production, so a client self-serving would have pasted a URL that looks right and delivers nothing. Extra Channels followed — create and duplicate are workspace-scoped, and a duplicate keeps its source's `workspace_id`, so there is no path from one client's channel to another's. Reply Settings followed too, but had to change shape first (finding N): it is now per-workspace, with Alembic `c9a4d1e60b73`. One bug that shape change created and closed in the same pass — Reply Setup PUTs the whole reply-space row, so it now round-trips the five new columns; without that, saving Setup would silently blank whatever Reply Settings had written, the model included. Smoke 327 → **353 checks**. `dist` rebuilt, no new dependencies. **M11 and M12 are still owed — see the note below.** |
| 2026-08-18 | Track 2 — Outbound | **Outbound is on the client rail**: Lists and Database, plus the whole Build group — Client Profile, Ask the Brain, ICP / Non-ICP, Formats, Rules, Workspace Training — at `/w/<slug>/enrichment/*`, from the operator's own components. The enrichment endpoints were already workspace-scoped, so two things changed: `_training_admin` became `_training_workspace` (it demanded owner/admin on top of the workspace check; a client owning their brain is the point of the client workspace, and the bridge's real safeties — revision snapshot before apply, rollback, `confirm_spend` on evaluate — are untouched), and `reoon/balance` gained the `require_workspace` it never had (finding O). `tests/test_training_bridge.py` asserted the old role gate; it now pins the workspace boundary that replaced it. Smoke 353 → **368 checks**. `dist` rebuilt, no new dependencies. |
| 2026-08-18 | Track 2 — Website Visitors | **Inbound capture joined Client Space**, next to Boards & Tables — one screen does not earn a module, and it is not Outbound: a form-fill travels the other way. Added to the client rail only; the operator already opens the same component from Inbound at `/inbound`, so a second entry would be two URLs for one page. Endpoints were already scoped (`/config` had `require_workspace`, `/visitors` uses `scoped()`); `/rotate` stays master-only because a rotation breaks a live form until the snippet is re-pasted. Two client-facing defects closed: the capture `form_url` came back **relative** whenever `PUBLIC_BASE_URL` was present-but-empty (`os.getenv` defaults only on absent), so a client would paste a path that posts to their own domain; and the lead rows linked to `#/deals/…` and `#/companies/…`, which the client shell does not mount, so those links are now omitted there rather than dead. Smoke 368 → **375 checks**. |
| 2026-08-18 | Track 2 — CRM | **The CRM module is on the client rail**: Pipeline, Reports, Revenue Inbox, Shared Documents, Email Sequences, Blueprints & Agreements, Invoices, Clients, Companies, Contacts, Onboarding, plus Build · CRM (Email Accounts, Client Profile) — eighteen screens at `/w/<slug>/…`, mirroring the operator paths so one helper fixes every link. That helper is `appPath()` in [clientUrl.js](frontend/src/clientspace/clientUrl.js) (+9 cases in `npm run check`) behind a `useAppPath()` hook: **51 absolute links across 16 files** were hardcoded to the operator base, and in the client shell each one matched no route and was silently absorbed by the catch-all. Six were `#/…` hrefs, inert on the client host, and became router links. Backend: three onboarding endpoints dropped `require_master` (they already scoped by workspace); `countersign` keeps it, because that is RevCadence signing, not the client. Smoke 375 → **401 checks**. |
| 2026-08-17 | M10 (C9) | **`/w/whiteboards` now lists real boards** instead of the scaffold's empty state. `GET/POST /api/workspace/whiteboards` reads and writes through `_pages()`, so the section is a filtered view of the page tree with no second content store, no second permission path. New boards land on their own page inside a `Whiteboards` folder; cards show a geometry-only thumbnail and open the document editor. Smoke 179 → **186 checks**. **D6 resolved as (a)**, exactly as recommended. |

---

## 8. Risk register

| Risk | Impact | Mitigation |
|---|---|---|
| **Sequences can't actually change what sends** (finding 3) — cold campaigns live in Bison/Instantly | Acceptance test #6 fails as literally written | **D1.** Ship the source-of-truth + export model first; treat real push as a separate, later integration with its own risk budget |
| **Spec files missing** (finding A) — launch template, seed pages, prototype | M4/M6/M9 content is guesswork; wrong durations look authoritative | **D2** early. Reconstructed values seeded as `PROVISIONAL` so wrongness is visible |
| **Alembic vs `db.migrate()`** (finding B) | New tables silently absent in production | M0-T4 convention + `test_migration_safety.py` in the exit check |
| **No warm-up data** (finding C) | The countdown — the workspace's headline number — is wrong | M4-T1 before M4-T6. Never ship a countdown with a fabricated input |
| **`client_admin` role sprawl** (finding 7) | A missed `"client"` literal silently grants or denies access | M0-T6 audit **before** M2 introduces the role; D5 keeps it a strict superset |
| **TipTap / tldraw weight** (finding F) | `dist` is committed and served — bundle growth is a shipped cost | Measure at M1-T1 and M10-T1; record the delta in §7 |
| **Two repos** (finding H) | Building the workspace in the wrong codebase | **D4** before any M1 frontend work |
| **Scope** — 11 milestones is a lot | Half-finished everything | M1–M5 are the product. M6 parallelises. M7–M10 are droppable |
