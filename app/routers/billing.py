"""Platform billing (master-only): track each client's subscription and see MRR.
Manual today; Stripe-ready. A subscription row is created lazily per workspace."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import AuthContext, require_master
from ..models.billing import SUB_STATUSES, Subscription
from ..models.identity import Workspace

router = APIRouter(prefix="/api/billing", tags=["billing"])


def _sub_for(db, workspace_id: int) -> Subscription:
    s = db.query(Subscription).filter(Subscription.workspace_id == workspace_id).first()
    if s is None:
        s = Subscription(workspace_id=workspace_id)
        db.add(s)
        db.commit()
    return s


def _out(s: Subscription):
    return {
        "workspace_id": s.workspace_id, "plan_name": s.plan_name or "",
        "price_monthly": s.price_monthly or 0, "status": s.status or "none",
        "started_at": s.started_at.isoformat() if s.started_at else None,
        "current_period_end": s.current_period_end.isoformat() if s.current_period_end else None,
        "notes": s.notes or "", "stripe_customer_id": s.stripe_customer_id or "",
    }


@router.get("/summary")
def billing_summary(ctx: AuthContext = Depends(require_master)):
    """MRR + status rollup + a row per client workspace (subscription created on
    first view so every workspace appears)."""
    workspaces = (ctx.db.query(Workspace).filter(Workspace.org_id == ctx.org_id)
                  .order_by(Workspace.name).all())
    rows, mrr, counts = [], 0.0, {k: 0 for k in SUB_STATUSES}
    now = datetime.utcnow()
    for w in workspaces:
        s = _sub_for(ctx.db, w.id)
        counts[s.status if s.status in counts else "none"] += 1
        if s.status in ("active", "trialing", "past_due"):
            mrr += float(s.price_monthly or 0)
        overdue = bool(s.current_period_end and s.current_period_end < now and s.status != "canceled")
        rows.append({**_out(s), "workspace_name": w.name, "overdue": overdue})
    return {
        "mrr": round(mrr), "active": counts.get("active", 0), "trialing": counts.get("trialing", 0),
        "past_due": counts.get("past_due", 0), "canceled": counts.get("canceled", 0),
        "unset": counts.get("none", 0), "clients": rows,
    }


class SubIn(BaseModel):
    plan_name: str | None = None
    price_monthly: float | None = None
    status: str | None = None
    current_period_end: str | None = None   # ISO date (YYYY-MM-DD)
    started_at: str | None = None
    notes: str | None = None


@router.put("/subscriptions/{workspace_id}")
def update_subscription(workspace_id: int, body: SubIn, ctx: AuthContext = Depends(require_master)):
    ctx.require_workspace(workspace_id)
    s = _sub_for(ctx.db, workspace_id)
    if body.plan_name is not None:
        s.plan_name = body.plan_name.strip()
    if body.price_monthly is not None:
        s.price_monthly = max(0.0, float(body.price_monthly))
    if body.status is not None:
        if body.status not in SUB_STATUSES:
            raise HTTPException(422, f"status must be one of {SUB_STATUSES}")
        s.status = body.status
        if body.status in ("active", "trialing") and not s.started_at:
            s.started_at = datetime.utcnow()

    def _parse(d):
        try:
            return datetime.fromisoformat(d.replace("Z", "")) if d else None
        except Exception:
            return None
    if body.current_period_end is not None:
        s.current_period_end = _parse(body.current_period_end)
    if body.started_at is not None:
        s.started_at = _parse(body.started_at)
    if body.notes is not None:
        s.notes = body.notes
    ctx.db.commit()
    return _out(s)
