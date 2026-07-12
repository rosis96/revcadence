# RevCadence — Revenue Engine Roadmap (Studio, Onboarding, Post-Meeting)

_A concrete, approvable plan. The goal: one workspace per client that runs the
whole revenue lifecycle — Onboarding → Outbound → Inbound → Meeting →
Post-Meeting (proposals) — with nothing done manually and nothing duplicated._

## Where we are (built + at parity)
Outbound (enrich/verify/ICP/personalize + list pipeline) · Reply Management
(engine, inbox, dashboard, test-thread, settings, Calendly scheduling with
anti-double-booking) · CRM (companies/contacts/deals, interested→Opportunity,
booked→Meeting Booked) · Inbound visitor capture · full migration toolchain ·
premium UI design system. Workspace = package (auto-provisioned).

## The two things you asked for

### 1. Studio inside the CRM — NOT hard (it's wiring, not a rebuild)
Your portals Document service (blueprint.ascendly.one / agreement.ascendly.one)
already generates, hosts, and e-signs documents. The legacy Studio (`revenue.py`)
just orchestrates it over a Service API (`X-Service-Key`). We copy that pattern
into RevCadence: a thin `svc()` client + a `/api/studio/*` router + React pages
under the CRM. **The portals service stays a separate Railway project** — we
talk to it, we don't absorb it. Document generation/signing/PDF/hosting are
already solved; we only build orchestration + UI.

What you provide once: on the portals service set `SERVICE_API_KEY=<random>`;
on RevCadence set `PORTALS_API_URL` + `PORTALS_API_KEY` (= that same value).
Then Studio is live inside RevCadence.

### 2. Client Onboarding — a first-class section
When a client is onboarded, a checklist tracks what's pending and captures the
info the system needs to run automatically — most importantly the client's
`sales@theirdomain.com` mailbox, which, once provided, is linked straight into
Reply Management as a follow-up channel (no manual setup). This closes your
Post-Meeting follow-up loop: proposals CC that mailbox, and our reply engine
follows up on the same thread.

---

## Phased plan (each phase ships independently, tested, no manual steps)

### Phase 1 — Studio core (Service API client + Home + Clients)  ·  ~1 session
- `app/studio/service.py`: `svc(method, path, body)` → portals with
  `X-Service-Key`; graceful when env unset.
- `app/routers/studio.py`: list clients, get client, `/service/info` health,
  activity feed — all proxied, workspace-scoped.
- Frontend (CRM mode → Studio): Home command center (stage-chip pipeline
  Draft→Published→Signed→Executed→Active, MRR, awaiting-countersign, drafts,
  live), Clients list. Studio Settings (portals connection status, models,
  default engagement).
- **Done when:** RevCadence shows every portals client + status, live.

### Phase 2 — Promote from CRM + transcript → proposal  ·  ~1 session
- `POST /api/studio/promote?deal_id=` → creates a DRAFT portals client
  prefilled from the CRM deal (contact/company/enrichment). Manual trigger,
  never automatic.
- Transcript intake: paste/attach a Fathom (or any) transcript →
  `POST /service/clients/{slug}/ai` (skipAI upsert then forced regen) → banner
  reports "call pricing applied: $X" or "no pricing — defaults kept" + MISMATCH
  warning. Add Fathom API pull so you click once instead of pasting (optional).
- Client workspace tabs: Overview / Blueprint / Agreement / Sales Intel
  (INTERNAL only) / Timeline / Notes.
- **Done when:** deal → promote → transcript → generated proposal at
  proposal/blueprint `.ascendly.one/{slug}`, reviewable.

### Phase 3 — Publish / present / sign / countersign  ·  ~1 session
- Blueprint tab: preview / Present (`?present=1`) / copy link / publish–
  unpublish / Regenerate AI / custom-HTML upload+revert.
- Agreement tab: signature status, countersign link, resend executed email,
  terms editor (locked once executed), download executed PDF.
- Sales Intel tab: opportunity score + sales coach + missing info (internal).
- **Done when:** full lifecycle promote→publish→sign→countersign→executed works
  end-to-end against the live portals API.

### Phase 4 — Client Onboarding section + mailbox connection  ·  ~1 session
- `OnboardingChecklist` model per workspace: items with status
  (pending/received), types (sales_mailbox, calendly, sending_platform_key,
  icp_confirmed, profile_confirmed, billing, features_chosen).
- One client-facing intake form. When they connect a mailbox (OAuth for
  Google/Microsoft, or app password) it's stored encrypted and auto-linked as
  the workspace's follow-up sender — the checklist item flips to received and
  no manual setup is needed.
- Per-client feature toggles (proposals/agreements/e-sign) chosen here drive
  which onboarding items even appear.
- Onboarding page (CRM mode): progress bar + what's pending + the intake link.
- **Done when:** onboarding is a guided checklist that wires the client's
  mailbox + preferences into the system automatically, with no post-onboarding
  asks.

### Phase 4b — Unibox (unified inbox over the connected mailbox)  ·  ~1 session
- `MailboxConnection` (per workspace: IMAP/SMTP host, user, encrypted app
  password) + `mailbox_messages` (threaded, matched to contact/deal).
- Worker job `sync_mailbox`: polls IMAP every few minutes, upserts messages
  (idempotent by message-id), links to contacts by email.
- Unibox page (CRM mode): threaded conversation list + reply box (sends via
  SMTP in-thread). Reuses the reply engine's send path.
- **Done when:** every email in the client's connected mailbox is visible and
  replyable inside the CRM, in real time, per workspace.

### Phase 5 — Post-Meeting follow-up loop (Scenario 1 + 2)  ·  ~1–2 sessions
- Scenario 2 (transcript-based): done by Phases 2–3 (we generate the proposal).
- Scenario 1 (client's own proposal): upload a proposal doc → read every line
  (same AI layer) → generate a follow-up sequence → follow up through the reply
  engine using the client's `sales@` mailbox (CC'd on the thread). Reuses the
  reply engine end-to-end — proposals become "threads" the follow-up loop owns.
- Proposal open/read tracking on the hosted pages → notify + auto follow-up if
  unopened in N days (job queue).
- **Done when:** both proposal scenarios follow up automatically, tracked in CRM.

### Phase 6 — Meeting layer polish  ·  ~1 session
- Pre-call: qualification form + agenda + full conversation context surfaced on
  the CRM deal (Calendly booking already creates the Meeting + brief hooks).
- No-show reminder + re-book nudge (job queue).

---

## Product decisions (locked in)

### Per-workspace feature toggles
Proposals, Agreements, and E-sign are each on/off **per client**. A client who
doesn't want signing turns off Agreements/E-sign; Studio then only produces the
blueprint/proposal for them. Stored on the workspace/Studio settings; Studio and
the onboarding checklist respect them (e.g. no signing tasks when e-sign is off).

### How follow-up emails are sent — connect one mailbox, reply in-thread
The client connects ONE sending mailbox on their domain at onboarding
(rep's mailbox or `sales@theirdomain`) — Google/Microsoft = one OAuth click;
anything else = an app password we store encrypted. Every post-meeting email +
follow-up is then sent **from that mailbox as a reply in the existing thread**,
so continuity is automatic (same From, same thread, no new participant, no
prospect effort). Auto-CC `sales@` on booking is an optional augmentation (so
the client sees the full history), NOT the send mechanism. We do NOT rely on the
prospect CC'ing anything, and we do NOT create mailboxes on domains we don't
control — we automate the connection + everything after it.

### Unibox — one mailbox connection powers both automation AND a human inbox
Connecting the client's mailbox (app password: IMAP read + SMTP send) does two
jobs at once:
- **Unibox** (CRM section): the worker syncs every message (inbox + sent) into a
  `mailbox_messages` table on a schedule, threaded and matched to the
  contact/deal by email. A human sees all replies in real time, in context, and
  can reply by hand.
- **Automated sending**: the reply engine sends/replies from the same mailbox
  in-thread.
So the platform is automated-first with a human window over the exact same
inbox — not either/or. Connection is set per workspace in Admin (belongs to that
client, isolated like all data). Gmail needs 2FA + an app password.

### Background automation — native jobs, not Make.com
All background work (enrichment, follow-ups, mailbox sync, proposal reminders,
the inbound 10-min SLA) runs on the native job queue + worker — reliable, no
per-op cost, no external dependency. Make.com is kept only as an OPTIONAL escape
hatch for gluing to tools we don't natively integrate (Slack ping, niche
webhook); the outbound webhook infra for that already exists. Make is never core
plumbing.

### Minimal client effort
One intake form at onboarding captures everything (mailbox connection, ICP,
profile, billing, which features they want). The checklist auto-completes as
items arrive; after that the system runs with no further asks.

## Guardrails (non-negotiable, applied every phase)
- Be my own QA: build passes + every new button tested before shipping.
- Nothing manual, nothing duplicated, everything synced through the one object
  model. Portals stays a separate service (Service API only).
- Clients only ever see blueprint./agreement.ascendly.one; Studio is internal;
  no reply-inbox data leaks into client-facing pages.
- Additive migrations; secrets encrypted at rest.

## What I need from you to start Phase 1
1. On the portals Railway service: `SERVICE_API_KEY=<long random string>`.
2. On RevCadence (web + worker): `PORTALS_API_URL=<portals URL>` and
   `PORTALS_API_KEY=<same value as SERVICE_API_KEY>`.
That's it — then I build Phase 1.
