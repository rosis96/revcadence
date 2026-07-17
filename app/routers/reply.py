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
    # Reply-delay parity: schedule the job `reply_delay_seconds` in the future
    # (legacy behavior). The worker only claims jobs whose run_at has passed.
    from datetime import datetime, timedelta
    delay = 0
    rws = db.query(ReplyWorkspace).filter(ReplyWorkspace.name == rws_name).first() if rws_name else None
    if rws and rws.reply_delay_seconds:
        delay = max(0, int(rws.reply_delay_seconds))
    j = Job(kind="process_reply", workspace_id=workspace_id,
            payload={"reply_workspace": rws_name, "platform": platform,
                     "flow": flow, "webhook": payload},
            run_at=datetime.utcnow() + timedelta(seconds=delay))
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
def list_rws(workspace_id: int | None = None, ctx: AuthContext = Depends(require_master)):
    q = ctx.db.query(ReplyWorkspace)
    if workspace_id:
        q = q.filter(ReplyWorkspace.workspace_id == workspace_id)
    return [_rws_out(w) for w in q.order_by(ReplyWorkspace.name).all()]


def _best_reply_space(spaces):
    """Pick the reply space the Setup page should show: the CONFIGURED one, not
    an empty auto-provisioned placeholder. Rank: has an API key > is active >
    has response types > lowest id. This makes imported config appear on refresh
    even though provisioning left an empty placeholder at a lower id."""
    def score(w):
        rf = w.reply_format or {}
        return (
            1 if (w.api_key_enc or "") else 0,
            1 if w.active else 0,
            1 if rf.get("response_types") else 0,
            -w.id,  # tie-break: earliest
        )
    return max(spaces, key=score) if spaces else None


@router.get("/workspaces/for/{workspace_id}")
def reply_space_for(workspace_id: int, ctx: AuthContext = Depends(require_master)):
    """The workspace's primary reply space — the one Setup edits. Returns the
    most-configured space (so imported config shows), auto-provisioning if none."""
    ctx.require_workspace(workspace_id)
    spaces = ctx.db.query(ReplyWorkspace).filter(ReplyWorkspace.workspace_id == workspace_id).all()
    if not spaces:
        from ..provision import provision_workspace
        from ..models.identity import Workspace
        provision_workspace(ctx.db, ctx.db.get(Workspace, workspace_id))
        ctx.db.commit()
        spaces = ctx.db.query(ReplyWorkspace).filter(ReplyWorkspace.workspace_id == workspace_id).all()
    return _rws_out(_best_reply_space(spaces))


@router.get("/workspaces/{rws_id}")
def get_rws(rws_id: int, ctx: AuthContext = Depends(require_master)):
    w = ctx.db.get(ReplyWorkspace, rws_id)
    if not w:
        raise HTTPException(404, "Not found")
    return _rws_out(w)


@router.get("/workspaces/{rws_id}/calendly-probe")
def calendly_probe(rws_id: int, ctx: AuthContext = Depends(require_master)):
    """'Check Calendly availability' — shows what the system reads and would
    propose (event type + sample real slots), or the exact error."""
    from ..reply.calendly import probe
    w = ctx.db.get(ReplyWorkspace, rws_id)
    if not w:
        raise HTTPException(404, "Not found")
    ctx.require_workspace(w.workspace_id)
    return probe(w)


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
def reply_leads(status: str = "", q: str = "", page: int = 1, workspace_id: int | None = None,
                ctx: AuthContext = Depends(get_ctx)):
    # Honor the workspace selector: a specific workspace shows ONLY its leads.
    # "All workspaces" (workspace_id omitted) shows the master rollup + Unrouted.
    ws_ids = ctx.workspace_ids_for_query(workspace_id)
    show_unrouted = ctx.is_master and workspace_id is None
    base = ctx.db.query(ReplyLead).filter(
        (ReplyLead.workspace_id.in_(ws_ids)) |
        (ReplyLead.workspace_id.is_(None) if show_unrouted else False))
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
        "draft": base.filter(ReplyLead.main_reply != "", ReplyLead.replied == False,  # noqa: E712
                             ReplyLead.action != "stop").count(),
    }
    q2 = base
    if status == "draft":
        q2 = base.filter(ReplyLead.main_reply != "", ReplyLead.replied == False,  # noqa: E712
                         ReplyLead.action != "stop")
    elif status == "needs_review":
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


@router.get("/processing")
def reply_processing(workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    """Live view of the reply pipeline: every inbound webhook becomes a
    `process_reply` job that is held for the reply-delay, then run. This shows
    the queue (scheduled → running → done/failed) with countdowns, so you can
    see WHETHER webhooks are arriving and WHAT happened to each — the answer to
    'I replied but nothing showed up yet'."""
    from datetime import datetime, timedelta
    from ..models.jobs import Job, Heartbeat

    now = datetime.utcnow()
    ws_ids = ctx.workspace_ids_for_query(workspace_id)
    show_unrouted = ctx.is_master and workspace_id is None
    base = ctx.db.query(Job).filter(Job.kind == "process_reply").filter(
        (Job.workspace_id.in_(ws_ids)) |
        (Job.workspace_id.is_(None) if show_unrouted else False))

    day_ago = now - timedelta(hours=24)
    recent = base.filter(Job.created_at >= day_ago)
    summary = {
        "last_24h": recent.count(),
        "scheduled": base.filter(Job.status == "pending", Job.run_at > now).count(),
        "due_now": base.filter(Job.status == "pending", Job.run_at <= now).count(),
        "running": base.filter(Job.status == "running").count(),
        "done_24h": recent.filter(Job.status == "done").count(),
        "failed": base.filter(Job.status == "failed").count(),
    }
    # worker liveness — if the worker is down, nothing in the queue moves
    hb = ctx.db.get(Heartbeat, "worker")
    worker_alive = bool(hb and hb.at and (now - hb.at).total_seconds() < 120)

    def _email(p):
        d = (p or {}).get("webhook") or {}
        d = d.get("data") or d
        lo = d.get("lead") or d
        return str(lo.get("email") or lo.get("lead_email") or "").lower()

    # Keep the live view clean: show only what's still in flight (pending/running)
    # plus jobs that finished in the last 2 hours. Anything done/failed older than
    # that drops off — the queue isn't a permanent log (Activity/audit is).
    from sqlalchemy import and_, or_
    cutoff = now - timedelta(hours=2)
    rows = (base.filter(or_(
                Job.status.in_(["pending", "running"]),
                and_(Job.status.in_(["done", "failed"]),
                     Job.finished_at.isnot(None), Job.finished_at >= cutoff)))
            .order_by(Job.id.desc()).limit(60).all())
    jobs = []
    for j in rows:
        p = j.payload or {}
        secs = int((j.run_at - now).total_seconds()) if (j.status == "pending" and j.run_at) else 0
        jobs.append({
            "id": j.id, "status": j.status,
            "routed_to": p.get("reply_workspace") or "Unrouted",
            "platform": p.get("platform"), "flow": p.get("flow", "reply"),
            "email": _email(p),
            "seconds_until_run": max(0, secs),
            "note": j.progress_note or "",
            "error": (j.error or "")[:300],
            "result": {k: v for k, v in (j.result or {}).items()} if j.result else {},
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "finished_at": j.finished_at.isoformat() if j.finished_at else None,
        })
    return {"summary": summary, "worker_alive": worker_alive, "jobs": jobs}


@router.get("/leads/{lead_id}")
def reply_lead_detail(lead_id: int, ctx: AuthContext = Depends(get_ctx)):
    l = ctx.db.get(ReplyLead, lead_id)
    if not l or (l.workspace_id is not None and l.workspace_id not in ctx.allowed_workspace_ids()):
        raise HTTPException(404, "Not found")
    from ..reply.sync import extract_lead_enrichment
    return {"id": l.id, "name": l.name, "email": l.email, "company": l.company,
            "workspace": l.reply_workspace, "platform": l.platform, "intent": l.intent,
            "confidence": l.confidence, "action": l.action, "stage": l.stage,
            "replied": l.replied, "reviewed": l.reviewed, "reply_text": l.reply_text,
            "main_reply": l.main_reply, "followups": l.followups or [],
            "thread": l.thread or [], "send_meta_present": bool(l.send_meta),
            "can_send_instantly": bool((l.send_meta or {}).get("reply_to_uuid") and (l.send_meta or {}).get("eaccount")),
            "send_error": l.send_error or "",
            "lead_details": extract_lead_enrichment(l.lead_data or {})}


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
        from ..reply.sync import STOP_LABELS, sync_reply_stage_to_deal
        l.stage = body.stage
        # "stop" outcomes (out of office / wrong person / unsubscribe) don't move
        # the pipeline — they just halt the lead.
        if body.stage in STOP_LABELS:
            l.action = "stop"
        else:
            # reply → CRM: move the matching deal to the mapped stage. Two-way with
            # the CRM board's stage-change sync.
            try:
                sync_reply_stage_to_deal(ctx.db, l)
            except Exception:
                pass
    if body.reviewed is not None:
        l.reviewed = body.reviewed
    if body.action is not None:
        l.action = body.action
    l.updated_at = datetime.utcnow()
    ctx.db.commit()
    return {"ok": True}


class LeadEdit(BaseModel):
    """Edit the details the webhook captured (and sync them to the CRM)."""
    name: str | None = None
    email: str | None = None
    company: str | None = None
    title: str | None = None
    location: str | None = None
    website: str | None = None
    contact_linkedin: str | None = None
    company_linkedin: str | None = None


@router.put("/leads/{lead_id}")
def edit_reply_lead(lead_id: int, body: LeadEdit, ctx: AuthContext = Depends(get_ctx)):
    """Edit the lead's captured details, then push the changes to the matching CRM
    contact/company so both stay in sync."""
    from ..reply.sync import extract_lead_enrichment
    l = ctx.db.get(ReplyLead, lead_id)
    if not l or (l.workspace_id is not None and l.workspace_id not in ctx.allowed_workspace_ids()):
        raise HTTPException(404, "Not found")
    patch = body.model_dump(exclude_unset=True)
    if "name" in patch:
        l.name = patch["name"]
    if "email" in patch:
        l.email = (patch["email"] or "").strip()
    if "company" in patch:
        l.company = patch["company"]
    # merge the rich fields into lead_data so extract_lead_enrichment reflects them
    ld = dict(l.lead_data or {})
    for k in ("title", "location", "website", "contact_linkedin", "company_linkedin"):
        if k in patch:
            ld[k] = patch[k]
    l.lead_data = ld
    l.updated_at = datetime.utcnow()
    # sync to CRM contact/company (best-effort)
    synced = {}
    if l.workspace_id:
        try:
            from ..models.crm import Company, Contact
            email = (l.email or "").lower().strip()
            contact = (ctx.db.query(Contact).filter(Contact.workspace_id == l.workspace_id,
                       Contact.email.ilike(email)).first()) if email else None
            if contact:
                if "name" in patch:
                    first, _, last = (l.name or "").partition(" ")
                    contact.first_name, contact.last_name = first, last
                if patch.get("title"):
                    contact.title = patch["title"]
                if patch.get("location"):
                    contact.location = patch["location"]
                if patch.get("contact_linkedin"):
                    contact.linkedin_url = patch["contact_linkedin"]
                if contact.company_id and (patch.get("website") or patch.get("company")):
                    co = ctx.db.get(Company, contact.company_id)
                    if co:
                        if patch.get("company"):
                            co.name = patch["company"]
                        if patch.get("website"):
                            co.website = patch["website"]
                synced = {"contact_id": contact.id}
        except Exception:
            pass
    ctx.db.commit()
    return {"ok": True, "synced": synced,
            "lead_details": extract_lead_enrichment(l.lead_data or {})}


@router.delete("/leads/{lead_id}")
def delete_reply_lead(lead_id: int, block: bool = False, ctx: AuthContext = Depends(get_ctx)):
    """Delete a reply lead. With ?block=true, also add the sender's email to the
    workspace blocklist so future replies from them are auto-stopped."""
    from ..models.reply import ReplyBlock
    l = ctx.db.get(ReplyLead, lead_id)
    if not l or (l.workspace_id is not None and l.workspace_id not in ctx.allowed_workspace_ids()):
        raise HTTPException(404, "Not found")
    blocked = False
    email = (l.email or "").lower().strip()
    if block and email and l.workspace_id:
        exists = (ctx.db.query(ReplyBlock)
                  .filter(ReplyBlock.workspace_id == l.workspace_id, ReplyBlock.email.ilike(email)).first())
        if not exists:
            ctx.db.add(ReplyBlock(workspace_id=l.workspace_id, email=email, reason="blocked from inbox"))
        blocked = True
    ctx.db.delete(l)
    ctx.db.commit()
    return {"ok": True, "blocked": blocked, "email": email}


@router.get("/blocklist")
def list_blocklist(workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    from ..models.reply import ReplyBlock
    ws_ids = ctx.workspace_ids_for_query(workspace_id)
    rows = ctx.db.query(ReplyBlock).filter(ReplyBlock.workspace_id.in_(ws_ids)).order_by(ReplyBlock.id.desc()).all()
    return [{"id": b.id, "email": b.email, "reason": b.reason,
             "at": b.created_at.isoformat() if b.created_at else None} for b in rows]


# ================================================================ test thread (zero side effects)
class TestThreadIn(BaseModel):
    reply_workspace_id: int
    thread: str


@router.post("/test-thread")
def test_thread(body: TestThreadIn, ctx: AuthContext = Depends(require_master)):
    """Paste a thread → run the exact engine (profile, format, rules, provider)
    → return the decision + drafted reply + follow-ups. NOTHING is sent, saved,
    or reserved. Detects the model-didn't-run fallback."""
    from ..reply import engine as E
    w = ctx.db.get(ReplyWorkspace, body.reply_workspace_id)
    if not w:
        raise HTTPException(404, "Reply workspace not found")
    ctx.require_workspace(w.workspace_id)
    thread = [{"direction": "in", "text": body.thread.strip()}]
    # Same engine path production uses (generate_reply), so the drafted reply,
    # follow-ups, intent and decision here match what the live pipeline produces.
    # Scheduling context is omitted (no real slot reservation in a dry run).
    gen = E.generate_reply(w, thread, prospect={"first_name": ""})
    reply = E.add_signature(gen["main_reply"], w.sender_name, w.website) if gen["main_reply"] else ""
    return {
        "intent": gen["intent"], "confidence": gen["confidence"],
        "decision": gen["action"], "would_auto_send": gen["action"] == "send" and E.auto_send_enabled(),
        "model_ran": gen["model_ran"],
        "reply": reply,
        "followups": gen["followups"],
    }


# ================================================================ global reply settings
SETTING_KEYS = [
    ("openai_api_key", True), ("gemini_api_key", True), ("openai_model", False),
    ("gemini_model", False), ("review_webhook_url", False), ("default_bison_base_url", False),
    ("reply_delay_seconds", False), ("reply_trigger_tag", False), ("followup_trigger_tag", False),
]


@router.get("/settings")
def get_settings(ctx: AuthContext = Depends(require_master)):
    from ..models.settings import AppSetting
    rows = {s.key: s for s in ctx.db.query(AppSetting).all()}
    out = {}
    for key, secret in SETTING_KEYS:
        s = rows.get(f"reply.{key}")
        if secret:
            out[key] = ""
            out[f"{key}_set"] = bool(s and s.value)
        else:
            out[key] = decrypt(s.value) if s else ""
    return out


@router.put("/settings")
def put_settings(body: dict, ctx: AuthContext = Depends(require_master)):
    from ..models.settings import AppSetting
    for key, secret in SETTING_KEYS:
        if key not in body:
            continue
        val = str(body[key])
        if secret and val == "":
            continue  # blank = keep existing secret
        row = ctx.db.get(AppSetting, f"reply.{key}")
        if row is None:
            row = AppSetting(key=f"reply.{key}", is_secret=1 if secret else 0)
            ctx.db.add(row)
        row.value = encrypt(val) if secret else val
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
    # Backfill send_meta from the lead record — leads created before send_meta
    # carried lead_email/campaign_id would otherwise skip the reply-target lookup
    # entirely (the lead always has .email and its raw payload).
    from ..reply.sync import _deep_get
    ld = l.lead_data or {}
    meta = {**(l.send_meta or {})}
    meta.setdefault("lead_email", l.email)
    meta.setdefault("to_name", l.name)
    meta.setdefault("to_email", l.email)
    meta.setdefault("subject", l.subject)
    meta.setdefault("reply_text_new", l.reply_text or "")
    if not meta.get("campaign_id"):
        meta["campaign_id"] = str(_deep_get(ld, {"campaign_id"}) or "")
    try:
        if l.platform == "bison":
            send_bison_reply(rws, meta, message)
        else:
            send_instantly_reply(rws, meta, message, l.subject)
    except Exception as e:
        # 400 (not 502) so the client reliably shows this JSON detail instead of a
        # bare gateway error; record it on the lead so the reason is visible later.
        l.action = "error"
        l.send_error = str(e)[:500]
        ctx.db.commit()
        raise HTTPException(400, f"Send failed: {e}")
    l.replied = True
    l.reviewed = True
    l.stage = "replied"
    l.send_error = ""
    ctx.db.commit()
    return {"ok": True, "sent_via": l.platform}
