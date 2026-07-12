"""Reply Management API: webhooks (public), workspace config, review console.
Webhooks only record + enqueue; the worker job does the engine run."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func

from ..auth import AuthContext, get_ctx, require_master
from ..crypto import decrypt, encrypt
from ..models.jobs import Job
from ..models.reply import ReplyLead, ReplyWorkspace

router = APIRouter(prefix="/api/reply", tags=["reply-management"])


# ================================================================ webhooks (no auth — platform-called)
def _enqueue(db, rws_name: str, workspace_id, platform: str, payload: dict, flow: str):
    j = Job(kind="process_reply", workspace_id=workspace_id,
            payload={"reply_workspace": rws_name, "platform": platform,
                     "flow": flow, "webhook": payload})
    db.add(j)
    db.commit()
    return j.id


@router.post("/webhooks/bison")
async def bison_webhook(request: Request, reply_workspace: str = "", fup_workspace: str = ""):
    """Combined reply+followup webhook (legacy: one webhook avoids double-sends).
    TAG_ATTACHED routes by trigger tag; other events need a findable lead id."""
    from ..db import SessionLocal
    from ..reply.engine import deep_find_lead_id
    payload = await request.json()
    event = str(payload.get("event") or payload.get("type") or "").upper()
    db = SessionLocal()
    try:
        tag = str((payload.get("data") or {}).get("tag_name", "")).lower()
        if event == "TAG_ATTACHED" and tag:
            target = fup_workspace if "follow" in tag else reply_workspace
            flow = "followup" if "follow" in tag else "reply"
        else:
            target, flow = reply_workspace, "reply"
        if not deep_find_lead_id(payload):
            return {"ok": True, "skipped": "no lead id in payload"}
        rws = db.query(ReplyWorkspace).filter(ReplyWorkspace.name == target,
                                              ReplyWorkspace.active == True).first()  # noqa: E712
        job_id = _enqueue(db, rws.name if rws else (target or "Unrouted"),
                          rws.workspace_id if rws else None, "bison", payload, flow)
        return {"ok": True, "job_id": job_id}
    finally:
        db.close()


@router.post("/webhooks/instantly")
async def instantly_webhook(request: Request, workspace_name: str = ""):
    """Routing order (legacy workspace-isolation fix): explicit ?workspace_name
    → payload workspace_name → single active Instantly workspace → 'Unrouted'.
    NEVER attribute unmatched leads to another workspace."""
    from ..db import SessionLocal
    payload = await request.json()
    db = SessionLocal()
    try:
        name = workspace_name or str(payload.get("workspace_name", ""))
        rws = None
        if name:
            rws = db.query(ReplyWorkspace).filter(ReplyWorkspace.name == name,
                                                  ReplyWorkspace.active == True).first()  # noqa: E712
        if rws is None:
            actives = (db.query(ReplyWorkspace)
                       .filter(ReplyWorkspace.platform == "instantly",
                               ReplyWorkspace.active == True).all())  # noqa: E712
            if len(actives) == 1:
                rws = actives[0]
        job_id = _enqueue(db, rws.name if rws else "Unrouted",
                          rws.workspace_id if rws else None, "instantly", payload, "reply")
        return {"ok": True, "job_id": job_id, "routed_to": rws.name if rws else "Unrouted"}
    finally:
        db.close()


# ================================================================ workspaces (master only)
class RWorkspaceIn(BaseModel):
    workspace_id: int
    name: str
    platform: str = "bison"
    mode: str = "reply"
    active: bool = True
    api_key: str | None = None
    base_url: str = ""
    reply_followup_campaign_id: str = ""
    website: str = ""
    sender_name: str = ""
    default_sender_email: str = ""
    calendly_token: str | None = None
    calendly_scheduling_url: str = ""
    ai_provider: str = "openai"
    ai_fallback: bool = False
    openai_key: str | None = None
    gemini_key: str | None = None
    client_profile: dict = {}
    reply_format: dict = {}
    ai_rules: str = ""
    reply_delay_seconds: int = 420


def _rws_out(w: ReplyWorkspace, reveal: bool = False):
    return {"id": w.id, "workspace_id": w.workspace_id, "name": w.name, "platform": w.platform,
            "mode": w.mode, "active": w.active, "base_url": w.base_url,
            "reply_followup_campaign_id": w.reply_followup_campaign_id,
            "website": w.website, "sender_name": w.sender_name,
            "default_sender_email": w.default_sender_email,
            "calendly_scheduling_url": w.calendly_scheduling_url,
            "ai_provider": w.ai_provider, "ai_fallback": w.ai_fallback,
            "client_profile": w.client_profile or {}, "reply_format": w.reply_format or {},
            "ai_rules": w.ai_rules or "", "reply_delay_seconds": w.reply_delay_seconds,
            "api_key_set": bool(w.api_key_enc), "calendly_token_set": bool(w.calendly_token_enc),
            "openai_key_set": bool(w.openai_key_enc), "gemini_key_set": bool(w.gemini_key_enc)}


@router.get("/workspaces")
def list_rws(ctx: AuthContext = Depends(require_master)):
    rows = ctx.db.query(ReplyWorkspace).order_by(ReplyWorkspace.name).all()
    return [_rws_out(w) for w in rows]


@router.post("/workspaces")
def create_rws(body: RWorkspaceIn, ctx: AuthContext = Depends(require_master)):
    ctx.require_workspace(body.workspace_id)
    if ctx.db.query(ReplyWorkspace).filter(ReplyWorkspace.name == body.name).first():
        raise HTTPException(409, "Reply-workspace name already exists")
    w = ReplyWorkspace(workspace_id=body.workspace_id, name=body.name)
    _apply(w, body)
    ctx.db.add(w)
    ctx.db.commit()
    return _rws_out(w)


@router.put("/workspaces/{rws_id}")
def update_rws(rws_id: int, body: RWorkspaceIn, ctx: AuthContext = Depends(require_master)):
    w = ctx.db.get(ReplyWorkspace, rws_id)
    if not w:
        raise HTTPException(404, "Not found")
    _apply(w, body)
    ctx.db.commit()
    return _rws_out(w)


def _apply(w: ReplyWorkspace, body: RWorkspaceIn):
    for f in ("name", "platform", "mode", "active", "base_url", "reply_followup_campaign_id",
              "website", "sender_name", "default_sender_email", "calendly_scheduling_url",
              "ai_provider", "ai_fallback", "client_profile", "reply_format", "ai_rules",
              "reply_delay_seconds", "workspace_id"):
        setattr(w, f, getattr(body, f))
    # secrets: None = keep existing; "" = clear; value = encrypt
    for plain, enc in (("api_key", "api_key_enc"), ("calendly_token", "calendly_token_enc"),
                       ("openai_key", "openai_key_enc"), ("gemini_key", "gemini_key_enc")):
        v = getattr(body, plain)
        if v is not None:
            setattr(w, enc, encrypt(v) if v else "")


@router.post("/workspaces/{rws_id}/duplicate")
def duplicate_rws(rws_id: int, ctx: AuthContext = Depends(require_master)):
    """Legacy duplicate-workspace: copies every config column, auto-numbers name."""
    w = ctx.db.get(ReplyWorkspace, rws_id)
    if not w:
        raise HTTPException(404, "Not found")
    base = w.name
    n = 2
    while ctx.db.query(ReplyWorkspace).filter(ReplyWorkspace.name == f"{base} ({n})").first():
        n += 1
    copy = ReplyWorkspace(**{c.name: getattr(w, c.name) for c in ReplyWorkspace.__table__.columns
                             if c.name not in ("id", "name", "created_at", "updated_at")},
                          name=f"{base} ({n})")
    ctx.db.add(copy)
    ctx.db.commit()
    return _rws_out(copy)


# ================================================================ leads console
@router.get("/leads")
def reply_leads(status: str = "", q: str = "", page: int = 1, ctx: AuthContext = Depends(get_ctx)):
    ws_ids = ctx.allowed_workspace_ids()
    base = ctx.db.query(ReplyLead).filter(
        (ReplyLead.workspace_id.in_(ws_ids)) |
        (ReplyLead.workspace_id.is_(None) if ctx.is_master else False))
    if q:
        like = f"%{q}%"
        base = base.filter((ReplyLead.email.ilike(like)) | (ReplyLead.name.ilike(like))
                           | (ReplyLead.company.ilike(like)))
    counts = {
        "all": base.count(),
        "needs_review": base.filter(ReplyLead.action.in_(["skip_enrich", "would_send"]),
                                    ReplyLead.reviewed == False).count(),  # noqa: E712
        "replied": base.filter(ReplyLead.replied == True).count(),          # noqa: E712
        "booked": base.filter(ReplyLead.stage == "booked").count(),
        "stopped": base.filter(ReplyLead.action == "stop").count(),
    }
    q2 = base
    if status == "needs_review":
        q2 = base.filter(ReplyLead.action.in_(["skip_enrich", "would_send"]),
                         ReplyLead.reviewed == False)  # noqa: E712
    elif status == "replied":
        q2 = base.filter(ReplyLead.replied == True)   # noqa: E712
    elif status == "booked":
        q2 = base.filter(ReplyLead.stage == "booked")
    elif status == "stopped":
        q2 = base.filter(ReplyLead.action == "stop")
    rows = q2.order_by(ReplyLead.id.desc()).offset((max(page, 1) - 1) * 50).limit(50).all()
    return {"counts": counts, "leads": [{
        "id": l.id, "name": l.name, "email": l.email, "company": l.company,
        "workspace": l.reply_workspace, "platform": l.platform, "intent": l.intent,
        "confidence": l.confidence, "action": l.action, "stage": l.stage,
        "replied": l.replied, "reviewed": l.reviewed,
        "reply_text": (l.reply_text or "")[:200],
        "at": l.created_at.isoformat() if l.created_at else None} for l in rows]}


@router.get("/leads/{lead_id}")
def reply_lead_detail(lead_id: int, ctx: AuthContext = Depends(get_ctx)):
    l = ctx.db.get(ReplyLead, lead_id)
    if not l or (l.workspace_id is not None and l.workspace_id not in ctx.allowed_workspace_ids()):
        raise HTTPException(404, "Not found")
    return {"id": l.id, "name": l.name, "email": l.email, "company": l.company,
            "workspace": l.reply_workspace, "platform": l.platform, "intent": l.intent,
            "confidence": l.confidence, "action": l.action, "stage": l.stage,
            "replied": l.replied, "reviewed": l.reviewed, "reply_text": l.reply_text,
            "main_reply": l.main_reply, "followups": l.followups or [],
            "thread": l.thread or [], "send_meta_present": bool(l.send_meta)}


class LeadAction(BaseModel):
    main_reply: str | None = None   # save edited draft
    stage: str | None = None
    reviewed: bool | None = None
    action: str | None = None       # e.g. force 'stop'


@router.post("/leads/{lead_id}/action")
def reply_lead_action(lead_id: int, body: LeadAction, ctx: AuthContext = Depends(get_ctx)):
    l = ctx.db.get(ReplyLead, lead_id)
    if not l or (l.workspace_id is not None and l.workspace_id not in ctx.allowed_workspace_ids()):
        raise HTTPException(404, "Not found")
    if body.main_reply is not None:
        l.main_reply = body.main_reply
    if body.stage is not None:
        l.stage = body.stage
    if body.reviewed is not None:
        l.reviewed = body.reviewed
    if body.action is not None:
        l.action = body.action
    l.updated_at = datetime.utcnow()
    ctx.db.commit()
    return {"ok": True}


@router.post("/leads/{lead_id}/send")
def approve_and_send(lead_id: int, ctx: AuthContext = Depends(get_ctx)):
    """Approve & Send — live send via the correct platform (legacy drawer action)."""
    from ..reply.engine import add_signature, send_bison_reply, send_instantly_reply
    l = ctx.db.get(ReplyLead, lead_id)
    if not l or (l.workspace_id is not None and l.workspace_id not in ctx.allowed_workspace_ids()):
        raise HTTPException(404, "Not found")
    if not l.main_reply:
        raise HTTPException(422, "No draft to send")
    if l.replied:
        raise HTTPException(409, "Already sent")
    rws = ctx.db.query(ReplyWorkspace).filter(ReplyWorkspace.name == l.reply_workspace).first()
    if not rws:
        raise HTTPException(422, "Reply-workspace config not found")
    message = add_signature(l.main_reply, rws.sender_name, rws.website)
    try:
        if l.platform == "bison":
            send_bison_reply(rws, l.send_meta or {}, message)
        else:
            send_instantly_reply(rws, l.send_meta or {}, message, l.subject)
    except Exception as e:
        raise HTTPException(502, f"Send failed: {e}")
    l.replied = True
    l.reviewed = True
    l.stage = "replied"
    ctx.db.commit()
    return {"ok": True, "sent_via": l.platform}
