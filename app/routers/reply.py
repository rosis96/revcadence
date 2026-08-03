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

# Clean, human intent buckets (5–7) over the engine's granular intent labels.
# Order matters: most specific first (a "not interested" reply also contains
# "interest"). Used for filtering, display, and export.
INTENT_BUCKETS = [
    ("Not interested", ("not interested", "no thanks", "no thank", "decline", "unsubscribe",
                        "stop", "remove", "opt out", "opt-out", "do not")),
    ("Out of office", ("out of office", "ooo", "vacation", "away", "on leave", "auto")),
    ("Referral / wrong contact", ("referral", "refer", "wrong person", "wrong contact",
                                  "someone else", "forward", "colleague", "not the right")),
    ("Price-based interest", ("pric", "cost", "budget", "quote", "ballpark", "rate", "fee", "how much")),
    ("Wants a call/meeting", ("call", "meeting", "book", "schedul", "demo", "zoom", "calendar", "chat")),
    ("Not ready / skeptical", ("skeptic", "later", "not now", "busy", "timing", "conditional",
                               "complex", "hesitant", "unsure", "maybe")),
    ("Basic interest", ("positive", "interest", "more info", "share", "tell me", "learn more",
                        "yes", "simple", "keen", "curious")),
]


def intent_bucket(intent: str) -> str:
    s = (intent or "").lower().replace("_", " ").strip()
    if not s:
        return "Needs review"
    for label, keys in INTENT_BUCKETS:
        if any(k in s for k in keys):
            return label
    return "Other"


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
async def instantly_webhook(request: Request, workspace_name: str = "", flow: str = "reply"):
    """Routing order (legacy workspace-isolation fix): explicit ?workspace_name
    → payload workspace_name → single active Instantly workspace → 'Unrouted'.
    NEVER attribute unmatched leads to another workspace.

    ?flow=followup runs the follow-up-only path (write {{followup_1}}… onto the
    lead, never send a reply) for leads that missed their follow-ups. The space's
    mode='followup' forces this too, so either trigger works."""
    from ..db import SessionLocal
    payload = await request.json()
    flow = flow if flow in ("reply", "followup") else "reply"
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
                          rws.workspace_id if rws else None, "instantly", payload, flow)
        return {"ok": True, "job_id": job_id, "routed_to": rws.name if rws else "Unrouted", "flow": flow}
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


class BuildReplyFormatsIn(BaseModel):
    instructions: str = ""        # the operator's reply rules / sample reply formats
    followups: bool = True        # also design the FUP1..6 follow-up ladder


@router.post("/workspaces/{rws_id}/build-reply-formats")
def build_reply_formats(rws_id: int, body: BuildReplyFormatsIn, ctx: AuthContext = Depends(require_master)):
    """Design the reply-management formats (response_types + follow-up ladder) with
    AI — the same idea as the outbound Formats builder, grounded in the SAME Client
    Brain. Describe how each reply type should be written; it builds the structured
    response_types and FUP1..6 for you to review and Save."""
    import json as _json

    from ..enrichment import ai
    from ..models.enrich import EnrichConfig
    w = ctx.db.get(ReplyWorkspace, rws_id)
    if not w:
        raise HTTPException(404, "Not found")
    ctx.require_workspace(w.workspace_id)
    if not ai.has_ai():
        raise HTTPException(422, "No OpenAI key set — connect AI before building reply formats.")
    ecfg = ctx.db.query(EnrichConfig).filter(EnrichConfig.workspace_id == w.workspace_id).first()
    brain = (ecfg.profile if ecfg else None) or {}
    # merge the reply workspace's own profile over the shared brain (same as the engine)
    merged = {**brain, **(w.client_profile or {})}

    system = (
        "You design the REPLY FORMATS an AI reply-writer uses to answer inbound prospect replies for THIS "
        "client, grounded in the CLIENT BRAIN + OPERATOR INSTRUCTIONS. Two rules of CARE:\n"
        "1) BE FAITHFUL to what the operator actually described — build the response types and rules THEY "
        "explain. If they give none, propose a sensible default set (e.g. positive/interested, asks-for-"
        "pricing, asks-a-question, not-now/later, not-interested, referral/forward).\n"
        "2) MATCH DEPTH per type to how much the operator explained it. Where they gave structure, rules, or "
        "examples, reflect them fully; where they said little, keep that type light — short guidance, no "
        "invented rigid template, no fabricated rules or examples. Only mark auto_send:true for a type the "
        "operator clearly said may send automatically; otherwise false (human review).\n"
        "Return JSON {\"response_types\": [ {\"id\": snake_case slug, \"intent\": str (when this type "
        "applies), \"examples\": [str], \"template\": str (optional; {{placeholders}} or \"\"), \"rules\": "
        "str (one rule per line, or \"\"), \"auto_send\": bool} ]"
        + (", \"followups\": [ {\"label\": \"FUP 1\", \"intent\": str (what this nudge does), \"max_words\": "
           "int|null, \"template\": str} ]" if body.followups else "")
        + " }. Ground everything ONLY in the CLIENT BRAIN + operator instructions; never invent client facts.")
    user = ("OPERATOR INSTRUCTIONS / REPLY RULES / SAMPLE FORMATS:\n"
            + (body.instructions or "(none — use best practice)")
            + "\n\nCLIENT BRAIN + PROFILE:\n" + _json.dumps(merged)[:14000])
    try:
        out = ai._call_openai(system, user, model=ai.extract_model())
    except Exception as e:
        raise HTTPException(502, f"AI reply-format design failed: {str(e)[:200]}")
    rtypes = out.get("response_types") if isinstance(out, dict) else None
    if not isinstance(rtypes, list) or not rtypes:
        raise HTTPException(502, "AI didn't return reply formats — try again with clearer instructions.")

    import re as _re

    def _slug(s, i):
        s = _re.sub(r"[^a-z0-9]+", "_", str(s or "").lower()).strip("_")
        return s or f"type_{i + 1}"
    clean_types = []
    for i, t in enumerate(rtypes):
        if not isinstance(t, dict):
            continue
        rules = t.get("rules")
        if isinstance(rules, list):
            rules = "\n".join(str(r) for r in rules if r)
        clean_types.append({
            "id": _slug(t.get("id") or t.get("intent"), i),
            "intent": str(t.get("intent") or ""),
            "examples": [str(e) for e in (t.get("examples") or []) if e],
            "template": str(t.get("template") or ""),
            "rules": str(rules or ""),
            "auto_send": t.get("auto_send", False) is True,
        })
    clean_fups = []
    if body.followups:
        fups = out.get("followups") if isinstance(out, dict) else None
        for i, f in enumerate(fups or []):
            if not isinstance(f, dict):
                continue
            clean_fups.append({
                "label": str(f.get("label") or f"FUP {i + 1}"),
                "intent": str(f.get("intent") or ""),
                "max_words": int(f.get("max_words") or 0) or 100,
                "template": str(f.get("template") or ""),
            })
    return {"reply_format": {"response_types": clean_types, "followups": clean_fups},
            "count": len(clean_types), "followup_count": len(clean_fups)}


# ================================================================ leads console
# Hot-first ordering for the unified inbox: booked meetings and engaged/interested
# replies float to the top; dead leads sink. This is what makes a client land on
# money, not noise.
_HOT_TIER = {
    "Wants a call/meeting": 40, "Price-based interest": 32, "Basic interest": 30,
    "Referral / wrong contact": 20, "Not ready / skeptical": 18,
    "Out of office": 6, "Not interested": 2,
}


@router.get("/leads")
def reply_leads(status: str = "", q: str = "", page: int = 1, workspace_id: int | None = None,
                sort: str = "", ctx: AuthContext = Depends(get_ctx)):
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
    BOOKED_STAGES = ["booked", "meeting_completed", "won"]
    # "Interested / not booked" = we replied, prospect is engaged, but NO meeting yet.
    interested = base.filter(ReplyLead.replied == True,                       # noqa: E712
                             ReplyLead.stage.notin_(BOOKED_STAGES + ["lost"]),
                             ReplyLead.action != "stop")
    counts = {
        "all": base.count(),
        "needs_review": base.filter(ReplyLead.action.in_(["skip_enrich", "would_send"]),
                                    ReplyLead.reviewed == False).count(),  # noqa: E712
        "replied": interested.count(),
        "booked": base.filter(ReplyLead.stage.in_(BOOKED_STAGES)).count(),
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
    elif status in ("replied", "interested"):
        q2 = interested                                # interested but NOT booked
    elif status == "booked":
        q2 = base.filter(ReplyLead.stage.in_(BOOKED_STAGES))
    elif status == "stopped":
        q2 = base.filter(ReplyLead.action == "stop")
    if sort == "priority":
        # Hottest first: booked > engaged/interested > everything else, then recency.
        from sqlalchemy import case, desc
        tier = case(
            (ReplyLead.stage.in_(BOOKED_STAGES), 60),
            (ReplyLead.action == "stop", 0),
            (ReplyLead.intent_bucket == "Wants a call/meeting", _HOT_TIER["Wants a call/meeting"]),
            (ReplyLead.intent_bucket == "Price-based interest", _HOT_TIER["Price-based interest"]),
            (ReplyLead.intent_bucket == "Basic interest", _HOT_TIER["Basic interest"]),
            (ReplyLead.replied == True, 28),  # noqa: E712  we replied → engaged
            (ReplyLead.intent_bucket == "Referral / wrong contact", _HOT_TIER["Referral / wrong contact"]),
            (ReplyLead.intent_bucket == "Not ready / skeptical", _HOT_TIER["Not ready / skeptical"]),
            (ReplyLead.intent_bucket == "Out of office", _HOT_TIER["Out of office"]),
            (ReplyLead.intent_bucket == "Not interested", _HOT_TIER["Not interested"]),
            else_=10,
        )
        q2 = q2.order_by(desc(tier), ReplyLead.updated_at.desc(), ReplyLead.id.desc())
    else:
        q2 = q2.order_by(ReplyLead.id.desc())
    rows = q2.offset((max(page, 1) - 1) * 50).limit(50).all()

    from ..reply.sync import _deep_get

    def _website(l):
        return str(_deep_get(l.lead_data or {}, {"website", "company_website", "domain", "url"}) or "")

    return {"counts": counts, "leads": [{
        "id": l.id, "name": l.name, "email": l.email, "company": l.company,
        "website": _website(l), "workspace": l.reply_workspace, "platform": l.platform,
        "campaign": l.campaign or "",
        "intent": l.intent, "intent_bucket": l.intent_bucket or intent_bucket(l.intent),
        "intent_reason": l.intent_reason or "",
        "confidence": l.confidence, "action": l.action, "stage": l.stage,
        "replied": l.replied, "reviewed": l.reviewed,
        "reply_text": (l.reply_text or "")[:200],
        "at": l.created_at.isoformat() if l.created_at else None} for l in rows]}


class ClassifyIn(BaseModel):
    lead_ids: list[int] = []
    status: str = ""
    q: str = ""
    workspace_id: int | None = None


@router.post("/classify-intents")
def classify_intents(body: ClassifyIn, ctx: AuthContext = Depends(get_ctx)):
    """AI-read the whole conversation and bucket each lead. Runs as a background
    job over the selected leads (or the current filter). Returns the job id."""
    ws_ids = ctx.workspace_ids_for_query(body.workspace_id)
    show_unrouted = ctx.is_master and body.workspace_id is None
    base = ctx.db.query(ReplyLead).filter(
        (ReplyLead.workspace_id.in_(ws_ids)) |
        (ReplyLead.workspace_id.is_(None) if show_unrouted else False))
    if body.lead_ids:
        base = base.filter(ReplyLead.id.in_([int(i) for i in body.lead_ids]))
    else:
        if body.q:
            like = f"%{body.q}%"
            base = base.filter((ReplyLead.email.ilike(like)) | (ReplyLead.name.ilike(like))
                               | (ReplyLead.company.ilike(like)))
        BOOKED_STAGES = ["booked", "meeting_completed", "won"]
        if body.status == "needs_review":
            base = base.filter(ReplyLead.action.in_(["skip_enrich", "would_send"]), ReplyLead.reviewed == False)  # noqa: E712
        elif body.status in ("replied", "interested"):
            base = base.filter(ReplyLead.replied == True, ReplyLead.stage.notin_(BOOKED_STAGES + ["lost"]), ReplyLead.action != "stop")  # noqa: E712
        elif body.status == "booked":
            base = base.filter(ReplyLead.stage.in_(BOOKED_STAGES))
        elif body.status == "stopped":
            base = base.filter(ReplyLead.action == "stop")
    ids = [r[0] for r in base.order_by(ReplyLead.id.desc()).limit(300).with_entities(ReplyLead.id).all()]
    if not ids:
        raise HTTPException(422, "No conversations to classify in this selection")
    j = Job(kind="classify_reply_intents",
            workspace_id=(ws_ids[0] if (body.workspace_id and ws_ids) else None),
            payload={"lead_ids": ids})
    ctx.db.add(j)
    ctx.db.commit()
    return {"job_id": j.id, "count": len(ids)}


@router.get("/leads/export")
def export_reply_leads(status: str = "", q: str = "", intent: str = "", bucket: str = "",
                       ids: str = "", workspace_id: int | None = None,
                       ctx: AuthContext = Depends(get_ctx)):
    """Full-info CSV export. Exports the SELECTED leads (ids=1,2,3) or, when no ids
    are given, the entire current filter (status + intent + bucket + search) — not
    just the visible page. Includes website, title, intents, stage and the last
    replies so the file is actually useful for handoff/CRM import."""
    import csv
    import io

    from fastapi.responses import PlainTextResponse

    from ..reply.sync import _deep_get
    ws_ids = ctx.workspace_ids_for_query(workspace_id)
    show_unrouted = ctx.is_master and workspace_id is None
    base = ctx.db.query(ReplyLead).filter(
        (ReplyLead.workspace_id.in_(ws_ids)) |
        (ReplyLead.workspace_id.is_(None) if show_unrouted else False))
    if q:
        like = f"%{q}%"
        base = base.filter((ReplyLead.email.ilike(like)) | (ReplyLead.name.ilike(like))
                           | (ReplyLead.company.ilike(like)))
    id_list = [int(i) for i in ids.split(",") if i.strip().isdigit()]
    if id_list:
        base = base.filter(ReplyLead.id.in_(id_list))
    else:
        BOOKED_STAGES = ["booked", "meeting_completed", "won"]
        if status == "needs_review":
            base = base.filter(ReplyLead.action.in_(["skip_enrich", "would_send"]), ReplyLead.reviewed == False)  # noqa: E712
        elif status in ("replied", "interested"):
            base = base.filter(ReplyLead.replied == True, ReplyLead.stage.notin_(BOOKED_STAGES + ["lost"]), ReplyLead.action != "stop")  # noqa: E712
        elif status == "booked":
            base = base.filter(ReplyLead.stage.in_(BOOKED_STAGES))
        elif status == "stopped":
            base = base.filter(ReplyLead.action == "stop")
        elif status == "draft":
            base = base.filter(ReplyLead.main_reply != "", ReplyLead.replied == False, ReplyLead.action != "stop")  # noqa: E712

    rows = base.order_by(ReplyLead.id.desc()).all()
    if intent:
        rows = [l for l in rows if l.intent == intent]
    if bucket:
        rows = [l for l in rows if intent_bucket(l.intent) == bucket]

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["first_name", "last_name", "email", "company", "website", "title", "campaign",
                "subject", "intent", "intent_bucket", "confidence", "stage", "action",
                "replied", "prospect_last_reply", "our_last_reply", "date", "workspace"])
    for l in rows:
        nm = (l.name or "").split(" ", 1)
        d = l.lead_data or {}
        site = str(_deep_get(d, {"website", "company_website", "domain", "url"}) or "")
        title = str(_deep_get(d, {"title", "job_title", "position", "headline"}) or "")
        w.writerow([nm[0] if nm else "", nm[1] if len(nm) > 1 else "", l.email or "", l.company or "",
                    site, title, l.campaign or "", l.subject or "", l.intent or "",
                    l.intent_bucket or intent_bucket(l.intent), l.confidence or "", l.stage or "", l.action or "",
                    "yes" if l.replied else "no", (l.reply_text or "").replace("\n", " ")[:500],
                    (l.main_reply or "").replace("\n", " ")[:500],
                    l.created_at.isoformat() if l.created_at else "", l.reply_workspace or ""])
    return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=reply-leads.csv"})


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
            "can_cancel": j.status == "pending",   # still held in the delay → stoppable

            "note": j.progress_note or "",
            "error": (j.error or "")[:300],
            "result": {k: v for k, v in (j.result or {}).items()} if j.result else {},
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "finished_at": j.finished_at.isoformat() if j.finished_at else None,
        })
    return {"summary": summary, "worker_alive": worker_alive, "jobs": jobs}


@router.post("/processing/{job_id}/cancel")
def cancel_reply_job(job_id: int, ctx: AuthContext = Depends(get_ctx)):
    """Stop a queued reply before it runs. Only jobs still HELD in the delay
    window (status=pending, not yet claimed by the worker) can be cancelled —
    once it's running or done it's too late. Use when a lead was marked
    interested by mistake, or a webhook fired that you don't want answered."""
    from ..models.jobs import Job
    j = ctx.db.get(Job, job_id)
    if not j or j.kind != "process_reply":
        raise HTTPException(404, "Job not found")
    if j.workspace_id is not None and j.workspace_id not in ctx.allowed_workspace_ids():
        raise HTTPException(403, "Not allowed for this workspace")
    if j.status != "pending":
        raise HTTPException(409, f"Can't stop a reply that is already {j.status}.")
    j.status = "cancelled"
    j.finished_at = datetime.utcnow()
    j.result = {**(j.result or {}), "skipped": "cancelled by user"}
    ctx.db.commit()
    return {"ok": True, "id": j.id, "status": j.status}


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


@router.post("/leads/{lead_id}/draft")
def reply_lead_draft(lead_id: int, ctx: AuthContext = Depends(get_ctx)):
    """Generate (or regenerate) the AI reply for a lead on demand. This is the
    recovery path when the live pipeline fell back to human_review with an empty
    draft (a transient model miss, a non-JSON response, or a temporary AI outage):
    the reviewer clicks 'Draft with AI' and gets a reply to edit and approve,
    instead of being stuck with nothing to send."""
    from ..reply import engine as E
    l = ctx.db.get(ReplyLead, lead_id)
    if not l or (l.workspace_id is not None and l.workspace_id not in ctx.allowed_workspace_ids()):
        raise HTTPException(404, "Not found")
    rws = ctx.db.query(ReplyWorkspace).filter(ReplyWorkspace.name == l.reply_workspace).first()
    if not rws:
        raise HTTPException(422, "This lead isn't routed to a reply workspace, so there's no config to draft from.")
    thread = list(l.thread or [])
    if not thread and l.reply_text:
        thread = [{"direction": "in", "text": l.reply_text}]
    if not thread:
        raise HTTPException(422, "No inbound message on this lead to draft a reply from.")
    # best-effort real scheduling context (open Calendly times); "" if unavailable
    sched = ""
    try:
        from ..reply.calendly import build_scheduling_context
        loc = str((l.lead_data or {}).get("location") or "")
        sched = build_scheduling_context(ctx.db, rws, loc, prospect_key=l.email, mode="reply")
    except Exception:
        sched = ""
    gen = E.generate_reply(rws, thread, scheduling_context=sched,
                           prospect={"first_name": E.first_name_of(l.name), "company": l.company},
                           client_brain=E.load_client_brain(ctx.db, l.workspace_id))
    if not (gen.get("main_reply") or "").strip():
        why = (gen.get("error") or "").strip()
        msg = "The AI couldn't draft a reply. "
        msg += f"Reason: {why}. " if why else ""
        msg += "Check this reply-space's AI key and model in Reply Settings, then try again."
        raise HTTPException(502, msg)
    l.main_reply = gen["main_reply"]
    l.intent = gen.get("intent") or l.intent
    l.confidence = gen.get("confidence") or l.confidence
    l.followups = gen.get("followups") or l.followups
    l.reply_added = bool(l.main_reply) and gen.get("model_ran", False)
    # keep it in review for a human to approve (never auto-sends from here)
    if l.action in (None, "", "skip_enrich", "error"):
        l.action = "would_send"
    l.send_error = ""
    l.updated_at = datetime.utcnow()
    ctx.db.commit()
    return {"ok": True, "main_reply": l.main_reply, "intent": l.intent, "confidence": l.confidence}


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
    brain = E.load_client_brain(ctx.db, w.workspace_id)
    gen = E.generate_reply(w, thread, prospect={"first_name": ""}, client_brain=brain)
    reply = E.add_signature(gen["main_reply"], w.sender_name, w.website) if gen["main_reply"] else ""
    # Match production: if the combined call skipped the follow-ups, generate them
    # explicitly so Test Thread shows exactly what the pipeline would push.
    followups = gen["followups"]
    fup_err = ""
    if not followups and (w.reply_format or {}).get("followups") and gen["action"] != "stop":
        fg = E.generate_followups(w, thread, prospect={"first_name": ""}, client_brain=brain)
        followups = fg["followups"]
        fup_err = fg.get("error", "")
    return {
        "intent": gen["intent"], "confidence": gen["confidence"],
        "decision": gen["action"], "would_auto_send": gen["action"] == "send" and E.auto_send_enabled(),
        "model_ran": gen["model_ran"],
        "error": gen.get("error", "") or fup_err,   # surface the real reason when nothing ran
        "reply": reply,
        "followups": followups,
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


class SendIn(BaseModel):
    body: str | None = None    # optional: send THIS text (a manual follow-up), else the draft


@router.post("/leads/{lead_id}/send")
def approve_and_send(lead_id: int, body: SendIn | None = None, ctx: AuthContext = Depends(get_ctx)):
    """Approve & Send — live send via the correct platform, IN THE SAME THREAD.
    With a `body`, sends that text as a manual follow-up (allowed even after the
    first reply). Every sent message is appended to the conversation thread so the
    chat shows exactly what we sent (WhatsApp-style)."""
    from ..reply.engine import add_signature, send_bison_reply, send_instantly_reply
    l = ctx.db.get(ReplyLead, lead_id)
    if not l or (l.workspace_id is not None and l.workspace_id not in ctx.allowed_workspace_ids()):
        raise HTTPException(404, "Not found")
    follow_up_text = (body.body if body else None)
    reply_body = (follow_up_text or l.main_reply or "").strip()
    if not reply_body:
        raise HTTPException(422, "No draft to send")
    if l.replied and not follow_up_text:
        raise HTTPException(409, "Already sent")   # nothing new to send
    rws = ctx.db.query(ReplyWorkspace).filter(ReplyWorkspace.name == l.reply_workspace).first()
    if not rws:
        raise HTTPException(422, "Reply-workspace config not found")
    message = add_signature(reply_body, rws.sender_name, rws.website)
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
            res = send_instantly_reply(rws, meta, message, l.subject, follow_up=bool(follow_up_text))
            # persist the resolved reply target so future follow-ups reuse it and
            # never have to re-look it up (the bug that broke follow-up sends).
            if res.get("reply_to_uuid") and res.get("eaccount"):
                l.send_meta = {**(l.send_meta or {}), "reply_to_uuid": res["reply_to_uuid"],
                               "eaccount": res["eaccount"]}
    except Exception as e:
        # 400 (not 502) so the client reliably shows this JSON detail instead of a
        # bare gateway error; record it on the lead so the reason is visible later.
        l.action = "error"
        l.send_error = str(e)[:500]
        ctx.db.commit()
        raise HTTPException(400, f"Send failed: {e}")
    # show exactly what we sent in the chat thread (WhatsApp-style outbound bubble)
    l.thread = list(l.thread or []) + [{"direction": "out", "text": reply_body,
                                        "at": datetime.utcnow().isoformat()}]
    l.replied = True
    l.reviewed = True
    l.stage = "replied"
    l.send_error = ""
    if follow_up_text:
        l.fup_added = True
    ctx.db.commit()
    return {"ok": True, "sent_via": l.platform, "follow_up": bool(follow_up_text)}
