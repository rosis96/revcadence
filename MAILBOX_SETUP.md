# Connecting your email — Deal Conversation (Revenue Inbox v1)

This is the same-thread follow-up engine. Once a mailbox is connected, RevCadence
sends from **your real address**, every reply comes back into the **same email
thread**, and the whole conversation lives on the **Deal → Conversation** tab until
the deal is Won or Lost. The prospect never sees a campaign or automation — it reads
like you wrote it. The AI drafts, **you approve**; the moment a prospect replies,
every scheduled follow-up is cancelled.

---

## v1 connection method: app password (SMTP + IMAP)

We use an **app password** so you can connect today without waiting on Google's
OAuth verification. (OAuth for Google/Microsoft is a later drop-in — same UI, same
behavior.) Your password is **encrypted at rest** and only used to send/receive on
your behalf.

Go to **Settings → Email** in RevCadence and pick your provider.

### Google Workspace / Gmail
1. The mailbox must have **2-Step Verification ON** (Google Account → Security).
2. Google Account → Security → **App passwords** → create one for "Mail".
3. Copy the **16-character** app password.
4. In RevCadence → Settings → Email:
   - Provider: **Google Workspace / Gmail**
   - Mailbox address: `you@yourdomain.com`
   - From name: your display name
   - App password: paste the 16-character password
   - Click **Connect mailbox** (hosts default to `smtp.gmail.com:587` / `imap.gmail.com:993`).

### Microsoft 365 / Outlook
1. The tenant must allow **SMTP AUTH** for the mailbox (admin: Microsoft 365 admin
   center → the user → Mail → *Manage email apps* → enable Authenticated SMTP). If
   security defaults are on, create an **app password**.
2. In RevCadence → Settings → Email:
   - Provider: **Microsoft 365 / Outlook**
   - Mailbox address + From name
   - App password (or account password if SMTP AUTH is allowed without one)
   - Click **Connect** (defaults `smtp.office365.com:587` / `outlook.office365.com:993`).

### Other (custom SMTP/IMAP)
Pick **Other** and enter your provider's SMTP host/port, IMAP host/port, login
username, and app password.

On connect, RevCadence verifies it can authenticate for sending and shows
**Connected** (or the exact error). Use **Test** anytime.

---

## How it works, day to day
1. Open a **Deal → Conversation** tab. You'll see the **Deal briefing** (stage, last
   contact, intent, risk, proposal/agreement status, recommended next action).
2. Type a reply, or click **AI draft** to have the AI write the next message —
   grounded in the whole thread + the blueprint/agreement.
3. Review, then **Send in thread**. It goes out from your mailbox, threaded onto the
   last message (same subject, `In-Reply-To`/`References`), so Gmail/Outlook keep it
   as one conversation the prospect already knows.
4. When the prospect replies, the worker syncs it into the same Conversation
   (usually within ~2 minutes) and **cancels every scheduled follow-up** for that
   deal. You take it from there.

Nothing is ever sent automatically. The AI only drafts; a human approves every send.

---

## Deploy notes (Railway)
- No new services needed — the existing **web** + **worker** cover it.
- New tables (`deal_conversations`, `conversation_messages`) and the extra
  `mailbox_connections` columns are created automatically on deploy (additive migrate).
- Optional variable: **`MAILBOX_POLL_SECONDS`** (default `120`) — how often the
  worker checks connected mailboxes for new replies.
- `JWT_SECRET` must be set (used to derive the encryption key for stored passwords),
  which it already is in production.

## Roadmap after v1
- OAuth for Google/Microsoft (removes app-password friction) behind the same
  provider interface (`app/mailbox/transport.py`).
- Attachments in-thread, HTML bodies, and the scheduled AI follow-up cadence UI
  (Day 2/5/9…) with per-step approval.
