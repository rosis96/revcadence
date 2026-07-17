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
            "last_checked_at": c.last_checked_at.isoformat() if c.last_checked_at else None}


@router.get("/mailbox")
def get_mailbox(workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    wsids = ctx.workspace_ids_for_query(workspace_id)
    c = (ctx.db.query(MailboxConnection).filter(MailboxConnection.workspace_id.in_(wsids))
         .order_by(MailboxConnection.id.desc()).first())
    return _mbx_out(c) if c else None


class MailboxIn(BaseModel):
    workspace_id: int
    provider: str = "gmail"          # gmail | outlook | smtp
    email: str
    app_password: str                # app password (not the account password)
    from_name: str = ""
    username: str = ""
    smtp_host: str = ""
    smtp_port: int | None = None
    imap_host: str = ""
    imap_port: int | None = None


@router.post("/mailbox/connect")
def connect(body: MailboxIn, ctx: AuthContext = Depends(get_ctx)):
    ctx.require_workspace(body.workspace_id)
    c = service.connect_mailbox(
        ctx.db, body.workspace_id, ctx.user.id, provider=body.provider, email=body.email,
        secret=body.app_password, from_name=body.from_name, username=body.username,
        smtp_host=body.smtp_host, smtp_port=body.smtp_port, imap_host=body.imap_host, imap_port=body.imap_port)
    if c.status != "connected":
        raise HTTPException(400, f"Could not connect: {c.last_error}")
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
def get_conversation(deal_id: int, ctx: AuthContext = Depends(get_ctx)):
    d = _deal(ctx, deal_id)
    conv = service.ensure_conversation(ctx.db, d)
    msgs = (ctx.db.query(ConversationMessage)
            .filter(ConversationMessage.conversation_id == conv.id)
            .order_by(ConversationMessage.id).all())
    mailbox = service.workspace_mailbox(ctx.db, d.workspace_id)
    return {
        "conversation": {"id": conv.id, "deal_id": conv.deal_id, "subject": conv.subject,
                         "prospect_email": conv.prospect_email, "state": conv.state,
                         "last_inbound_at": conv.last_inbound_at.isoformat() if conv.last_inbound_at else None,
                         "last_outbound_at": conv.last_outbound_at.isoformat() if conv.last_outbound_at else None},
        "mailbox_connected": bool(mailbox and mailbox.status == "connected"),
        "messages": [_msg_out(m) for m in msgs],
    }


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
@router.get("/revenue-inbox")
def revenue_inbox(workspace_id: int | None = None, status: str = "pending",
                  ctx: AuthContext = Depends(get_ctx)):
    """Threads where our mailbox was a participant WITH a known Contact, not yet
    attached to a deal. The user attaches each to a deal with one click."""
    ws_ids = ctx.workspace_ids_for_query(workspace_id)
    q = ctx.db.query(RevenueInboxItem).filter(RevenueInboxItem.workspace_id.in_(ws_ids))
    if status:
        q = q.filter(RevenueInboxItem.status == status)
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
        out.append({"id": r.id, "from_email": r.from_email, "subject": r.subject,
                    "preview": (r.body_text or "")[:180], "participants": r.participants or [],
                    "status": r.status, "created_at": r.created_at.isoformat() if r.created_at else None,
                    "contact": {"id": contact.id, "name": f"{contact.first_name} {contact.last_name}".strip(),
                                "email": contact.email} if contact else None,
                    "company": {"id": company.id, "name": company.name} if company else None,
                    "deals": deals})
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

    return {
        "deal": {"id": d.id, "name": d.name, "value": d.value, "company": company.name if company else ""},
        "stage": stage.name if stage else "—",
        "last_contact_days": days,
        "awaiting_us": awaiting_us,
        "intent": intent,
        "risk": risk,
        "ghost": ghost,
        "blueprint": bool(bp), "blueprint_viewed": bool(bp and (bp.view_count or 0) > 0),
        "agreement_status": ag.status if ag else None,
        "invoice_status": inv.status if inv else None,
        "recommendation": rec,
        "next_action": action,
        "conversation_state": conv.state,
    }
