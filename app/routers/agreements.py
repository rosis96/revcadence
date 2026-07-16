"""Agreement API — generation, structured editing, versioning, the internal
countersign flow, execution, PDF downloads, and invoice creation from approved
terms. Public client-signing lives in routers/public.py (no auth)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from ..agreements import pdf, service
from ..auth import AuthContext, get_ctx, require_master, scoped
from ..models.agreements import Agreement
from ..models.client_profile import ClientProfile
from ..models.crm import Company, Contact, Deal
from ..models.documents import Document

router = APIRouter(prefix="/api", tags=["agreements"])


def _ag(ctx, agreement_id) -> Agreement:
    a = scoped(ctx.db.query(Agreement), Agreement, ctx).filter(Agreement.id == agreement_id).first()
    if not a:
        raise HTTPException(404, "Agreement not found")
    return a


def _out(a: Agreement, full=False) -> dict:
    d = {"id": a.id, "workspace_id": a.workspace_id, "company_id": a.company_id,
         "contact_id": a.contact_id, "deal_id": a.deal_id, "blueprint_doc_id": a.blueprint_doc_id,
         "client_profile_id": a.client_profile_id, "number": a.number, "title": a.title,
         "slug": a.slug, "status": a.status, "version": a.version, "root_id": a.root_id,
         "is_current": bool(a.is_current), "supersedes_id": a.supersedes_id,
         "missing_flags": a.missing_flags or [], "locked": bool(a.locked),
         "client_signed_at": a.client_signed_at.isoformat() if a.client_signed_at else None,
         "countersigned_at": a.countersigned_at.isoformat() if a.countersigned_at else None,
         "executed_at": a.executed_at.isoformat() if a.executed_at else None,
         "client_signer_name": a.client_signer_name, "counter_signer_name": a.counter_signer_name,
         "view_count": a.view_count or 0, "checksum": a.checksum or "",
         "public_path": f"/agreement/{a.slug}" if a.slug else "",
         "updated_at": a.updated_at.isoformat() if a.updated_at else None}
    if full:
        d.update({"sections": a.sections or [], "fields": a.fields or {}, "html": a.html,
                  "client_signer_email": a.client_signer_email, "client_signer_title": a.client_signer_title,
                  "counter_signer_email": a.counter_signer_email, "counter_signer_title": a.counter_signer_title})
    return d


@router.get("/agreements")
def list_agreements(workspace_id: int | None = None, company_id: int | None = None,
                    deal_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    q = scoped(ctx.db.query(Agreement), Agreement, ctx, workspace_id)
    if company_id:
        q = q.filter(Agreement.company_id == company_id)
    if deal_id:
        q = q.filter(Agreement.deal_id == deal_id)
    rows = q.order_by(Agreement.updated_at.desc()).limit(200).all()
    return [_out(a) for a in rows]


class GenerateIn(BaseModel):
    workspace_id: int | None = None
    company_id: int | None = None
    contact_id: int | None = None
    deal_id: int | None = None
    blueprint_id: int | None = None
    title: str | None = None
    notes: str = ""
    overrides: dict | None = None


@router.post("/agreements/generate")
def generate(body: GenerateIn, ctx: AuthContext = Depends(get_ctx)):
    company = ctx.db.get(Company, body.company_id) if body.company_id else None
    deal = ctx.db.get(Deal, body.deal_id) if body.deal_id else None
    if deal and not company and deal.company_id:
        company = ctx.db.get(Company, deal.company_id)
    wsid = body.workspace_id or (company.workspace_id if company else None) or (deal.workspace_id if deal else None)
    if not wsid:
        raise HTTPException(422, "workspace_id (or a company/deal) is required")
    ctx.require_workspace(wsid)
    contact = ctx.db.get(Contact, body.contact_id) if body.contact_id else \
        (ctx.db.get(Contact, deal.contact_id) if deal and deal.contact_id else None)
    blueprint = ctx.db.get(Document, body.blueprint_id) if body.blueprint_id else \
        (ctx.db.query(Document).filter(Document.company_id == company.id, Document.kind == "blueprint")
         .order_by(Document.updated_at.desc()).first() if company else None)
    profile = ctx.db.query(ClientProfile).filter(ClientProfile.company_id == company.id).first() if company else None
    overrides = dict(body.overrides or {})
    if body.title:
        overrides["title"] = body.title
    a = service.generate_agreement(ctx.db, wsid, company=company, contact=contact, deal=deal,
                                   blueprint=blueprint, profile=profile, notes=body.notes,
                                   overrides=overrides, actor_user_id=ctx.user.id)
    return _out(a, full=True)


@router.get("/agreements/{agreement_id}")
def get_agreement(agreement_id: int, ctx: AuthContext = Depends(get_ctx)):
    return _out(_ag(ctx, agreement_id), full=True)


@router.get("/agreements/{agreement_id}/versions")
def versions(agreement_id: int, ctx: AuthContext = Depends(get_ctx)):
    a = _ag(ctx, agreement_id)
    root = a.root_id or a.id
    rows = (scoped(ctx.db.query(Agreement), Agreement, ctx)
            .filter((Agreement.root_id == root) | (Agreement.id == root))
            .order_by(Agreement.version).all())
    return [_out(v) for v in rows]


class EditIn(BaseModel):
    title: str | None = None
    sections: list | None = None
    fields: dict | None = None


@router.put("/agreements/{agreement_id}")
def edit(agreement_id: int, body: EditIn, ctx: AuthContext = Depends(get_ctx)):
    a = _ag(ctx, agreement_id)
    try:
        service.update_sections(ctx.db, a, sections=body.sections, fields=body.fields,
                                title=body.title, actor_user_id=ctx.user.id)
    except PermissionError as e:
        raise HTTPException(409, str(e))
    return _out(a, full=True)


class StatusIn(BaseModel):
    status: str


@router.post("/agreements/{agreement_id}/status")
def status(agreement_id: int, body: StatusIn, ctx: AuthContext = Depends(get_ctx)):
    a = _ag(ctx, agreement_id)
    try:
        if body.status == "voided":
            service.void(ctx.db, a, ctx.user.id)
        else:
            service.set_status(ctx.db, a, body.status, ctx.user.id)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return _out(a, full=True)


@router.post("/agreements/{agreement_id}/send")
def send(agreement_id: int, ctx: AuthContext = Depends(get_ctx)):
    a = _ag(ctx, agreement_id)
    try:
        service.send(ctx.db, a, ctx.user.id)
    except ValueError as e:
        raise HTTPException(409, str(e))
    try:
        from ..extapi import events as _ev
        _ev.emit(ctx.db, a.workspace_id, "agreement.sent",
                 {"id": a.id, "number": a.number, "title": a.title, "status": a.status,
                  "company_id": a.company_id, "deal_id": a.deal_id})
    except Exception:
        pass
    return _out(a, full=True)


class CountersignIn(BaseModel):
    name: str
    email: str = ""
    title: str = ""


@router.post("/agreements/{agreement_id}/countersign")
def countersign(agreement_id: int, body: CountersignIn, request: Request,
                ctx: AuthContext = Depends(require_master)):
    a = _ag(ctx, agreement_id)
    try:
        service.countersign(ctx.db, a, ctx.user, body.name, body.email or ctx.user.email,
                            body.title, ip=(request.client.host if request.client else ""),
                            user_agent=request.headers.get("user-agent", ""))
    except ValueError as e:
        raise HTTPException(409, str(e))
    try:
        from ..extapi import events as _ev
        _ev.emit(ctx.db, a.workspace_id, "agreement.executed",
                 {"id": a.id, "number": a.number, "title": a.title, "status": a.status,
                  "company_id": a.company_id, "deal_id": a.deal_id})
    except Exception:
        pass
    return _out(a, full=True)


@router.post("/agreements/{agreement_id}/version")
def make_version(agreement_id: int, ctx: AuthContext = Depends(get_ctx)):
    a = _ag(ctx, agreement_id)
    nv = service.new_version(ctx.db, a, ctx.user.id)
    return _out(nv, full=True)


@router.delete("/agreements/{agreement_id}")
def delete_agreement(agreement_id: int, ctx: AuthContext = Depends(get_ctx)):
    a = _ag(ctx, agreement_id)
    if a.status == "executed":
        raise HTTPException(409, "Executed agreements are locked; archive instead of deleting.")
    ctx.db.delete(a)
    ctx.db.commit()
    return {"ok": True}


@router.get("/agreements/{agreement_id}/pdf")
def agreement_pdf(agreement_id: int, mode: str = "draft", ctx: AuthContext = Depends(get_ctx)):
    a = _ag(ctx, agreement_id)
    if mode == "executed" and not a.executed_at:
        raise HTTPException(409, "Agreement is not executed yet.")
    company = ctx.db.get(Company, a.company_id) if a.company_id else None
    contact = ctx.db.get(Contact, a.contact_id) if a.contact_id else None
    data = pdf.build_agreement_pdf(a, company, contact, mode=mode)
    fname = f"{a.number}-{mode}.pdf"
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ---- invoice from agreement --------------------------------------------------
class InvoiceFromIn(BaseModel):
    overrides: dict | None = None


@router.post("/agreements/{agreement_id}/invoice")
def invoice_from(agreement_id: int, body: InvoiceFromIn, ctx: AuthContext = Depends(get_ctx)):
    from .invoices import _out as inv_out
    a = _ag(ctx, agreement_id)
    inv = service.invoice_from_agreement(ctx.db, a, overrides=body.overrides, actor_user_id=ctx.user.id)
    return inv_out(inv, full=True)
