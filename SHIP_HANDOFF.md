# RevCadence — Shipping Handoff

Status of the platform for going live with paying clients. Written after a full
QA pass (all 8 test suites green — 260 checks; app boots clean; frontend builds).

---

## 1. What's shippable now (verified)

| Area | State |
|---|---|
| **Multi-tenancy** | Solid. Clients scoped to one workspace via JWT; masters see the whole org. Every query forced through `workspace_ids_for_query` — a forgotten filter fails *closed*. Isolation tested. |
| **Outbound enrichment** | Verify → ESP → ICP → AI writing. ESP (mailbox provider) with multi-select filter. Reoon fail-safe (never fakes "safe"). Email self-heal from uploaded rows. Cross-list dedupe. |
| **Writer controls** | Per-variable on/off + fallback, reading level, model selector, research depth. |
| **Reply management** | AI-drafted replies + human review, same-thread follow-ups, Meeting Booked separated from Interested, AI intent buckets, full-info bulk CSV export. |
| **CRM / Pipeline** | Companies, contacts, deals, stages, activity timeline. Dedup-aware. |
| **Reports** | Client-facing ROI: KPIs, conversion funnel, weekly trend, top deals. |
| **Inbound** | Per-workspace form capture → deal + 10-min task; visitor webhook. Dedup-safe. |
| **Blueprints / Agreements / Invoices** | Generation, signing, execution locking, PDFs. |
| **First-run** | Guided "Getting Started" checklist on a new client's dashboard. |
| **Billing** | Per-client subscriptions + MRR rollup (manual entry today). Master-only. |

---

## 2. Onboard a client (no code)

1. **Admin → Add workspace** — name it after the client.
2. **Admin → New user** — role **client**, assign the **one** workspace.
3. **Admin → reset-link** on that user — send them the set-password link.
4. They log in and see only their workspace; you keep the global view.
5. **Billing** — set their plan/price/status so MRR is tracked.

The client physically cannot see another client's data.

---

## 3. Keys / config you must set (env vars on Railway)

| Var | Powers | Without it |
|---|---|---|
| `OPENAI_API_KEY` | ICP scoring + AI writing + intent classification | Falls back to templated demo copy — **set it** |
| `REOON_API_KEY` (or per-workspace in Client Profile) | Real email verification | Emails stop as "unverified" (fail-safe, never fake-safe) |
| Instantly/Bison API key (per reply workspace, in Setup) | Reply send + thread fetch | Replies can't send |
| `INBOUND_WEBHOOK_KEY` *(optional/legacy)* | Global visitor webhook | Use the per-workspace key instead (auto-generated) |
| `PUBLIC_BASE_URL` | Inbound form URL shown to clients | Defaults to engine.revcadence.com |
| Mailbox app password (per workspace, Email Accounts) | Revenue Inbox send/receive | Mailbox features off |

---

## 4. Deploy

- `git push` → Railway rebuilds. New DB columns/tables **auto-migrate on boot**
  (`db.migrate()` adds columns + tables; no manual migration).
- New tables this pass: `subscriptions`. New columns: `workspaces.inbound_key`,
  `reply_leads.intent_bucket/intent_reason`, `enrich_configs.reading_level/
  writer_model/research_depth/reoon_api_key_enc/skip_icp`.

---

## 5. Not done / needs your accounts (honest gaps)

- **Live Stripe billing** — the subscription model + MRR tracking work manually;
  automated collection (checkout + webhooks) needs your Stripe keys and a real
  webhook endpoint to test. Fields are Stripe-ready.
- **Anonymous visitor de-anonymization** — we capture + route visitor webhooks,
  but identifying anonymous traffic needs a data vendor (RB2B etc.) posting to us.
- **JS-rendered site crawling** — the writer reads static HTML; JS-heavy sites
  return thin content (would need a headless browser).
- **Two "inbox" surfaces** (Reply Inbox vs Revenue Inbox) are different engines,
  not duplicated data — a labels-only cleanup is optional/cosmetic.

---

## 6. First-send safety reminder

Any leads verified/enriched **before** the Reoon key was connected carry stale
"demo" verdicts. Before sending a list: **Clear verification** (with no filter
active = whole list) → **Verify** → then send. Don't trust old "safe/done" states.
