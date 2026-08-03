"""Deal Conversation API — connect a mailbox, and run the same-thread
relationship on a Deal (get thread, AI-draft the next reply, send in-thread,
AI briefing). Inbound replies are synced by the poll worker + cancel follow-ups."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import AuthContext, get_ctx, scoped
from ..mailbox import service
from ..models.crm import Company, Contact, Deal, Stage
from ..models.documents import Document
from ..models.agreements import Agreement, Invoice
from ..models.mailbox import ConversationMessage, DealConversation, RevenueInboxItem
from ..models.onboarding import MailboxConnection

router = APIRouter(prefix="/api", tags=["deal-conversation"])


# ============================================================ mailbox
def _mbx_out(c: MailboxConnection) -> dict:
    return {"id": c.id, "provider": c.provider, "email": c.email, "from_name": c.from_name,
            "username": c.username, "smtp_host": c.smtp_host, "smtp_port": c.smtp_port,
            "imap_host": c.imap_host, "imap_port": c.imap_port, "status": c.status,
            "last_error": c.last_error, "active": bool(c.active),
            "default_autopilot": bool(getattr(c, "default_autopilot", False)),
            "default_interval_days": getattr(c, "default_interval_days", 4) or 4,
            "default_max_followups": getattr(c, "default_max_followups", 4) or 4,
            "last_checked_at": c.last_checked_at.isoformat() if c.last_checked_at else None}


@router.get("/mailbox")
def get_mailbox(workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    wsids = ctx.workspace_ids_for_query(workspace_id)
    c = (ctx.db.query(MailboxConnection).filter(MailboxConnection.workspace_id.in_(wsids))
         .order_by(MailboxConnection.id.desc()).first())
    return _mbx_out(c) if c else None


class MailboxIn(BaseModel):
    workspace_id: int
    provider: str = "gmail"          # gmail | outlook | smtp | google_workspace
    email: str
    app_password: str = ""           # app password (blank for google_workspace)
    from_name: str = ""
    username: str = ""
    smtp_host: str = ""
    smtp_port: int | None = None
    imap_host: str = ""
    imap_port: int | None = None


@router.get("/mailbox/google-workspace")
def google_workspace_info(ctx: AuthContext = Depends(get_ctx)):
    """What the frontend needs to show the domain-wide-delegation connect flow:
    whether the server has a service account configured, and the client_id +
    scopes a Workspace admin must authorize (Admin console -> Security -> API
    controls -> Domain-wide delegation)."""
    from ..mailbox import gmail_api
    return {"enabled": gmail_api.enabled(), "client_id": gmail_api.client_id(),
            "scopes": gmail_api.SCOPES,
            "admin_url": "https://admin.google.com/ac/owl/domainwidedelegation"}


@router.get("/mailbox/microsoft")
def microsoft_info(ctx: AuthContext = Depends(get_ctx)):
    """Microsoft 365 (Graph app-only) connect info: whether it's configured, the
    app client_id, the application permissions to grant, and the admin-consent URL
    a Workspace/tenant admin visits once."""
    from ..mailbox import graph_api
    return {"enabled": graph_api.enabled(), "client_id": graph_api.client_id(),
            "scopes": graph_api.SCOPES_DISPLAY,
            "admin_url": graph_api.admin_consent_url()}


@router.post("/mailbox/connect")
def connect(body: MailboxIn, ctx: AuthContext = Depends(get_ctx)):
    ctx.require_workspace(body.workspace_id)
    c = service.connect_mailbox(
        ctx.db, body.workspace_id, ctx.user.id, provider=body.provider, email=body.email,
        secret=body.app_password, from_name=body.from_name, username=body.username,
        smtp_host=body.smtp_host, smtp_port=body.smtp_port, imap_host=body.imap_host, imap_port=body.imap_port)
    if c.status != "connected":
        raise HTTPException(400, f"Could not connect: {c.last_error}")
    # WOW on connect: immediately import the last ~60 days in the background and
    # match to known contacts/deals, so the Revenue Inbox is useful within minutes.
    job_id = None
    try:
        from ..models.jobs import Job
        j = Job(kind="mailbox_backfill", workspace_id=body.workspace_id, payload={"days": 60})
        ctx.db.add(j)
        ctx.db.commit()
        job_id = j.id
    except Exception:
        pass
    out = _mbx_out(c)
    out["backfill_job_id"] = job_id
    return out


class FollowupDefaultsIn(BaseModel):
    workspace_id: int
    default_autopilot: bool | None = None
    default_interval_days: int | None = None
    default_max_followups: int | None = None


@router.put("/mailbox/followup-defaults")
def set_followup_defaults(body: FollowupDefaultsIn, ctx: AuthContext = Depends(get_ctx)):
    """Workspace-level follow-up autopilot defaults — new deal conversations
    inherit these (existing ones are unchanged)."""
    ctx.require_workspace(body.workspace_id)
    c = service.workspace_mailbox(ctx.db, body.workspace_id)
    if not c:
        raise HTTPException(404, "Connect a mailbox first")
    if body.default_autopilot is not None:
        c.default_autopilot = bool(body.default_autopilot)
    if body.default_interval_days is not None:
        c.default_interval_days = max(1, min(int(body.default_interval_days), 60))
    if body.default_max_followups is not None:
        c.default_max_followups = max(0, min(int(body.default_max_followups), 12))
    ctx.db.commit()
    return _mbx_out(c)


@router.post("/mailbox/test")
def test(workspace_id: int, ctx: AuthContext = Depends(get_ctx)):
    ctx.require_workspace(workspace_id)
    c = service.workspace_mailbox(ctx.db, workspace_id)
    if not c:
        raise HTTPException(404, "No mailbox connected")
    ok, err = service.test_connection(c)
    c.status = "connected" if ok else "error"
    c.last_error = "" if ok else err
    c.last_checked_at = datetime.utcnow()
    ctx.db.commit()
    return _mbx_out(c)


@router.delete("/mailbox/{mailbox_id}")
def disconnect(mailbox_id: int, ctx: AuthContext = Depends(get_ctx)):
    c = (scoped(ctx.db.query(MailboxConnection), MailboxConnection, ctx)
         .filter(MailboxConnection.id == mailbox_id).first())
    if not c:
        raise HTTPException(404, "Not found")
    ctx.db.delete(c)
    ctx.db.commit()
    return {"ok": True}


# ============================================================ deal conversation
def _deal(ctx, deal_id) -> Deal:
    d = scoped(ctx.db.query(Deal), Deal, ctx).filter(Deal.id == deal_id).first()
    if not d:
        raise HTTPException(404, "Deal not found")
    return d


def _msg_out(m: ConversationMessage) -> dict:
    return {"id": m.id, "direction": m.direction, "from_email": m.from_email, "to_email": m.to_email,
            "subject": m.subject, "body_text": m.body_text, "status": m.status,
            "ai_generated": bool(m.ai_generated),
            "scheduled_at": m.scheduled_at.isoformat() if m.scheduled_at else None,
            "sent_at": m.sent_at.isoformat() if m.sent_at else None,
            "created_at": m.created_at.isoformat() if m.created_at else None}


@router.get("/deals/{deal_id}/conversation")
def get_conversation(deal_id: int, sync: bool = True, ctx: AuthContext = Depends(get_ctx)):
    d = _deal(ctx, deal_id)
    conv = service.ensure_conversation(ctx.db, d)
    if sync:
        # pull any new replies from the live thread so the view is always current
        try:
            service.sync_conversation_thread(ctx.db, conv)
        except Exception:  # noqa: BLE001
            pass
    msgs = (ctx.db.query(ConversationMessage)
            .filter(ConversationMessage.conversation_id == conv.id)
            .order_by(ConversationMessage.id).all())
    mailbox = service.workspace_mailbox(ctx.db, d.workspace_id)
    return {
        "conversation": {"id": conv.id, "deal_id": conv.deal_id, "subject": conv.subject,
                         "prospect_email": conv.prospect_email, "state": conv.state,
                         "autopilot": bool(conv.autopilot),
                         "next_followup_at": conv.next_followup_at.isoformat() if conv.next_followup_at else None,
                         "followups_sent": conv.followups_sent or 0, "max_followups": conv.max_followups or 4,
                         "followup_interval_days": conv.followup_interval_days or 4,
                         "last_inbound_at": conv.last_inbound_at.isoformat() if conv.last_inbound_at else None,
                         "last_outbound_at": conv.last_outbound_at.isoformat() if conv.last_outbound_at else None},
        "mailbox_connected": bool(mailbox and mailbox.status == "connected"),
        "messages": [_msg_out(m) for m in msgs],
    }


class AutopilotIn(BaseModel):
    enabled: bool
    interval_days: int | None = None
    max_followups: int | None = None


@router.post("/deals/{deal_id}/conversation/autopilot")
def set_autopilot(deal_id: int, body: AutopilotIn, ctx: AuthContext = Depends(get_ctx)):
    """Turn the autonomous follow-up cadence on/off for this deal's conversation."""
    d = _deal(ctx, deal_id)
    conv = service.ensure_conversation(ctx.db, d)
    if body.enabled and not service.workspace_mailbox(ctx.db, d.workspace_id):
        raise HTTPException(409, "Connect a mailbox first (Settings → Email) before enabling autopilot.")
    conv = service.set_autopilot(ctx.db, conv, enabled=body.enabled,
                                 interval_days=body.interval_days, max_followups=body.max_followups)
    return {"autopilot": bool(conv.autopilot),
            "next_followup_at": conv.next_followup_at.isoformat() if conv.next_followup_at else None,
            "followups_sent": conv.followups_sent or 0, "max_followups": conv.max_followups or 4,
            "followup_interval_days": conv.followup_interval_days or 4}


class FollowupPreviewIn(BaseModel):
    guidance: str = ""
    steps: int = 3
    interval_days: int | None = None


@router.post("/deals/{deal_id}/conversation/followup-plan/preview")
def preview_followup_plan(deal_id: int, body: FollowupPreviewIn, ctx: AuthContext = Depends(get_ctx)):
    """Draft the whole follow-up sequence so the operator can review/edit before enabling."""
    d = _deal(ctx, deal_id)
    conv = service.ensure_conversation(ctx.db, d)
    if body.interval_days:
        conv.followup_interval_days = max(1, min(int(body.interval_days), 60))
        ctx.db.commit()
    plan = service.generate_followup_sequence(ctx.db, conv, guidance=body.guidance, steps=body.steps)
    return {"guidance": body.guidance, "plan": plan,
            "followups_sent": conv.followups_sent or 0}


class FollowupPlanIn(BaseModel):
    guidance: str = ""
    enabled: bool = True
    plan: list[dict] = []          # [{days:int, body:str}]


@router.get("/deals/{deal_id}/conversation/followup-plan")
def get_followup_plan(deal_id: int, ctx: AuthContext = Depends(get_ctx)):
    d = _deal(ctx, deal_id)
    conv = service.ensure_conversation(ctx.db, d)
    return {"guidance": conv.followup_guidance or "", "plan": conv.followup_plan or [],
            "autopilot": bool(conv.autopilot), "followups_sent": conv.followups_sent or 0,
            "next_followup_at": conv.next_followup_at.isoformat() if conv.next_followup_at else None}


@router.put("/deals/{deal_id}/conversation/followup-plan")
def save_followup_plan(deal_id: int, body: FollowupPlanIn, ctx: AuthContext = Depends(get_ctx)):
    """Save the reviewed follow-up plan (guidance + per-step body & timing) and,
    if enabled, schedule it. These exact emails are what get sent."""
    d = _deal(ctx, deal_id)
    conv = service.ensure_conversation(ctx.db, d)
    if body.enabled and not service.workspace_mailbox(ctx.db, d.workspace_id):
        raise HTTPException(409, "Connect a mailbox first (Settings → Email) before enabling follow-ups.")
    conv = service.save_followup_plan(ctx.db, conv, guidance=body.guidance, plan=body.plan, enabled=body.enabled)
    return {"autopilot": bool(conv.autopilot), "plan": conv.followup_plan or [],
            "next_followup_at": conv.next_followup_at.isoformat() if conv.next_followup_at else None}


class SendIn(BaseModel):
    body: str
    subject: str | None = None
    ai_generated: bool = False


@router.post("/deals/{deal_id}/conversation/send")
def send(deal_id: int, body: SendIn, ctx: AuthContext = Depends(get_ctx)):
    d = _deal(ctx, deal_id)
    conv = service.ensure_conversation(ctx.db, d)
    try:
        cm = service.send_message(ctx.db, conv, body.body, subject=body.subject,
                                  ai_generated=body.ai_generated, user_id=ctx.user.id)
    except ValueError as e:
        raise HTTPException(409, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Send failed: {e}")
    return _msg_out(cm)


@router.post("/deals/{deal_id}/conversation/draft")
def draft(deal_id: int, ctx: AuthContext = Depends(get_ctx)):
    d = _deal(ctx, deal_id)
    conv = service.ensure_conversation(ctx.db, d)
    return service.draft_followup(ctx.db, conv)


# ============================================================ revenue inbox (candidates)
def _first_mailbox(ctx, workspace_id):
    for wid in ctx.workspace_ids_for_query(workspace_id):
        m = service.workspace_mailbox(ctx.db, wid)
        if m:
            return m
    return None


@router.get("/mailbox/labels")
def mailbox_labels(workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    """Gmail labels / Outlook folders for the connected mailbox, so the user can
    import an entire label at once."""
    mailbox = _first_mailbox(ctx, workspace_id)
    if not mailbox or mailbox.status != "connected":
        return {"labels": [], "error": "No connected mailbox."}
    labels = service.mailbox_labels(mailbox)
    resp = {"labels": labels}
    if not labels and mailbox.provider == "google_workspace":
        # Empty is suspicious (most mailboxes have labels) — surface the reason.
        from ..mailbox import gmail_api
        ok, err = gmail_api.gmail_test(mailbox.email)
        resp["error"] = err or ("Connected, but Gmail returned no labels. Make sure "
                                 "gmail.readonly is among the authorized delegation scopes.")
    return resp


@router.get("/mailbox/threads")
def mailbox_threads(days: int = 90, limit: int = 100, q: str = "", label: str = "",
                    workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    """Browse recent conversations in the connected mailbox so the user can pick
    which ones to import — optionally filtered by a Gmail label and/or a search
    string. Flags each thread as a known lead (a CRM contact = pipeline lead) and
    whether it's already been imported."""
    mailbox = _first_mailbox(ctx, workspace_id)
    if not mailbox or mailbox.status != "connected":
        return {"items": [], "mailbox": None, "note": "no connected mailbox"}
    # Build a Gmail search query from the chosen label + free-text search.
    parts = []
    if label.strip():
        parts.append(f'label:"{label.strip()}"')
    if q.strip():
        parts.append(q.strip())
    query = " ".join(parts)
    msgs = service.fetch_recent(mailbox, days=days, limit=limit, query=query, folder=label or "INBOX")
    me = (mailbox.email or "").lower()

    # Collapse a Gmail thread (many messages) into ONE row, keeping the newest
    # message and the union of participants across the whole thread.
    def _norm_subj(s):
        n = (s or "").strip().lower()
        while n.startswith("re:") or n.startswith("fwd:"):
            n = n[3:].strip(": ").strip() if n.startswith("re:") else n[4:].strip(": ").strip()
        return n

    threads = {}
    for m in msgs:
        frm = (m.get("from_email") or "").lower()
        counterpart = (m.get("to_email") or "").lower() if frm == me else frm
        if not counterpart:
            continue
        tkey = m.get("thread_id") or f"{counterpart}|{_norm_subj(m.get('subject'))}"
        ts = int(m.get("internal_ts") or 0)
        cur = threads.get(tkey)
        parts = set((cur or {}).get("participants", [])) | set(m.get("participants") or [counterpart])
        if not cur or ts >= cur.get("_ts", 0):
            threads[tkey] = {**m, "counterpart": counterpart, "_ts": ts, "_key": tkey,
                             "participants": list(parts)}
        else:
            cur["participants"] = list(parts)

    out = []
    for t in sorted(threads.values(), key=lambda x: x.get("_ts", 0), reverse=True):
        counterpart = t["counterpart"]
        parts = t.get("participants") or [counterpart]
        contact = service.find_known_contact(ctx.db, mailbox.workspace_id, parts, exclude=me)
        tid = t.get("thread_id", "")
        mid = t.get("rfc_message_id", "")
        dup = ctx.db.query(RevenueInboxItem).filter(
            RevenueInboxItem.workspace_id == mailbox.workspace_id,
            RevenueInboxItem.status != "dismissed",
            (RevenueInboxItem.thread_id == tid) if tid else (RevenueInboxItem.rfc_message_id == mid)).first()
        out.append({
            "rfc_message_id": mid, "thread_id": tid, "from_email": (t.get("from_email") or "").lower(),
            "to_email": t.get("to_email", ""), "subject": (t.get("subject") or "").strip(),
            "preview": (t.get("body_text", "") or "")[:180], "participants": parts, "counterpart": counterpart,
            "in_reply_to": t.get("in_reply_to", ""), "references": t.get("references", ""),
            "known": contact is not None, "already": bool(dup),
            "contact": {"id": contact.id, "name": f"{contact.first_name} {contact.last_name}".strip(),
                        "email": contact.email} if contact else None,
        })
    return {"items": out, "mailbox": mailbox.email, "workspace_id": mailbox.workspace_id}


class ThreadImportIn(BaseModel):
    workspace_id: int
    items: list[dict]


@router.post("/mailbox/threads/import")
def import_threads(body: ThreadImportIn, ctx: AuthContext = Depends(get_ctx)):
    """Surface the selected threads in the Revenue Inbox to attach to deals."""
    ctx.require_workspace(body.workspace_id)
    mailbox = service.workspace_mailbox(ctx.db, body.workspace_id)
    n = 0
    for m in body.items:
        mid = m.get("rfc_message_id", "")
        tid = m.get("thread_id", "")
        exists = ctx.db.query(RevenueInboxItem).filter(
            RevenueInboxItem.workspace_id == body.workspace_id,
            RevenueInboxItem.status != "dismissed",
            (RevenueInboxItem.thread_id == tid) if tid else (RevenueInboxItem.rfc_message_id == mid)).first()
        if exists:
            continue
        parts = m.get("participants") or [m.get("from_email", "")]
        contact = service.find_known_contact(ctx.db, body.workspace_id, parts, exclude="")
        # Pull the WHOLE thread (all messages) for full context.
        messages = []
        if mailbox and tid:
            messages = service.thread_messages(mailbox, service.fetch_thread(mailbox, tid))
        body_text = (messages[-1]["text"] if messages else (m.get("preview", "") or m.get("body_text", "") or ""))[:8000]
        ctx.db.add(RevenueInboxItem(
            workspace_id=body.workspace_id, from_email=m.get("from_email", ""),
            subject=m.get("subject", ""), body_text=body_text, messages=messages,
            participants=parts, rfc_message_id=mid, thread_id=tid, in_reply_to=m.get("in_reply_to", ""),
            references=m.get("references", ""),
            matched_contact_id=contact.id if contact else None,
            matched_company_id=contact.company_id if contact else None, status="pending"))
        n += 1
    ctx.db.commit()
    return {"imported": n}


@router.post("/mailbox/sync")
def mailbox_sync(workspace_id: int, ctx: AuthContext = Depends(get_ctx)):
    """Manual 'Sync now': re-scan the mailbox and auto-surface any thread with a
    known lead (pipeline contacts included). Runs the same backfill as on connect."""
    ctx.require_workspace(workspace_id)
    try:
        res = service.backfill(ctx.db, workspace_id, days=60, limit=200)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Sync failed: {e}")
    return res


@router.get("/revenue-inbox")
def revenue_inbox(workspace_id: int | None = None, status: str = "",
                  ctx: AuthContext = Depends(get_ctx)):
    """Imported/surfaced email threads, Gmail-style: each item carries its full
    message history. Pending ones can be attached to a deal; attached ones link to
    their deal. Dismissed ones are hidden."""
    ws_ids = ctx.workspace_ids_for_query(workspace_id)
    q = ctx.db.query(RevenueInboxItem).filter(RevenueInboxItem.workspace_id.in_(ws_ids))
    if status:
        q = q.filter(RevenueInboxItem.status == status)
    else:
        q = q.filter(RevenueInboxItem.status != "dismissed")
    rows = q.order_by(RevenueInboxItem.id.desc()).limit(100).all()
    out = []
    for r in rows:
        contact = ctx.db.get(Contact, r.matched_contact_id) if r.matched_contact_id else None
        company = ctx.db.get(Company, r.matched_company_id) if r.matched_company_id else None
        deals = []
        if contact:
            deals = [{"id": d.id, "name": d.name} for d in
                     ctx.db.query(Deal).filter(Deal.workspace_id == r.workspace_id,
                                               Deal.contact_id == contact.id).all()]
        attached_deal = None
        if r.deal_id:
            d = ctx.db.get(Deal, r.deal_id)
            if d:
                attached_deal = {"id": d.id, "name": d.name}
        out.append({"id": r.id, "from_email": r.from_email, "subject": r.subject,
                    "preview": (r.body_text or "")[:180], "participants": r.participants or [],
                    "messages": r.messages or [], "status": r.status,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "contact": {"id": contact.id, "name": f"{contact.first_name} {contact.last_name}".strip(),
                                "email": contact.email} if contact else None,
                    "company": {"id": company.id, "name": company.name} if company else None,
                    "attached_deal": attached_deal, "deals": deals})
    return out


class AttachIn(BaseModel):
    deal_id: int


@router.post("/revenue-inbox/{item_id}/attach")
def attach(item_id: int, body: AttachIn, ctx: AuthContext = Depends(get_ctx)):
    item = ctx.db.get(RevenueInboxItem, item_id)
    if not item or item.workspace_id not in ctx.allowed_workspace_ids():
        raise HTTPException(404, "Not found")
    d = _deal(ctx, body.deal_id)
    conv = service.attach_item_to_deal(ctx.db, item, d, user_id=ctx.user.id)
    return {"ok": True, "deal_id": d.id, "conversation_id": conv.id}


@router.post("/revenue-inbox/{item_id}/create-deal")
def create_deal_from_item(item_id: int, ctx: AuthContext = Depends(get_ctx)):
    """Turn an imported thread into a followable deal: ensure a contact exists,
    create a deal on the pipeline, and attach the conversation. From the deal
    record you can then send follow-ups in the same thread."""
    from ..models.crm import Activity
    item = ctx.db.get(RevenueInboxItem, item_id)
    if not item or item.workspace_id not in ctx.allowed_workspace_ids():
        raise HTTPException(404, "Not found")
    wsid = item.workspace_id
    contact = ctx.db.get(Contact, item.matched_contact_id) if item.matched_contact_id else None
    email = (item.from_email or "").lower().strip()
    if not contact and email:
        contact = ctx.db.query(Contact).filter(Contact.workspace_id == wsid, Contact.email == email).first()
    if not contact:
        base = email.split("@")[0].replace(".", " ").replace("_", " ").title() if email else "New contact"
        fn, _, ln = base.partition(" ")
        contact = Contact(workspace_id=wsid, email=email, first_name=fn, last_name=ln)
        ctx.db.add(contact)
        ctx.db.flush()
    stage = (ctx.db.query(Stage).filter(Stage.workspace_id == wsid).order_by(Stage.sort_order).first())
    name = item.subject or f"{contact.first_name} {contact.last_name}".strip() or "New deal"
    deal = Deal(workspace_id=wsid, name=name, contact_id=contact.id, company_id=contact.company_id,
                stage_id=stage.id if stage else None, value=0)
    ctx.db.add(deal)
    ctx.db.flush()
    ctx.db.add(Activity(workspace_id=wsid, deal_id=deal.id, contact_id=contact.id, kind="deal_created",
                        title=f"Deal created from email: {name}", actor_user_id=ctx.user.id))
    conv = service.attach_item_to_deal(ctx.db, item, deal, user_id=ctx.user.id)
    ctx.db.commit()
    return {"ok": True, "deal_id": deal.id, "conversation_id": conv.id}


@router.post("/revenue-inbox/{item_id}/dismiss")
def dismiss(item_id: int, ctx: AuthContext = Depends(get_ctx)):
    item = ctx.db.get(RevenueInboxItem, item_id)
    if not item or item.workspace_id not in ctx.allowed_workspace_ids():
        raise HTTPException(404, "Not found")
    item.status = "dismissed"
    ctx.db.commit()
    return {"ok": True}


@router.get("/deals/{deal_id}/conversation/briefing")
def briefing(deal_id: int, ctx: AuthContext = Depends(get_ctx)):
    """The persistent AI briefing shown at the top of the Conversation tab:
    stage, last contact, intent, risk, proposal/agreement status, next action."""
    d = _deal(ctx, deal_id)
    conv = service.ensure_conversation(ctx.db, d)
    now = datetime.utcnow()
    stage = ctx.db.get(Stage, d.stage_id) if d.stage_id else None
    company = ctx.db.get(Company, d.company_id) if d.company_id else None

    last = conv.last_inbound_at or conv.last_outbound_at
    days = int((now - last).total_seconds() // 86400) if last else None
    awaiting_us = bool(conv.last_inbound_at and (not conv.last_outbound_at or conv.last_inbound_at > conv.last_outbound_at))

    bp = (ctx.db.query(Document).filter(Document.company_id == d.company_id, Document.kind == "blueprint")
          .order_by(Document.updated_at.desc()).first()) if d.company_id else None
    ag = (ctx.db.query(Agreement).filter(Agreement.deal_id == d.id)
          .order_by(Agreement.updated_at.desc()).first())
    inv = (ctx.db.query(Invoice).filter(Invoice.deal_id == d.id)
           .order_by(Invoice.updated_at.desc()).first())

    # simple, honest heuristics (no fabricated numbers)
    intent = d.lead_intent or ("high" if awaiting_us else "medium")
    if days is None:
        risk = "unknown"
    elif days >= 10:
        risk = "high"       # going cold / ghost territory
    elif days >= 5:
        risk = "medium"
    else:
        risk = "low"
    ghost = bool(ag and ag.status in ("sent", "viewed") and days is not None and days >= 7 and not conv.last_inbound_at)

    if awaiting_us:
        rec = "The prospect replied and is waiting on you. Draft a reply and send this week."
        action = "Review draft → Send"
    elif ghost or (risk == "high"):
        rec = "No reply and it's going cold. Send a light, human check-in in the same thread."
        action = "Draft follow-up → Review → Send"
    elif not (bp or ag):
        rec = "Keep the relationship warm; reference the last conversation."
        action = "Draft follow-up → Review → Send"
    else:
        rec = "On track. Follow up if you don't hear back in a few days."
        action = "Wait / schedule follow-up"

    # relationship health (Healthy / Cooling / Ghosted)
    if ghost:
        health = "ghosted"
    elif risk == "high":
        health = "cooling"
    elif risk in ("low", "medium") or awaiting_us:
        health = "healthy" if not (days and days >= 5) else "cooling"
    else:
        health = "unknown"

    contact = ctx.db.get(Contact, d.contact_id) if d.contact_id else None
    nxt = (ctx.db.query(ConversationMessage)
           .filter(ConversationMessage.conversation_id == conv.id,
                   ConversationMessage.status == "scheduled")
           .order_by(ConversationMessage.scheduled_at).first())

    return {
        "deal": {"id": d.id, "name": d.name, "value": d.value, "close_date": d.close_date or "",
                 "company": company.name if company else "", "company_id": d.company_id},
        "contact": {"name": f"{contact.first_name} {contact.last_name}".strip(), "email": contact.email,
                    "id": contact.id} if contact else None,
        "stage": stage.name if stage else "—",
        "last_contact_days": days,
        "awaiting_us": awaiting_us,
        "next_followup_at": nxt.scheduled_at.isoformat() if (nxt and nxt.scheduled_at) else None,
        "intent": intent,
        "risk": risk,
        "health": health,
        "ghost": ghost,
        "blueprint": bool(bp), "blueprint_viewed": bool(bp and (bp.view_count or 0) > 0),
        "agreement_status": ag.status if ag else None,
        "invoice_status": inv.status if inv else None,
        "summary": rec,
        "recommendation": rec,
        "next_action": action,
        "conversation_state": conv.state,
    }
