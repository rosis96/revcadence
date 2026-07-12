"""Inbound: website-visitor capture ONLY (per product decision — replies live in
Reply Management). Pipeline: visitor webhook → company/contact created →
auto-enrich queued → shows in Visitors. The 10-minute draft-email SLA rides on
the job queue (enrich job runs immediately)."""
import os

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import AuthContext, get_ctx, scoped
from ..models.crm import Activity, Company, Contact
from ..models.jobs import Job

router = APIRouter(prefix="/api/inbound", tags=["inbound"])


@router.post("/visitor")
async def visitor_webhook(request: Request, key: str = "", workspace_id: int = 0):
    """Public webhook for RB2B/visitor-ID providers. Auth: ?key= must equal
    INBOUND_WEBHOOK_KEY env. Payload (tolerant): {company, website/domain,
    first_name, last_name, email, title, page, ...}"""
    expected = os.getenv("INBOUND_WEBHOOK_KEY", "")
    if not expected or key != expected:
        raise HTTPException(401, "Bad or missing ?key= (set INBOUND_WEBHOOK_KEY)")
    if not workspace_id:
        raise HTTPException(422, "?workspace_id= required")
    payload = await request.json()
    from ..db import SessionLocal
    db = SessionLocal()
    try:
        cname = str(payload.get("company") or payload.get("company_name") or "").strip()
        website = str(payload.get("website") or payload.get("domain") or "").strip()
        email = str(payload.get("email") or "").lower().strip()
        company = None
        if cname:
            company = (db.query(Company).filter(Company.workspace_id == workspace_id,
                                                Company.name == cname).first())
            if company is None:
                company = Company(workspace_id=workspace_id, name=cname, website=website)
                db.add(company)
                db.flush()
        contact = None
        if email:
            contact = (db.query(Contact).filter(Contact.workspace_id == workspace_id,
                                                Contact.email == email).first())
        if contact is None and (email or payload.get("first_name")):
            contact = Contact(workspace_id=workspace_id, email=email,
                              first_name=str(payload.get("first_name") or ""),
                              last_name=str(payload.get("last_name") or ""),
                              title=str(payload.get("title") or ""),
                              company_id=company.id if company else None, source="visitor")
            db.add(contact)
            db.flush()
        db.add(Activity(workspace_id=workspace_id,
                        company_id=company.id if company else None,
                        contact_id=contact.id if contact else None,
                        kind="visitor", title=f"Website visitor: {cname or email or 'unknown'}",
                        data={"page": payload.get("page", ""), "raw": payload}))
        jobs = []
        if company is not None and (company.website or company.domain):
            j = Job(kind="enrich_company", workspace_id=workspace_id,
                    payload={"company_id": company.id})
            db.add(j); jobs.append("company")
        if contact is not None:
            j = Job(kind="enrich_contact", workspace_id=workspace_id,
                    payload={"contact_id": contact.id})
            db.add(j); jobs.append("contact")
        db.commit()
        return {"ok": True, "company_id": company.id if company else None,
                "contact_id": contact.id if contact else None, "enrich_queued": jobs}
    finally:
        db.close()


@router.get("/visitors")
def visitors(workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    acts = (scoped(ctx.db.query(Activity), Activity, ctx, workspace_id)
            .filter(Activity.kind == "visitor")
            .order_by(Activity.occurred_at.desc()).limit(200).all())
    contacts = (scoped(ctx.db.query(Contact), Contact, ctx, workspace_id)
                .filter(Contact.source == "visitor")
                .order_by(Contact.created_at.desc()).limit(200).all())
    return {
        "webhook_hint": "/api/inbound/visitor?key=<INBOUND_WEBHOOK_KEY>&workspace_id=<id>",
        "events": [{"id": a.id, "title": a.title, "company_id": a.company_id,
                    "contact_id": a.contact_id, "page": (a.data or {}).get("page", ""),
                    "at": a.occurred_at.isoformat() if a.occurred_at else None} for a in acts],
        "contacts": [{"id": c.id, "name": f"{c.first_name} {c.last_name}".strip(),
                      "email": c.email, "company_id": c.company_id,
                      "revenue_score": c.revenue_score,
                      "enriched": c.revenue_score is not None} for c in contacts],
    }
