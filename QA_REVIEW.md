# RevCadence — System QA Review

_Full-system code review across backend (FastAPI, ~18.6K lines / 81 modules), the job worker, and the React frontend. Focus: real bugs, data integrity, security, and robustness — not style._

Reviewed by: Rosis (assisted). Date: 2026-08-04.

---

## Summary

The system is well-architected. The two areas most likely to cause silent, expensive failures — multi-tenant data isolation and background-job concurrency — are done correctly. Most of what I found is low-to-medium severity: a few display/robustness bugs (fixed this pass) and one security recommendation (webhook authenticity) that needs a non-breaking rollout.

**Fixed this pass (committed):**

1. Calendly slot reservations accumulated on every re-draft.
2. Naive-UTC timestamps rendered as local time (wrong clock time in the UI).
3. Boot migration was all-or-nothing — one bad column add could break a deploy.

Plus the reply-engine fixes from the prior sessions (model config, follow-up generation, human-review over-flagging, empty-draft recovery).

---

## What was verified CLEAN (no action needed)

**Multi-tenancy / data isolation — excellent.** Every scoped query goes through `scoped()` / `workspace_ids_for_query()`, which fail safe (a forgotten filter returns nothing, never another tenant's data). By-ID fetches use `_one_or_404` (scoped) or an explicit `workspace_id not in ctx.allowed_workspace_ids()` check. Related-object `db.get()` calls hang off an already-scoped parent. No IDOR found in the CRM, invoice, agreement, enrich, or mailbox routers.

**Background worker concurrency — correct.** Jobs are claimed with `SELECT … FOR UPDATE SKIP LOCKED` on Postgres, so multiple workers never double-process a job. Failures roll back partial writes and back off exponentially with a max-attempts cap.

**Input parsing — defensive.** Email/name splits are guarded (`if "@" in …`), numeric inputs are clamped (`max(1, min(int(x), N))`), and Pydantic types the request bodies.

**Frontend hooks — clean.** No Rules-of-Hooks violations (the one that crashed the deal page earlier is fixed and no others exist). Flagged files were false positives (helper functions with early returns above the component).

---

## Findings & fixes

### 1. Calendly slot reservations accumulated on re-draft — FIXED (Medium)
`build_scheduling_context` reserved N new time slots every time a reply was drafted, but only pruned *past* slots — never a prospect's own superseded reservations. Re-drafting/regenerating the same lead kept stacking holds, slowly draining visible availability with phantom reservations.
**Fix:** before reserving, release this prospect's own prior future reservations, so a re-draft reuses their slots instead of accumulating new ones.

### 2. Timestamps shown in the wrong time zone — FIXED (Low)
The backend stores naive UTC datetimes (no `Z`). Several UI spots did `new Date(iso).toLocaleString()`, which JavaScript interprets as *local* time — showing the clock shifted by the viewer's UTC offset (e.g., message times in the Revenue Inbox, next-follow-up dates, comment times, developer "last used").
**Fix:** added `localDateTime()` / `localDate()` helpers that append `Z` before formatting, and switched the affected spots to them. `timeAgo()` was already correct.

### 3. Boot migration was all-or-nothing — FIXED (Medium, latent)
`migrate()` ran every `ALTER TABLE ADD COLUMN` inside a single transaction. If any one column add failed (an incompatible type, a partially-applied prior migration), the whole batch rolled back and the app failed to boot.
**Fix:** each column add now runs in its own transaction and logs-and-skips on failure, so one bad column can't break the deploy. Columns are added nullable (safe on populated tables).

---

## Recommendations (not changed — need your call / safe rollout)

### A. Inbound webhooks are unauthenticated (Medium — security)
`POST /api/reply/webhooks/instantly` and `/bison` accept any payload and trust the `workspace_name` in the URL. Anyone who learns a webhook URL could inject fake replies (junk in the review queue, phantom CRM opportunities). Blast radius is limited today because auto-send is gated by `AUTO_SEND_ENABLED` (default off → review), but it's still worth closing.
**Why I didn't change it:** adding mandatory auth now would break your live Instantly integration mid-operations. Safe rollout: add an optional shared-secret query token (`?token=…`), configure it in Instantly, then flip to enforce once verified. I can implement this on your go-ahead.

### B. `AUTO_SEND_ENABLED` gates real sending (Operational, not a bug)
Replies only auto-send when `AUTO_SEND_ENABLED=1` in Railway; otherwise every reply is drafted and parked in "Needs Review." If you expect hands-off sending and everything's sitting in review, set that variable. (Follow-up variables push either way.)

### C. Observability: ~70 `except: … pass` blocks (Low)
Most are intentional "best-effort" guards (CRM sync must never block the pipeline). That's a reasonable design, but it hides failures. Where it matters most (the follow-up push), I already switched to surfacing the error in Processing. Consider logging the swallowed exceptions elsewhere so silent failures are diagnosable.

### D. Consider consolidating the 22 reply response-types (Quality)
The engine now handles the volume (crisp type menu + best-fit matching), but 22 overlapping types still dilute classification. Trimming to ~8–10 clearly distinct types would make replies more consistent. Offered separately.

---

## Deploy note

All QA fixes are committed and build clean. Push `git push origin main` to deploy. None of the fixes change behavior you rely on; they remove wrong output and failure modes.
