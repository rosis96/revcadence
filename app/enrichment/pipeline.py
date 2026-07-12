"""The Verify → Enrich pipeline, ported from the enrichment dashboard's
_pipeline_one. Cheapest-first funnel — ORDER IS DELIBERATE, DO NOT REORDER:

  1. FREE verify   → reject dead emails at $0        → status "invalid"
  2. Reoon verify  → mailbox real? not safe → stop   → status "unsafe"
  3. Title gate + ICP (one scrape + one extraction)  → Non-ICP → "skipped"
  4. Write copy (reuses the ICP context — no second scrape/extraction) → "done"

Resume semantics: leads already in a TERMINAL status are never re-processed.
"""
import json
import os
from datetime import datetime

from ..models.enrich import TERMINAL_STATUSES, EnrichConfig, EnrichLead
from . import ai
from .crawler import crawl_site
from .engine import SENIOR_TITLES
from .reoon import verify_one
from .verify_free import check as free_check


def _config(db, workspace_id) -> EnrichConfig:
    cfg = db.query(EnrichConfig).filter(EnrichConfig.workspace_id == workspace_id).first()
    if cfg is None:
        cfg = EnrichConfig(workspace_id=workspace_id)
        db.add(cfg)
        db.flush()
    return cfg


def _title_gate(title: str) -> bool:
    t = (title or "").lower()
    return any(s in t for s in SENIOR_TITLES)


def _icp_and_facts(lead: EnrichLead, cfg: EnrichConfig) -> dict:
    """One scrape + one extraction; returns ctx reused by the writer."""
    crawl = crawl_site(lead.website, html_override=(lead.data or {}).get("html_override", ""))
    if crawl.get("error") or not crawl.get("text"):
        return {"error": crawl.get("error") or "no website content", "crawl": crawl}
    if ai.has_ai():
        system = ("You are an ICP classifier and fact extractor. Ground everything ONLY in the "
                  "provided site text — never invent. ICP definition (single source of truth):\n"
                  + (cfg.icp_definition or "B2B companies selling high-value services to other businesses.")
                  + '\nReturn JSON: {"icp_decision": "ICP"|"Non-ICP"|"Needs Review", "icp_score": 0-100, '
                    '"icp_reason": str, "industry": str, "facts": {"description": str, "services": [str]}}')
        user = f"Company: {lead.company}\nSite: {crawl.get('url')}\nText:\n{crawl.get('text')[:8000]}"
        try:
            out = ai._call_openai(system, user)
            out["crawl"] = crawl
            out["source"] = "openai"
            return out
        except Exception as e:
            pass  # fall through to demo
    facts = ai.extract_company(crawl)
    fit = facts.get("icp_fit", "unknown")
    return {"icp_decision": "ICP" if fit in ("strong", "possible") else "Needs Review",
            "icp_score": {"strong": 85, "possible": 60}.get(fit, 40),
            "icp_reason": facts.get("icp_reason", ""), "industry": facts.get("industry", ""),
            "facts": {"description": facts.get("description", ""), "services": facts.get("services", [])},
            "crawl": crawl, "source": "demo"}


def _write_copy(lead: EnrichLead, cfg: EnrichConfig, ctx: dict) -> dict:
    """Writes the configured variables, reusing ctx (no second scrape)."""
    formats = cfg.formats or []
    if not formats:
        formats = [{"label": "Personalized First Line", "name": "personalized_first_line",
                    "guidance": "One specific sentence proving we researched THIS company, "
                                "grounded in a real fact from their site. No generic flattery.",
                    "min_words": 12, "max_words": 25}]
    rules = [ln.strip() for ln in (cfg.rules or "").splitlines() if ln.strip()]
    if ai.has_ai():
        # Static prefix FIRST (prompt caching), per-lead content LAST — preserve ordering.
        system = ("You write personalized cold-email copy grounded ONLY in verified facts. "
                  "Never fabricate. Match each variable's guidance and word range exactly.\n"
                  "CLIENT PROFILE:\n" + json.dumps(cfg.profile or {}) +
                  "\nGLOBAL RULES (obey every line):\n" + "\n".join(rules) +
                  "\nVARIABLES (return JSON keyed by 'name'):\n" + json.dumps(formats))
        user = ("LEAD: " + json.dumps({"first_name": lead.first_name, "company": lead.company,
                                       "title": lead.title}) +
                "\nVERIFIED FACTS: " + json.dumps(ctx.get("facts", {})) +
                "\nSITE EXCERPT:\n" + (ctx.get("crawl", {}).get("text", "")[:6000]))
        try:
            out = ai._call_openai(system, user)
            return {"vars": {f["name"]: out.get(f["name"], "") for f in formats}, "source": "openai"}
        except Exception:
            pass
    desc = (ctx.get("facts", {}) or {}).get("description", "") or f"what {lead.company} does"
    return {"vars": {f.get("name", f"var_{i}"):
                     f"Really like how {lead.company} focuses on {desc[:80].rstrip('.')} — impressive work."
                     for i, f in enumerate(formats)}, "source": "demo"}


def process_lead(db, lead: EnrichLead, cfg: EnrichConfig, steps: str = "pipeline") -> str:
    """Run one lead through the funnel. steps: 'verify' (stop after Reoon) or
    'pipeline' (full). Returns the resulting status."""
    if lead.status in TERMINAL_STATUSES:
        return lead.status  # resume semantics — never re-charge finished work

    # 1. FREE verify ($0)
    if not lead.free_status:
        v = free_check(lead.email)
        lead.free_status = v["verdict"]
        if v["reject"]:
            lead.status = "invalid"
            lead.email_status = "skipped"     # Reoon credit saved
            lead.verify_source = "free"
            db.commit()
            return lead.status

    # 2. Reoon (mailbox-level)
    if not lead.email_status or lead.email_status == "skipped":
        r = verify_one(lead.email)
        lead.email_status = r["status"]
        lead.verify_source = "reoon"
        lead.result = {**(lead.result or {}), "_reoon": r["raw"]}
        if r["status"] not in ("safe", "valid", "catch_all", "unknown"):
            lead.status = "unsafe"
            db.commit()
            return lead.status
        if r["status"] in ("catch_all", "unknown") and os.getenv("ONLY_SAFE", "1") == "1" \
                and r["status"] == "invalid":
            pass  # explicitness; invalid handled above
    if steps == "verify":
        db.commit()
        return lead.status or "pending"

    # 3. Title gate (before any scraping) + ICP
    if not cfg.skip_title_gate and lead.title and not _title_gate(lead.title):
        lead.title_status = "rejected"
        lead.status = "skipped"
        lead.icp_decision = "Non-ICP"
        lead.icp_reason = "title gate: not a senior decision-maker"
        db.commit()
        return lead.status
    lead.title_status = lead.title_status or "pass"

    if not lead.website:
        lead.status = "error"
        lead.result = {**(lead.result or {}), "_error": "no website"}
        db.commit()
        return lead.status

    icp = _icp_and_facts(lead, cfg)
    if icp.get("error"):
        lead.status = "error"
        lead.result = {**(lead.result or {}), "_error": icp["error"]}
        db.commit()
        return lead.status
    lead.icp_decision = icp.get("icp_decision", "Needs Review")
    lead.icp_score = icp.get("icp_score")
    lead.icp_reason = icp.get("icp_reason", "")
    lead.industry = icp.get("industry", "")
    if lead.icp_decision == "Non-ICP":
        lead.status = "skipped"
        db.commit()
        return lead.status

    # 4. Write copy — reuses icp ctx; no second scrape/extraction
    written = _write_copy(lead, cfg, icp)
    lead.result = {**(lead.result or {}), **written["vars"],
                   "_facts": icp.get("facts", {}), "_writer": written["source"]}
    lead.status = "done"
    lead.updated_at = datetime.utcnow()
    db.commit()
    return lead.status
