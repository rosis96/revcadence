"""Pipeline-kind registry (the pattern from the Intelligence Workspace schema):
new capabilities are registered handlers, never architecture changes.

A handler is `def handler(db, job) -> dict` — the returned dict is stored in
job.result. Raise to fail the job (it retries up to max_attempts)."""

HANDLERS: dict = {}


def register(kind: str):
    def deco(fn):
        HANDLERS[kind] = fn
        return fn
    return deco


# ---------------------------------------------------------------- built-ins
@register("noop")
def noop(db, job):
    """Health-check job used by tests and the deploy checklist."""
    return {"ok": True, "echo": job.payload}


@register("import_legacy_leads")
def import_legacy_leads(db, job):
    """Wraps scripts/import_legacy.py so a migration can be run as a queued job
    from the API. payload: {"legacy_db_url": "...", "dry_run": true}"""
    from scripts.import_legacy import run_import
    return run_import(job.payload.get("legacy_db_url", ""), dry_run=bool(job.payload.get("dry_run", True)))

# ---------------------------------------------------------------- enrichment
@register("enrich_company")
def enrich_company_job(db, job):
    """payload: {company_id, html_override?}"""
    from ..enrichment.engine import enrich_company
    from ..models.crm import Company
    company = db.get(Company, int(job.payload.get("company_id", 0)))
    if company is None or company.workspace_id != job.workspace_id:
        raise RuntimeError("company not found in this job's workspace")
    return enrich_company(db, company, job=job, html_override=job.payload.get("html_override", ""))


@register("enrich_contact")
def enrich_contact_job(db, job):
    """payload: {contact_id, html_override?}"""
    from ..enrichment.engine import enrich_contact
    from ..models.crm import Contact
    contact = db.get(Contact, int(job.payload.get("contact_id", 0)))
    if contact is None or contact.workspace_id != job.workspace_id:
        raise RuntimeError("contact not found in this job's workspace")
    return enrich_contact(db, contact, job=job, html_override=job.payload.get("html_override", ""))


@register("generate_blueprint")
def generate_blueprint_job(db, job):
    """payload: {company_id?, contact_id?, deal_id?} — at least one of company/contact"""
    from ..enrichment.blueprint import generate_blueprint
    from ..models.crm import Company, Contact
    company = db.get(Company, int(job.payload["company_id"])) if job.payload.get("company_id") else None
    contact = db.get(Contact, int(job.payload["contact_id"])) if job.payload.get("contact_id") else None
    for rec in (company, contact):
        if rec is not None and rec.workspace_id != job.workspace_id:
            raise RuntimeError("record not in this job's workspace")
    if company is None and contact is None:
        raise RuntimeError("company_id or contact_id required")
    if company is None and contact is not None and contact.company_id:
        company = db.get(Company, contact.company_id)
    doc = generate_blueprint(db, job.workspace_id, company, contact, job.payload.get("deal_id"))
    return {"document_id": doc.id, "slug": doc.slug, "title": doc.title}

@register("run_enrich_list")
def run_enrich_list(db, job):
    """List pipeline runner. payload: {list_id, lead_ids?: [..], steps: 'verify'|'pipeline',
    limit?: int}. Processes non-terminal leads only (resume semantics); checks for
    cancellation between leads; updates job progress live."""
    from ..models.enrich import TERMINAL_STATUSES, EnrichLead, EnrichList
    from ..models.jobs import Job as JobModel
    from ..enrichment.pipeline import _config, process_lead

    lst = db.get(EnrichList, int(job.payload.get("list_id", 0)))
    if lst is None or lst.workspace_id != job.workspace_id:
        raise RuntimeError("list not found in this job's workspace")
    cfg = _config(db, job.workspace_id)
    q = db.query(EnrichLead).filter(EnrichLead.list_id == lst.id,
                                    EnrichLead.status.notin_(TERMINAL_STATUSES))
    ids = job.payload.get("lead_ids") or []
    if ids:
        q = q.filter(EnrichLead.id.in_([int(i) for i in ids]))
    limit = int(job.payload.get("limit") or 0)
    leads = q.order_by(EnrichLead.id).limit(limit if limit > 0 else 100000).all()
    steps = job.payload.get("steps", "pipeline")
    counts = {"processed": 0, "done": 0, "invalid": 0, "unsafe": 0, "skipped": 0, "error": 0}
    total = len(leads)
    for i, lead in enumerate(leads):
        # hard Stop: re-read job status so Cancel takes effect mid-run
        db.expire(job)
        if db.get(JobModel, job.id).status == "cancelled":
            job.status = "cancelled"
            break
        status = process_lead(db, lead, cfg, steps=steps)
        counts["processed"] += 1
        counts[status] = counts.get(status, 0) + 1
        job.progress = int(((i + 1) / max(total, 1)) * 100)
        job.progress_note = f"{i + 1}/{total} · {lead.email or lead.company}"[:250]
        db.commit()
    return {"total_selected": total, **counts}


# Future handlers, one decorator each:
#   @register("same_day_nudge")     — handoff doc §12
#   @register("proposal_follow_up") — unopened-proposal reminder
