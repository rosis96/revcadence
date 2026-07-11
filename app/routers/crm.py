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
@router.get("/companies")
def list_companies(workspace_id: int | None = None, q: str = "", ctx: AuthContext = Depends(get_ctx)):
    qry = scoped(ctx.db.query(Company), Company, ctx, workspace_id)
    if q:
        qry = qry.filter(Company.name.ilike(f"%{q}%"))
    rows = qry.order_by(Company.updated_at.desc()).limit(200).all()
    return [{"id": c.id, "workspace_id": c.workspace_id, "name": c.name, "domain": c.domain,
             "industry": c.industry, "icp_fit": c.icp_fit} for c in rows]


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


class ContactIn(BaseModel):
    workspace_id: int
    email: str = ""
    first_name: str = ""
    last_name: str = ""
    title: str = ""
    company_id: int | None = None


@router.post("/contacts")
def create_contact(body: ContactIn, ctx: AuthContext = Depends(get_ctx)):
    ctx.require_workspace(body.workspace_id)
    c = Contact(workspace_id=body.workspace_id, email=body.email.lower().strip(),
                first_name=body.first_name, last_name=body.last_name, title=body.title,
                company_id=body.company_id, source="manual")
    ctx.db.add(c)
    ctx.db.commit()
    return {"id": c.id}


# ---------------------------------------------------------------- contacts
@router.get("/contacts")
def list_contacts(workspace_id: int | None = None, q: str = "", ctx: AuthContext = Depends(get_ctx)):
    qry = scoped(ctx.db.query(Contact), Contact, ctx, workspace_id)
    if q:
        like = f"%{q}%"
        qry = qry.filter((Contact.email.ilike(like)) | (Contact.first_name.ilike(like)) | (Contact.last_name.ilike(like)))
    rows = qry.order_by(Contact.updated_at.desc()).limit(200).all()
    return [{"id": c.id, "workspace_id": c.workspace_id, "email": c.email,
             "name": f"{c.first_name} {c.last_name}".strip(), "title": c.title,
             "company_id": c.company_id, "email_status": c.email_status,
             "revenue_score": c.revenue_score, "source": c.source} for c in rows]


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


@router.get("/deals/board")
def deals_board(workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    """Kanban data: stages with deal cards + per-column totals (the Instantly-style
    '$140,000 · 28 deals' headers)."""
    ws_ids = ctx.workspace_ids_for_query(workspace_id)
    stages = ctx.db.query(Stage).filter(Stage.workspace_id.in_(ws_ids)).order_by(Stage.sort_order).all()
    deals = scoped(ctx.db.query(Deal), Deal, ctx, workspace_id).all()
    by_stage: dict = {}
    for d in deals:
        by_stage.setdefault(d.stage_id, []).append(d)
    out = []
    for s in stages:
        cards = by_stage.get(s.id, [])
        out.append({
            "stage": {"id": s.id, "name": s.name, "color": s.color, "is_won": s.is_won, "is_lost": s.is_lost},
            "count": len(cards),
            "total_value": sum(d.value or 0 for d in cards),
            "deals": [{"id": d.id, "name": d.name, "value": d.value, "contact_id": d.contact_id} for d in cards],
        })
    return out


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
    ctx.db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- dashboard
@router.get("/dashboard/summary")
def dashboard_summary(workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    """The client-shareable rollup: pipeline by stage, totals, recent activity."""
    board = deals_board(workspace_id, ctx)
    recent = (scoped(ctx.db.query(Activity), Activity, ctx, workspace_id)
              .order_by(Activity.occurred_at.desc()).limit(20).all())
    return {
        "pipeline": [{"stage": b["stage"]["name"], "count": b["count"], "value": b["total_value"]} for b in board],
        "open_value": sum(b["total_value"] for b in board if not b["stage"]["is_won"] and not b["stage"]["is_lost"]),
        "won_value": sum(b["total_value"] for b in board if b["stage"]["is_won"]),
        "recent_activity": [{"kind": a.kind, "title": a.title,
                             "at": a.occurred_at.isoformat() if a.occurred_at else None} for a in recent],
    }
