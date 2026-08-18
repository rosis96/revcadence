"""Onboarding API.

Public (token link — no login; this is what the client fills):
  GET  /api/onboarding/form/{token}          → form schema + saved draft
  POST /api/onboarding/form/{token}/save     → save draft (partial)
  POST /api/onboarding/form/{token}/submit    → submit + auto-wire the workspace

Admin (master):
  POST /api/onboarding                        → create an onboarding + link
  GET  /api/onboarding                        → list with status + progress
  GET  /api/onboarding/{id}                   → submitted data + checklist
"""
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import AuthContext, get_ctx
from ..crypto import encrypt
from ..db import get_db
from ..models.onboarding import MailboxConnection, Onboarding
from fastapi import Request  # noqa: E402

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])

# The form definition — sections + fields. `secret: true` fields are never
# returned on GET. Rendered by the public form page.
FORM = [
    {"section": "Company & brand", "fields": [
        {"key": "company_name", "label": "Company name", "type": "text", "required": True},
        {"key": "website", "label": "Company website", "type": "url", "required": True, "placeholder": "https://…"},
        {"key": "industry", "label": "Industry", "type": "text"},
    ]},
    {"section": "Primary contact", "fields": [
        {"key": "contact_name", "label": "Your full name", "type": "text", "required": True},
        {"key": "contact_email", "label": "Your email", "type": "email", "required": True},
        {"key": "contact_role", "label": "Your role", "type": "text"},
    ]},
    {"section": "Who you sell to (ICP)", "fields": [
        {"key": "icp", "label": "Describe your ideal customer", "type": "textarea", "required": True,
         "hint": "Industries, company size, roles you sell to."},
        {"key": "non_icp", "label": "Who is NOT a fit (exclusions)", "type": "textarea"},
    ]},
    {"section": "Your offer", "fields": [
        {"key": "main_offer", "label": "What you sell (main offer)", "type": "textarea", "required": True},
        {"key": "value_prop", "label": "The outcome / value you deliver", "type": "textarea"},
    ]},
    {"section": "Sending mailbox (powers follow-ups & your unified inbox)", "fields": [
        {"key": "mailbox_email", "label": "Sending email address", "type": "email",
         "placeholder": "sales@yourdomain.com",
         "hint": "The mailbox we send follow-ups from and show in your Unibox."},
        {"key": "mailbox_app_password", "label": "App password", "type": "password", "secret": True,
         "hint": "Gmail: enable 2FA, then create an app password. We store it encrypted."},
    ]},
    {"section": "Scheduling", "fields": [
        {"key": "calendly_url", "label": "Calendly scheduling link", "type": "url",
         "placeholder": "https://calendly.com/you/intro"},
        {"key": "calendly_token", "label": "Calendly token (optional)", "type": "password", "secret": True},
    ]},
    {"section": "Features you want", "fields": [
        {"key": "want_proposals", "label": "Send proposals for me", "type": "toggle", "default": True},
        {"key": "want_agreements", "label": "Send agreements", "type": "toggle", "default": True},
        {"key": "want_esign", "label": "Collect e-signatures", "type": "toggle", "default": True},
    ]},
    {"section": "Anything else", "fields": [
        {"key": "notes", "label": "Notes for our team", "type": "textarea"},
    ]},
]
SECRET_KEYS = {f["key"] for sec in FORM for f in sec["fields"] if f.get("secret")}
ALL_KEYS = {f["key"] for sec in FORM for f in sec["fields"]}


def _public_data(o: Onboarding) -> dict:
    """Drop secret values before sending to the browser."""
    return {k: v for k, v in (o.data or {}).items() if k not in SECRET_KEYS}


def _checklist(o: Onboarding) -> list:
    d = o.data or {}
    def has(*keys):
        return all(str(d.get(k, "")).strip() for k in keys)
    return [
        {"key": "company", "label": "Company & website", "done": has("company_name", "website")},
        {"key": "contact", "label": "Primary contact", "done": has("contact_name", "contact_email")},
        {"key": "icp", "label": "ICP defined", "done": has("icp")},
        {"key": "offer", "label": "Offer defined", "done": has("main_offer")},
        {"key": "mailbox", "label": "Sending mailbox connected",
         "done": bool(d.get("mailbox_email")) and bool(d.get("_mailbox_connected"))},
        {"key": "calendly", "label": "Calendly linked", "done": has("calendly_url")},
        {"key": "features", "label": "Features chosen", "done": True},
    ]


# ================================================================ public (token)
def _get_by_token(db, token) -> Onboarding:
    o = db.query(Onboarding).filter(Onboarding.token == token).first()
    if not o:
        raise HTTPException(404, "Onboarding link not found")
    return o


@router.get("/form/{token}")
def get_form(token: str, db=Depends(get_db)):
    from ..models.identity import Workspace
    o = _get_by_token(db, token)
    ws = db.get(Workspace, o.workspace_id)
    return {"form": FORM, "status": o.status, "data": _public_data(o),
            "secret_set": {k: bool((o.data or {}).get(k)) for k in SECRET_KEYS},
            "workspace_name": ws.name if ws else ""}


class SaveIn(BaseModel):
    data: dict


def _merge(o: Onboarding, incoming: dict):
    cur = dict(o.data or {})
    for k, v in incoming.items():
        if k not in ALL_KEYS:
            continue
        if k in SECRET_KEYS and v == "":
            continue  # blank secret = keep existing
        cur[k] = v
    o.data = cur


@router.post("/form/{token}/save")
def save_form(token: str, body: SaveIn, db=Depends(get_db)):
    o = _get_by_token(db, token)
    if o.status == "submitted":
        raise HTTPException(409, "This onboarding was already submitted.")
    _merge(o, body.data)
    o.updated_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "saved": True}


@router.post("/form/{token}/submit")
def submit_form(token: str, body: SaveIn, db=Depends(get_db)):
    o = _get_by_token(db, token)
    if o.status == "submitted":
        raise HTTPException(409, "Already submitted.")
    _merge(o, body.data)
    d = o.data or {}
    missing = [f["label"] for sec in FORM for f in sec["fields"]
               if f.get("required") and not str(d.get(f["key"], "")).strip()]
    if missing:
        raise HTTPException(422, f"Please complete: {', '.join(missing)}")
    _auto_wire(db, o)
    o.status = "submitted"
    o.submitted_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "submitted": True}


def _auto_wire(db, o: Onboarding):
    """Map the answers into the system so nothing is set up by hand."""
    from ..enrichment.pipeline import _config
    from ..models.identity import Workspace
    from ..models.reply import ReplyWorkspace
    d = o.data or {}
    wsid = o.workspace_id
    profile = {
        "client_name": d.get("company_name", ""),
        "service_brief": d.get("main_offer", ""),
        "main_offer": d.get("main_offer", ""),
        "value_prop": d.get("value_prop", ""),
        "icp_summary": d.get("icp", ""),
        "website": d.get("website", ""),
    }
    # enrichment config
    cfg = _config(db, wsid)
    cfg.profile = {**(cfg.profile or {}), **{k: v for k, v in profile.items() if v}}
    if d.get("icp"):
        cfg.icp_definition = cfg.icp_definition or d["icp"]
    # reply space (primary)
    rws = (db.query(ReplyWorkspace).filter(ReplyWorkspace.workspace_id == wsid)
           .order_by(ReplyWorkspace.id).first())
    if rws:
        rws.client_profile = {**(rws.client_profile or {}), **{k: v for k, v in profile.items() if v}}
        if d.get("website") and not rws.website:
            rws.website = d["website"]
        if d.get("contact_name") and not rws.sender_name:
            rws.sender_name = d["contact_name"]
        if d.get("calendly_url") and not rws.calendly_scheduling_url:
            rws.calendly_scheduling_url = d["calendly_url"]
        if d.get("calendly_token"):
            rws.calendly_token_enc = encrypt(d["calendly_token"])
    # feature toggles onto the workspace settings
    ws = db.get(Workspace, wsid)
    if ws:
        s = dict(ws.settings or {})
        s["features"] = {"proposals": bool(d.get("want_proposals", True)),
                         "agreements": bool(d.get("want_agreements", True)),
                         "esign": bool(d.get("want_esign", True))}
        ws.settings = s
    # mailbox connection (Unibox + follow-up sender)
    if d.get("mailbox_email") and d.get("mailbox_app_password"):
        mc = db.query(MailboxConnection).filter(MailboxConnection.workspace_id == wsid,
                                                MailboxConnection.email == d["mailbox_email"]).first()
        if mc is None:
            mc = MailboxConnection(workspace_id=wsid, email=d["mailbox_email"])
            db.add(mc)
        mc.app_password_enc = encrypt(d["mailbox_app_password"])
        mc.active = True
        d["_mailbox_connected"] = True
        o.data = d
    db.flush()


# ================================================================ admin
class CreateIn(BaseModel):
    workspace_id: int


@router.post("")
def create_onboarding(body: CreateIn, request: Request, ctx: AuthContext = Depends(get_ctx)):
    ctx.require_workspace(body.workspace_id)
    o = Onboarding(workspace_id=body.workspace_id, token=secrets.token_urlsafe(24))
    ctx.db.add(o)
    ctx.db.commit()
    base = str(request.base_url).rstrip("/")
    return {"id": o.id, "token": o.token, "link": f"{base}/#/onboard/{o.token}"}


@router.get("")
def list_onboardings(workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    ws_ids = ctx.workspace_ids_for_query(workspace_id)
    from ..models.identity import Workspace
    rows = ctx.db.query(Onboarding).filter(Onboarding.workspace_id.in_(ws_ids)).order_by(Onboarding.id.desc()).all()
    names = {w.id: w.name for w in ctx.db.query(Workspace).filter(Workspace.id.in_(ws_ids)).all()}
    out = []
    for o in rows:
        done = sum(1 for c in _checklist(o) if c["done"])
        out.append({"id": o.id, "workspace_id": o.workspace_id,
                    "workspace_name": names.get(o.workspace_id, ""), "status": o.status,
                    "token": o.token, "progress": f"{done}/{len(_checklist(o))}",
                    "submitted_at": o.submitted_at.isoformat() if o.submitted_at else None})
    return out


@router.get("/{oid}")
def onboarding_detail(oid: int, ctx: AuthContext = Depends(get_ctx)):
    o = ctx.db.get(Onboarding, oid)
    if not o:
        raise HTTPException(404, "Not found")
    ctx.require_workspace(o.workspace_id)
    return {"id": o.id, "workspace_id": o.workspace_id, "status": o.status,
            "data": _public_data(o), "checklist": _checklist(o),
            "secret_set": {k: bool((o.data or {}).get(k)) for k in SECRET_KEYS},
            "submitted_at": o.submitted_at.isoformat() if o.submitted_at else None}
