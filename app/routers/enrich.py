"""Enrichment API: enqueue enrichment/blueprint jobs, track progress, read results."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import AuthContext, get_ctx, scoped
from ..models.crm import Company, Contact
from ..models.documents import Document
from ..models.jobs import Job

router = APIRouter(prefix="/api", tags=["enrichment"])


class EnrichIn(BaseModel):
    workspace_id: int
    company_ids: list[int] = []
    contact_ids: list[int] = []
    html_override: str = ""   # tests / pre-fetched HTML; normally empty


@router.post("/enrich")
def enqueue_enrichment(body: EnrichIn, ctx: AuthContext = Depends(get_ctx)):
    ctx.require_workspace(body.workspace_id)
    if not body.company_ids and not body.contact_ids:
        raise HTTPException(422, "Provide company_ids and/or contact_ids")
    jobs = []
    for cid in body.company_ids:
        c = scoped(ctx.db.query(Company), Company, ctx, body.workspace_id).filter(Company.id == cid).first()
        if not c:
            raise HTTPException(404, f"Company {cid} not found in workspace")
        payload = {"company_id": cid}
        if body.html_override:
            payload["html_override"] = body.html_override
        j = Job(kind="enrich_company", workspace_id=body.workspace_id, payload=payload)
        ctx.db.add(j); jobs.append(j)
    for cid in body.contact_ids:
        c = scoped(ctx.db.query(Contact), Contact, ctx, body.workspace_id).filter(Contact.id == cid).first()
        if not c:
            raise HTTPException(404, f"Contact {cid} not found in workspace")
        payload = {"contact_id": cid}
        if body.html_override:
            payload["html_override"] = body.html_override
        j = Job(kind="enrich_contact", workspace_id=body.workspace_id, payload=payload)
        ctx.db.add(j); jobs.append(j)
    ctx.db.commit()
    return {"job_ids": [j.id for j in jobs], "queued": len(jobs)}


class BlueprintIn(BaseModel):
    workspace_id: int
    company_id: int | None = None
    contact_id: int | None = None
    deal_id: int | None = None


@router.post("/blueprints/generate")
def enqueue_blueprint(body: BlueprintIn, ctx: AuthContext = Depends(get_ctx)):
    ctx.require_workspace(body.workspace_id)
    if not body.company_id and not body.contact_id:
        raise HTTPException(422, "company_id or contact_id required")
    payload = {k: v for k, v in body.model_dump().items() if v and k != "workspace_id"}
    j = Job(kind="generate_blueprint", workspace_id=body.workspace_id, payload=payload)
    ctx.db.add(j)
    ctx.db.commit()
    return {"job_id": j.id}


@router.get("/jobs/{job_id}/status")
def job_status(job_id: int, ctx: AuthContext = Depends(get_ctx)):
    j = ctx.db.query(Job).filter(Job.id == job_id).first()
    if not j:
        raise HTTPException(404, "Job not found")
    if j.workspace_id is not None:
        ctx.require_workspace(j.workspace_id)
    elif not ctx.is_master:
        raise HTTPException(403, "Org-level job")
    return {"id": j.id, "kind": j.kind, "status": j.status, "progress": j.progress,
            "progress_note": j.progress_note, "attempts": j.attempts,
            "result": j.result, "error": (j.error or "")[-500:]}


# ---------------------------------------------------------------- record detail
@router.get("/companies/{company_id}")
def company_detail(company_id: int, ctx: AuthContext = Depends(get_ctx)):
    c = scoped(ctx.db.query(Company), Company, ctx).filter(Company.id == company_id).first()
    if not c:
        raise HTTPException(404, "Company not found")
    return {"id": c.id, "workspace_id": c.workspace_id, "name": c.name, "domain": c.domain,
            "website": c.website, "industry": c.industry, "location": c.location,
            "icp_fit": c.icp_fit, "enrichment": c.enrichment or {}}


@router.get("/contacts/{contact_id}")
def contact_detail(contact_id: int, ctx: AuthContext = Depends(get_ctx)):
    c = scoped(ctx.db.query(Contact), Contact, ctx).filter(Contact.id == contact_id).first()
    if not c:
        raise HTTPException(404, "Contact not found")
    return {"id": c.id, "workspace_id": c.workspace_id, "email": c.email,
            "name": f"{c.first_name} {c.last_name}".strip(), "title": c.title,
            "company_id": c.company_id, "email_status": c.email_status,
            "revenue_score": c.revenue_score, "enrichment": c.enrichment or {}}


@router.get("/documents")
def list_documents(workspace_id: int | None = None, kind: str = "", ctx: AuthContext = Depends(get_ctx)):
    q = scoped(ctx.db.query(Document), Document, ctx, workspace_id)
    if kind:
        q = q.filter(Document.kind == kind)
    rows = q.order_by(Document.updated_at.desc()).limit(200).all()
    return [{"id": d.id, "workspace_id": d.workspace_id, "kind": d.kind, "status": d.status,
             "title": d.title, "slug": d.slug, "company_id": d.company_id,
             "view_count": d.view_count} for d in rows]


@router.get("/documents/{doc_id}")
def document_detail(doc_id: int, ctx: AuthContext = Depends(get_ctx)):
    d = scoped(ctx.db.query(Document), Document, ctx).filter(Document.id == doc_id).first()
    if not d:
        raise HTTPException(404, "Document not found")
    return {"id": d.id, "kind": d.kind, "status": d.status, "title": d.title, "slug": d.slug,
            "fields": d.fields or {}, "html": d.html}
