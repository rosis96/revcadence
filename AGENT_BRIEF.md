# Agent brief — RevCadence Client Workspace

**Repo:** `revcadence-engine`
**Companion files:** `revcadence-workspace-prototype.html` (open in a browser — the visual
spec), `WORKSPACE_SPEC.md` (full data model), `EXAMPLE_PAGES.md` (seed content).

---

## 0. Mission

Build a **client-facing workspace** inside each client's existing workspace. The client
logs in and sees: where their launch is, what needs them, the documents they approve, the
emails that will send, and their live results.

Most of the *data* already exists — it lives on the admin side. A large part of this job
is exposing it to the client safely. But three things are genuinely new and must be
built from scratch:

1. a **document system** (pages, blocks, comments, versions, approvals)
2. an **email sequence** object (angle → steps → A–G variants)
3. a **launch plan** (tasks with owners, dates, dependencies, a projected launch date)

Do not describe this project as "copy admin pages to the client side." That is true for
maybe 40% of it. The other 60% does not exist yet.

---

## 1. STEP 0 — verify before you build

**This brief was written without direct access to `revcadence-engine`.** The "already
exists" claims below come from `README.md`, `VISION_FOR_CODEX.md` and `DESIGN_SYSTEM.md`.
Before estimating or coding, confirm each one and report back what is actually there.

Check and report:

| # | Question | How to check |
|---|---|---|
| 1 | Does a shared `DataTable` component exist? | `frontend/src/` — search for a generic table component. `DESIGN_SYSTEM.md` says pages hand-roll tables. **This blocks the views work.** |
| 2 | Is there any `Page` / `Document` / `Note` model beyond `Blueprint`? | `app/models/` |
| 3 | Is there a campaign / sequence / step object anywhere? | `app/models/`, `app/routers/` — or is sending entirely delegated to Instantly/Bison? |
| 4 | Is the Training Bridge preview→apply→rollback logic a reusable service function, or inline in a router? | `app/routers/enrich_lists.py`. Inline → extract it first. |
| 5 | Do `formats` support multiple variants per variable, or one definition each? | `EnrichConfig.formats` shape |
| 6 | Is there a `Meeting` model, or are meetings implied by Calendly event + Deal + Activity? | `app/models/crm.py`, `app/reply/calendly.py` |
| 7 | Does `Membership` support adding a role, or are roles an enum that needs a migration? | `app/models/identity.py` |
| 8 | Is `frontend/dist` still committed and served by FastAPI? | repo root / `app/main.py` |

Report answers before writing code. If any answer contradicts this brief, say so.

---

## 2. Non-negotiable rules

These come from `VISION_FOR_CODEX.md` §8 and are not stylistic preferences.

1. **One brain per client.** The workspace must never store a second copy of the ICP,
   formats, rules or profile. Doc pages point at `EnrichConfig` — they do not copy it.
2. **Multi-tenant, fail closed.** Every query goes through the existing
   `AuthContext.workspace_ids_for_query()` / `scoped()`. A client sees exactly one
   workspace. Add a test in `tests/test_smoke.py` proving cross-workspace access 404s.
3. **Additive migrations only.** New tables/columns via `db.migrate()`. Nothing
   destructive.
4. **Evidence first, never fabricate.** Client-supplied facts are usable but must be
   tagged; the writer may only make *named* claims from verified evidence.
5. **Accumulate, don't replace.** Teaching the brain merges; it never wipes prior work.
6. **Cost discipline.** Do not remove AI content caps. No new uncapped model calls.
7. **Design system.** Use the tokens and components in `DESIGN_SYSTEM.md`. No page
   invents its own table, button, or layout. The prototype already uses these tokens —
   lift them.

---

## 3. Bucket A — already exists, just expose it to the client (read-only)

This is the "copy admin → client" part. No new pipelines. Wrap existing queries in
client-safe, workspace-scoped, read-only endpoints and render them in the workspace UI.

| Client sees | Comes from | Notes |
|---|---|---|
| Prospect / lead list with verify + research status | enrichment lists, `enrich_lists.py` | hide internal cost/diagnostic fields |
| "142 flagged insufficient evidence" | pipeline research-sufficiency gate | shown as a status, not an error |
| Segments, TAM, in-list counts | enrichment + list counts | |
| Meetings | Calendly webhook (`reply/calendly.py`) + CRM | see Bucket B for the outcome field |
| Replies and intent classification | `reply/engine.py` | client sees intent + status, not the raw model output |
| Deals / pipeline | `models/crm.py` | |
| Mailbox warm-up status, health | `mailbox/service.py` | drives the launch countdown |
| Reply rate / sent / positive / meetings metrics | `/reports/summary` | never typed by hand, cached 60s |
| Case-study and brain content | `EnrichConfig.profile` | rendered as live blocks, see Bucket B |

**Rule:** the client never sees cost figures, model names, prompt internals, other
workspaces, or internal margin/delivery notes. Add a `visibility` concept, don't rely on
the UI hiding things.

---

## 4. Bucket B — exists, but needs a client-safe *write* path

| What | Today | Needs |
|---|---|---|
| ICP definition | admin edits `cfg.icp_definition` | client can edit via a live block → preview → QC → apply → audit → rollback |
| Formats / variables | admin edits `cfg.formats` | same, plus the QC + banned-phrase pass runs on client edits identically |
| Global rules | `cfg.rules` | same |
| Case studies / proof | brain chat, operator-entered | client can add; new records tagged `client_supplied` |
| Do-not-contact list | operator-managed | client-owned; exclusions apply before research runs |
| **Meeting outcome** ("Quality of lead") | not captured — this is the ClickUp column that always says "No update" | one-click field on the meeting row; auto-set to Qualified when a deal moves to Proposal |

The apply path already exists — it is the **Workspace Training Bridge**
(preview revision → audit entry → rollback snapshot). Reuse it. Do not write a second one.

---

## 5. Bucket C — genuinely new. Build these.

### C1. Document system
`Page`, `Block`, `PageVersion`, `Comment`.

- Page tree (sections: Strategy / Operations / Reference / Internal), page kinds, ordering
- Block editor — **TipTap**, exactly 11 block types, no more:
  `heading, text, list, checklist, callout, table, file, divider, embed, live, view`
- Comments anchored to a block, threaded, resolvable
- Autosave (debounce 800ms), optimistic UI, rollback + toast on error
- Version history; **no real-time co-editing, no CRDT** — last-write-wins plus history

### C2. Live blocks
`app/workspace/bindings.py` — a registry mapping `entity_type` → `{read, write, preview}`.

```python
REGISTRY = {
  "icp": IcpBinding,            # cfg.icp_definition
  "format": FormatBinding,      # cfg.formats[key]
  "rule": RuleBinding,          # cfg.rules
  "case_study": CaseStudyBinding,
  "segment": SegmentBinding,
  "angle": AngleBinding,
  "icp_test": IcpTestBinding,
  "metric_query": MetricBinding,   # READ-ONLY
}
```

A live block stores a **pointer** (`entity_type`, `entity_id`, `field_path`) — never a
value. Values resolve server-side on read. Writes go preview → QC → apply → audit.

### C3. Approvals
State machine: `draft → in_review → approved`, with `changes_requested` and
`approved_changed_since`.

- Approving writes a `PageVersion` snapshot (with live values resolved at that moment) and
  pins it — "what did they approve" must be answerable later
- Approval can **gate** a pipeline step (`blocks_list_build`)
- Editing after approval sets `approved_changed_since` with a diff — it never silently
  reverts to approved
- Add role `client_admin` to `Membership`. Only client_admins approve; all other client
  users edit and comment freely.

### C4. Email Sequences
`Angle`, `Sequence`, `SequenceStep`, `Variant`, `SequenceTemplate`.

- Structure: **angle → sequence → steps → variants A–G**, each variant individually
  enabled/disabled, enabled variants rotate evenly
- Variant bodies contain `{{placeholders}}` that resolve through the **same format
  bindings as C2** — edit in the doc or the sequence, both move
- `change_note` is **required** on every variant ("adds a question", "forwards original")
- Every variant runs the existing QC + banned-phrase + evidence check before it can be
  enabled; a variant whose proof asset is missing shows "needs proof"
- Promote winner → copy to slot A, archive losers **with stats intact**. Never delete.
- Seed three org-level 4-step templates: Standard, Case-study led, Trigger-event
- UI reference: the Email Sequences screen in the prototype

### C5. Launch Plan
`PlanTemplate`, `PlanTemplateTask`, `Plan`, `PlanTask`.

- Seed the standard RevCadence launch template (full table in `WORKSPACE_SPEC.md` §8.1)
- Instantiate per client on workspace creation; store a baseline for "baseline vs actual"
- `owner_role`: us / client / system
- **`auto_source`** — tasks close themselves from system events. No human ticks these:
  `onboarding_form`, `crawl_complete`, `brain_built`, `warmup_complete`,
  `doc_approved:<page_id>`, `list_researched`, `first_send`
- **Critical path** — compute and display:
  `launch = max(warmup_started + 14d, angles_approved + list_build, icp_approved + list_build)`
  Warm-up is normally binding. When a client task goes overdue, show the **new projected
  date**, not just a red dot.
- Views: Gantt (hand-built, ~200 lines — see prototype), List, Board

### C6. Views (Boards & Tables)
`View` model = `dataset` + `type` + `config` (filters, columns, sort, group_by).

- Five renderers over **one** `View.config`: table, list, board, calendar, gantt
- Requires the shared `DataTable` (Step 0 question #1) — **build that first if missing**
- Needs a **dataset resolver**: maps `dataset: "meetings"` → one workspace-scoped query
  with filters/sort/pagination. Today each module has its own endpoints; this is the small
  new piece of glue.
- Datasets: meetings, leads, deals, companies, contacts, segments, case_studies,
  icp_tests, plan_tasks
- A saved view can be embedded in a doc via the `view` block

### C7. Library + provenance
`CaseStudy`, `Segment`, `IcpTest` (and `Angle` from C4), each with:

```
source: verified | client_supplied | operator
source_url, verified_at, verified_by
```

**`source` is mandatory.** Then change the writer: named claims only from `verified`.
`client_supplied` is usable but flagged in preview. Small edit, real consequences —
review it carefully.

Client-facing "+ Add" surfaces should be contextual, not a blank page:
*+ Add a case study* · *+ Add an account we shouldn't contact* · *+ Add an objection*.

### C8. Deep links
Add `link_kind` + `link_id` to `PlanTask`. Render the Overview stage rail, Gantt task
names and List rows as links.

| Phase | Opens |
|---|---|
| Intake | Docs → Kickoff Notes |
| Client Brain | Docs → Client Brain |
| ICP & Targeting | Docs → ICP Definition · Library → Segments |
| Infrastructure | Mailboxes (warm-up status) |
| Angles & Copy | Email Sequences |
| List Build | Boards & Tables → prospect list |
| Launch | Launch Plan |

**Rule: no dead-end status.** If the workspace says something is happening, one click
reaches where it is happening.

### C9. Whiteboard — as a *block*, not a section
**Decision:** do not build a separate Whiteboards area. A whiteboard is a block type
inside a page (tldraw, doc JSON stored opaquely). This keeps one page tree, one comment
system, one permission model, one approval flow.

When a page containing a canvas is approved, the version snapshot stores a **rendered PNG
plus the canvas JSON** — you cannot text-diff a drawing, so approvals show before/after
images. Check tldraw's commercial licence before committing.

### C10. Notifications
Extend `digest.py`. Weekly client digest + immediate alert on approval requests **only**.
Batch comments. The digest must say, in one sentence: *"2 things need you: approve Angles
v4, upload 2 case studies. Launch slips to Sep 8 if not done by Friday."*

### C11. Workspace instantiation
On client creation: generate the page tree, the plan, and default sequences from
templates, pre-filled from the onboarding form and the website crawl. Seed content is in
`EXAMPLE_PAGES.md`. A new client should land on a workspace already ~60% written about
them.

---

## 6. Build order

Ship in this order. Do not start a step before the previous one passes its check.

| # | Step | Passes when |
|---|---|---|
| 0 | Verify §1 + build `DataTable` if missing | Step-0 report delivered; DataTable renders in a kitchen-sink route |
| 1 | C1 Document system | A shared doc can be written, commented on, and versioned |
| 2 | C3 Approvals + visibility + `client_admin` | Client approves; version pins; internal pages invisible to client |
| 3 | C2 Live blocks | Editing the ICP block in a doc changes `cfg.icp_definition`, writes an audit entry, and is revertible |
| 4 | C5 Launch Plan | Overview shows a correct countdown and correctly names the blocking item |
| 5 | C8 Deep links | Every stage and task clicks through to its space |
| 6 | C4 Email Sequences | 4-step sequence with A–G variants; toggling a variant changes what sends |
| 7 | C6 Views | One dataset renders as table/list/board/calendar/gantt |
| 8 | C7 Library + provenance | Client-added case study is tagged `client_supplied` and flagged in writer preview |
| 9 | C10, C11 | New client lands on a pre-filled workspace; digest sends |
| 10 | C9 Whiteboard block | A sticky note promotes into a real Segment record |

Steps 1–5 are the product. 6 can run in parallel with a second dev — it barely touches
the same code.

---

## 7. Do NOT do

- Do not build real-time collaborative editing (CRDT). Version history solves the actual
  problem for a two-party document.
- Do not build nested databases-in-pages, a custom-fields UI, an automations builder,
  public share links, or AI writing inside docs. All v2 or never.
- Do not extend the Blueprint editor into the doc system — different object, different
  lifecycle.
- Do not create a second knowledge store. If you find yourself copying `EnrichConfig`
  values into a Block, stop.
- Do not let the client edit computed values: metrics, verification results, audit
  entries, prior approvals. Those are records of what happened.
- Do not remove or loosen the QC, banned-phrase, or research-sufficiency checks to make
  client editing easier.

---

## 8. Acceptance test (the demo that proves it works)

1. Create a client workspace → full page tree, launch plan and default sequence appear,
   pre-filled from the onboarding form and crawl.
2. Client logs in, sees only shared pages, comments on a format block.
3. Operator edits that format from inside the doc → preview shows a diff → apply → audit
   entry written → change visible in the enrichment config.
4. Client approves the Angles doc → version pinned → the plan task closes → the list-build
   gate releases → Overview countdown recalculates.
5. Client uploads a case study → tagged `client_supplied` → writer preview flags it rather
   than treating it as a verified named claim.
6. Toggle variant C off in step 2 of a sequence → the next send rotation excludes it.
7. Click "ICP" on the Overview rail → lands on the ICP Definition page.
8. Client user requests another workspace's page id → 404, enforced in the data layer,
   covered by a test in `tests/test_smoke.py`.
