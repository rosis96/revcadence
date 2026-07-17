"""Deal Conversation service — the brain of same-thread relationship management.

Rules enforced here:
- One mailbox per workspace (v1). Outgoing mail goes through it.
- Every send threads onto the previous message (In-Reply-To + References) and keeps
  the same subject, so it stays in ONE email thread the prospect sees.
- A received reply CANCELS every scheduled follow-up for that Deal and hands control
  back to the human.
- AI never auto-sends: drafts are `status="draft"`, follow-ups are `status="scheduled"`.
"""
from datetime import datetime
from email.message import EmailMessage
from email.utils import make_msgid

from ..crypto import decrypt, encrypt
from ..models.crm import Activity, Company, Contact, Deal
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

    try:
        from ..enrichment import ai
        if ai.has_ai() and thread:
            convo = "\n\n".join(f"[{m['direction'].upper()}] {m['text']}" for m in thread)
            system = (
                "You are the salesperson continuing a REAL email thread with a prospect after a meeting. "
                "Write the next email in the SAME thread — natural, human, brief, no salesy fluff, no "
                "signature (the system adds it), no subject line. Reference what was actually said. If they "
                "asked for time (e.g. 'give me two weeks'), respect it and check in lightly. Never sound "
                "automated. Output ONLY the email body.")
            user = (f"Prospect first name: {first}\n"
                    f"Context (our offer): {ground}\n\n"
                    f"THREAD (oldest→newest):\n{convo}\n\nWrite the next follow-up email body:")
            import os
            import requests
            r = requests.post(ai.OPENAI_URL,
                headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}", "Content-Type": "application/json"},
                json={"model": ai.writer_model().lower(), "temperature": 0.5,
                      "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
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
