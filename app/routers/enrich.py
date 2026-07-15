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


class EnrichWorkspaceIn(BaseModel):
    workspace_id: int
    limit: int = 50          # safety cap per call — same credit-burn philosophy as the old dashboard
    only_unenriched: bool = True


@router.post("/enrich/workspace")
def enqueue_workspace_enrichment(body: EnrichWorkspaceIn, ctx: AuthContext = Depends(get_ctx)):
    """Bulk: enqueue enrichment for companies+contacts in a workspace.
    Defaults to only records never enriched, capped at `limit` jobs."""
    ctx.require_workspace(body.workspace_id)
    limit = max(1, min(body.limit, 500))
    jobs = []
    companies = scoped(ctx.db.query(Company), Company, ctx, body.workspace_id).all()
    for c in companies:
        if len(jobs) >= limit:
            break
        if body.only_unenriched and (c.enrichment or {}).get("last_crawl"):
            continue
        if not (c.website or c.domain):
            continue
        j = Job(kind="enrich_company", workspace_id=body.workspace_id, payload={"company_id": c.id})
        ctx.db.add(j); jobs.append(j)
    contacts = scoped(ctx.db.query(Contact), Contact, ctx, body.workspace_id).all()
    for c in contacts:
        if len(jobs) >= limit:
            break
        if body.only_unenriched and c.revenue_score is not None:
            continue
        j = Job(kind="enrich_contact", workspace_id=body.workspace_id, payload={"contact_id": c.id})
        ctx.db.add(j); jobs.append(j)
    ctx.db.commit()
    return {"queued": len(jobs), "job_ids": [j.id for j in jobs], "limit": limit}


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


# ---------------------------------------------------------------- CSV in / out (Clay-style)
class ImportRow(BaseModel):
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    title: str = ""
    company: str = ""
    website: str = ""


class ImportIn(BaseModel):
    workspace_id: int
    rows: list[ImportRow]
    auto_enrich: bool = False


@router.post("/import/contacts")
def import_contacts(body: ImportIn, ctx: AuthContext = Depends(get_ctx)):
    """CSV import (parsed client-side): creates companies (by name) and
    contacts (deduped by email per workspace); optionally queues enrichment."""
    ctx.require_workspace(body.workspace_id)
    if len(body.rows) > 2000:
        raise HTTPException(422, "Max 2000 rows per import")
    created = merged = companies_created = jobs = 0
    for row in body.rows:
        email = row.email.lower().strip()
        if not email and not (row.first_name or row.company):
            continue
        company = None
        cname = row.company.strip()
        if cname:
            company = (ctx.db.query(Company)
                       .filter(Company.workspace_id == body.workspace_id, Company.name == cname).first())
            if company is None:
                company = Company(workspace_id=body.workspace_id, name=cname, website=row.website.strip())
                ctx.db.add(company)
                ctx.db.flush()
                companies_created += 1
            elif row.website.strip() and not company.website:
                company.website = row.website.strip()
        contact = (ctx.db.query(Contact)
                   .filter(Contact.workspace_id == body.workspace_id, Contact.email == email).first()
                   if email else None)
        if contact is None:
            contact = Contact(workspace_id=body.workspace_id, email=email, first_name=row.first_name.strip(),
                              last_name=row.last_name.strip(), title=row.title.strip(),
                              company_id=company.id if company else None, source="import")
            ctx.db.add(contact)
            ctx.db.flush()
            created += 1
        else:
            if company and not contact.company_id:
                contact.company_id = company.id
            if row.title.strip() and not contact.title:
                contact.title = row.title.strip()
            merged += 1
        if body.auto_enrich:
            ctx.db.add(Job(kind="enrich_contact", workspace_id=body.workspace_id,
                           payload={"contact_id": contact.id}))
            jobs += 1
    ctx.db.commit()
    return {"contacts_created": created, "contacts_merged": merged,
            "companies_created": companies_created, "enrich_jobs_queued": jobs}


@router.get("/export/leads")
def export_leads(workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    """Campaign-ready CSV of contacts + company enrichment (upload to
    Instantly/Bison as-is)."""
    import csv
    import io

    from fastapi.responses import PlainTextResponse

    contacts = scoped(ctx.db.query(Contact), Contact, ctx, workspace_id).limit(5000).all()
    coids = {c.company_id for c in contacts if c.company_id}
    companies = ({c.id: c for c in ctx.db.query(Company).filter(Company.id.in_(coids)).all()}
                 if coids else {})
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["first_name", "last_name", "email", "title", "company", "website", "industry",
                "icp_fit", "revenue_score", "email_status", "company_description"])
    for c in contacts:
        co = companies.get(c.company_id)
        desc = ""
        if co and isinstance((co.enrichment or {}).get("description"), dict):
            desc = str(co.enrichment["description"].get("value", ""))
        w.writerow([c.first_name, c.last_name, c.email, c.title,
                    co.name if co else "", co.website if co else "",
                    co.industry if co else "", co.icp_fit if co else "",
                    c.revenue_score if c.revenue_score is not None else "",
                    c.email_status, desc])
    return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=revcadence-leads.csv"})


# ---------------------------------------------------------------- record detail
@router.get("/companies/{company_id}")
def company_detail(company_id: int, ctx: AuthContext = Depends(get_ctx)):
    from ..models.crm import Activity, Deal, Stage
    from ..models.client_profile import ClientProfile
    c = scoped(ctx.db.query(Company), Company, ctx).filter(Company.id == company_id).first()
    if not c:
        raise HTTPException(404, "Company not found")
    contacts = ctx.db.query(Contact).filter(Contact.company_id == c.id).all()
    deals = ctx.db.query(Deal).filter(Deal.company_id == c.id).all()
    acts = (scoped(ctx.db.query(Activity), Activity, ctx)
            .filter(Activity.company_id == c.id).order_by(Activity.occurred_at.desc()).limit(50).all())
    docs = (ctx.db.query(Document).filter(Document.company_id == c.id)
            .order_by(Document.updated_at.desc()).all())
    prof = ctx.db.query(ClientProfile).filter(ClientProfile.company_id == c.id).first()

    # pipeline status = most-advanced stage across this company's deals (+ Client)
    ws_ids = ctx.workspace_ids_for_query(None)
    from .crm import _pipeline_status
    _, _, client_co, status_for = _pipeline_status(ctx, ws_ids)
    stage_ids = [d.stage_id for d in deals if d.stage_id is not None]
    status = status_for(stage_ids, c.id in client_co)
    smap = {s.id: s for s in ctx.db.query(Stage).filter(Stage.workspace_id == c.workspace_id).all()}

    return {"id": c.id, "workspace_id": c.workspace_id, "name": c.name, "domain": c.domain,
            "website": c.website, "industry": c.industry, "location": c.location,
            "icp_fit": c.icp_fit, "enrichment": c.enrichment or {}, "status": status,
            "contacts": [{"id": p.id, "name": f"{p.first_name} {p.last_name}".strip(),
                          "email": p.email, "title": p.title, "revenue_score": p.revenue_score}
                         for p in contacts],
            "deals": [{"id": d.id, "name": d.name, "value": d.value, "stage_id": d.stage_id,
                       "stage_name": smap[d.stage_id].name if d.stage_id in smap else "",
                       "lead_intent": d.lead_intent}
                      for d in deals],
            "documents": [{"id": d.id, "kind": d.kind, "title": d.title, "slug": d.slug,
                           "status": d.status, "published": bool(d.published),
                           "generator": (d.fields or {}).get("generator", ""),
                           "public_path": f"/p/{d.slug}" if d.slug else "",
                           "view_count": d.view_count or 0} for d in docs],
            "client_profile": ({"id": prof.id, "is_active_client": bool(prof.is_active_client),
                                "onboarding_status": prof.onboarding_status,
                                "completeness": prof.completeness} if prof else None),
            "timeline": [{"id": a.id, "kind": a.kind, "title": a.title,
                          "at": a.occurred_at.isoformat() if a.occurred_at else None} for a in acts]}


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
def list_documents(workspace_id: int | None = None, kind: str = "", company_id: int | None = None,
                   ctx: AuthContext = Depends(get_ctx)):
    q = scoped(ctx.db.query(Document), Document, ctx, workspace_id)
    if kind:
        q = q.filter(Document.kind == kind)
    if company_id:
        q = q.filter(Document.company_id == company_id)
    rows = q.order_by(Document.updated_at.desc()).limit(200).all()
    return [{"id": d.id, "workspace_id": d.workspace_id, "kind": d.kind, "status": d.status,
             "title": d.title, "slug": d.slug, "company_id": d.company_id,
             "published": bool(d.published), "generator": (d.fields or {}).get("generator", ""),
             "public_path": f"/p/{d.slug}" if d.slug else "",
             "updated_at": d.updated_at.isoformat() if d.updated_at else None,
             "view_count": d.view_count or 0} for d in rows]


@router.get("/documents/{doc_id}")
def document_detail(doc_id: int, ctx: AuthContext = Depends(get_ctx)):
    d = scoped(ctx.db.query(Document), Document, ctx).filter(Document.id == doc_id).first()
    if not d:
        raise HTTPException(404, "Document not found")
    return _doc_out(d)


def _doc_out(d: Document) -> dict:
    return {"id": d.id, "kind": d.kind, "status": d.status, "title": d.title, "slug": d.slug,
            "published": bool(d.published), "company_id": d.company_id, "contact_id": d.contact_id,
            "deal_id": d.deal_id, "view_count": d.view_count or 0,
            "first_viewed_at": d.first_viewed_at.isoformat() if d.first_viewed_at else None,
            "last_viewed_at": d.last_viewed_at.isoformat() if d.last_viewed_at else None,
            "fields": d.fields or {}, "html": d.html,
            "public_path": f"/p/{d.slug}" if d.slug else ""}


# ---------------------------------------------------------------- blueprint from Fathom transcript
class TranscriptIn(BaseModel):
    workspace_id: int | None = None
    company_id: int | None = None
    contact_id: int | None = None
    deal_id: int | None = None
    transcript: str
    doc_id: int | None = None      # regenerate an existing blueprint in place


@router.post("/blueprints/from-transcript")
def blueprint_from_transcript(body: TranscriptIn, ctx: AuthContext = Depends(get_ctx)):
    """Paste a Fathom (or any) call transcript → generate a personalized blueprint
    Document. Runs synchronously so the editor gets the result immediately."""
    from ..enrichment.blueprint import generate_from_transcript
    if not (body.transcript or "").strip():
        raise HTTPException(422, "transcript is required")
    doc = None
    if body.doc_id:
        doc = scoped(ctx.db.query(Document), Document, ctx).filter(Document.id == body.doc_id).first()
        if not doc:
            raise HTTPException(404, "Document not found")
    wsid = body.workspace_id or (doc.workspace_id if doc else None)
    if not wsid:
        raise HTTPException(422, "workspace_id required")
    ctx.require_workspace(wsid)
    company = ctx.db.get(Company, body.company_id or (doc.company_id if doc else 0))
    contact = ctx.db.get(Contact, body.contact_id or (doc.contact_id if doc else 0))
    out = generate_from_transcript(ctx.db, wsid, company, contact, body.transcript,
                                   deal_id=body.deal_id or (doc.deal_id if doc else None),
                                   doc_id=doc.id if doc else None)
    return _doc_out(out)


# ---------------------------------------------------------------- upload a custom blueprint
class UploadIn(BaseModel):
    workspace_id: int | None = None
    company_id: int | None = None
    contact_id: int | None = None
    deal_id: int | None = None
    title: str | None = None
    html: str
    slug: str | None = None
    doc_id: int | None = None      # replace the HTML of an existing blueprint in place


@router.post("/blueprints/upload")
def upload_blueprint(body: UploadIn, ctx: AuthContext = Depends(get_ctx)):
    """Bring your own blueprint: upload a custom HTML / landing page built outside
    the system. It becomes a blueprint Document with its own slug + public link —
    exactly like a system-generated one, just with your HTML."""
    from ..enrichment.blueprint import slugify, unique_slug
    if not (body.html or "").strip():
        raise HTTPException(422, "html is required")

    doc = None
    if body.doc_id:
        doc = scoped(ctx.db.query(Document), Document, ctx).filter(Document.id == body.doc_id).first()
        if not doc:
            raise HTTPException(404, "Document not found")
    wsid = body.workspace_id or (doc.workspace_id if doc else None)
    if not wsid:
        raise HTTPException(422, "workspace_id required")
    ctx.require_workspace(wsid)

    company = ctx.db.get(Company, body.company_id) if body.company_id else \
        (ctx.db.get(Company, doc.company_id) if doc and doc.company_id else None)
    name = (body.title or (company.name if company else "") or "Blueprint").strip()

    if doc is None:
        doc = Document(workspace_id=wsid, company_id=company.id if company else None,
                       contact_id=body.contact_id, deal_id=body.deal_id, kind="blueprint")
        doc.slug = unique_slug(ctx.db, slugify(body.slug) if body.slug else name)
        doc.status = "draft"
        doc.published = False
        ctx.db.add(doc)
    doc.title = f"Revenue Blueprint — {name}" if not (body.title) else body.title
    doc.html = body.html
    doc.fields = {**(doc.fields or {}), "generator": "uploaded"}
    ctx.db.flush()
    from ..models.crm import Activity
    ctx.db.add(Activity(workspace_id=wsid, company_id=doc.company_id, contact_id=doc.contact_id,
                        deal_id=doc.deal_id, kind="doc_created",
                        title="Custom blueprint uploaded", data={"document_id": doc.id}))
    ctx.db.commit()
    return _doc_out(doc)


class DocPatch(BaseModel):
    title: str | None = None
    html: str | None = None
    slug: str | None = None
    published: bool | None = None
    status: str | None = None
    fields: dict | None = None


@router.put("/documents/{doc_id}")
def update_document(doc_id: int, body: DocPatch, ctx: AuthContext = Depends(get_ctx)):
    from ..enrichment.blueprint import slugify, unique_slug
    d = scoped(ctx.db.query(Document), Document, ctx).filter(Document.id == doc_id).first()
    if not d:
        raise HTTPException(404, "Document not found")
    if body.title is not None:
        d.title = body.title
    if body.html is not None:
        d.html = body.html
    if body.fields is not None:
        d.fields = {**(d.fields or {}), **body.fields}
    if body.status is not None:
        d.status = body.status
    if body.slug is not None:
        want = slugify(body.slug)
        d.slug = want if not ctx.db.query(Document).filter(Document.slug == want, Document.id != d.id).first() \
            else unique_slug(ctx.db, want, exclude_id=d.id)
    if body.published is not None:
        d.published = body.published
        if body.published:
            if not d.slug:
                from ..models.crm import Company as _C
                c = ctx.db.get(_C, d.company_id) if d.company_id else None
                d.slug = unique_slug(ctx.db, (c.name if c else "") or d.title or "blueprint")
            if d.status == "draft":
                d.status = "published"
    ctx.db.commit()
    return _doc_out(d)


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: int, ctx: AuthContext = Depends(get_ctx)):
    d = scoped(ctx.db.query(Document), Document, ctx).filter(Document.id == doc_id).first()
    if not d:
        raise HTTPException(404, "Document not found")
    ctx.db.delete(d)
    ctx.db.commit()
    return {"ok": True}
