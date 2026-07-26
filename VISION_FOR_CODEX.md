# RevCadence — Vision & System Brief (for Codex)

Read this first. It explains what we are building, why it matters, what we sell, and
how the code is organized so you can work on it safely and in the right direction.

---

## 1. What RevCadence is, in one sentence

RevCadence is a **done-for-you Revenue Operating System** for agencies and consultancies:
we run a company's entire outbound-to-revenue motion — find the right prospects,
research them deeply, write genuinely personalized cold email, verify deliverability,
handle replies, book meetings, follow up, and track the pipeline through to closed
revenue — as a **managed service sold at ~$3,000/month**, not as self-serve SaaS.

The product is the software; **the business is the service the software makes possible.**

---

## 2. Who we sell to and why they buy

Our buyers are **B2B agencies, consultancies, and professional-services firms** (branding
firms, marketing agencies, dev shops, fractional-exec firms, boutique consultancies) who
want more qualified sales conversations but don't have — and don't want to build — an
internal SDR team, a data/enrichment stack, a deliverability operation, and a CRM
discipline. They want **booked meetings and a healthy pipeline**, not another tool to log
into.

Why they can't get this elsewhere:

- Generic CRMs (HubSpot, Zoho, Salesforce) are empty boxes — they store data but don't
  *do* the outbound, research, writing, or follow-up.
- Cold-email tools (Instantly, Smartlead) send volume but produce templated, generic copy
  that doesn't convert and burns domains.
- Hiring an in-house team is slow, expensive, and hard to manage.

RevCadence is the whole engine, operated for them. That is the wedge and the moat: **the
service is the business.** The software exists to make one operator able to run many
clients at a quality level that looks like a dedicated team per client.

---

## 3. The ultimate goal

Become a **full revenue-engine company**: a client hands us their website and their offer,
and we stand up a complete, measurable revenue machine for them — prospecting → research →
personalization → sending → reply handling → meeting booking → follow-up → pipeline/CRM →
reporting/ROI — with the quality bar of a senior human doing bespoke research on every
single prospect, at software scale and margin.

Concretely, "full revenue engine" means every stage below is owned by the system and wired
into a single per-client brain, so the client sees one coherent, accountable motion and we
can operate many clients without linear headcount.

---

## 4. The core belief that drives every technical decision

**Personalization must come from real, verifiable research — never from guessing.**

The single biggest quality lesson we've learned: a system that writes "researched-sounding"
copy from a company name + job title + a guessed industry is worse than useless — it looks
personalized but says nothing, and it destroys trust with the exact buyers we target. Our
competitive edge is that we **research like a human analyst first, build an evidence bank of
concrete facts (named clients, projects, case-study results, methodologies, awards), and
only then write** — and if we can't find enough real evidence, we **refuse to generate** and
flag the lead instead of fabricating.

If you touch the enrichment/writing path, this is the prime directive: **evidence first, no
fabrication, refuse rather than guess.**

---

## 5. The revenue loop (how the pieces connect)

Everything is organized around one loop, unified per client:

1. **Prospect list** comes in (CSV import or inbound capture).
2. **Verify** deliverability cheaply first (free MX check → Reoon), so we never waste
   research/sending on dead or unsafe mailboxes.
3. **ICP gate** — decide if the company is a real fit using the client's ICP definition.
4. **Research → Evidence bank** — crawl the whole prospect site (case-study/work pages, JS
   render when configured), extract typed, citeable evidence.
5. **Write** — score the evidence, assign a *different* piece to each variable, generate the
   cold-email variables, run a QC/regeneration pass, and refuse (mark "insufficient") if
   there isn't enough real evidence.
6. **Send** through the client's mailboxes / sending tool (Instantly, Bison).
7. **Replies** come back via webhooks → classified by intent → drafted/answered by the reply
   engine, grounded in the same client brain.
8. **Meetings** get booked (Calendly), deals move through the **CRM pipeline**.
9. **Follow-ups** run on autopilot until a reply or a closed stage.
10. **Reports/ROI** show the client what the engine produced (meetings, pipeline, revenue).

The thing that makes this *one* engine rather than ten disconnected tools is the **Client
Brain**: a single structured knowledge base per client that feeds outbound writing, reply
writing, follow-ups, ICP decisions, and formats — so the client's voice, proof, and
positioning are consistent everywhere.

---

## 6. The Client Brain (the heart of the system)

The Client Brain is a rich, structured profile per client workspace (`EnrichConfig.profile`,
a JSON blob) that captures who the client is, what they sell, their case studies, proof
points, methodologies, the problems they solve per industry, target titles, etc. It is built
by AI from the client's website + uploaded material and grows over time (accumulate, never
blindly replace).

It powers four kinds of "teach it once, use it everywhere" actions, exposed in the **Ask the
Brain** chat (`frontend/src/pages/BrainChat.jsx`, endpoints in
`app/routers/enrich_lists.py`):

- **Save to brain** → company knowledge (case studies, services, metrics).
- **Build formats** → the outbound *variables* (how each cold-email field is written);
  edits in place, revising only the variables you describe and keeping the rest.
- **Save as rule** → *global rules* (`cfg.rules`) obeyed on every email (e.g. "never repeat
  the same personalization across variables").
- **Update ICP** → accumulate fit/reject signals into the ICP definition
  (`cfg.icp_definition`).

The same brain is read by the reply engine (`load_client_brain`) and follow-up drafter, so
there is **one brain per client**, not separate ones per module. The chat can also read any
website URL the user pastes (it wires the crawler into the chat).

**Formats** are the per-variable definitions (name, guidance, per-variable rules, template
with `{{placeholders}}`, word ranges, examples, fallback, enable toggle). The reply side has
its own analog — **response types** + a **follow-up ladder (FUP1–6)** — and a matching
"Build reply formats with AI" action, grounded in the same brain.

---

## 7. What's been built (module map)

Backend is **FastAPI** (`app/`), frontend is **React + Vite** with HashRouter
(`frontend/`), served as a committed `frontend/dist`. Background work runs in a **job
queue + worker**.

### Enrichment (outbound research + writing) — `app/enrichment/`
- `crawler.py` — website crawler. Static fetch with browser headers + a second-fingerprint
  retry, homepage **render fallback** when static fails, **sitemap.xml + seed-path
  discovery** to reach `/work` and case-study pages, optional **JS rendering** (ScrapingBee/
  ScraperAPI/Browserless via `RENDER_PROVIDER` + `RENDER_API_KEY`), and a per-crawl
  **diagnostics** packet (HTTP status, final URL, pages crawled/failed, rendered pages,
  signals text length, etc.).
- `pipeline.py` — the funnel: free verify → Reoon verify → title gate + ICP → **evidence
  bank → signal scoring → per-variable evidence assignment → generation → QC/regeneration**.
  Contains the **research-sufficiency gate**: fewer than `MIN_RESEARCH_SIGNALS` (3) distinct
  company-specific signals → status `insufficient`, **no copy written** (never fabricate).
- `ai.py` — OpenAI helpers (global `OPENAI_API_KEY`), model selection, content-size caps
  (there is a real cost-runaway history — respect the char caps).
- `reoon.py` — email verification; **fail-safe**: no key → `unverified`, never fake "safe".
- `verify_free.py` — free MX-based verification + ESP (mailbox provider) detection.
- Routers: `enrich_lists.py` (lists, config, brain chat/learn, build-formats/icp/rules,
  dedupe, ESP filters, diagnostics surfaced to the lead drawer), `enrich.py`.

### Reply management — `app/reply/`
- `engine.py` — classifies inbound reply intent, drafts/sends replies grounded in the client
  brain, resolves the correct prospect thread (a real bug we fixed: never reply-to-self).
- `calendly.py`, `sync.py`; router `app/routers/reply.py` (webhooks, workspace config,
  response types, follow-up ladder, "build reply formats with AI", review console).

### Mailbox / sending + follow-up autopilot — `app/mailbox/`
- `service.py` — mailbox polling, conversation tracking, **follow-up autopilot**
  (`run_due_followups` with guards: deal closed via won/lost stage, replied-since, no
  mailbox, no first email), draft follow-ups grounded in the brain.
- `transport.py`; router `app/routers/mailbox.py`.

### CRM / pipeline / documents — `app/routers/` + `app/models/`
- `crm.py` (pipeline, `/reports/summary` ROI, `/setup/checklist` first-run), `agreements.py`,
  `invoices.py`, `deal_workspace.py`, `inbound.py` (per-workspace inbound form/visitor
  capture), `billing.py` (master-only MRR).

### Platform
- `app/auth.py` — **multi-tenancy**: JWT carries `ws` claim; `AuthContext` with
  `is_master`, `allowed_workspace_ids()`, `require_workspace()`, `workspace_ids_for_query()`,
  `scoped()`. A **client** sees exactly one workspace; **master** sees the whole org. Fails
  closed.
- `app/db.py` — `migrate()` runs `create_all` + additive `ALTER TABLE ADD COLUMN` on boot;
  new columns/tables are auto-created on deploy.
- `app/workers/registry.py` + `runner.py` — job queue (`@register(kind)` handlers) and the
  worker loop (`beat()`, periodic mailbox poll + follow-up tick).

### Frontend (`frontend/src/pages/`)
Dashboard, EnrichLists/EnrichListDetail/EnrichConfig/EnrichDatabase, BrainChat, Reports,
Billing, InboundVisitors, Pipeline, DealRecord, Clients/Companies, Reply* pages, Mailbox
connect, Blueprints/Agreements/Invoices, Admin/Settings/Developers. Design tokens and the
shared component library are documented in `DESIGN_SYSTEM.md`.

---

## 8. Hard-won principles you must follow

These are not stylistic preferences — each one comes from a real failure we already paid for:

1. **Evidence first, never fabricate.** In the enrichment/writing path, ground every line in
   verified facts. If research is insufficient, refuse and mark `insufficient` — do not write
   generic praise. Banned-phrase and named-specificity checks exist for this reason; keep
   them.
2. **Refuse loudly, don't guess quietly.** A failed fetch/thin research must surface (status
   + diagnostics), never be papered over with plausible-sounding output.
3. **One brain per client.** Don't create parallel/competing knowledge stores. Outbound,
   replies, follow-ups, ICP, and formats all read the same `EnrichConfig.profile`.
4. **Accumulate, don't replace.** When teaching the brain/ICP/formats, merge and dedupe;
   don't wipe the operator's prior work. Edits should be surgical (revise only what was
   described).
5. **Additive migrations only.** Add columns/tables via `db.migrate()`; never write
   destructive schema changes that would break existing tenants on deploy.
6. **Multi-tenant, fail-closed.** Every data query must be workspace-scoped through the auth
   helpers. A client must never see another workspace's data.
7. **Cost discipline.** AI content caps exist because of a real spend runaway. Don't remove
   them casually; prefer targeted, bounded calls.
8. **Verify cheap before spending.** The funnel order (free verify → Reoon → ICP → research →
   write) is deliberate; don't reorder it so that expensive steps run on junk leads.
9. **Ship real files, not descriptions.** This is a working product; changes must parse,
   import, build (`npm run build`), and be committed.

---

## 9. Where we are and what "sellable" means

The system is being pushed from "works" to "sellable done-for-you service." The remaining
theme is **quality and trust at the research/writing layer** (the evidence-based rewrite),
plus the operational surface a service business needs: reports/ROI, first-run checklist,
inbound capture, intent classification, billing/MRR, autopilot follow-ups, and a clean
per-client workspace model. When you pick up work, bias toward: (a) making the output
indistinguishable from a senior human's bespoke research, (b) never embarrassing us with
fabricated or generic copy, and (c) making one operator able to run many clients.

---

## 10. Practical notes for working in this repo

- Backend: FastAPI in `app/`, run/deploy config in `railway*.json`. Frontend built to
  `frontend/dist` and served by FastAPI — after frontend changes, run `npm run build` in
  `frontend/`.
- Sanity check before committing: `python -c "import app.main"` (imports the whole app) and
  `npm run build`. There are unit-testable pure-logic functions (signal scoring, evidence
  assignment, QC) — prefer testing those directly since the sandbox blocks outbound network
  (DNS/OpenAI/render/SMTP are not reachable in local test).
- Other docs worth reading: `README.md`, `ROADMAP_V1.md`, `SHIP_HANDOFF.md`,
  `DESIGN_SYSTEM.md`, `MAILBOX_SETUP.md`, and the `*_PORT_GAPS.md` files.
