"""Deal Conversation service — the brain of same-thread relationship management.

Rules enforced here:
- One mailbox per workspace (v1). Outgoing mail goes through it.
- Every send threads onto the previous message (In-Reply-To + References) and keeps
  the same subject, so it stays in ONE email thread the prospect sees.
- A received reply CANCELS every scheduled follow-up for that Deal and hands control
  back to the human.
- AI never auto-sends: drafts are `status="draft"`, follow-ups are `status="scheduled"`.
"""
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import make_msgid

from ..crypto import decrypt, encrypt
from ..models.crm import Activity, Company, Contact, Deal, Stage
from ..models.mailbox import ConversationMessage, DealConversation
from ..models.onboarding import MailboxConnection
from . import transport

PROVIDER_DEFAULTS = {
    "gmail":   {"smtp_host": "smtp.gmail.com",       "smtp_port": 587, "imap_host": "imap.gmail.com",           "imap_port": 993},
    "outlook": {"smtp_host": "smtp.office365.com",   "smtp_port": 587, "imap_host": "outlook.office365.com",    "imap_port": 993},
    "smtp":    {"smtp_host": "",                     "smtp_port": 587, "imap_host": "",                         "imap_port": 993},
}


# ---- connection -------------------------------------------------------------
def connect_mailbox(db, workspace_id, user_id, *, provider, email, secret, from_name="",
                    username="", smtp_host="", smtp_port=None, imap_host="", imap_port=None):
    """Create/replace the workspace's mailbox (v1: one per workspace), encrypt the
    app password, and verify it can authenticate for sending."""
    d = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS["smtp"])
    conn = db.query(MailboxConnection).filter(MailboxConnection.workspace_id == workspace_id).first()
    if conn is None:
        conn = MailboxConnection(workspace_id=workspace_id)
        db.add(conn)
    conn.user_id = user_id
    conn.provider = provider
    conn.email = email.strip().lower()
    conn.from_name = from_name or conn.from_name
    conn.username = (username or email).strip()
    conn.smtp_host = smtp_host or d["smtp_host"]
    conn.smtp_port = int(smtp_port or d["smtp_port"])
    conn.imap_host = imap_host or d["imap_host"]
    conn.imap_port = int(imap_port or d["imap_port"])
    if secret:
        conn.app_password_enc = encrypt(secret)
    conn.active = True
    db.flush()
    ok, err = test_connection(conn)
    conn.status = "connected" if ok else "error"
    conn.last_error = "" if ok else err
    conn.last_checked_at = datetime.utcnow()
    db.commit()
    return conn


def test_connection(conn: MailboxConnection) -> tuple[bool, str]:
    if not conn.app_password_enc:
        return False, "No password stored"
    try:
        secret = decrypt(conn.app_password_enc)
    except Exception as e:  # noqa: BLE001
        return False, f"Could not read stored password: {e}"
    return transport.smtp_test(conn.smtp_host, conn.smtp_port, conn.username, secret)


def workspace_mailbox(db, workspace_id) -> MailboxConnection | None:
    return (db.query(MailboxConnection)
            .filter(MailboxConnection.workspace_id == workspace_id, MailboxConnection.active == True)  # noqa: E712
            .order_by(MailboxConnection.id.desc()).first())


# ---- conversation lifecycle -------------------------------------------------
def ensure_conversation(db, deal: Deal) -> DealConversation:
    """Get or create THE conversation for a deal (one thread per deal)."""
    conv = db.query(DealConversation).filter(DealConversation.deal_id == deal.id).first()
    if conv:
        return conv
    contact = db.get(Contact, deal.contact_id) if deal.contact_id else None
    company = db.get(Company, deal.company_id) if deal.company_id else None
    mailbox = workspace_mailbox(db, deal.workspace_id)
    subject = f"{company.name if company else (deal.name or 'Following up')}"
    conv = DealConversation(
        workspace_id=deal.workspace_id, deal_id=deal.id, company_id=deal.company_id,
        contact_id=deal.contact_id, mailbox_id=mailbox.id if mailbox else None,
        subject=subject, prospect_email=(contact.email.lower().strip() if contact and contact.email else ""),
        state="active")
    # inherit the workspace's follow-up autopilot defaults (armed on first send)
    if mailbox:
        conv.autopilot = bool(getattr(mailbox, "default_autopilot", False))
        conv.followup_interval_days = getattr(mailbox, "default_interval_days", 4) or 4
        conv.max_followups = getattr(mailbox, "default_max_followups", 4) or 4
    db.add(conv)
    db.commit()
    return conv


def _last_message(db, conv):
    return (db.query(ConversationMessage)
            .filter(ConversationMessage.conversation_id == conv.id,
                    ConversationMessage.status.in_(["sent", "received"]))
            .order_by(ConversationMessage.id.desc()).first())


def build_mime(conn: MailboxConnection, conv: DealConversation, to_email: str, subject: str,
               body_text: str, last) -> tuple[EmailMessage, str, str, str]:
    """Build the outgoing MIME with threading headers. Returns (msg, message_id,
    in_reply_to, references)."""
    msg = EmailMessage()
    msg["From"] = f"{conn.from_name} <{conn.email}>" if conn.from_name else conn.email
    msg["To"] = to_email
    msg["Subject"] = subject
    message_id = make_msgid(domain=(conn.email.split("@")[-1] or "revcadence.com"))
    msg["Message-ID"] = message_id
    in_reply_to, references = "", ""
    if last and last.rfc_message_id:
        in_reply_to = last.rfc_message_id
        references = (f"{conv.thread_refs} {last.rfc_message_id}").strip()
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = references
    msg.set_content(body_text)
    return msg, message_id, in_reply_to, references


def send_message(db, conv: DealConversation, body_text: str, *, subject=None,
                 ai_generated=False, user_id=None):
    """Send an email THROUGH the connected mailbox, threaded onto the last message
    so the prospect sees one continuous conversation. Records it + timeline."""
    mailbox = db.get(MailboxConnection, conv.mailbox_id) if conv.mailbox_id else workspace_mailbox(db, conv.workspace_id)
    if not mailbox:
        raise ValueError("No mailbox connected for this workspace. Connect one in Settings → Email.")
    if not conv.prospect_email:
        raise ValueError("This conversation has no prospect email address.")
    last = _last_message(db, conv)
    # keep the same thread subject; add Re: for replies
    subj = subject or conv.subject or "Following up"
    if last and not subj.lower().startswith("re:"):
        subj = f"Re: {subj}"
    msg, message_id, in_reply_to, references = build_mime(mailbox, conv, conv.prospect_email, subj, body_text, last)

    secret = decrypt(mailbox.app_password_enc)
    transport.smtp_send(mailbox.smtp_host, mailbox.smtp_port, mailbox.username, secret, msg)

    cm = ConversationMessage(
        conversation_id=conv.id, workspace_id=conv.workspace_id, deal_id=conv.deal_id,
        direction="out", from_email=mailbox.email, to_email=conv.prospect_email, subject=subj,
        body_text=body_text, rfc_message_id=message_id, in_reply_to=in_reply_to, references=references,
        status="sent", sent_at=datetime.utcnow(), ai_generated=ai_generated, approved_by=user_id)
    db.add(cm)
    conv.subject = subj[4:].strip() if subj.lower().startswith("re:") else subj
    conv.thread_refs = (references or f"{conv.thread_refs} {message_id}").strip()[:4000]
    conv.last_outbound_at = datetime.utcnow()
    conv.state = "active"
    # autopilot: arm the next follow-up after this send (spacing from now)
    if conv.autopilot and (conv.followups_sent or 0) < (conv.max_followups or 4):
        conv.next_followup_at = datetime.utcnow() + timedelta(days=conv.followup_interval_days or 4)
    db.add(Activity(workspace_id=conv.workspace_id, deal_id=conv.deal_id, contact_id=conv.contact_id,
                    company_id=conv.company_id, kind="email_out",
                    title=f"Email sent{' (AI)' if ai_generated else ''}: {subj}",
                    body=body_text[:1000], data={"conversation_id": conv.id, "message_id": cm.id},
                    actor_user_id=user_id))
    db.commit()
    return cm


def schedule_followups(db, conv: DealConversation, drafts: list[dict], user_id=None):
    """Queue AI follow-up drafts as scheduled messages (never sent automatically —
    each still needs approval before send, and any reply cancels them all).
    drafts: [{body, scheduled_at}]"""
    made = []
    for d in drafts:
        cm = ConversationMessage(
            conversation_id=conv.id, workspace_id=conv.workspace_id, deal_id=conv.deal_id,
            direction="out", to_email=conv.prospect_email, subject=conv.subject,
            body_text=d.get("body", ""), status="scheduled", scheduled_at=d.get("scheduled_at"),
            ai_generated=True, approved_by=None)
        db.add(cm)
        made.append(cm)
    db.commit()
    return made


def cancel_scheduled(db, conv: DealConversation) -> int:
    """Cancel every pending scheduled follow-up for this conversation."""
    n = (db.query(ConversationMessage)
         .filter(ConversationMessage.conversation_id == conv.id,
                 ConversationMessage.status == "scheduled")
         .update({ConversationMessage.status: "cancelled"}, synchronize_session=False))
    return n


def record_inbound(db, conv: DealConversation, *, from_email, subject, body_text,
                   rfc_message_id="", in_reply_to="", references=""):
    """A prospect reply landed. Store it in the same conversation, CANCEL all
    scheduled follow-ups, and hand control back to the human."""
    cm = ConversationMessage(
        conversation_id=conv.id, workspace_id=conv.workspace_id, deal_id=conv.deal_id,
        direction="in", from_email=(from_email or "").lower(), to_email=conv.prospect_email or "",
        subject=subject or "", body_text=body_text or "", rfc_message_id=rfc_message_id,
        in_reply_to=in_reply_to, references=references, status="received")
    db.add(cm)
    cancelled = cancel_scheduled(db, conv)
    conv.last_inbound_at = datetime.utcnow()
    conv.next_followup_at = None    # prospect replied → stop autopilot, hand back to human
    conv.state = "active"
    if references or rfc_message_id:
        conv.thread_refs = (f"{conv.thread_refs} {rfc_message_id}").strip()[:4000]
    db.add(Activity(workspace_id=conv.workspace_id, deal_id=conv.deal_id, contact_id=conv.contact_id,
                    company_id=conv.company_id, kind="email_in",
                    title=f"Prospect replied: {subject or '(no subject)'}",
                    body=(body_text or "")[:1000],
                    data={"conversation_id": conv.id, "cancelled_followups": cancelled}))
    db.commit()
    return cm, cancelled


def find_known_contact(db, workspace_id, emails: list, exclude: str = ""):
    """Return the first workspace Contact whose email is among `emails` (any known
    lead on the thread). Excludes our own mailbox address."""
    ex = (exclude or "").lower().strip()
    cands = [e.lower().strip() for e in (emails or []) if e and e.lower().strip() != ex]
    if not cands:
        return None
    return (db.query(Contact)
            .filter(Contact.workspace_id == workspace_id, Contact.email.in_(cands))
            .order_by(Contact.id).first())


def poll_and_sync(db, workspace_id) -> dict:
    """Fetch new mail from the connected mailbox. Each message either:
    1) matches an existing Deal Conversation → land it (cancels scheduled follow-ups), or
    2) involves a KNOWN Contact but no conversation yet → surface it in the Revenue
       Inbox as a pending candidate the user can attach to a deal.
    Safe to call repeatedly."""
    from ..models.mailbox import RevenueInboxItem
    mailbox = workspace_mailbox(db, workspace_id)
    if not mailbox or mailbox.status != "connected":
        return {"skipped": "no connected mailbox"}
    secret = decrypt(mailbox.app_password_enc)
    incoming = transport.imap_fetch_unseen(mailbox.imap_host, mailbox.imap_port, mailbox.username, secret)
    matched, candidates, ignored = 0, 0, 0
    for m in incoming:
        if (m.get("from_email") or "").lower() == mailbox.email.lower():
            continue  # our own outbound echo
        mid = m.get("rfc_message_id", "")
        conv = match_inbound_to_conversation(db, workspace_id, from_email=m.get("from_email", ""),
                                             in_reply_to=m.get("in_reply_to", ""),
                                             references=m.get("references", ""))
        if conv:
            if mid and db.query(ConversationMessage).filter(
                    ConversationMessage.conversation_id == conv.id,
                    ConversationMessage.rfc_message_id == mid).first():
                continue
            record_inbound(db, conv, from_email=m.get("from_email", ""), subject=m.get("subject", ""),
                           body_text=m.get("body_text", ""), rfc_message_id=mid,
                           in_reply_to=m.get("in_reply_to", ""), references=m.get("references", ""))
            matched += 1
            continue
        # no conversation yet → is a known lead on the thread?
        participants = m.get("participants") or [m.get("from_email", "")]
        contact = find_known_contact(db, workspace_id, participants, exclude=mailbox.email)
        if not contact:
            ignored += 1
            continue
        if mid and db.query(RevenueInboxItem).filter(RevenueInboxItem.workspace_id == workspace_id,
                                                     RevenueInboxItem.rfc_message_id == mid).first():
            continue  # already surfaced
        db.add(RevenueInboxItem(
            workspace_id=workspace_id, from_email=m.get("from_email", ""), subject=m.get("subject", ""),
            body_text=(m.get("body_text", "") or "")[:8000], participants=participants,
            rfc_message_id=mid, in_reply_to=m.get("in_reply_to", ""), references=m.get("references", ""),
            matched_contact_id=contact.id, matched_company_id=contact.company_id, status="pending"))
        candidates += 1
    mailbox.last_sync_at = datetime.utcnow()
    db.commit()
    return {"matched": matched, "candidates": candidates, "ignored": ignored, "fetched": len(incoming)}


def backfill(db, workspace_id, days=60, limit=200) -> dict:
    """The 'wow on connect' import: pull the last `days` of mail, match each thread
    to an existing Deal Conversation (record it) or to a known Contact (surface it
    in the Revenue Inbox). Marks nothing as read; deduped; safe to re-run."""
    from ..models.mailbox import RevenueInboxItem
    mailbox = workspace_mailbox(db, workspace_id)
    if not mailbox or mailbox.status != "connected":
        return {"skipped": "no connected mailbox"}
    secret = decrypt(mailbox.app_password_enc)
    msgs = transport.imap_fetch_since(mailbox.imap_host, mailbox.imap_port, mailbox.username,
                                      secret, days=days, limit=limit, folder="INBOX")
    matched, candidates = 0, 0
    contacts_touched = set()
    for m in msgs:
        frm = (m.get("from_email") or "").lower()
        if frm == mailbox.email.lower():
            continue  # our own outbound (from the connected box)
        mid = m.get("rfc_message_id", "")
        conv = match_inbound_to_conversation(db, workspace_id, from_email=frm,
                                             in_reply_to=m.get("in_reply_to", ""),
                                             references=m.get("references", ""))
        if conv:
            if mid and db.query(ConversationMessage).filter(
                    ConversationMessage.conversation_id == conv.id,
                    ConversationMessage.rfc_message_id == mid).first():
                continue
            record_inbound(db, conv, from_email=frm, subject=m.get("subject", ""),
                           body_text=m.get("body_text", ""), rfc_message_id=mid,
                           in_reply_to=m.get("in_reply_to", ""), references=m.get("references", ""))
            matched += 1
            continue
        participants = m.get("participants") or [frm]
        contact = find_known_contact(db, workspace_id, participants, exclude=mailbox.email)
        if not contact:
            continue
        if mid and db.query(RevenueInboxItem).filter(RevenueInboxItem.workspace_id == workspace_id,
                                                     RevenueInboxItem.rfc_message_id == mid).first():
            continue
        db.add(RevenueInboxItem(
            workspace_id=workspace_id, from_email=frm, subject=m.get("subject", ""),
            body_text=(m.get("body_text", "") or "")[:8000], participants=participants,
            rfc_message_id=mid, in_reply_to=m.get("in_reply_to", ""), references=m.get("references", ""),
            matched_contact_id=contact.id, matched_company_id=contact.company_id, status="pending"))
        candidates += 1
        contacts_touched.add(contact.id)
    mailbox.last_sync_at = datetime.utcnow()
    db.commit()
    return {"scanned": len(msgs), "matched": matched, "candidates": candidates,
            "contacts": len(contacts_touched), "days": days}


def attach_item_to_deal(db, item, deal, user_id=None):
    """Turn a Revenue Inbox candidate into a Deal Conversation: ensure the deal's
    conversation exists, drop the email in as the first inbound message, and mark
    the candidate attached."""
    conv = ensure_conversation(db, deal)
    # seed the prospect email + thread refs from the item so future sends thread onto it
    if not conv.prospect_email:
        conv.prospect_email = (item.from_email or "").lower()
    if item.rfc_message_id:
        conv.thread_refs = (f"{conv.thread_refs} {item.rfc_message_id}").strip()[:4000]
    if item.subject and not conv.subject:
        conv.subject = item.subject
    cm = ConversationMessage(
        conversation_id=conv.id, workspace_id=conv.workspace_id, deal_id=conv.deal_id,
        direction="in", from_email=item.from_email, to_email=conv.prospect_email or "",
        subject=item.subject or "", body_text=item.body_text or "", rfc_message_id=item.rfc_message_id,
        in_reply_to=item.in_reply_to, references=item.references, status="received")
    db.add(cm)
    conv.last_inbound_at = datetime.utcnow()
    conv.state = "active"
    item.status = "attached"
    item.deal_id = deal.id
    item.conversation_id = conv.id
    db.add(Activity(workspace_id=conv.workspace_id, deal_id=deal.id, contact_id=conv.contact_id,
                    company_id=conv.company_id, kind="email_in",
                    title=f"Thread attached to deal: {item.subject or '(no subject)'}",
                    body=(item.body_text or "")[:1000], data={"revenue_inbox_item": item.id},
                    actor_user_id=user_id))
    db.commit()
    return conv


def draft_followup(db, conv: DealConversation) -> dict:
    """Prepare the NEXT email in THIS thread — grounded in the full conversation +
    the deal's blueprint/agreement — reading like the salesperson wrote it. Never
    sent; returns a draft for human approval. AI when available, template otherwise."""
    msgs = (db.query(ConversationMessage)
            .filter(ConversationMessage.conversation_id == conv.id,
                    ConversationMessage.status.in_(["sent", "received"]))
            .order_by(ConversationMessage.id).all())
    contact = db.get(Contact, conv.contact_id) if conv.contact_id else None
    first = (contact.first_name if contact else "") or ""
    thread = [{"direction": m.direction, "text": m.body_text} for m in msgs]

    # ground with the latest blueprint content for this company (if any)
    ground = ""
    from ..models.documents import Document
    bp = (db.query(Document).filter(Document.company_id == conv.company_id, Document.kind == "blueprint")
          .order_by(Document.updated_at.desc()).first()) if conv.company_id else None
    if bp:
        c = (bp.fields or {}).get("content") or {}
        ground = c.get("exec_summary") or c.get("target_outcome") or ""

    # unified Client Brain — the SAME profile outbound + replies use, so follow-ups
    # speak the client's language (offer, per-industry problems, real case studies).
    brain = {}
    try:
        from ..models.enrich import EnrichConfig
        bc = db.query(EnrichConfig).filter(EnrichConfig.workspace_id == conv.workspace_id).first()
        brain = (bc.profile or {}) if bc else {}
    except Exception:
        brain = {}

    try:
        import json as _json

        from ..enrichment import ai
        if ai.has_ai() and thread:
            convo = "\n\n".join(f"[{m['direction'].upper()}] {m['text']}" for m in thread)
            brain_ctx = _json.dumps({k: brain.get(k) for k in
                                     ("main_offer", "target_outcome", "positioning",
                                      "problem_library", "case_studies", "proof_points")
                                     if brain.get(k)})[:3000]
            system = (
                "You are the salesperson continuing a REAL email thread with a prospect after a meeting. "
                "Write the next email in the SAME thread — natural, human, brief, no salesy fluff, no "
                "signature (the system adds it), no subject line. Reference what was actually said. Draw on "
                "the CLIENT PROFILE's problem_library for the prospect's situation and reference a real "
                "case_study/proof_point only if it genuinely fits — never fabricate. If they asked for time "
                "(e.g. 'give me two weeks'), respect it and check in lightly. Never sound automated. Output "
                "ONLY the email body.")
            user = (f"Prospect first name: {first}\n"
                    f"Context (our offer): {ground}\n"
                    f"CLIENT PROFILE: {brain_ctx}\n\n"
                    f"THREAD (oldest→newest):\n{convo}\n\nWrite the next follow-up email body:")
            import os
            import requests
            followup_model = ai.writer_model().lower()
            followup_payload = {
                "model": followup_model,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
            }
            if followup_model.startswith("gpt-5"):
                followup_payload["reasoning_effort"] = "low"
            else:
                followup_payload["temperature"] = 0.5
            r = requests.post(ai.OPENAI_URL,
                headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}", "Content-Type": "application/json"},
                json=followup_payload,
                timeout=60)
            r.raise_for_status()
            body = r.json()["choices"][0]["message"]["content"].strip()
            return {"body": body, "source": "openai"}
    except Exception:  # noqa: BLE001
        pass

    hi = f"Hi {first}," if first else "Hi,"
    return {"body": f"{hi}\n\nJust following up on our last conversation — happy to answer any "
            "questions and figure out the best next step whenever the timing works for you.\n\n"
            "Would a quick call this week or next be helpful?", "source": "template"}


def set_autopilot(db, conv: DealConversation, *, enabled: bool, interval_days=None, max_followups=None):
    """Turn the autonomous follow-up cadence on/off for a conversation. When ON it
    sends AI follow-ups on a schedule until the prospect replies or the cap is hit.
    Opt-in and reversible — never on by default."""
    conv.autopilot = bool(enabled)
    if interval_days:
        conv.followup_interval_days = max(1, min(int(interval_days), 60))
    if max_followups is not None:
        conv.max_followups = max(0, min(int(max_followups), 12))
    if enabled:
        # Only arm if a first email already went out (autopilot FOLLOWS UP — it never
        # cold-sends). If nothing sent yet, stay dormant; the first send arms it.
        replied_since = conv.last_inbound_at and conv.last_outbound_at and conv.last_inbound_at >= conv.last_outbound_at
        if conv.last_outbound_at and not replied_since and (conv.followups_sent or 0) < (conv.max_followups or 4):
            conv.next_followup_at = conv.last_outbound_at + timedelta(days=conv.followup_interval_days or 4)
        else:
            conv.next_followup_at = None
    else:
        conv.next_followup_at = None
    db.commit()
    return conv


def run_due_followups(db, now=None) -> dict:
    """Send every follow-up that is due. Safety rails: opt-in (autopilot), hard cap
    (max_followups), stops the instant a prospect replies, and only ever continues
    the SAME thread. One failure never blocks the rest."""
    now = now or datetime.utcnow()
    due = (db.query(DealConversation)
           .filter(DealConversation.autopilot == True,                       # noqa: E712
                   DealConversation.state == "active",
                   DealConversation.next_followup_at != None,                # noqa: E711
                   DealConversation.next_followup_at <= now).all())
    sent = skipped = 0
    for conv in due:
        try:
            # deal-closed guard: NEVER keep emailing a Won or Lost deal.
            deal = db.get(Deal, conv.deal_id) if conv.deal_id else None
            if deal and deal.stage_id:
                st = db.get(Stage, deal.stage_id)
                if st and (st.is_won or st.is_lost):
                    conv.autopilot = False
                    conv.next_followup_at = None
                    conv.state = "won" if st.is_won else "lost"
                    db.commit()
                    skipped += 1
                    continue
            # replied-since guard: if a reply landed after our last send, hand to human
            if conv.last_inbound_at and conv.last_outbound_at and conv.last_inbound_at >= conv.last_outbound_at:
                conv.next_followup_at = None
                skipped += 1
                continue
            if (conv.followups_sent or 0) >= (conv.max_followups or 4):
                conv.next_followup_at = None
                skipped += 1
                continue
            if not conv.prospect_email or not workspace_mailbox(db, conv.workspace_id):
                conv.next_followup_at = None
                skipped += 1
                continue
            if not conv.last_outbound_at:      # never cold-send: require a first email
                conv.next_followup_at = None
                skipped += 1
                continue
            draft = draft_followup(db, conv)
            body = (draft or {}).get("body", "").strip()
            if not body:
                conv.next_followup_at = now + timedelta(days=1)   # retry tomorrow
                continue
            send_message(db, conv, body, ai_generated=True)       # threads + logs + re-arms
            conv.followups_sent = (conv.followups_sent or 0) + 1
            if conv.followups_sent >= (conv.max_followups or 4):
                conv.next_followup_at = None                      # sequence complete
            db.commit()
            sent += 1
        except Exception:
            db.rollback()
            try:
                conv.next_followup_at = now + timedelta(days=1)   # back off, don't hammer
                db.commit()
            except Exception:
                db.rollback()
    return {"sent": sent, "skipped": skipped, "due": len(due)}


def match_inbound_to_conversation(db, workspace_id, *, from_email, in_reply_to="", references=""):
    """Find which Deal Conversation an inbound reply belongs to: first by RFC
    threading (a message-id we sent appears in In-Reply-To/References), then by the
    prospect's email address. Pure lookup — no side effects."""
    ids = set()
    for h in (in_reply_to or "", references or ""):
        for tok in h.replace(",", " ").split():
            tok = tok.strip()
            if tok:
                ids.add(tok)
    if ids:
        msg = (db.query(ConversationMessage)
               .filter(ConversationMessage.workspace_id == workspace_id,
                       ConversationMessage.direction == "out",
                       ConversationMessage.rfc_message_id.in_(list(ids))).first())
        if msg:
            return db.get(DealConversation, msg.conversation_id)
    fe = (from_email or "").lower().strip()
    if fe:
        return (db.query(DealConversation)
                .filter(DealConversation.workspace_id == workspace_id,
                        DealConversation.prospect_email == fe)
                .order_by(DealConversation.updated_at.desc()).first())
    return None
