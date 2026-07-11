"""Enrichment engine: orchestrates crawl → extract → write, with provenance,
progress tracking, and CRM timeline records. Workspace isolation is inherent —
every record already carries workspace_id and jobs are enqueued through the
workspace-scoped API."""
from datetime import datetime

from ..models.crm import Activity, Company, Contact
from . import ai
from .crawler import crawl_site

SENIOR_TITLES = ("founder", "ceo", "coo", "cfo", "cmo", "cro", "owner", "president",
                 "vp", "vice president", "head of", "director", "partner", "principal")


def _provenance(fields: dict, source: str) -> dict:
    at = datetime.utcnow().isoformat()
    return {k: {"value": v, "source": source, "at": at} for k, v in fields.items() if v not in ("", [], None)}


def _progress(db, job, pct, note):
    if job is not None:
        job.progress = pct
        job.progress_note = note[:250]
        db.commit()


def enrich_company(db, company: Company, job=None, html_override: str = "") -> dict:
    _progress(db, job, 10, "crawling website")
    crawl = crawl_site(company.website or company.domain, html_override=html_override,
                       on_progress=lambda m: _progress(db, job, 25, m))
    _progress(db, job, 55, "extracting facts")
    facts = ai.extract_company(crawl)
    source = facts.pop("_source", "unknown")

    _progress(db, job, 80, "writing enrichment")
    if facts.get("industry") and not company.industry:
        company.industry = facts["industry"]
    if facts.get("location") and not company.location:
        company.location = facts["location"]
    if facts.get("icp_fit"):
        company.icp_fit = facts["icp_fit"]
    enrichment = dict(company.enrichment or {})
    enrichment.update(_provenance(facts, source))
    enrichment["last_crawl"] = {"value": {"pages": crawl.get("pages", []), "title": crawl.get("title", ""),
                                          "error": crawl.get("error", "")},
                                "source": "crawler", "at": datetime.utcnow().isoformat()}
    company.enrichment = enrichment
    company.updated_at = datetime.utcnow()

    db.add(Activity(workspace_id=company.workspace_id, company_id=company.id, kind="enriched",
                    title=f"Company enriched ({source})",
                    data={"fields": list(facts.keys()), "pages": crawl.get("pages", [])}))
    db.commit()
    _progress(db, job, 100, "done")
    return {"company_id": company.id, "source": source, "fields": list(facts.keys()),
            "icp_fit": company.icp_fit, "crawl_error": crawl.get("error", "")}


def revenue_score(contact: Contact, company: Company | None) -> float:
    """AI Revenue Score v1: transparent heuristic (0–100). Recomputed on every
    enrichment; later phases blend engagement signals."""
    score = 20.0
    title = (contact.title or "").lower()
    if any(t in title for t in SENIOR_TITLES):
        score += 30
    elif title:
        score += 10
    if contact.email_status == "valid":
        score += 15
    if company is not None:
        fit = (company.icp_fit or "").lower()
        score += {"strong": 30, "possible": 15, "weak": 0}.get(fit, 5)
        if company.industry:
            score += 5
    return min(round(score, 1), 100.0)


def enrich_contact(db, contact: Contact, job=None, html_override: str = "") -> dict:
    company = db.get(Company, contact.company_id) if contact.company_id else None
    # company first (it feeds the score); skip if enriched recently
    if company is not None and not (company.enrichment or {}).get("last_crawl"):
        _progress(db, job, 10, "enriching company first")
        enrich_company(db, company, job=None, html_override=html_override)

    _progress(db, job, 60, "deriving contact fields")
    facts = {}
    if not contact.timezone and contact.location:
        facts["location_note"] = contact.location
    seniority = "senior" if any(t in (contact.title or "").lower() for t in SENIOR_TITLES) else \
                ("staff" if contact.title else "unknown")
    facts["seniority"] = seniority

    enrichment = dict(contact.enrichment or {})
    enrichment.update(_provenance(facts, "derived"))
    contact.enrichment = enrichment
    contact.revenue_score = revenue_score(contact, company)
    contact.updated_at = datetime.utcnow()

    db.add(Activity(workspace_id=contact.workspace_id, contact_id=contact.id,
                    company_id=contact.company_id, kind="enriched",
                    title=f"Contact enriched · score {contact.revenue_score}",
                    data={"seniority": seniority, "revenue_score": contact.revenue_score}))
    db.commit()
    _progress(db, job, 100, "done")
    return {"contact_id": contact.id, "revenue_score": contact.revenue_score, "seniority": seniority}
