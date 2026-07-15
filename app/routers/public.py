"""Public, no-auth client pages:
- Growth Blueprint at /p/{slug} (and blueprint.<domain>/{slug}).
- Agreement at /agreement/{slug} (and agreement.<domain>/{slug}), with a
  token-guarded, rate-limited signing endpoint.
- Invoice at /invoice/{slug} (and invoice.<domain>/{slug}).

Only publicly-available records render; unknown / unpublished / voided / draft
records return 404. Internal fields never appear here. View opens are counted.
"""
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ..db import SessionLocal
from ..models.agreements import Agreement, Invoice
from ..models.crm import Company, Contact
from ..models.documents import Document

router = APIRouter(tags=["public"])

_404 = HTMLResponse(
    "<!doctype html><meta charset='utf-8'><title>Not found</title>"
    "<div style=\"font-family:-apple-system,Segoe UI,Arial;max-width:520px;margin:18vh auto;"
    "text-align:center;color:#333\"><h1 style='font-size:1.4rem'>This page isn't available</h1>"
    "<p style='color:#777'>The link may be unpublished or incorrect.</p></div>", status_code=404)


def _render_blueprint(slug: str) -> HTMLResponse:
    db = SessionLocal()
    try:
        d = (db.query(Document)
             .filter(Document.slug == slug, Document.kind == "blueprint",
                     Document.published == True)  # noqa: E712
             .first())
        if not d or not d.html:
            return _404
        now = datetime.utcnow()
        if d.last_viewed_at is None or (now - d.last_viewed_at) > timedelta(hours=6):
            d.view_count = (d.view_count or 0) + 1
            d.last_viewed_at = now
            if d.first_viewed_at is None:
                d.first_viewed_at = now
            if d.status == "published":
                d.status = "viewed"
            db.commit()
        return HTMLResponse(d.html)
    finally:
        db.close()


@router.get("/p/{slug}", include_in_schema=False)
def public_blueprint(slug: str):
    return _render_blueprint(slug)


# ============================================================ agreements
# statuses that are publicly viewable (draft/ready/voided/archived are NOT)
_AG_PUBLIC = {"sent", "viewed", "client_signed", "countersigned", "executed"}
_AG_SIGNABLE = {"sent", "viewed"}


def _render_agreement(slug: str) -> HTMLResponse:
    from ..agreements import render, service
    db = SessionLocal()
    try:
        a = db.query(Agreement).filter(Agreement.slug == slug).first()
        if not a or a.status not in _AG_PUBLIC:
            return _404
        service.track_view(db, a)
        company = db.get(Company, a.company_id) if a.company_id else None
        contact = db.get(Contact, a.contact_id) if a.contact_id else None
        signing = a.status in _AG_SIGNABLE and not a.client_signed_at
        return HTMLResponse(render.render_agreement(a, company, contact, signing=signing))
    finally:
        db.close()


@router.get("/agreement/{slug}", include_in_schema=False)
def public_agreement(slug: str):
    return _render_agreement(slug)


# ---- signing (rate-limited, token-guarded) ----
_SIGN_HITS: dict = defaultdict(lambda: deque(maxlen=20))
_RATE_MAX = 6          # max sign attempts
_RATE_WINDOW = 300     # per 5 minutes per IP


def _rate_ok(ip: str) -> bool:
    now = time.time()
    dq = _SIGN_HITS[ip]
    while dq and now - dq[0] > _RATE_WINDOW:
        dq.popleft()
    if len(dq) >= _RATE_MAX:
        return False
    dq.append(now)
    return True


def _confirm_page(a) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'><title>Signed</title>"
        "<div style=\"font-family:-apple-system,Segoe UI,Arial;max-width:560px;margin:16vh auto;"
        "text-align:center;color:#222\"><div style='font-size:2.4rem'>&#10003;</div>"
        f"<h1 style='font-size:1.5rem'>Thank you — {(a.client_signer_name or '').strip() or 'your signature'} is recorded</h1>"
        f"<p style='color:#666'>Agreement {a.number} has been signed. We'll countersign and send you the "
        "fully executed copy. You can close this page.</p></div>")


@router.post("/agreement/{token}/sign", include_in_schema=False)
def public_sign(token: str, request: Request, name: str = Form(...), email: str = Form(...),
                title: str = Form(""), consent: str = Form(""), consent_text: str = Form("")):
    from ..agreements import service
    ip = request.client.host if request.client else ""
    if not _rate_ok(ip):
        return HTMLResponse("<h1>Too many attempts</h1><p>Please wait a few minutes and try again.</p>",
                            status_code=429)
    if consent != "yes":
        return HTMLResponse("<h1>Consent required</h1><p>Please tick the consent box to sign.</p>",
                            status_code=400)
    db = SessionLocal()
    try:
        a = db.query(Agreement).filter(Agreement.public_token == token).first()
        if not a or a.status not in _AG_PUBLIC:
            return _404
        try:
            service.sign_client(db, a, name=name, email=email, title=title,
                                consent_text=consent_text, ip=ip,
                                user_agent=request.headers.get("user-agent", ""))
        except ValueError as e:
            return HTMLResponse(f"<h1>Could not sign</h1><p>{e}</p>", status_code=409)
        return _confirm_page(a)
    finally:
        db.close()


@router.get("/agreement/{slug}/pdf", include_in_schema=False)
def public_agreement_pdf(slug: str):
    from ..agreements import pdf
    db = SessionLocal()
    try:
        a = db.query(Agreement).filter(Agreement.slug == slug).first()
        if not a or not a.executed_at:      # only the executed PDF is public
            return _404
        company = db.get(Company, a.company_id) if a.company_id else None
        contact = db.get(Contact, a.contact_id) if a.contact_id else None
        data = pdf.build_agreement_pdf(a, company, contact, mode="executed")
        return Response(content=data, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{a.number}-executed.pdf"'})
    finally:
        db.close()


# ============================================================ invoices
_INV_PUBLIC = {"issued", "viewed", "partially_paid", "paid", "overdue"}


def _render_invoice(slug: str) -> HTMLResponse:
    from ..agreements import render, service
    db = SessionLocal()
    try:
        i = db.query(Invoice).filter(Invoice.slug == slug).first()
        if not i or i.status not in _INV_PUBLIC:
            return _404
        service.track_invoice_view(db, i)
        company = db.get(Company, i.company_id) if i.company_id else None
        return HTMLResponse(render.render_invoice(i, company))
    finally:
        db.close()


@router.get("/invoice/{slug}", include_in_schema=False)
def public_invoice(slug: str):
    return _render_invoice(slug)


@router.get("/invoice/{slug}/pdf", include_in_schema=False)
def public_invoice_pdf(slug: str):
    from ..agreements import pdf
    db = SessionLocal()
    try:
        i = db.query(Invoice).filter(Invoice.slug == slug).first()
        if not i or i.status not in _INV_PUBLIC:
            return _404
        company = db.get(Company, i.company_id) if i.company_id else None
        data = pdf.build_invoice_pdf(i, company)
        return Response(content=data, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{i.number}.pdf"'})
    finally:
        db.close()
