"""Client Profile API — the operational source of truth per company. Structured
sections (with provenance), scope-specific onboarding, and manual approve.
Workspace-isolated: a profile is only visible/editable within its workspace."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import AuthContext, get_ctx
from ..client import profiles as P
from ..client import schema
from ..models.client_profile import ClientProfile
from ..models.crm import Activity, Company

router = APIRouter(prefix="/api/client-profiles", tags=["client-profile"])


def _get(ctx: AuthContext, company_id: int) -> ClientProfile:
    co = ctx.db.get(Company, company_id)
    if not co or co.workspace_id not in ctx.allowed_workspace_ids():
        raise HTTPException(404, "Company not found")
    p = ctx.db.query(ClientProfile).filter(ClientProfile.company_id == company_id).first()
    return p


def _out(p: ClientProfile) -> dict:
    return {
        "id": p.id, "workspace_id": p.workspace_id, "company_id": p.company_id,
        "contact_id": p.contact_id, "deal_id": p.deal_id,
        "blueprint_doc_id": p.blueprint_doc_id, "agreement_doc_id": p.agreement_doc_id,
        "is_active_client": bool(p.is_active_client), "scope_type": p.scope_type,
        "onboarding_status": p.onboarding_status, "onboarding_token": p.onboarding_token,
        "onboarding_form": p.onboarding_form or {}, "completeness": p.completeness or 0,
        "review_flags": p.review_flags or [], "data": p.data or {},
        "submissions_count": len(p.onboarding_submissions or []),
        "sections": [{"key": k, "label": v[0],
                      "fields": [{"key": fk, "label": fl, "visibility": vis} for fk, fl, vis in v[1]]}
                     for k, v in schema.SECTIONS.items()],
    }


def _fval(p, section, field):
    return (((p.data or {}).get(section, {}) or {}).get(field, {}) or {}).get("value", "")


@router.get("")
def list_clients(workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    """The Clients section: every closed-won / active client in the workspace with
    a delivery-focused summary (scope, onboarding %, start date, pricing, payment)."""
    ws_ids = ctx.workspace_ids_for_query(workspace_id)
    q = (ctx.db.query(ClientProfile, Company.name)
         .join(Company, Company.id == ClientProfile.company_id)
         .filter(ClientProfile.workspace_id.in_(ws_ids))
         .order_by(ClientProfile.updated_at.desc()))
    out = []
    for p, cname in q.all():
        out.append({
            "company_id": p.company_id, "company_name": cname, "workspace_id": p.workspace_id,
            "is_active_client": bool(p.is_active_client), "scope_type": p.scope_type,
            "onboarding_status": p.onboarding_status, "completeness": p.completeness or 0,
            "review_flags": len(p.review_flags or []),
            "start_date": _fval(p, "delivery_scope", "start_date"),
            "pricing": _fval(p, "delivery_scope", "pricing"),
            "payment_status": _fval(p, "delivery_scope", "payment_status"),
            "blueprint_doc_id": p.blueprint_doc_id, "agreement_doc_id": p.agreement_doc_id,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        })
    return out


@router.get("/{company_id}")
def get_profile(company_id: int, ctx: AuthContext = Depends(get_ctx)):
    p = _get(ctx, company_id)
    if not p:
        raise HTTPException(404, "No client profile yet")
    return _out(p)


class ActivateIn(BaseModel):
    deal_id: int | None = None


@router.post("/{company_id}/activate")
def activate(company_id: int, body: ActivateIn, ctx: AuthContext = Depends(get_ctx)):
    """Manually create/refresh the profile (same idempotent path as Closed Won)."""
    co = ctx.db.get(Company, company_id)
    if not co or co.workspace_id not in ctx.allowed_workspace_ids():
        raise HTTPException(404, "Company not found")
    p = P.ensure_profile(ctx.db, company_id, body.deal_id, ctx.user.id)
    return _out(p)


class FieldIn(BaseModel):
    section: str
    field: str
    value: str = ""
    visibility: str | None = None


@router.put("/{company_id}/field")
def set_field(company_id: int, body: FieldIn, ctx: AuthContext = Depends(get_ctx)):
    p = _get(ctx, company_id)
    if not p:
        raise HTTPException(404, "No client profile yet")
    if not schema.field_meta(f"{body.section}.{body.field}"):
        raise HTTPException(422, "Unknown field")
    P.set_field(p, body.section, body.field, body.value, source="manual",
                by=ctx.user.id, visibility=body.visibility, overwrite=True)
    p.completeness = P.compute_completeness(p)
    ctx.db.commit()
    return _out(p)


class ScopeIn(BaseModel):
    scope_type: str


@router.put("/{company_id}/scope")
def set_scope(company_id: int, body: ScopeIn, ctx: AuthContext = Depends(get_ctx)):
    p = _get(ctx, company_id)
    if not p:
        raise HTTPException(404, "No client profile yet")
    if body.scope_type not in ("outbound", "inbound", "full"):
        raise HTTPException(422, "bad scope_type")
    p.scope_type = body.scope_type
    p.onboarding_form = schema.build_onboarding_form(body.scope_type)
    p.completeness = P.compute_completeness(p)
    ctx.db.commit()
    return _out(p)


class SubmitIn(BaseModel):
    answers: dict
    submitted_by: str = "internal"


@router.post("/{company_id}/onboarding-submit")
def onboarding_submit(company_id: int, body: SubmitIn, ctx: AuthContext = Depends(get_ctx)):
    p = _get(ctx, company_id)
    if not p:
        raise HTTPException(404, "No client profile yet")
    res = P.submit_onboarding(ctx.db, p, body.answers, body.submitted_by)
    return {**res, **_out(p)}


@router.post("/{company_id}/approve")
def approve(company_id: int, ctx: AuthContext = Depends(get_ctx)):
    p = _get(ctx, company_id)
    if not p:
        raise HTTPException(404, "No client profile yet")
    p.onboarding_status = "approved"
    ctx.db.add(Activity(workspace_id=p.workspace_id, company_id=company_id, kind="client_profile_approved",
                        title="Client profile approved", actor_user_id=ctx.user.id))
    ctx.db.commit()
    return _out(p)


class ResolveFlagIn(BaseModel):
    index: int
    accept: bool = False   # accept=True overwrites the field with the submitted value


@router.post("/{company_id}/resolve-flag")
def resolve_flag(company_id: int, body: ResolveFlagIn, ctx: AuthContext = Depends(get_ctx)):
    p = _get(ctx, company_id)
    if not p:
        raise HTTPException(404, "No client profile yet")
    flags = list(p.review_flags or [])
    if body.index < 0 or body.index >= len(flags):
        raise HTTPException(422, "bad flag index")
    f = flags.pop(body.index)
    if body.accept and "." in f.get("field", ""):
        sec, fld = f["field"].split(".", 1)
        P.set_field(p, sec, fld, f.get("submitted", ""), "onboarding-review", ctx.user.id, overwrite=True)
    p.review_flags = flags
    p.completeness = P.compute_completeness(p)
    ctx.db.commit()
    return _out(p)
