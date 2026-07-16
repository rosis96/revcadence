"""Global search for the command palette (one endpoint, every entity).

GET /api/search?q=acme  ->  {q, results: [{type, id, title, subtitle, href}]}
Cheap ILIKE lookups, workspace-scoped, max PER_TYPE per entity. Frontend groups
results by type; hrefs are hash-router paths."""
from fastapi import APIRouter, Depends

from ..auth import AuthContext, get_ctx, scoped
from ..models.crm import Activity, Company, Contact, Deal
from ..models.documents import Document

router = APIRouter(prefix="/api", tags=["search"])

PER_TYPE = 8

DOC_HREF = {"blueprint": "/blueprints/{id}", "agreement": "/agreements/{id}", "invoice": "/invoices/{id}"}


@router.get("/search")
def global_search(q: str = "", workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    q = (q or "").strip()
    if len(q) < 2:
        return {"q": q, "results": []}
    like = f"%{q}%"
    results = []

    def safe(fn):
        try:
            fn()
        except Exception:
            pass  # one broken entity must never break the whole palette

    def companies():
        rows = (scoped(ctx.db.query(Company), Company, ctx, workspace_id)
                .filter((Company.name.ilike(like)) | (Company.domain.ilike(like)))
                .order_by(Company.updated_at.desc()).limit(PER_TYPE).all())
        for c in rows:
            results.append({"type": "company", "id": c.id, "title": c.name,
                            "subtitle": c.domain or c.industry or "", "href": f"/companies/{c.id}"})

    def contacts():
        rows = (scoped(ctx.db.query(Contact), Contact, ctx, workspace_id)
                .filter((Contact.first_name.ilike(like)) | (Contact.last_name.ilike(like)) | (Contact.email.ilike(like)))
                .order_by(Contact.updated_at.desc()).limit(PER_TYPE).all())
        for c in rows:
            name = f"{c.first_name} {c.last_name}".strip() or c.email
            results.append({"type": "contact", "id": c.id, "title": name,
                            "subtitle": c.title or c.email or "", "href": "/contacts"})

    def deals():
        rows = (scoped(ctx.db.query(Deal), Deal, ctx, workspace_id)
                .filter(Deal.name.ilike(like)).order_by(Deal.updated_at.desc()).limit(PER_TYPE).all())
        for d in rows:
            results.append({"type": "deal", "id": d.id, "title": d.name or f"Deal #{d.id}",
                            "subtitle": d.status_label or "", "href": "/pipeline"})

    def documents():
        rows = (scoped(ctx.db.query(Document), Document, ctx, workspace_id)
                .filter((Document.title.ilike(like)) | (Document.slug.ilike(like)))
                .order_by(Document.id.desc()).limit(PER_TYPE).all())
        for d in rows:
            href = DOC_HREF.get(d.kind, "/blueprints/{id}").format(id=d.id)
            results.append({"type": d.kind if d.kind in DOC_HREF else "document", "id": d.id,
                            "title": d.title or d.slug or f"{d.kind} #{d.id}",
                            "subtitle": d.status or "", "href": href})

    def replies():
        rows = (scoped(ctx.db.query(Activity), Activity, ctx, workspace_id)
                .filter(Activity.kind == "email_in")
                .filter((Activity.title.ilike(like)) | (Activity.body.ilike(like)))
                .order_by(Activity.id.desc()).limit(PER_TYPE).all())
        for a in rows:
            results.append({"type": "reply", "id": a.id, "title": a.title or "Reply",
                            "subtitle": (a.intent or "")[:60], "href": "/reply/inbox"})

    for fn in (companies, contacts, deals, documents, replies):
        safe(fn)
    return {"q": q, "results": results}
