"""Invoice API — create/edit drafts, issue, record payment status, void, PDF
download, and listing. Public invoice pages live in routers/public.py."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from ..agreements import pdf, service
from ..auth import AuthContext, get_ctx, scoped
from ..models.agreements import Invoice
from ..models.crm import Company, Contact, Deal

router = APIRouter(prefix="/api", tags=["invoices"])


def _inv(ctx, invoice_id) -> Invoice:
    i = scoped(ctx.db.query(Invoice), Invoice, ctx).filter(Invoice.id == invoice_id).first()
    if not i:
        raise HTTPException(404, "Invoice not found")
    return i


def _out(i: Invoice, full=False) -> dict:
    d = {"id": i.id, "workspace_id": i.workspace_id, "company_id": i.company_id,
         "contact_id": i.contact_id, "deal_id": i.deal_id, "agreement_id": i.agreement_id,
         "number": i.number, "slug": i.slug, "status": i.status, "currency": i.currency,
         "issue_date": i.issue_date, "due_date": i.due_date,
         "subtotal": i.subtotal, "tax_amount": i.tax_amount, "discount_amount": i.discount_amount,
         "total": i.total, "amount_paid": i.amount_paid, "balance_due": i.balance_due,
         "view_count": i.view_count or 0, "public_path": f"/invoice/{i.slug}" if i.slug else "",
         "updated_at": i.updated_at.isoformat() if i.updated_at else None}
    if full:
        d.update({"bill_to_name": i.bill_to_name, "bill_to_company": i.bill_to_company,
                  "bill_to_email": i.bill_to_email, "bill_to_address": i.bill_to_address,
                  "line_items": i.line_items or [], "tax_rate": i.tax_rate,
                  "notes": i.notes, "payment_instructions": i.payment_instructions})
    return d


@router.get("/invoices")
def list_invoices(workspace_id: int | None = None, company_id: int | None = None,
                  ctx: AuthContext = Depends(get_ctx)):
    q = scoped(ctx.db.query(Invoice), Invoice, ctx, workspace_id)
    if company_id:
        q = q.filter(Invoice.company_id == company_id)
    rows = q.order_by(Invoice.updated_at.desc()).limit(200).all()
    return [_out(i) for i in rows]


class InvoiceIn(BaseModel):
    workspace_id: int | None = None
    company_id: int | None = None
    contact_id: int | None = None
    deal_id: int | None = None
    agreement_id: int | None = None
    line_items: list | None = None
    overrides: dict | None = None


@router.post("/invoices")
def create_invoice(body: InvoiceIn, ctx: AuthContext = Depends(get_ctx)):
    company = ctx.db.get(Company, body.company_id) if body.company_id else None
    wsid = body.workspace_id or (company.workspace_id if company else None)
    if not wsid:
        raise HTTPException(422, "workspace_id (or company_id) required")
    ctx.require_workspace(wsid)
    contact = ctx.db.get(Contact, body.contact_id) if body.contact_id else None
    deal = ctx.db.get(Deal, body.deal_id) if body.deal_id else None
    inv = service.create_invoice(ctx.db, wsid, company=company, contact=contact, deal=deal,
                                 line_items=body.line_items or [], overrides=body.overrides,
                                 actor_user_id=ctx.user.id)
    return _out(inv, full=True)


@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: int, ctx: AuthContext = Depends(get_ctx)):
    return _out(_inv(ctx, invoice_id), full=True)


class InvoiceEdit(BaseModel):
    line_items: list | None = None
    bill_to_name: str | None = None
    bill_to_company: str | None = None
    bill_to_email: str | None = None
    bill_to_address: str | None = None
    issue_date: str | None = None
    due_date: str | None = None
    currency: str | None = None
    tax_rate: float | None = None
    discount_amount: float | None = None
    notes: str | None = None
    payment_instructions: str | None = None


@router.put("/invoices/{invoice_id}")
def edit_invoice(invoice_id: int, body: InvoiceEdit, ctx: AuthContext = Depends(get_ctx)):
    i = _inv(ctx, invoice_id)
    if i.status in ("paid", "void"):
        raise HTTPException(409, f"Invoice is {i.status} and cannot be edited.")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(i, k, v)
    service.recompute_invoice(i)
    ctx.db.commit()
    return _out(i, full=True)


@router.post("/invoices/{invoice_id}/issue")
def issue(invoice_id: int, ctx: AuthContext = Depends(get_ctx)):
    i = _inv(ctx, invoice_id)
    try:
        service.issue_invoice(ctx.db, i, ctx.user.id)
    except ValueError as e:
        raise HTTPException(409, str(e))
    try:
        from ..extapi import events as _ev
        _ev.emit(ctx.db, i.workspace_id, "invoice.issued",
                 {"id": i.id, "number": i.number, "status": i.status, "total": i.total,
                  "currency": i.currency, "company_id": i.company_id})
    except Exception:
        pass
    return _out(i, full=True)


class PaymentIn(BaseModel):
    amount_paid: float


@router.post("/invoices/{invoice_id}/payment")
def payment(invoice_id: int, body: PaymentIn, ctx: AuthContext = Depends(get_ctx)):
    i = _inv(ctx, invoice_id)
    service.set_payment(ctx.db, i, body.amount_paid, ctx.user.id)
    try:
        if i.status == "paid":
            from ..extapi import events as _ev
            _ev.emit(ctx.db, i.workspace_id, "invoice.paid",
                     {"id": i.id, "number": i.number, "status": i.status, "total": i.total,
                      "amount_paid": i.amount_paid, "company_id": i.company_id})
    except Exception:
        pass
    return _out(i, full=True)


@router.post("/invoices/{invoice_id}/void")
def void(invoice_id: int, ctx: AuthContext = Depends(get_ctx)):
    i = _inv(ctx, invoice_id)
    service.void_invoice(ctx.db, i, ctx.user.id)
    return _out(i, full=True)


@router.get("/invoices/{invoice_id}/pdf")
def invoice_pdf(invoice_id: int, ctx: AuthContext = Depends(get_ctx)):
    i = _inv(ctx, invoice_id)
    company = ctx.db.get(Company, i.company_id) if i.company_id else None
    data = pdf.build_invoice_pdf(i, company)
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{i.number}.pdf"'})
