# RevCadence v1.0 — Master Implementation Plan

> The single source of truth from now until launch. Every task references this
> document. If a task isn't here, we decide whether it belongs in v1.0 *before*
> building it. Owner: Product Lead. Status: **in progress**.

---

## 1. North Star

When a prospect watches a 15-minute demo, they must conclude:

> **"This is one Revenue Operating System."**

Not: "a CRM + a blueprint tool + a reply manager + an agreement tool stitched
together." Every decision below is judged against that one sentence.

### Definition of Done for v1.0
1. **One navigation.** No "modes." A person understands the whole product in 10 minutes.
2. **One vocabulary.** The same nouns everywhere (see §3).
3. **One record, one timeline.** Company/Deal/Contact each show every interaction in one place.
4. **The revenue story runs end-to-end in a demo** — lead → meeting → blueprint →
   agreement → invoice → **and the post-meeting relationship continues inside the
   Deal, in the same email thread** (Deal Conversation, §6). The story never
   dead-ends at the meeting.
5. **Every client-facing artifact (Blueprint, Agreement, Invoice) looks premium** — branded, designed, presentable.
6. **A real Reports screen** exists (pipeline, conversion, revenue, aging, going-cold).
7. **First run isn't empty** — seeded demo + guided setup + coached empty states.
8. Nothing feels half-built: consistent empty/loading/error states, no dead ends.

---

## 2. Product principles (apply to every task)

- **Reuse before building.** We already have a shared component system
  (`Button`, `StatusPill`, `Badge`, `Modal`, `Breadcrumbs`, `PageHeader`,
  `SaveIndicator`, `useApi`, `useAutoSave`, `useToast`, `Avatar`, `Tabs`) and a
  unified `Activity` timeline + event bus. New screens compose these, never reinvent.
- **The conversation/record is the hero; metadata collapses.** (We already applied
  this to the reply inbox.)
- **AI assists, never auto-acts.** Grounded suggestions, human approval.
- **Consistency > cleverness.** Same spacing, same status colors, same nouns.

---

## 3. Vocabulary standard (canonical — use everywhere)

| Use | Never say | Meaning |
|-----|-----------|---------|
| **Deal** | Opportunity | the revenue object moving through the pipeline |
| **Company** | Account | the organization |
| **Contact** | Lead (in CRM) | a person |
| **Client** | — | a Company with an *active engagement* (a status, not a new object) |
| **Pipeline** | — | the board/table of Deals |
| **Timeline** | Activity feed | the unified stream on a record |
| **Blueprint / Agreement / Invoice** | proposal/contract/bill (mixed) | the three revenue documents |
| **Replies** | Reply Management | inbound cold-reply automation (distinct from the future Revenue Inbox) |

"Lead" survives only inside Replies/prospecting (a not-yet-qualified inbound), and
becomes a **Contact + Deal** the moment it enters the pipeline.

---

## 4. Screen-by-screen audit

Verdict key: ✅ good · 🟡 needs work · 🔴 blocker/redesign · ✂️ remove/merge

| Screen | Premium? | Belongs? | Verdict & the one thing that matters |
|--------|----------|----------|--------------------------------------|
| Sidebar / mode switcher | 🔴 | — | The 4 modes fragment the product. **Collapse to one grouped nav.** (Task 1) |
| Master Dashboard | 🟡 | ✅ | Metrics strip, not a command center. Redesign around "what needs me + revenue trend". |
| Reply Dashboard | 🟡 | ✂️ | Second dashboard → fold into the one Home. |
| Pipeline (board+table) | ✅ | ✅ | Strongest screen. Add saved views, tasks/reminders, next-step. Rename Opportunity→Deal. |
| Companies list | ✅ | ✅ | Good (status chips, booked-plus default). Keep. |
| Company detail (hub) | ✅ | ✅ | **Best screen — the template for everything else.** |
| Contacts list | 🟡 | ✅ | Feels like a list, not a record. Give the contact a hub like the company. |
| Contact drawer | 🟡 | ✅ | Thin. Promote to a real record with timeline. |
| Reply Inbox | ✅ | ✅ | Now strong (thread, collapsible AI, labels, export). Lives in its own mode — surface it in the one nav. |
| Reply Processing | ✅ | ✅ | Good utility. Keep under Replies. |
| Test Thread | ✅ | ✅ | Keep (now uses the real engine). Move under Replies. |
| Reply Setup / Settings / Extra Channels | 🟡 | ✅ | Config-heavy; fine, but group under Settings/Replies. |
| Blueprints list | 🟡 | ✅ | Fine. Rename nav from "Blueprints & Agreements" (that item conflates two objects). |
| Blueprint detail/editor | 🟡 | ✅ | Reads like a generated doc. **Needs a designed, branded template to present with pride.** |
| Blueprint public page | 🟡 | ✅ | Clean but not designed. Cover/hero + client logo + "prepared for". |
| Agreement editor | ✅ | ✅ | Real (versions, lock, audit). Add signer-field placement + email delivery for DocuSign parity. |
| Agreement public sign | 🟡 | ✅ | Works, but delivery is copy-a-link. Add "send for signature" email + guided signer UX. |
| Invoice editor | ✅ | ✅ | Solid. Add branding/letterhead + tax IDs + PO for $50k feel. |
| Invoice public page | 🟡 | ✅ | Add a "Pay" path (later Stripe) and remit-to. |
| Client Profiles | 🟡 | ✅ | Unique & valuable, but dense form. Redesign as a readable client one-pager. |
| Onboarding (nav) | 🟡 | ✂️ | Duplicated with the profile's onboarding. Merge. |
| Onboarding public form | ✅ | ✅ | Good. Keep. |
| Enrichment Lists/Database/Config (Outbound) | 🟡 | ✅ | Powerful but a whole "mode". Group as **Prospecting**, de-emphasize in the demo path. |
| Inbound Visitors | 🟡 | ✅ | Niche. Group under Prospecting; not on the golden path. |
| Jobs | ✅ | ✅ | Move under Settings (plumbing, not a top-level product surface). |
| Settings / Developers / CRM Integrations | 🟡 | ✅ | Too much plumbing in primary nav → one Settings area. |
| Admin | ✅ | ✅ | Keep (master only). |
| **Reports** | 🔴 | **missing** | Does not exist. **Build it — a launch blocker.** |
| First-run / empty states | 🔴 | missing | A fresh workspace looks broken. Seed + guide. |

---

## 5. Master task list — dependency-ordered

Ordered so each task unblocks the next (Navigation → CRM → Company Workspace →
Timeline → Replies → Blueprint → Agreement → Invoice → Reports → First-run → Polish).
Tags: **[C]** Critical (before launch) · **[I]** Important (if time) · **[N]** Nice (v1.1).

Complexity: S (hours) · M (1–2 days) · L (3–5 days).

### T1 — Unify navigation (remove modes) **[C] · M**
- **Why:** the mode switcher is the #1 reason it feels like 4 apps.
- **Impact:** whole product legible in one glance; "one OS" lands instantly.
- **Reuse:** existing routes/pages/`NavLink`; only the sidebar structure changes.
- **Unifies:** literally the definition of one product. **First because everything is judged against the nav.**

### T2 — Vocabulary standardization **[C] · S–M**
- **Why:** Deal/Opportunity, Company/Client, Lead/Contact confuse buyers.
- **Impact:** consistency = premium. Demo language matches the UI.
- **Reuse:** label-level changes; stage rename "Opportunity"→"Interested/Deal" handled carefully (data-safe).
- **Unifies:** one language across every screen.

### T3 — Contact record = hub (parity with Company) **[I] · M**
- **Why:** contacts are a dead-end list today.
- **Impact:** a rep can work a person, not just an account.
- **Reuse:** the Company hub layout + `Timeline`.
- **Unifies:** every core object (Company, Deal, Contact) uses the same record pattern.

### T4 — Unified Timeline everywhere **[C] · M**
- **Why:** the "we never lose track" promise requires every interaction on one stream.
- **Impact:** the demo's emotional peak — "everything's here."
- **Reuse:** `Activity` model + timeline component already exist; wire consistently to Company/Deal/Contact.
- **Unifies:** the connective tissue of the whole OS.

### T5 — CRM depth: tasks/reminders + saved views + next-step **[C] · M–L**
- **Why:** "can I run my whole sales process here?" — today, not quite.
- **Impact:** RevCadence replaces their pipeline tool, not supplements it.
- **Reuse:** `Task` model exists; Pipeline board/table exist.
- **Unifies:** the CRM becomes the operating surface, not a viewer.

### T6 — Home/Dashboard redesign (merge the two dashboards) **[C] · M**
- **Why:** two dashboards + vanity metrics ≠ a command center.
- **Impact:** first screen every day answers "what needs me + how's revenue."
- **Reuse:** metric cards, activity list, event data.
- **Unifies:** one home for the whole OS.

### T7 — Replies surfaced in the unified nav + inbox polish **[I] · S**
- **Why:** it's strong but hidden in a mode.
- **Impact:** the follow-up story is visible in the one product.
- **Reuse:** the redesigned inbox (done).
- **Unifies:** conversations sit beside the CRM, not in a separate app.

### T8 — Blueprint premium template **[C] · M**
- **Why:** it's the first artifact a client sees; must feel like a $50k firm made it.
- **Impact:** prospects trust the product on sight.
- **Reuse:** existing blueprint generation + public route; new designed HTML/print template + logo.
- **Unifies:** client-facing polish matches the internal quality.

### T9 — Agreement: email delivery + guided signer + field placement **[I] · M–L**
- **Why:** DocuSign parity is a stated bar.
- **Impact:** clients sign confidently; we look enterprise-grade.
- **Reuse:** agreement engine, public sign page, webhook events (email is the gap).
- **Unifies:** the close step feels first-class inside the OS.

### T10 — Invoice branding (letterhead, tax IDs, remit-to) **[C] · S–M**
- **Why:** must look professional for $50k+.
- **Impact:** removes the "is this legit?" hesitation at payment.
- **Reuse:** invoice PDF (ReportLab) + editor.
- **Unifies:** the money step matches the brand.

### T11 — Client Profile redesign (readable one-pager) + merge Onboarding **[I] · M**
- **Why:** unique asset buried in a dense form; onboarding duplicated.
- **Impact:** post-sale value is obvious; less clutter.
- **Reuse:** profile schema/data; the hub layout pattern.
- **Unifies:** delivery/success lives cleanly in the same product.

### T12 — Reports **[C] · L**
- **Why:** the economic buyer lives here; today it's missing.
- **Impact:** unlocks the management/visibility value prop.
- **Reuse:** deals/stages/invoices/activities data; chart components (recharts available).
- **Unifies:** the OS proves it manages revenue, not just tasks.

### T13 — First-run: seed demo + guided setup + empty states **[C] · M**
- **Why:** trials are won or lost in 60 seconds.
- **Impact:** a prospect self-serves the "aha".
- **Reuse:** existing provisioning/bootstrap; empty-state component.
- **Unifies:** the product introduces *itself* as one OS.

### T14 — Deal Conversation: same-thread relationship management (§6) **[C] · L**
- **What it is:** NOT an inbox module and NOT a campaign tool. Every **Deal owns a
  Conversation** that lives in **one continuous email thread** with the prospect,
  from post-meeting until the Deal is Won or Lost. The AI drafts the *next reply in
  the same thread*; the rep approves; it sends from the connected mailbox; the
  prospect experiences a normal human email. The instant the prospect replies, all
  scheduled follow-ups cancel. The rep can jump into the same thread manually anytime.
- **Why:** without it RevCadence stops at the meeting — the OS breaks. This is a
  primary reason companies buy: the prospect never knows they entered a follow-up.
- **Impact:** the post-meeting relationship stays connected to the Deal, Company,
  Contact, Meeting, Blueprint, Agreement, and Invoice — nothing leaks to Gmail.
- **Depends on:** a real **Deal record page with tabs** (Timeline · Conversation ·
  Blueprint · Agreement · Invoice) — elevate the Deal from a drawer to a record
  (fold into T4/T5). Plus a connected-mailbox layer + RFC-thread persistence.
- **Reuse:** `generate_reply()` for drafting in-thread, the follow-up scheduler
  (jobs queue), the approval UX, the `Activity` timeline, the event bus, encrypted
  token storage (`crypto.encrypt`).
- **Unifies:** the conversation becomes part of the Deal itself — the literal
  continuation of the revenue journey, not a separate surface.

### T15 — Global polish pass **[C] · M**
- **Why:** consistency is the difference between "tool" and "premium product."
- **Impact:** the whole thing feels intentional.
- **Reuse:** shared components, design tokens.
- **Unifies:** the final coat that makes 12 screens feel like one.

---

## 6. Deal Conversation (Revenue Inbox v1) — the definitive spec

This is **persistent, same-thread relationship management owned by the Deal.** It is
**not** an inbox, **not** a campaign engine, **not** a new conversation each time.
There is exactly one email thread per Deal's relationship, and it never leaves that thread.

### The workflow
```
Connect ONE mailbox (Google Workspace or Microsoft 365) — one is enough for v1
        ↓
The Deal gets a Conversation tab (Timeline · Conversation · Blueprint · Agreement · Invoice)
        ↓
Every email is SENT THROUGH the connected mailbox, from the rep's real address
        ↓
Every reply returns into the EXACT SAME email thread (Gmail/Outlook thread it natively)
        ↓
AI reads the full history + Blueprint + Agreement + meeting transcript
        ↓
When proposal-sent + no-reply + intent-alive → AI DRAFTS the next email IN the same thread
        ↓
Rep reviews / edits / approves  (or just types and sends manually in the same thread)
        ↓
It sends through the connected mailbox, in the same conversation — reads like the rep wrote it
        ↓
The MOMENT the prospect replies → every scheduled follow-up is cancelled
        ↓
Continues until the Deal is Won or Lost
```

### The non-negotiable rules
1. **Same thread forever.** On send, set `In-Reply-To` + `References` to the last
   message and keep the `Re:` subject, so Gmail/Outlook keep it in the *same visible
   thread*. Send via the mailbox's native reply (Gmail `messages.send` with `threadId`
   / Graph reply). Never open a new thread, never a campaign.
2. **From the rep's real mailbox.** No separate sending domain, no ESP, no Instantly.
3. **Never feels automated.** No unsubscribe footer, no campaign artifacts, no tracking
   pixel by default. It is indistinguishable from the rep writing it.
4. **AI never auto-sends.** It drafts in-thread; a human approves (or pre-approves the plan).
5. **Reply cancels everything.** A synced inbound reply immediately cancels all
   pending scheduled follow-ups for that Deal, and hands control back to the human.
6. **The rep is always in control.** They can write and send in the same thread at any moment.
7. **Stops on Won / Lost.**

### Data model (reuse-first)
- **MailboxConnection** (provider, encrypted tokens, address) — one per workspace for v1.
- **Deal → Conversation → Message** (rfc `Message-ID`, `In-Reply-To`, `References`,
  `thread_id`, direction, from/to, body, sent_at). Each Message is also an `Activity`.
- **Follow-up schedule** on the Deal (Day 2/5/9/…): each step is a same-thread draft
  requiring approval; a nightly/near-real-time check cancels the schedule on any inbound.
- Drafting reuses `generate_reply()`; scheduling reuses the jobs queue; sync + send use a
  provider layer (aggregator such as Aurinko/Unipile/Nylas to avoid Google's CASA review,
  behind an abstraction so we can move to direct Gmail/Graph APIs later).

**Explicitly NOT in v1.0:** shared/team inboxes, assignment/collision, multiple mailboxes,
calling, SMS, WhatsApp, LinkedIn. Those are future roadmap. But **Deal Conversation v1 is
a Critical part of RevCadence v1.0 — not optional.**

---

## 7. Challenges (where we push back on ourselves)

- **Don't build the full Revenue Inbox now.** The minimal slice tells the whole
  story; the full module is a v2 trap.
- **Don't add SMS/Calling/WhatsApp/AI-SDR/Mobile for v1.0.** None blocks the sale.
- **Remove, don't expand:** the second dashboard, the standalone Onboarding nav item,
  and Jobs/Developers/Integrations from primary nav (→ Settings).
- **Redesign, don't extend:** the Client Profile (form → one-pager) and the Home
  (metrics → command center).
- **Prospecting (enrichment lists, inbound visitors) is not the golden-path demo.**
  Keep it, group it, but don't let it dominate the first impression.

---

## 8. Launch checklist (v1.0 is "complete" when…)
- [ ] One sidebar, no modes; 10-minute comprehension.
- [ ] One vocabulary across every screen.
- [ ] Company, Deal, Contact all use the hub + timeline pattern.
- [ ] Tasks/reminders + saved views in the CRM.
- [ ] One Home command center.
- [ ] Blueprint, Agreement, Invoice all look branded & premium.
- [ ] Agreement can be emailed for signature; invoice shows remit/branding.
- [ ] Reports screen shipped.
- [ ] First-run seeds + guides a new workspace.
- [ ] Revenue Inbox minimal slice: mailbox → timeline → AI follow-up → approve → send.
- [ ] Consistent empty/loading/error states; no dead ends.

---

*Implementation status is tracked in the task list. Current build: **T1 — Unify navigation.***
