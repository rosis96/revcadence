"""Inbound capture. Two public entry points, each routed by a PER-WORKSPACE key
(multi-tenant safe — every client gets their own key/URL):
  • form    — a website form-fill (high intent) → company/contact/DEAL + a
              'respond within 10 minutes' task + enrichment. Shows in Pipeline.
  • visitor — a de-anonymized website visitor (RB2B etc.) → company/contact +
              enrichment (a signal, not a deal, to avoid pipeline spam).
The 10-minute SLA rides on the task due date + the immediate enrich job."""
import os
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import AuthContext, get_ctx, require_master, scoped
from ..models.crm import Activity, Company, Contact, Deal, Stage, Task
from ..models.identity import Workspace
from ..models.jobs import Job

router = APIRouter(prefix="/api/inbound", tags=["inbound"])


# ---------------------------------------------------------------- helpers
def _ensure_key(db, ws: Workspace) -> str:
    if not ws.inbound_key:
        ws.inbound_key = secrets.token_urlsafe(24)
        db.commit()
    return ws.inbound_key


def _resolve_ws(db, key: str, workspace_id: int = 0) -> Workspace:
    """Find the workspace for a public capture call. Prefer the per-workspace
    key; fall back to the legacy global env key + explicit workspace_id."""
    if key:
        ws = db.query(Workspace).filter(Workspace.inbound_key == key).first()
        if ws:
            return ws
    env = os.getenv("INBOUND_WEBHOOK_KEY", "")
    if env and key == env and workspace_id:
        ws = db.get(Workspace, workspace_id)
        if ws:
            return ws
    raise HTTPException(401, "Bad or missing capture key")


def _first_stage_id(db, workspace_id: int):
    s = (db.query(Stage).filter(Stage.workspace_id == workspace_id)
         .order_by(Stage.sort_order).first())
    return s.id if s else None


def _upsert_company_contact(db, workspace_id, payload):
    cname = str(payload.get("company") or payload.get("company_name") or "").strip()
    website = str(payload.get("website") or payload.get("domain") or "").strip()
    email = str(payload.get("email") or "").lower().strip()
    company = None
    if cname:
        company = (db.query(Company).filter(Company.workspace_id == workspace_id,
                                            Company.name.ilike(cname)).first())  # case-insensitive, no dup
        if company is None:
            company = Company(workspace_id=workspace_id, name=cname, website=website)
            db.add(company); db.flush()
        elif website and not company.website:
            company.website = website
    contact = None
    if email:
        contact = (db.query(Contact).filter(Contact.workspace_id == workspace_id,
                                            Contact.email == email).first())
    if contact is None and (email or payload.get("first_name") or payload.get("name")):
        nm = str(payload.get("name") or "").strip()
        fn = str(payload.get("first_name") or (nm.split(" ", 1)[0] if nm else "")).strip()
        ln = str(payload.get("last_name") or (nm.split(" ", 1)[1] if " " in nm else "")).strip()
        contact = Contact(workspace_id=workspace_id, email=email, first_name=fn, last_name=ln,
                          title=str(payload.get("title") or ""),
                          company_id=company.id if company else None, source="inbound")
        db.add(contact); db.flush()
    return company, contact


def _queue_enrich(db, workspace_id, company, contact):
    if company is not None and (company.website or company.domain):
        db.add(Job(kind="enrich_company", workspace_id=workspace_id, payload={"company_id": company.id}))
    if contact is not None:
        db.add(Job(kind="enrich_contact", workspace_id=workspace_id, payload={"contact_id": contact.id}))


# ---------------------------------------------------------------- public capture
@router.post("/form")
async def form_capture(request: Request, key: str = ""):
    """Public website-form capture. Routed by the workspace's inbound key.
    Creates a DEAL + a 10-minute response task so inbound never gets dropped."""
    from ..db import SessionLocal
    db = SessionLocal()
    try:
        ws = _resolve_ws(db, key)
        wid = ws.id
        try:
            payload = await request.json()
        except Exception:
            form = await request.form()
            payload = dict(form)
        company, contact = _upsert_company_contact(db, wid, payload)
        who = (f"{contact.first_name} {contact.last_name}".strip() if contact else "") \
            or (company.name if company else "") or str(payload.get("email") or "unknown")
        # Dedupe: reuse this contact's existing OPEN deal (repeat form-fills must not
        # spawn duplicate deals) — otherwise create a fresh Opportunity.
        deal = None
        if contact is not None:
            closed = {s.id for s in db.query(Stage).filter(
                Stage.workspace_id == wid, (Stage.is_won == True) | (Stage.is_lost == True)).all()}  # noqa: E712
            dq = db.query(Deal).filter(Deal.workspace_id == wid, Deal.contact_id == contact.id)
            if closed:
                dq = dq.filter(Deal.stage_id.notin_(closed))
            deal = dq.order_by(Deal.id.desc()).first()
        existed = deal is not None
        if deal is None:
            deal = Deal(workspace_id=wid, name=f"Inbound — {who}",
                        company_id=company.id if company else None,
                        contact_id=contact.id if contact else None,
                        stage_id=_first_stage_id(db, wid), value=0.0,
                        source="inbound_form", lead_intent="inbound",
                        next_step="Respond within 10 minutes")
            db.add(deal); db.flush()
        db.add(Task(workspace_id=wid, deal_id=deal.id, contact_id=contact.id if contact else None,
                    title="Respond to inbound lead within 10 minutes",
                    due_at=datetime.utcnow() + timedelta(minutes=10)))
        db.add(Activity(workspace_id=wid, deal_id=deal.id,
                        company_id=company.id if company else None,
                        contact_id=contact.id if contact else None,
                        kind="inbound_lead",
                        title=f"Inbound form: {who}",
                        body=str(payload.get("message") or payload.get("note") or "")[:2000],
                        data={"page": payload.get("page", ""), "source": "form", "raw": payload}))
        _queue_enrich(db, wid, company, contact)
        db.commit()
        return {"ok": True, "deal_id": deal.id, "existed": existed,
                "company_id": company.id if company else None,
                "contact_id": contact.id if contact else None}
    finally:
        db.close()


@router.post("/visitor")
async def visitor_webhook(request: Request, key: str = "", workspace_id: int = 0):
    """De-anonymized website visitor (RB2B/visitor-ID providers). Routed by the
    per-workspace key (legacy: env key + ?workspace_id=). Creates company/contact
    + enrichment — a signal, not a pipeline deal."""
    from ..db import SessionLocal
    db = SessionLocal()
    try:
        ws = _resolve_ws(db, key, workspace_id)
        wid = ws.id
        payload = await request.json()
        company, contact = _upsert_company_contact(db, wid, payload)
        if contact is not None:
            contact.source = "visitor"
        db.add(Activity(workspace_id=wid, company_id=company.id if company else None,
                        contact_id=contact.id if contact else None, kind="visitor",
                        title=f"Website visitor: {(company.name if company else '') or (contact.email if contact else 'unknown')}",
                        data={"page": payload.get("page", ""), "raw": payload}))
        _queue_enrich(db, wid, company, contact)
        db.commit()
        return {"ok": True, "company_id": company.id if company else None,
                "contact_id": contact.id if contact else None}
    finally:
        db.close()


# ---------------------------------------------------------------- authed config + list
@router.get("/config")
def inbound_config(workspace_id: int, ctx: AuthContext = Depends(get_ctx)):
    """The client's capture key + ready-to-paste form snippet."""
    ctx.require_workspace(workspace_id)
    ws = ctx.db.get(Workspace, workspace_id)
    key = _ensure_key(ctx.db, ws)
    base = os.getenv("PUBLIC_BASE_URL", "https://engine.revcadence.com")
    form_url = f"{base}/api/inbound/form?key={key}"
    snippet = (f'<form action="{form_url}" method="POST">\n'
               '  <input name="name" placeholder="Name">\n'
               '  <input name="email" placeholder="Email">\n'
               '  <input name="company" placeholder="Company">\n'
               '  <textarea name="message" placeholder="How can we help?"></textarea>\n'
               '  <button type="submit">Send</button>\n</form>')
    return {"inbound_key": key, "form_url": form_url, "form_snippet": snippet}


@router.post("/rotate")
def rotate_key(workspace_id: int, ctx: AuthContext = Depends(require_master)):
    ctx.require_workspace(workspace_id)
    ws = ctx.db.get(Workspace, workspace_id)
    ws.inbound_key = secrets.token_urlsafe(24)
    ctx.db.commit()
    return {"inbound_key": ws.inbound_key}


@router.get("/visitors")
def visitors(workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    acts = (scoped(ctx.db.query(Activity), Activity, ctx, workspace_id)
            .filter(Activity.kind.in_(["visitor", "inbound_lead"]))
            .order_by(Activity.occurred_at.desc()).limit(200).all())
    contacts = (scoped(ctx.db.query(Contact), Contact, ctx, workspace_id)
                .filter(Contact.source.in_(["visitor", "inbound"]))
                .order_by(Contact.created_at.desc()).limit(200).all())
    return {
        "events": [{"id": a.id, "title": a.title, "kind": a.kind, "company_id": a.company_id,
                    "contact_id": a.contact_id, "deal_id": a.deal_id,
                    "page": (a.data or {}).get("page", ""),
                    "at": a.occurred_at.isoformat() if a.occurred_at else None} for a in acts],
        "contacts": [{"id": c.id, "name": f"{c.first_name} {c.last_name}".strip(),
                      "email": c.email, "company_id": c.company_id, "source": c.source,
                      "revenue_score": c.revenue_score,
                      "enriched": c.revenue_score is not None} for c in contacts],
    }
