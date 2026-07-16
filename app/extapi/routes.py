"""The client-facing external API, mounted at /api/v1 as its own FastAPI app so
its OpenAPI (/api/v1/openapi.json, /api/v1/docs) contains ONLY these endpoints.

Auth:  Authorization: Bearer rck_...   (workspace API key; hashed at rest)
Every request is workspace-scoped by the key. Consistent error envelope:
{"error": {"code": "...", "message": "..."}}."""
import time
from datetime import datetime

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..db import SessionLocal as session_factory
from ..models.crm import Activity, Company, Contact, Deal, Stage
from ..models.devapi import ApiKey, ApiRequestLog, IdempotencyRecord
from ..models.documents import Document
from ..models.reply import ReplyLead
from .security import key_prefix_of, rate_limit_check, verify_api_key
from . import events

extapp = FastAPI(
    title="RevCadence API",
    version="v1",
    description=(
        "RevCadence works alongside your existing CRM. Authenticate with a workspace "
        "API key (`Authorization: Bearer rck_...`). All data is scoped to your "
        "workspace. Writes accept an `Idempotency-Key` header. List endpoints support "
        "`page`, `page_size` (max 100), `sort` (`field:asc|desc`), `updated_since` "
        "(ISO 8601) and `external_id`. Rate limits: 120 requests/minute per key."
    ),
    docs_url="/docs", openapi_url="/openapi.json", redoc_url=None,
)


def err(status: int, code: str, message: str):
    return HTTPException(status, detail={"code": code, "message": message})


@extapp.exception_handler(HTTPException)
async def _err_handler(_req, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"code": "error", "message": str(exc.detail)}
    return JSONResponse(status_code=exc.status_code, content={"error": detail},
                        headers=getattr(exc, "headers", None))


# ---------------------------------------------------------------- auth dependency
class ApiCtx:
    def __init__(self, db, key: ApiKey):
        self.db = db
        self.key = key
        self.workspace_id = key.workspace_id

    def require(self, scope: str):
        if scope not in (self.key.scopes or []):
            raise err(403, "missing_scope", f"This key does not have the '{scope}' scope.")


def get_api_ctx(request: Request, authorization: str = Header(default="")) -> ApiCtx:
    token = ""
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    token = token or request.headers.get("x-api-key", "")
    if not token.startswith("rck_"):
        raise err(401, "missing_key", "Provide a workspace API key: Authorization: Bearer rck_...")
    db = request.state.db
    key = db.query(ApiKey).filter(ApiKey.prefix == key_prefix_of(token)).first()
    if not key or not verify_api_key(token, key.key_hash):
        raise err(401, "invalid_key", "Unknown or invalid API key.")
    if key.revoked_at:
        raise err(401, "revoked_key", "This API key has been revoked.")
    if key.expires_at and key.expires_at < datetime.utcnow():
        raise err(401, "expired_key", "This API key has expired.")
    allowed, retry = rate_limit_check(key.id)
    if not allowed:
        e = err(429, "rate_limited", "Rate limit exceeded. Slow down and retry.")
        e.headers = {"Retry-After": str(retry)}
        raise e
    key.last_used_at = datetime.utcnow()
    request.state.api_key = key
    return ApiCtx(db, key)


@extapp.middleware("http")
async def _db_and_logging(request: Request, call_next):
    t0 = time.time()
    db = session_factory()
    request.state.db = db
    request.state.api_key = None
    try:
        response = await call_next(request)
        return response
    finally:
        try:
            key = getattr(request.state, "api_key", None)
            if key is not None and not request.url.path.endswith(("/docs", "/openapi.json")):
                db.add(ApiRequestLog(
                    workspace_id=key.workspace_id, api_key_id=key.id,
                    method=request.method, path=request.url.path[:255],
                    status=getattr(locals().get("response"), "status_code", 0) if "response" in locals() else 500,
                    latency_ms=round((time.time() - t0) * 1000, 2)))
                db.commit()
        except Exception:
            db.rollback()
        db.close()


# ---------------------------------------------------------------- helpers
def paginate(q, request: Request, sortable: dict, default_sort: str):
    p = request.query_params
    try:
        page = max(1, int(p.get("page", 1)))
        page_size = min(100, max(1, int(p.get("page_size", 25))))
    except ValueError:
        raise err(422, "invalid_pagination", "page and page_size must be integers.")
    sort = p.get("sort", default_sort)
    field, _, direction = sort.partition(":")
    col = sortable.get(field)
    if col is None:
        raise err(422, "invalid_sort", f"sort must be one of: {', '.join(sortable)} (append :asc or :desc).")
    q = q.order_by(col.desc() if direction != "asc" else col.asc())
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    return rows, {"page": page, "page_size": page_size, "total": total,
                  "has_more": page * page_size < total}


def updated_since_filter(q, model, request: Request):
    raw = request.query_params.get("updated_since", "")
    if not raw:
        return q
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        raise err(422, "invalid_updated_since", "updated_since must be ISO 8601.")
    return q.filter(model.updated_at >= dt)


def iso(dt):
    return dt.isoformat() + "Z" if dt else None


def idempotent(ctx: ApiCtx, request: Request, idem_key: str | None, make):
    """Run `make()` once per (key, Idempotency-Key); replay stored response after."""
    if not idem_key:
        return make()
    existing = (ctx.db.query(IdempotencyRecord)
                .filter(IdempotencyRecord.api_key_id == ctx.key.id,
                        IdempotencyRecord.idem_key == idem_key).first())
    if existing:
        return JSONResponse(status_code=existing.status or 200, content=existing.response)
    result = make()
    try:
        ctx.db.add(IdempotencyRecord(api_key_id=ctx.key.id, idem_key=idem_key,
                                     method=request.method, path=request.url.path[:255],
                                     status=201, response=result))
        ctx.db.commit()
    except Exception:
        ctx.db.rollback()
    return result


# ---------------------------------------------------------------- serializers (safe fields only)
def company_out(c: Company) -> dict:
    return {"id": c.id, "name": c.name, "domain": c.domain, "website": c.website,
            "industry": c.industry, "location": c.location,
            "employee_count": c.employee_count, "revenue_range": c.revenue_range,
            "icp_fit": c.icp_fit, "external_id": c.external_id or None,
            "external_source": c.external_source or None,
            "created_at": iso(c.created_at), "updated_at": iso(c.updated_at)}


def contact_out(c: Contact) -> dict:
    return {"id": c.id, "company_id": c.company_id, "email": c.email,
            "first_name": c.first_name, "last_name": c.last_name, "title": c.title,
            "linkedin_url": c.linkedin_url, "location": c.location,
            "buying_role": c.buying_role, "email_status": c.email_status,
            "revenue_score": c.revenue_score, "source": c.source,
            "external_id": c.external_id or None, "external_source": c.external_source or None,
            "created_at": iso(c.created_at), "updated_at": iso(c.updated_at)}


def deal_out(d: Deal, stage_name: str = "") -> dict:
    return {"id": d.id, "company_id": d.company_id, "contact_id": d.contact_id,
            "name": d.name, "value": d.value, "stage_id": d.stage_id,
            "stage": stage_name, "status_label": d.status_label, "source": d.source,
            "next_step": d.next_step, "close_date": d.close_date, "tags": d.tags or [],
            "external_id": d.external_id or None, "external_source": d.external_source or None,
            "created_at": iso(d.created_at), "updated_at": iso(d.updated_at)}


def activity_out(a: Activity) -> dict:
    return {"id": a.id, "kind": a.kind, "title": a.title, "body": a.body,
            "company_id": a.company_id, "contact_id": a.contact_id, "deal_id": a.deal_id,
            "occurred_at": iso(a.occurred_at)}


# ---------------------------------------------------------------- companies
class CompanyIn(BaseModel):
    name: str | None = None
    domain: str | None = None
    website: str | None = None
    industry: str | None = None
    location: str | None = None
    external_id: str | None = None
    external_source: str | None = None


@extapp.get("/companies", tags=["companies"])
def list_companies(request: Request, ctx: ApiCtx = Depends(get_api_ctx)):
    ctx.require("companies:read")
    q = ctx.db.query(Company).filter(Company.workspace_id == ctx.workspace_id)
    ext = request.query_params.get("external_id")
    if ext:
        q = q.filter(Company.external_id == ext)
    q = updated_since_filter(q, Company, request)
    rows, meta = paginate(q, request, {"created_at": Company.created_at,
                                       "updated_at": Company.updated_at,
                                       "name": Company.name}, "updated_at:desc")
    return {"data": [company_out(c) for c in rows], "pagination": meta}


@extapp.get("/companies/{company_id}", tags=["companies"])
def get_company(company_id: int, ctx: ApiCtx = Depends(get_api_ctx)):
    ctx.require("companies:read")
    c = (ctx.db.query(Company).filter(Company.workspace_id == ctx.workspace_id,
                                      Company.id == company_id).first())
    if not c:
        raise err(404, "not_found", "Company not found.")
    return {"data": company_out(c)}


@extapp.post("/companies", status_code=201, tags=["companies"])
def create_company(body: CompanyIn, request: Request, ctx: ApiCtx = Depends(get_api_ctx),
                   idempotency_key: str | None = Header(default=None)):
    ctx.require("companies:write")
    if not (body.name or "").strip():
        raise err(422, "missing_field", "name is required.")

    def make():
        if body.external_id:
            dup = (ctx.db.query(Company)
                   .filter(Company.workspace_id == ctx.workspace_id,
                           Company.external_id == body.external_id).first())
            if dup:
                raise err(409, "duplicate_external_id",
                          f"A company with external_id '{body.external_id}' already exists (id {dup.id}).")
        c = Company(workspace_id=ctx.workspace_id, name=body.name.strip(),
                    domain=body.domain or "", website=body.website or "",
                    industry=body.industry or "", location=body.location or "",
                    external_id=body.external_id or "", external_source=body.external_source or "")
        ctx.db.add(c); ctx.db.commit()
        events.emit(ctx.db, ctx.workspace_id, "company.created", company_out(c))
        return {"data": company_out(c)}
    return idempotent(ctx, request, idempotency_key, make)


@extapp.patch("/companies/{company_id}", tags=["companies"])
def patch_company(company_id: int, body: CompanyIn, ctx: ApiCtx = Depends(get_api_ctx)):
    ctx.require("companies:write")
    c = (ctx.db.query(Company).filter(Company.workspace_id == ctx.workspace_id,
                                      Company.id == company_id).first())
    if not c:
        raise err(404, "not_found", "Company not found.")
    for f in ("name", "domain", "website", "industry", "location", "external_id", "external_source"):
        v = getattr(body, f)
        if v is not None:
            setattr(c, f, v)
    ctx.db.commit()
    events.emit(ctx.db, ctx.workspace_id, "company.updated", company_out(c))
    return {"data": company_out(c)}


# ---------------------------------------------------------------- contacts
class ContactIn(BaseModel):
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    title: str | None = None
    company_id: int | None = None
    linkedin_url: str | None = None
    location: str | None = None
    external_id: str | None = None
    external_source: str | None = None


@extapp.get("/contacts", tags=["contacts"])
def list_contacts(request: Request, ctx: ApiCtx = Depends(get_api_ctx)):
    ctx.require("contacts:read")
    q = ctx.db.query(Contact).filter(Contact.workspace_id == ctx.workspace_id)
    ext = request.query_params.get("external_id")
    if ext:
        q = q.filter(Contact.external_id == ext)
    email = request.query_params.get("email")
    if email:
        q = q.filter(Contact.email == email.lower().strip())
    q = updated_since_filter(q, Contact, request)
    rows, meta = paginate(q, request, {"created_at": Contact.created_at,
                                       "updated_at": Contact.updated_at,
                                       "email": Contact.email}, "updated_at:desc")
    return {"data": [contact_out(c) for c in rows], "pagination": meta}


@extapp.get("/contacts/{contact_id}", tags=["contacts"])
def get_contact(contact_id: int, ctx: ApiCtx = Depends(get_api_ctx)):
    ctx.require("contacts:read")
    c = (ctx.db.query(Contact).filter(Contact.workspace_id == ctx.workspace_id,
                                      Contact.id == contact_id).first())
    if not c:
        raise err(404, "not_found", "Contact not found.")
    return {"data": contact_out(c)}


@extapp.post("/contacts", status_code=201, tags=["contacts"])
def create_contact(body: ContactIn, request: Request, ctx: ApiCtx = Depends(get_api_ctx),
                   idempotency_key: str | None = Header(default=None)):
    ctx.require("contacts:write")
    if not (body.email or body.first_name or body.last_name):
        raise err(422, "missing_field", "Provide at least an email or a name.")

    def make():
        if body.external_id:
            dup = (ctx.db.query(Contact)
                   .filter(Contact.workspace_id == ctx.workspace_id,
                           Contact.external_id == body.external_id).first())
            if dup:
                raise err(409, "duplicate_external_id",
                          f"A contact with external_id '{body.external_id}' already exists (id {dup.id}).")
        if body.email:
            dup = (ctx.db.query(Contact)
                   .filter(Contact.workspace_id == ctx.workspace_id,
                           Contact.email == body.email.lower().strip()).first())
            if dup:
                raise err(409, "duplicate_email",
                          f"A contact with this email already exists (id {dup.id}).")
        c = Contact(workspace_id=ctx.workspace_id, email=(body.email or "").lower().strip(),
                    first_name=body.first_name or "", last_name=body.last_name or "",
                    title=body.title or "", company_id=body.company_id,
                    linkedin_url=body.linkedin_url or "", location=body.location or "",
                    source="api", external_id=body.external_id or "",
                    external_source=body.external_source or "")
        ctx.db.add(c); ctx.db.commit()
        events.emit(ctx.db, ctx.workspace_id, "contact.created", contact_out(c))
        return {"data": contact_out(c)}
    return idempotent(ctx, request, idempotency_key, make)


@extapp.patch("/contacts/{contact_id}", tags=["contacts"])
def patch_contact(contact_id: int, body: ContactIn, ctx: ApiCtx = Depends(get_api_ctx)):
    ctx.require("contacts:write")
    c = (ctx.db.query(Contact).filter(Contact.workspace_id == ctx.workspace_id,
                                      Contact.id == contact_id).first())
    if not c:
        raise err(404, "not_found", "Contact not found.")
    for f in ("email", "first_name", "last_name", "title", "company_id",
              "linkedin_url", "location", "external_id", "external_source"):
        v = getattr(body, f)
        if v is not None:
            setattr(c, f, v.lower().strip() if f == "email" else v)
    ctx.db.commit()
    events.emit(ctx.db, ctx.workspace_id, "contact.updated", contact_out(c))
    return {"data": contact_out(c)}


# ---------------------------------------------------------------- deals
class DealIn(BaseModel):
    name: str | None = None
    value: float | None = None
    company_id: int | None = None
    contact_id: int | None = None
    stage: str | None = None          # stage NAME (mapped per workspace)
    next_step: str | None = None
    close_date: str | None = None
    external_id: str | None = None
    external_source: str | None = None


def _stage_by_name(ctx: ApiCtx, name: str):
    return (ctx.db.query(Stage).filter(Stage.workspace_id == ctx.workspace_id,
                                       Stage.name == name).first())


@extapp.get("/deals", tags=["deals"])
def list_deals(request: Request, ctx: ApiCtx = Depends(get_api_ctx)):
    ctx.require("deals:read")
    q = ctx.db.query(Deal).filter(Deal.workspace_id == ctx.workspace_id)
    ext = request.query_params.get("external_id")
    if ext:
        q = q.filter(Deal.external_id == ext)
    q = updated_since_filter(q, Deal, request)
    rows, meta = paginate(q, request, {"created_at": Deal.created_at,
                                       "updated_at": Deal.updated_at,
                                       "value": Deal.value}, "updated_at:desc")
    stages = {s.id: s.name for s in ctx.db.query(Stage).filter(Stage.workspace_id == ctx.workspace_id)}
    return {"data": [deal_out(d, stages.get(d.stage_id, "")) for d in rows], "pagination": meta}


@extapp.get("/deals/{deal_id}", tags=["deals"])
def get_deal(deal_id: int, ctx: ApiCtx = Depends(get_api_ctx)):
    ctx.require("deals:read")
    d = (ctx.db.query(Deal).filter(Deal.workspace_id == ctx.workspace_id,
                                   Deal.id == deal_id).first())
    if not d:
        raise err(404, "not_found", "Deal not found.")
    st = ctx.db.get(Stage, d.stage_id) if d.stage_id else None
    return {"data": deal_out(d, st.name if st else "")}


@extapp.post("/deals", status_code=201, tags=["deals"])
def create_deal(body: DealIn, request: Request, ctx: ApiCtx = Depends(get_api_ctx),
                idempotency_key: str | None = Header(default=None)):
    ctx.require("deals:write")

    def make():
        if body.external_id:
            dup = (ctx.db.query(Deal)
                   .filter(Deal.workspace_id == ctx.workspace_id,
                           Deal.external_id == body.external_id).first())
            if dup:
                raise err(409, "duplicate_external_id",
                          f"A deal with external_id '{body.external_id}' already exists (id {dup.id}).")
        stage = _stage_by_name(ctx, body.stage) if body.stage else None
        if body.stage and not stage:
            raise err(422, "unknown_stage", f"No stage named '{body.stage}' in this workspace.")
        d = Deal(workspace_id=ctx.workspace_id, name=body.name or "",
                 value=body.value or 0.0, company_id=body.company_id,
                 contact_id=body.contact_id, stage_id=stage.id if stage else None,
                 next_step=body.next_step or "", close_date=body.close_date or "",
                 source="api", external_id=body.external_id or "",
                 external_source=body.external_source or "")
        ctx.db.add(d); ctx.db.commit()
        events.emit(ctx.db, ctx.workspace_id, "deal.created", deal_out(d, stage.name if stage else ""))
        return {"data": deal_out(d, stage.name if stage else "")}
    return idempotent(ctx, request, idempotency_key, make)


@extapp.patch("/deals/{deal_id}", tags=["deals"])
def patch_deal(deal_id: int, body: DealIn, ctx: ApiCtx = Depends(get_api_ctx)):
    ctx.require("deals:write")
    d = (ctx.db.query(Deal).filter(Deal.workspace_id == ctx.workspace_id,
                                   Deal.id == deal_id).first())
    if not d:
        raise err(404, "not_found", "Deal not found.")
    stage_changed = False
    if body.stage is not None:
        stage = _stage_by_name(ctx, body.stage)
        if not stage:
            raise err(422, "unknown_stage", f"No stage named '{body.stage}' in this workspace.")
        stage_changed = stage.id != d.stage_id
        d.stage_id = stage.id
        if stage_changed:
            d.stage_changed_at = datetime.utcnow()
    for f in ("name", "value", "company_id", "contact_id", "next_step", "close_date",
              "external_id", "external_source"):
        v = getattr(body, f)
        if v is not None:
            setattr(d, f, v)
    ctx.db.commit()
    st = ctx.db.get(Stage, d.stage_id) if d.stage_id else None
    out = deal_out(d, st.name if st else "")
    events.emit(ctx.db, ctx.workspace_id, "deal.updated", out)
    if stage_changed:
        events.emit(ctx.db, ctx.workspace_id, "deal.stage_changed", out)
    return {"data": out}


# ---------------------------------------------------------------- activities
class ActivityIn(BaseModel):
    kind: str = "note"
    title: str = ""
    body: str | None = ""
    company_id: int | None = None
    contact_id: int | None = None
    deal_id: int | None = None


@extapp.get("/activities", tags=["activities"])
def list_activities(request: Request, ctx: ApiCtx = Depends(get_api_ctx)):
    ctx.require("activities:read")
    q = ctx.db.query(Activity).filter(Activity.workspace_id == ctx.workspace_id)
    kind = request.query_params.get("kind")
    if kind:
        q = q.filter(Activity.kind == kind)
    for fk, col in (("company_id", Activity.company_id), ("contact_id", Activity.contact_id),
                    ("deal_id", Activity.deal_id)):
        v = request.query_params.get(fk)
        if v:
            q = q.filter(col == int(v))
    rows, meta = paginate(q, request, {"occurred_at": Activity.occurred_at}, "occurred_at:desc")
    return {"data": [activity_out(a) for a in rows], "pagination": meta}


@extapp.post("/activities", status_code=201, tags=["activities"])
def create_activity(body: ActivityIn, request: Request, ctx: ApiCtx = Depends(get_api_ctx),
                    idempotency_key: str | None = Header(default=None)):
    ctx.require("activities:write")
    if not body.title.strip():
        raise err(422, "missing_field", "title is required.")

    def make():
        a = Activity(workspace_id=ctx.workspace_id, kind=body.kind or "note",
                     title=body.title.strip(), body=body.body or "",
                     company_id=body.company_id, contact_id=body.contact_id,
                     deal_id=body.deal_id)
        ctx.db.add(a); ctx.db.commit()
        return {"data": activity_out(a)}
    return idempotent(ctx, request, idempotency_key, make)


# ---------------------------------------------------------------- read-only resources
@extapp.get("/replies", tags=["replies"])
def list_replies(request: Request, ctx: ApiCtx = Depends(get_api_ctx)):
    ctx.require("replies:read")
    q = ctx.db.query(ReplyLead).filter(ReplyLead.workspace_id == ctx.workspace_id)
    intent = request.query_params.get("intent")
    if intent:
        q = q.filter(ReplyLead.intent == intent)
    rows, meta = paginate(q, request, {"created_at": ReplyLead.created_at}, "created_at:desc")
    return {"data": [{
        "id": r.id, "name": r.name, "email": r.email, "company": r.company,
        "subject": r.subject, "intent": r.intent, "decision": r.action,
        "replied": r.replied, "stage": r.stage, "created_at": iso(r.created_at),
    } for r in rows], "pagination": meta}


@extapp.get("/meetings", tags=["meetings"])
def list_meetings(request: Request, ctx: ApiCtx = Depends(get_api_ctx)):
    ctx.require("meetings:read")
    q = (ctx.db.query(Activity).filter(Activity.workspace_id == ctx.workspace_id,
                                       Activity.kind.in_(["meeting_booked", "meeting_held"])))
    rows, meta = paginate(q, request, {"occurred_at": Activity.occurred_at}, "occurred_at:desc")
    return {"data": [activity_out(a) for a in rows], "pagination": meta}


@extapp.get("/blueprints", tags=["blueprints"])
def list_blueprints(request: Request, ctx: ApiCtx = Depends(get_api_ctx)):
    ctx.require("blueprints:read")
    q = (ctx.db.query(Document).filter(Document.workspace_id == ctx.workspace_id,
                                       Document.kind == "blueprint"))
    rows, meta = paginate(q, request, {"created_at": Document.created_at,
                                       "updated_at": Document.updated_at}, "updated_at:desc")
    return {"data": [{
        "id": d.id, "title": d.title, "slug": d.slug, "status": d.status,
        "published": d.published, "company_id": d.company_id,
        "view_count": d.view_count, "created_at": iso(d.created_at),
        "updated_at": iso(d.updated_at),
    } for d in rows], "pagination": meta}


@extapp.get("/agreements", tags=["agreements"])
def list_agreements(request: Request, ctx: ApiCtx = Depends(get_api_ctx)):
    ctx.require("agreements:read")
    from ..models.agreements import Agreement
    q = ctx.db.query(Agreement).filter(Agreement.workspace_id == ctx.workspace_id)
    rows, meta = paginate(q, request, {"created_at": Agreement.created_at,
                                       "updated_at": Agreement.updated_at}, "updated_at:desc")
    return {"data": [{
        "id": a.id, "number": a.number, "title": a.title, "status": a.status,
        "version": a.version, "company_id": a.company_id, "deal_id": a.deal_id,
        "client_signed_at": iso(a.client_signed_at), "executed_at": iso(a.executed_at),
        "created_at": iso(a.created_at), "updated_at": iso(a.updated_at),
    } for a in rows], "pagination": meta}


@extapp.get("/invoices", tags=["invoices"])
def list_invoices(request: Request, ctx: ApiCtx = Depends(get_api_ctx)):
    ctx.require("invoices:read")
    from ..models.agreements import Invoice
    q = ctx.db.query(Invoice).filter(Invoice.workspace_id == ctx.workspace_id)
    rows, meta = paginate(q, request, {"created_at": Invoice.created_at,
                                       "updated_at": Invoice.updated_at}, "updated_at:desc")
    return {"data": [{
        "id": i.id, "number": i.number, "status": i.status, "currency": i.currency,
        "subtotal": i.subtotal, "total": i.total, "amount_paid": i.amount_paid,
        "balance_due": i.balance_due, "issue_date": i.issue_date, "due_date": i.due_date,
        "company_id": i.company_id, "created_at": iso(i.created_at), "updated_at": iso(i.updated_at),
    } for i in rows], "pagination": meta}
