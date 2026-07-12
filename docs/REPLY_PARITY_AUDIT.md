# Reply Management — one-to-one parity audit (legacy vs RevCadence)

_Source of truth: `~/Desktop/reply management` (main.py/dashboard.py/db.py/crm.py)
+ CLAUDE_HANDOFF.md + the "reply management system" build session. Legend:
✅ present · ⚠ partial · ❌ missing → built this session._

| # | Legacy feature | RevCadence before | Action |
|---|---|---|---|
| 1 | Dedicated Reply dashboard: Performance Overview (Total Replies / Replied / Meeting Booked / Needs Review / Follow-ups / Stopped) + Recent Leads Activity table + rich filters (stage/status/intent/action/confidence/date) | ⚠ Inbox list only | ✅ built ReplyDashboard |
| 2 | Section tabs (All / Needs Review / Replied / Meeting Booked / Stopped) with live counts | ✅ chips | kept |
| 3 | View button → drawer: intent+confidence, stage select, **lead details (email/website/LinkedIn from platform payload)**, full conversation, AI follow-up sequence, editable reply, Approve & Send | ⚠ drawer w/o lead-data + convo | ✅ enriched drawer |
| 4 | Meeting booked / stage change → **auto-sync to CRM** (creates/updates a deal, contact, company) | ❌ | ✅ booked→CRM sync |
| 5 | Webhook received → **save lead info + sync CRM + enrich by email + auto status** | ⚠ recorded reply only | ✅ webhook→CRM+enrich |
| 6 | Reply in the SAME thread (Instantly reply-to-prospect eaccount fix) | ✅ engine | kept |
| 7 | Test thread: paste a thread → engine recognizes reply → drafts reply+follow-ups for review, **zero side effects** | ❌ | ✅ built /reply/test |
| 8 | Reply Settings: OpenAI/Gemini keys + models, human-review webhook URL, default Bison base URL, reply delay, trigger tags | ⚠ per-workspace only | ✅ global Reply Settings |
| 9 | Rules: quick extra rules to cut AI patterns, injected every prompt | ✅ per-workspace (Setup) | kept |
| 10 | Lead data recorded from sending-platform API (email/website/LinkedIn/company) & viewable | ⚠ stored raw, not shown | ✅ shown in drawer |
| 11 | Full-width, uncluttered UI | ⚠ narrow | ✅ widened |

## What was already correct (do not touch)
Engine decision logic, stop-intent guard, per-workspace AI provider+fallback,
signature dedupe, follow-up loop guard, Bison variable-merge, Instantly
reply-to-prospect threading, AUTO_SEND kill-switch, encrypted secrets.

## Built this session (session 16)
Dedicated Reply dashboard · test-thread sandbox · global Reply Settings ·
webhook→CRM+enrichment sync · booked→CRM deal sync · lead-data + conversation
in the drawer · wider layout.
