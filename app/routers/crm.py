"""CRM endpoints on the unified object model. Every read/write goes through the
workspace scope — a client user physically cannot see another workspace's data."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import AuthContext, get_ctx, scoped
from ..models.crm import Activity, Company, Contact, Deal, Stage

router = APIRouter(prefix="/api", tags=["crm"])


def _one_or_404(ctx, model, obj_id, workspace_id=None):
    row = scoped(ctx.db.query(model), model, ctx, workspace_id).filter(model.id == obj_id).first()
    if not row:
        raise HTTPException(404, f"{model.__name__} not found")
    return row


# ---------------------------------------------------------------- companies
def _pipeline_status(ctx, ws_ids):
    """Per-record pipeline status derived from its deals' most-advanced stage
    (+ 'Client' when an active Client Profile exists). Returns (by_company,
    by_contact, is_client_company_ids, status_for) where status_for(stage_ids,
    is_client) -> {key,label,color}. The entry 'Opportunity' stage shows as
    'Interested'."""
    from collections import defaultdict
    from ..models.client_profile import ClientProfile
    stages = {s.id: s for s in ctx.db.query(Stage).filter(Stage.workspace_id.in_(ws_ids)).all()}
    by_co, by_ct = defaultdict(list), defaultdict(list)
    for d in ctx.db.query(Deal.company_id, Deal.contact_id, Deal.stage_id).filter(Deal.workspace_id.in_(ws_ids)).all():
        if d.company_id is not None:
            by_co[d.company_id].append(d.stage_id)
        if d.contact_id is not None:
            by_ct[d.contact_id].append(d.stage_id)
    client_co = {p.company_id for p in ctx.db.query(ClientProfile.company_id)
                 .filter(ClientProfile.workspace_id.in_(ws_ids), ClientProfile.is_active_client == True).all()}  # noqa: E712

    def status_for(stage_ids, is_client):
        if is_client:
            return {"key": "client", "label": "Client", "color": "#16a34a"}
        sids = [s for s in stage_ids if s in stages]
        if not sids:
            return {"key": "none", "label": "No deal", "color": "#94a3b8"}
        best = max((stages[s] for s in sids), key=lambda st: st.sort_order)
        label = "Interested" if best.name == "Opportunity" else best.name
        return {"key": label.lower().replace(" ", "_"), "label": label, "color": best.color}

    return by_co, by_ct, client_co, status_for


@router.get("/companies")
def list_companies(workspace_id: int | None = None, q: str = "", status: str = "",
                   ctx: AuthContext = Depends(get_ctx)):
    ws_ids = ctx.workspace_ids_for_query(workspace_id)
    by_co, _, client_co, status_for = _pipeline_status(ctx, ws_ids)
    qry = scoped(ctx.db.query(Company), Company, ctx, workspace_id)
    if q:
        qry = qry.filter(Company.name.ilike(f"%{q}%"))
    rows = qry.order_by(Company.updated_at.desc()).limit(500).all()
    out = []
    for c in rows:
        st = status_for(by_co.get(c.id, []), c.id in client_co)
        if status and st["key"] != status:
            continue
        out.append({"id": c.id, "workspace_id": c.workspace_id, "name": c.name, "domain": c.domain,
                    "industry": c.industry, "icp_fit": c.icp_fit, "status": st})
    return out


class CompanyIn(BaseModel):
    workspace_id: int
    name: str
    website: str = ""
    domain: str = ""


@router.post("/companies")
def create_company(body: CompanyIn, ctx: AuthContext = Depends(get_ctx)):
    ctx.require_workspace(body.workspace_id)
    c = Company(workspace_id=body.workspace_id, name=body.name, website=body.website, domain=body.domain)
    ctx.db.add(c)
    ctx.db.commit()
    return {"id": c.id}


class CompanyPatch(BaseModel):
    name: str | None = None
    website: str | None = None
    domain: str | None = None
    industry: str | None = None
    location: str | None = None


@router.put("/companies/{company_id}")
def update_company(company_id: int, body: CompanyPatch, ctx: AuthContext = Depends(get_ctx)):
    c = _one_or_404(ctx, Company, company_id)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(c, k, v)
    ctx.db.commit()
    return {"id": c.id}


@router.delete("/companies/{company_id}")
def delete_company(company_id: int, ctx: AuthContext = Depends(get_ctx)):
    """Delete a company and everything hanging off it (its contacts, deals,
    documents, client profile, and activities) — for cleaning the workspace.
    Workspace-scoped; children removed first so FKs never block the delete."""
    from ..models.client_profile import ClientProfile
    from ..models.documents import Document
    c = _one_or_404(ctx, Company, company_id)
    deal_ids = [d.id for d in ctx.db.query(Deal.id).filter(Deal.company_id == c.id).all()]
    contact_ids = [x.id for x in ctx.db.query(Contact.id).filter(Contact.company_id == c.id).all()]
    aq = ctx.db.query(Activity).filter(
        (Activity.company_id == c.id)
        | (Activity.deal_id.in_(deal_ids) if deal_ids else False)
        | (Activity.contact_id.in_(contact_ids) if contact_ids else False))
    aq.delete(synchronize_session=False)
    ctx.db.query(Document).filter(Document.company_id == c.id).delete(synchronize_session=False)
    ctx.db.query(ClientProfile).filter(ClientProfile.company_id == c.id).delete(synchronize_session=False)
    ctx.db.query(Deal).filter(Deal.company_id == c.id).delete(synchronize_session=False)
    ctx.db.query(Contact).filter(Contact.company_id == c.id).delete(synchronize_session=False)
    ctx.db.delete(c)
    ctx.db.commit()
    return {"ok": True, "deleted": {"deals": len(deal_ids), "contacts": len(contact_ids)}}


class ContactIn(BaseModel):
    workspace_id: int
    email: str = ""
    first_name: str = ""
    last_name: str = ""
    title: str = ""
    company_id: int | None = None
    auto_enrich: bool = False   # queue an enrich_contact job immediately


@router.post("/contacts")
def create_contact(body: ContactIn, ctx: AuthContext = Depends(get_ctx)):
    ctx.require_workspace(body.workspace_id)
    c = Contact(workspace_id=body.workspace_id, email=body.email.lower().strip(),
                first_name=body.first_name, last_name=body.last_name, title=body.title,
                company_id=body.company_id, source="manual")
    ctx.db.add(c)
    ctx.db.flush()
    job_id = None
    if body.auto_enrich:
        from ..models.jobs import Job
        j = Job(kind="enrich_contact", workspace_id=body.workspace_id, payload={"contact_id": c.id})
        ctx.db.add(j)
        ctx.db.flush()
        job_id = j.id
    ctx.db.commit()
    return {"id": c.id, "enrich_job_id": job_id}


# ---------------------------------------------------------------- contacts
@router.get("/contacts")
def list_contacts(workspace_id: int | None = None, q: str = "", status: str = "",
                  ctx: AuthContext = Depends(get_ctx)):
    ws_ids = ctx.workspace_ids_for_query(workspace_id)
    _, by_ct, client_co, status_for = _pipeline_status(ctx, ws_ids)
    qry = scoped(ctx.db.query(Contact), Contact, ctx, workspace_id)
    if q:
        like = f"%{q}%"
        qry = qry.filter((Contact.email.ilike(like)) | (Contact.first_name.ilike(like)) | (Contact.last_name.ilike(like)))
    rows = qry.order_by(Contact.updated_at.desc()).limit(500).all()
    coids = {c.company_id for c in rows if c.company_id}
    cmap = ({c.id: c.name for c in ctx.db.query(Company).filter(Company.id.in_(coids)).all()}
            if coids else {})
    # attach the reply INTENT (latest reply lead matching the email) so exports
    # can be intent-driven, e.g. "all positive_simple leads → new campaign".
    from ..models.reply import ReplyLead
    emails = [c.email.lower() for c in rows if c.email]
    intent_map = {}
    if emails:
        for rl in (ctx.db.query(ReplyLead.email, ReplyLead.intent)
                   .filter(ReplyLead.workspace_id.in_(ws_ids), ReplyLead.email.in_(emails))
                   .order_by(ReplyLead.id).all()):
            if rl.email:
                intent_map[rl.email.lower()] = rl.intent or ""   # last wins = latest
    out = []
    for c in rows:
        st = status_for(by_ct.get(c.id, []), c.company_id in client_co)
        if status and st["key"] != status:
            continue
        out.append({"id": c.id, "workspace_id": c.workspace_id, "email": c.email,
                    "name": f"{c.first_name} {c.last_name}".strip(),
                    "first_name": c.first_name, "last_name": c.last_name, "title": c.title,
                    "company_id": c.company_id, "company_name": cmap.get(c.company_id, ""),
                    "email_status": c.email_status, "enriched": bool(c.revenue_score is not None),
                    "revenue_score": c.revenue_score, "source": c.source, "status": st,
                    "intent": intent_map.get((c.email or "").lower(), "")})
    return out


@router.get("/contacts/{contact_id}/timeline")
def contact_timeline(contact_id: int, ctx: AuthContext = Depends(get_ctx)):
    c = _one_or_404(ctx, Contact, contact_id)
    acts = (scoped(ctx.db.query(Activity), Activity, ctx)
            .filter(Activity.contact_id == c.id)
            .order_by(Activity.occurred_at.desc()).limit(500).all())
    return [{"id": a.id, "kind": a.kind, "title": a.title, "body": a.body,
             "occurred_at": a.occurred_at.isoformat() if a.occurred_at else None} for a in acts]


# ---------------------------------------------------------------- deals
class DealIn(BaseModel):
    workspace_id: int
    name: str = ""
    contact_id: int | None = None
    company_id: int | None = None
    stage_id: int | None = None
    value: float = 0.0
    description: str = ""


@router.get("/deals")
def list_deals(workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    deals = scoped(ctx.db.query(Deal), Deal, ctx, workspace_id).order_by(Deal.updated_at.desc()).limit(500).all()
    return [{"id": d.id, "workspace_id": d.workspace_id, "name": d.name, "value": d.value,
             "stage_id": d.stage_id, "contact_id": d.contact_id, "company_id": d.company_id,
             "lead_intent": d.lead_intent, "tags": d.tags} for d in deals]


def _name_maps(ctx, deals):
    cids = {d.contact_id for d in deals if d.contact_id}
    coids = {d.company_id for d in deals if d.company_id}
    contacts = {c.id: c for c in ctx.db.query(Contact).filter(Contact.id.in_(cids)).all()} if cids else {}
    companies = {c.id: c for c in ctx.db.query(Company).filter(Company.id.in_(coids)).all()} if coids else {}
    return contacts, companies


@router.get("/deals/board")
def deals_board(workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    """Kanban data: stages with deal cards + per-column totals. When viewing all
    workspaces (master), stages with the same name are merged into one column."""
    ws_ids = ctx.workspace_ids_for_query(workspace_id)
    stages = ctx.db.query(Stage).filter(Stage.workspace_id.in_(ws_ids)).order_by(Stage.sort_order).all()
    deals = scoped(ctx.db.query(Deal), Deal, ctx, workspace_id).all()
    contacts, companies = _name_maps(ctx, deals)
    stage_name = {s.id: s.name for s in stages}
    by_name: dict = {}
    order, meta = [], {}
    for s in stages:
        if s.name not in meta:
            order.append(s.name)
            meta[s.name] = s
    for d in deals:
        by_name.setdefault(stage_name.get(d.stage_id), []).append(d)
    out = []
    for name in order:
        s = meta[name]
        cards = by_name.get(name, [])
        out.append({
            "stage": {"id": s.id, "name": s.name, "color": s.color, "is_won": s.is_won, "is_lost": s.is_lost},
            "count": len(cards),
            "total_value": sum(d.value or 0 for d in cards),
            "deals": [{
                "id": d.id, "name": d.name, "value": d.value, "workspace_id": d.workspace_id,
                "contact_id": d.contact_id, "company_id": d.company_id,
                "contact_name": (f"{contacts[d.contact_id].first_name} {contacts[d.contact_id].last_name}".strip()
                                 if d.contact_id in contacts else ""),
                "company_name": companies[d.company_id].name if d.company_id in companies else "",
                "lead_intent": d.lead_intent,
                "updated_at": d.updated_at.isoformat() if d.updated_at else None,
            } for d in sorted(cards, key=lambda x: x.updated_at or datetime.min, reverse=True)],
        })
    return out


@router.get("/deals/{deal_id}")
def deal_detail(deal_id: int, ctx: AuthContext = Depends(get_ctx)):
    d = _one_or_404(ctx, Deal, deal_id)
    contact = ctx.db.get(Contact, d.contact_id) if d.contact_id else None
    company = ctx.db.get(Company, d.company_id) if d.company_id else None
    stage = ctx.db.get(Stage, d.stage_id) if d.stage_id else None
    stages = (ctx.db.query(Stage).filter(Stage.workspace_id == d.workspace_id)
              .order_by(Stage.sort_order).all())
    acts = (scoped(ctx.db.query(Activity), Activity, ctx)
            .filter(Activity.deal_id == d.id).order_by(Activity.occurred_at.desc()).limit(50).all())
    return {
        "id": d.id, "workspace_id": d.workspace_id, "name": d.name, "value": d.value,
        "description": d.description, "lead_intent": d.lead_intent, "status_label": d.status_label,
        "next_step": d.next_step, "close_date": d.close_date, "tags": d.tags,
        "stage": {"id": stage.id, "name": stage.name, "color": stage.color} if stage else None,
        "stages": [{"id": s.id, "name": s.name, "color": s.color} for s in stages],
        "contact": ({"id": contact.id, "name": f"{contact.first_name} {contact.last_name}".strip(),
                     "email": contact.email, "title": contact.title} if contact else None),
        "company": ({"id": company.id, "name": company.name, "industry": company.industry,
                     "icp_fit": company.icp_fit} if company else None),
        "timeline": [{"id": a.id, "kind": a.kind, "title": a.title,
                      "at": a.occurred_at.isoformat() if a.occurred_at else None} for a in acts],
    }


@router.post("/deals")
def create_deal(body: DealIn, ctx: AuthContext = Depends(get_ctx)):
    ctx.require_workspace(body.workspace_id)
    stage_id = body.stage_id
    if stage_id is None:
        first = (ctx.db.query(Stage).filter(Stage.workspace_id == body.workspace_id)
                 .order_by(Stage.sort_order).first())
        stage_id = first.id if first else None
    d = Deal(workspace_id=body.workspace_id, name=body.name, contact_id=body.contact_id,
             company_id=body.company_id, stage_id=stage_id, value=body.value, description=body.description)
    ctx.db.add(d)
    ctx.db.flush()
    ctx.db.add(Activity(workspace_id=d.workspace_id, deal_id=d.id, contact_id=d.contact_id,
                        kind="deal_created", title=f"Deal created: {d.name}", actor_user_id=ctx.user.id))
    ctx.db.commit()
    return {"id": d.id}


class LeadIn(BaseModel):
    workspace_id: int
    # company: link an existing one, or create by name
    company_id: int | None = None
    company_name: str = ""
    # contact: link an existing one, or create from these fields
    contact_id: int | None = None
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    title: str = ""
    # deal
    stage_id: int | None = None
    deal_name: str = ""
    value: float = 0.0


@router.post("/leads")
def create_lead(body: LeadIn, ctx: AuthContext = Depends(get_ctx)):
    """One-shot lead entry: resolve/create the company, create (or link) the contact,
    and open a deal at the chosen stage — so a manual lead lands in Companies,
    Contacts AND the Pipeline at once (for website/referral leads)."""
    ctx.require_workspace(body.workspace_id)

    # --- company
    company = None
    if body.company_id:
        company = _one_or_404(ctx, Company, body.company_id, body.workspace_id)
    elif body.company_name.strip():
        company = Company(workspace_id=body.workspace_id, name=body.company_name.strip())
        ctx.db.add(company)
        ctx.db.flush()

    # --- contact
    contact = None
    if body.contact_id:
        contact = _one_or_404(ctx, Contact, body.contact_id, body.workspace_id)
        if company and not contact.company_id:
            contact.company_id = company.id
    elif (body.first_name or body.last_name or body.email).strip():
        contact = Contact(workspace_id=body.workspace_id, email=(body.email or "").lower().strip(),
                          first_name=body.first_name, last_name=body.last_name, title=body.title,
                          company_id=company.id if company else None, source="manual")
        ctx.db.add(contact)
        ctx.db.flush()

    # --- deal (stage defaults to first stage)
    stage_id = body.stage_id
    if stage_id is None:
        first = (ctx.db.query(Stage).filter(Stage.workspace_id == body.workspace_id)
                 .order_by(Stage.sort_order).first())
        stage_id = first.id if first else None
    nm = body.deal_name.strip() or (company.name if company else "") or \
        (f"{body.first_name} {body.last_name}".strip() or "New lead")
    deal = Deal(workspace_id=body.workspace_id, name=nm,
                contact_id=contact.id if contact else None,
                company_id=company.id if company else None,
                stage_id=stage_id, value=body.value)
    ctx.db.add(deal)
    ctx.db.flush()
    ctx.db.add(Activity(workspace_id=body.workspace_id, deal_id=deal.id,
                        company_id=company.id if company else None,
                        contact_id=contact.id if contact else None,
                        kind="deal_created", title=f"Lead added: {nm}", actor_user_id=ctx.user.id))
    ctx.db.commit()
    return {"deal_id": deal.id,
            "company_id": company.id if company else None,
            "contact_id": contact.id if contact else None}


class MoveIn(BaseModel):
    stage_id: int


@router.post("/deals/{deal_id}/move")
def move_deal(deal_id: int, body: MoveIn, ctx: AuthContext = Depends(get_ctx)):
    d = _one_or_404(ctx, Deal, deal_id)
    stage = ctx.db.query(Stage).filter(Stage.id == body.stage_id, Stage.workspace_id == d.workspace_id).first()
    if not stage:
        raise HTTPException(422, "Stage not in this deal's workspace")
    old = d.stage_id
    d.stage_id = stage.id
    d.stage_changed_at = datetime.utcnow()
    ctx.db.add(Activity(workspace_id=d.workspace_id, deal_id=d.id, contact_id=d.contact_id,
                        kind="stage_change", title=f"Stage → {stage.name}",
                        data={"from": old, "to": stage.id}, actor_user_id=ctx.user.id))
    # two-way sync: reflect this stage on the matching ReplyLead(s) so the reply
    # inbox shows the same status (e.g. mark No Show / Meeting Booked in the CRM).
    try:
        from ..reply.sync import sync_deal_stage_to_reply
        sync_deal_stage_to_reply(ctx.db, d, stage)
    except Exception:
        pass
    ctx.db.commit()
    # Closed Won → activate the client + build the Client Profile (idempotent).
    profile_id = None
    if stage.is_won and d.company_id:
        try:
            from ..client.profiles import ensure_profile
            profile_id = ensure_profile(ctx.db, d.company_id, d.id, ctx.user.id).id
        except Exception:
            pass  # never block the stage move
    try:
        from ..extapi import events as _ev
        _st = ctx.db.get(Stage, d.stage_id) if d.stage_id else None
        _ev.emit(ctx.db, d.workspace_id, "deal.stage_changed",
                 {"id": d.id, "name": d.name, "value": d.value,
                  "stage": _st.name if _st else "", "company_id": d.company_id})
    except Exception:
        pass
    return {"ok": True, "client_profile_id": profile_id}


# ---------------------------------------------------------------- activities
@router.get("/activities")
def list_activities(workspace_id: int | None = None, kind: str = "", limit: int = 50,
                    ctx: AuthContext = Depends(get_ctx)):
    q = scoped(ctx.db.query(Activity), Activity, ctx, workspace_id)
    if kind:
        q = q.filter(Activity.kind == kind)
    rows = q.order_by(Activity.occurred_at.desc()).limit(min(max(limit, 1), 200)).all()
    return [{"id": a.id, "workspace_id": a.workspace_id, "kind": a.kind, "title": a.title,
             "body": (a.body or "")[:300], "contact_id": a.contact_id, "company_id": a.company_id,
             "deal_id": a.deal_id, "intent": (a.data or {}).get("intent", ""),
             "at": a.occurred_at.isoformat() if a.occurred_at else None}
            for a in rows]


# ---------------------------------------------------------------- dashboard
@router.get("/dashboard/summary")
def dashboard_summary(workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    """The client-shareable rollup: counts, pipeline by stage, health, recent activity."""
    from datetime import timedelta

    from ..models.jobs import Job

    ws_ids = ctx.workspace_ids_for_query(workspace_id)
    board = deals_board(workspace_id, ctx)
    deals = scoped(ctx.db.query(Deal), Deal, ctx, workspace_id).all()
    stage_flags = {}
    for b in board:
        stage_flags[b["stage"]["name"]] = (b["stage"]["is_won"], b["stage"]["is_lost"])
    won_lost_ids = {s.id for s in ctx.db.query(Stage).filter(Stage.workspace_id.in_(ws_ids))
                    .filter((Stage.is_won == True) | (Stage.is_lost == True)).all()}  # noqa: E712
    booked_ids = {s.id for s in ctx.db.query(Stage).filter(Stage.workspace_id.in_(ws_ids),
                                                           Stage.name == "Meeting Booked").all()}
    now = datetime.utcnow()
    stalled = sum(1 for d in deals if d.stage_id not in won_lost_ids
                  and d.stage_changed_at and (now - d.stage_changed_at) > timedelta(days=14))
    replies = scoped(ctx.db.query(Activity), Activity, ctx, workspace_id).filter(Activity.kind == "email_in").all()
    positive = sum(1 for a in replies if "positive" in str((a.data or {}).get("intent", "")).lower())
    jobs_running = (ctx.db.query(Job).filter(Job.workspace_id.in_(ws_ids),
                                             Job.status.in_(["pending", "running"])).count())
    recent = (scoped(ctx.db.query(Activity), Activity, ctx, workspace_id)
              .order_by(Activity.occurred_at.desc()).limit(15).all())
    return {
        "totals": {
            "companies": scoped(ctx.db.query(Company), Company, ctx, workspace_id).count(),
            "contacts": scoped(ctx.db.query(Contact), Contact, ctx, workspace_id).count(),
            "active_deals": sum(1 for d in deals if d.stage_id not in won_lost_ids),
            "meetings_booked": sum(1 for d in deals if d.stage_id in booked_ids),
            "replies": len(replies),
            "positive_replies": positive,
            "stalled_deals": stalled,
            "enrichment_jobs_running": jobs_running,
        },
        "pipeline": [{"stage": b["stage"]["name"], "color": b["stage"]["color"],
                      "count": b["count"], "value": b["total_value"]} for b in board],
        "open_value": sum(b["total_value"] for b in board if not b["stage"]["is_won"] and not b["stage"]["is_lost"]),
        "won_value": sum(b["total_value"] for b in board if b["stage"]["is_won"]),
        "recent_activity": [{"kind": a.kind, "title": a.title,
                             "at": a.occurred_at.isoformat() if a.occurred_at else None} for a in recent],
    }


@router.get("/reports/summary")
def reports_summary(workspace_id: int | None = None, days: int = 90,
                    ctx: AuthContext = Depends(get_ctx)):
    """Client-facing ROI report: headline KPIs, the conversion funnel, and a
    weekly trend. Everything is scoped to the workspace (a client sees only
    theirs). Funnel is stage-membership based so it's accurate and defensible."""
    from datetime import timedelta

    ws_ids = ctx.workspace_ids_for_query(workspace_id)
    days = max(7, min(int(days or 90), 365))
    now = datetime.utcnow()
    since = now - timedelta(days=days)

    stages = {s.id: s for s in ctx.db.query(Stage).filter(Stage.workspace_id.in_(ws_ids)).all()}
    won_ids = {i for i, s in stages.items() if s.is_won}
    lost_ids = {i for i, s in stages.items() if s.is_lost}
    name_of = {i: s.name for i, s in stages.items()}
    BOOKED = {"Meeting Booked", "Meeting Completed", "No Show", "Follow-up", "Won"}
    COMPLETED = {"Meeting Completed", "Follow-up", "Won"}

    deals = scoped(ctx.db.query(Deal), Deal, ctx, workspace_id).all()
    open_deals = [d for d in deals if d.stage_id not in won_ids and d.stage_id not in lost_ids]
    won_deals = [d for d in deals if d.stage_id in won_ids]
    booked = [d for d in deals if name_of.get(d.stage_id, "") in BOOKED]
    completed = [d for d in deals if name_of.get(d.stage_id, "") in COMPLETED]

    def in_range(dt):
        return dt is not None and dt >= since

    opps_range = [d for d in deals if in_range(d.created_at)]
    won_range = [d for d in won_deals if in_range(d.stage_changed_at or d.updated_at)]
    replies = scoped(ctx.db.query(Activity), Activity, ctx, workspace_id).filter(Activity.kind == "email_in").all()
    positive = [a for a in replies if "positive" in str((a.data or {}).get("intent", "")).lower()]
    positive_range = [a for a in positive if in_range(a.occurred_at)]

    def rate(n, d):
        return round(100 * n / d) if d else 0

    funnel = [
        {"label": "Opportunities", "count": len(deals)},
        {"label": "Meetings booked", "count": len(booked)},
        {"label": "Meetings completed", "count": len(completed)},
        {"label": "Won", "count": len(won_deals)},
    ]

    # weekly trend (most recent `weeks` buckets)
    weeks = max(1, min((days + 6) // 7, 26))
    start = now - timedelta(days=weeks * 7)
    trend = [{"week": (start + timedelta(days=i * 7)).strftime("%b %d"),
              "opportunities": 0, "meetings": 0, "won_value": 0.0} for i in range(weeks)]

    def bucket(dt):
        if dt is None or dt < start:
            return None
        idx = (dt - start).days // 7
        return idx if 0 <= idx < weeks else None

    for d in deals:
        b = bucket(d.created_at)
        if b is not None:
            trend[b]["opportunities"] += 1
    for d in won_deals:
        b = bucket(d.stage_changed_at or d.updated_at)
        if b is not None:
            trend[b]["won_value"] += float(d.value or 0)
    for a in scoped(ctx.db.query(Activity), Activity, ctx, workspace_id).filter(
            Activity.kind == "stage_change").all():
        if "meeting booked" in str(a.title or "").lower():
            b = bucket(a.occurred_at)
            if b is not None:
                trend[b]["meetings"] += 1

    top = sorted(open_deals, key=lambda d: (d.value or 0), reverse=True)[:8]
    return {
        "range_days": days,
        "kpis": {
            "open_pipeline_value": round(sum(d.value or 0 for d in open_deals)),
            "won_revenue": round(sum(d.value or 0 for d in won_deals)),
            "won_revenue_in_range": round(sum(d.value or 0 for d in won_range)),
            "active_deals": len(open_deals),
            "opportunities_in_range": len(opps_range),
            "meetings_booked": len(booked),
            "deals_won_in_range": len(won_range),
            "positive_replies_in_range": len(positive_range),
        },
        "conversion": {
            "booked_rate": rate(len(booked), len(deals)),
            "completed_rate": rate(len(completed), len(booked)),
            "won_rate": rate(len(won_deals), len(completed)),
            "opp_to_won_rate": rate(len(won_deals), len(deals)),
        },
        "funnel": funnel,
        "trend": trend,
        "top_open_deals": [{"id": d.id, "name": d.name or "(unnamed)", "value": round(d.value or 0),
                            "stage": name_of.get(d.stage_id, "")} for d in top],
    }


@router.get("/companies/{company_id}/revenue-timeline")
def revenue_timeline(company_id: int, ctx: AuthContext = Depends(get_ctx)):
    """The Revenue Timeline: one chronological journey for a company, from the
    first touch to revenue. Merges CRM activities, replies, documents,
    agreements, invoices and onboarding into a single ordered stream, plus a
    milestone summary of how far the journey has progressed."""
    from ..models.agreements import Agreement, Invoice
    from ..models.client_profile import ClientProfile
    from ..models.documents import Document

    c = _one_or_404(ctx, Company, company_id)
    ev = []

    def add(at, kind, title, detail="", href=None):
        if at:
            ev.append({"at": at.isoformat(), "kind": kind, "title": title,
                       "detail": detail, "href": href})

    add(c.created_at, "lead", "Lead created", c.source if hasattr(c, "source") else "")

    # activities: outreach, replies, meetings, stage changes, docs viewed …
    KIND_LABEL = {
        "email_out": ("outreach", "Outbound email sent"),
        "email_in": ("reply", "Reply received"),
        "reply_drafted": ("reply", "AI reply drafted"),
        "meeting_booked": ("meeting", "Meeting booked"),
        "meeting_held": ("meeting", "Meeting completed"),
        "stage_change": ("deal", "Deal stage changed"),
        "deal_created": ("deal", "Deal created"),
        "doc_viewed": ("doc", "Document viewed by client"),
        "doc_signed": ("signature", "Document signed"),
        "enriched": ("system", "Enriched"),
    }
    first_outreach_done = False
    acts = (ctx.db.query(Activity).filter(Activity.company_id == c.id)
            .order_by(Activity.occurred_at.asc()).limit(500).all())
    for a in acts:
        kind, label = KIND_LABEL.get(a.kind, ("system", a.kind.replace("_", " ")))
        title = a.title or label
        if a.kind == "email_out" and not first_outreach_done:
            title = "Outbound campaign started"
            first_outreach_done = True
        elif a.kind == "email_in":
            intent = str((a.data or {}).get("intent", ""))
            if "positive" in intent.lower():
                kind, title = "reply_positive", "Positive reply"
        add(a.occurred_at, kind, title, (a.title if a.title and a.title != title else ""))

    # blueprints
    for d in ctx.db.query(Document).filter(Document.company_id == c.id,
                                           Document.kind == "blueprint").all():
        add(d.created_at, "blueprint", "Blueprint generated", d.title, f"/blueprints/{d.id}")
        if d.published:
            add(d.updated_at if not d.first_viewed_at else d.first_viewed_at,
                "blueprint", "Blueprint published", d.title, f"/blueprints/{d.id}")
        add(d.first_viewed_at, "doc", "Blueprint viewed by client", d.title, f"/blueprints/{d.id}")

    # agreements
    for a in ctx.db.query(Agreement).filter(Agreement.company_id == c.id).all():
        if a.status not in ("draft", "ready"):
            add(a.created_at, "agreement", "Agreement sent", a.number, f"/agreements/{a.id}")
        add(a.first_viewed_at, "doc", "Agreement viewed by client", a.number, f"/agreements/{a.id}")
        add(a.client_signed_at, "signature", "Client signed", a.number, f"/agreements/{a.id}")
        add(a.executed_at, "signature", "Agreement executed", a.number, f"/agreements/{a.id}")

    # invoices → revenue
    revenue = 0.0
    for i in ctx.db.query(Invoice).filter(Invoice.company_id == c.id).all():
        if i.status not in ("draft", "void"):
            add(i.created_at, "invoice", "Invoice issued",
                f"{i.number} · {i.currency} {int(i.total or 0):,}", f"/invoices/{i.id}")
        add(i.paid_at, "revenue", "Invoice paid — revenue generated",
            f"{i.number} · {i.currency} {int(i.amount_paid or 0):,}", f"/invoices/{i.id}")
        if i.paid_at:
            revenue += i.amount_paid or 0

    # onboarding + campaign live (client profile)
    p = ctx.db.query(ClientProfile).filter(ClientProfile.company_id == c.id).first()
    if p is not None:
        try:
            from ..models.onboarding import Onboarding
            ob = (ctx.db.query(Onboarding)
                  .filter(Onboarding.client_profile_id == p.id).first()
                  if hasattr(Onboarding, "client_profile_id") else None)
            if ob is not None:
                add(ob.created_at, "onboarding", "Onboarding sent")
                add(ob.submitted_at, "onboarding", "Onboarding submitted")
        except Exception:
            pass
        if p.is_active_client:
            add(getattr(p, "updated_at", None) or getattr(p, "created_at", None),
                "live", "Client active — campaign live")

    ev.sort(key=lambda e: e["at"])

    ORDER = ["lead", "outreach", "reply_positive", "meeting", "blueprint",
             "agreement", "signature", "invoice", "revenue", "live"]
    reached = {k: None for k in ORDER}
    for e in ev:
        k = e["kind"] if e["kind"] in reached else None
        if k and reached[k] is None:
            reached[k] = e["at"]
    return {"company": {"id": c.id, "name": c.name}, "events": ev,
            "revenue": revenue,
            "milestones": [{"key": k, "reached_at": reached[k]} for k in ORDER]}


@router.get("/dashboard/master")
def master_dashboard(workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    """One rollup across ALL sections — the master dashboard. Outbound
    (enrichment), Reply Management, Inbound visitors, and CRM in one view."""
    from ..models.enrich import EnrichLead, EnrichList
    from ..models.reply import ReplyLead
    ws_ids = ctx.workspace_ids_for_query(workspace_id)
    summary = dashboard_summary(workspace_id, ctx)

    enr = ctx.db.query(EnrichLead).filter(EnrichLead.workspace_id.in_(ws_ids))
    reply = ctx.db.query(ReplyLead).filter(ReplyLead.workspace_id.in_(ws_ids))
    visitors = (scoped(ctx.db.query(Activity), Activity, ctx, workspace_id)
                .filter(Activity.kind == "visitor").count())
    return {
        "crm": summary["totals"],
        "pipeline": summary["pipeline"],
        "open_value": summary["open_value"],
        "won_value": summary["won_value"],
        "outbound": {
            "lists": ctx.db.query(EnrichList).filter(EnrichList.workspace_id.in_(ws_ids)).count(),
            "leads": enr.count(),
            "enriched": enr.filter(EnrichLead.status == "done").count(),
            "icp": enr.filter(EnrichLead.icp_decision == "ICP").count(),
        },
        "reply": {
            "total": reply.count(),
            "needs_review": reply.filter(ReplyLead.action.in_(["skip_enrich", "would_send"]),
                                         ReplyLead.reviewed == False).count(),  # noqa: E712
            "replied": reply.filter(ReplyLead.replied == True).count(),          # noqa: E712
            "booked": reply.filter(ReplyLead.stage == "booked").count(),
        },
        "inbound": {"visitors": visitors},
        "recent_activity": summary["recent_activity"],
    }


@router.get("/dashboard/command")
def command_center(workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    """The command-center dashboard (DESIGN_SYSTEM.md Part 4, step 2): today's
    meetings, open tasks, revenue + pipeline, recent replies/clients, and every
    document waiting on an action. Flat lists, max 5-6 rows per section."""
    from datetime import timedelta

    from ..models.agreements import Agreement, Invoice
    from ..models.client_profile import ClientProfile
    from ..models.crm import Task
    from ..models.documents import Document
    from ..models.reply import ReplyLead

    ws_ids = ctx.workspace_ids_for_query(workspace_id)
    summary = dashboard_summary(workspace_id, ctx)

    now = datetime.utcnow()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    meetings = (scoped(ctx.db.query(Activity), Activity, ctx, workspace_id)
                .filter(Activity.kind.in_(["meeting_booked", "meeting_held"]),
                        Activity.occurred_at >= day_start, Activity.occurred_at < day_end)
                .order_by(Activity.occurred_at.asc()).limit(6).all())

    tasks = (ctx.db.query(Task).filter(Task.workspace_id.in_(ws_ids), Task.done == False)  # noqa: E712
             .order_by(Task.due_at.is_(None), Task.due_at.asc()).limit(6).all())

    replies = (ctx.db.query(ReplyLead).filter(ReplyLead.workspace_id.in_(ws_ids))
               .order_by(ReplyLead.id.desc()).limit(5).all())

    clients = (ctx.db.query(ClientProfile, Company)
               .join(Company, Company.id == ClientProfile.company_id)
               .filter(ClientProfile.workspace_id.in_(ws_ids))
               .order_by(ClientProfile.id.desc()).limit(5).all())

    blueprints = (scoped(ctx.db.query(Document), Document, ctx, workspace_id)
                  .filter(Document.kind == "blueprint",
                          Document.status.in_(["draft", "published", "viewed"]))
                  .order_by(Document.id.desc()).limit(5).all())

    agreements = (ctx.db.query(Agreement)
                  .filter(Agreement.workspace_id.in_(ws_ids),
                          Agreement.status.in_(["draft", "ready", "sent", "viewed", "client_signed"]))
                  .order_by(Agreement.id.desc()).limit(5).all())

    invoices = (ctx.db.query(Invoice)
                .filter(Invoice.workspace_id.in_(ws_ids),
                        Invoice.status.in_(["draft", "issued", "viewed", "partially_paid", "overdue"]))
                .order_by(Invoice.id.desc()).limit(5).all())

    needs_review = (ctx.db.query(ReplyLead)
                    .filter(ReplyLead.workspace_id.in_(ws_ids),
                            ReplyLead.action.in_(["skip_enrich", "would_send"]),
                            ReplyLead.reviewed == False).count())  # noqa: E712

    def iso(dt):
        return dt.isoformat() if dt else None

    return {
        "totals": summary["totals"],
        "open_value": summary["open_value"],
        "won_value": summary["won_value"],
        "pipeline": summary["pipeline"],
        "recent_activity": summary["recent_activity"][:8],
        "needs_review": needs_review,
        "meetings_today": [{"id": a.id, "title": a.title or "Meeting", "at": iso(a.occurred_at),
                            "kind": a.kind} for a in meetings],
        "tasks": [{"id": t.id, "title": t.title, "due_at": iso(t.due_at)} for t in tasks],
        "recent_replies": [{"id": r.id,
                            "name": (getattr(r, "name", "") or getattr(r, "email", "") or "Reply"),
                            "intent": getattr(r, "intent", "") or "",
                            "at": iso(getattr(r, "created_at", None))} for r in replies],
        "recent_clients": [{"id": p.id, "company": co.name, "active": bool(p.is_active_client),
                            "company_id": co.id} for p, co in clients],
        "blueprints_waiting": [{"id": d.id, "title": d.title or d.slug or f"Blueprint #{d.id}",
                                "status": d.status} for d in blueprints],
        "agreements_waiting": [{"id": a.id, "title": a.title or a.number or f"Agreement #{a.id}",
                                "status": a.status} for a in agreements],
        "invoices_waiting": [{"id": i.id, "title": i.number or f"Invoice #{i.id}",
                              "status": i.status} for i in invoices],
    }
