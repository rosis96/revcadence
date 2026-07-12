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
        status = process_lead(db, lead, cfg, steps=steps,
                              enrichments=job.payload.get("enrichments") or None)
        counts["processed"] += 1
        counts[status] = counts.get(status, 0) + 1
        job.progress = int(((i + 1) / max(total, 1)) * 100)
        job.progress_note = f"{i + 1}/{total} · {lead.email or lead.company}"[:250]
        db.commit()
    return {"total_selected": total, **counts}


@register("find_competitors")
def find_competitors_job(db, job):
    """payload: {list_id, lead_ids: [..]}. Skips leads that already have
    competitors (or a recorded empty attempt). Cancellable mid-run."""
    from ..enrichment.ai import find_competitors
    from ..models.enrich import EnrichLead, EnrichList
    from ..models.jobs import Job as JobModel

    lst = db.get(EnrichList, int(job.payload.get("list_id", 0)))
    if lst is None or lst.workspace_id != job.workspace_id:
        raise RuntimeError("list not found in this job's workspace")
    ids = [int(i) for i in (job.payload.get("lead_ids") or [])]
    leads = (db.query(EnrichLead).filter(EnrichLead.list_id == lst.id,
                                         EnrichLead.id.in_(ids)).order_by(EnrichLead.id).all())
    found = skipped = 0
    total = len(leads)
    for i, lead in enumerate(leads):
        db.expire(job)
        if db.get(JobModel, job.id).status == "cancelled":
            job.status = "cancelled"
            break
        if lead.competitors or (lead.result or {}).get("_competitors_ran"):
            skipped += 1
            continue
        services = ((lead.result or {}).get("_facts") or {}).get("services", [])
        comps = find_competitors(lead.company, lead.industry, services)
        lead.competitors = comps
        lead.result = {**(lead.result or {}), "_competitors_ran": True}
        found += 1 if comps else 0
        job.progress = int(((i + 1) / max(total, 1)) * 100)
        job.progress_note = f"{i + 1}/{total} · {lead.company}"[:250]
        db.commit()
    return {"total_selected": total, "found_for": found, "skipped_existing": skipped}


@register("process_reply")
def process_reply_job(db, job):
    """The engine run for one inbound webhook. Guards, generation, decision —
    auto-send only when AUTO_SEND_ENABLED=1; otherwise action='would_send'
    lands in Needs Review. Never breaks on unrouted leads."""
    import json as _json
    from datetime import datetime

    from ..models.reply import ReplyLead, ReplyWorkspace
    from ..reply import engine as E
    from ..crypto import decrypt

    p = job.payload or {}
    payload, platform, flow = p.get("webhook") or {}, p.get("platform"), p.get("flow", "reply")
    rws = db.query(ReplyWorkspace).filter(ReplyWorkspace.name == p.get("reply_workspace")).first()

    # extract identity from payload (tolerant, both platforms)
    data = payload.get("data") or payload
    lead_obj = data.get("lead") or data
    email = str(lead_obj.get("email") or lead_obj.get("lead_email") or "").lower().strip()
    external_id = str(E.deep_find_lead_id(payload) or email or "")
    reply_id = str(data.get("reply_id") or (data.get("reply") or {}).get("id") or "")
    dedupe = f"{platform}:{external_id}:{reply_id or email}"
    if db.query(ReplyLead).filter(ReplyLead.dedupe_key == dedupe).first():
        return {"skipped": "duplicate reply"}

    lead = ReplyLead(
        workspace_id=rws.workspace_id if rws else None,
        reply_workspace=p.get("reply_workspace") or "Unrouted",
        platform=platform, dedupe_key=dedupe, external_lead_id=external_id, reply_id=reply_id,
        name=str(lead_obj.get("first_name") or lead_obj.get("name") or "").strip(),
        email=email, company=str(lead_obj.get("company") or lead_obj.get("company_name") or ""),
        campaign=str(data.get("campaign_name") or data.get("campaign_id") or ""),
        subject=str(data.get("subject") or ""), lead_data=payload)
    db.add(lead)
    db.commit()

    if rws is None:
        lead.action = "error"
        lead.intent = "unrouted"
        db.commit()
        return {"recorded": lead.id, "unrouted": True}

    # follow-up loop guard (reply mode only — legacy §8, two layers)
    if flow == "reply" and rws.mode == "reply":
        handled = (db.query(ReplyLead)
                   .filter(ReplyLead.reply_workspace == rws.name,
                           ReplyLead.external_lead_id == external_id,
                           ReplyLead.id != lead.id,
                           (ReplyLead.replied == True) | (ReplyLead.fup_added == True)  # noqa: E712
                           | (ReplyLead.reply_added == True)).first())
        if handled or E.scan_for_campaign_id(payload, rws.reply_followup_campaign_id):
            lead.action = "stop"
            lead.intent = "already_handled"
            db.commit()
            return {"recorded": lead.id, "guard": "follow-up loop"}

    # thread
    thread, send_meta = [], {}
    if platform == "bison" and rws.base_url:
        thread = E.fetch_bison_thread(external_id, decrypt(rws.api_key_enc), rws.base_url)
        inbound = [m for m in thread if m.get("direction") == "in"]
        if inbound:
            lead.reply_text = inbound[-1].get("text", "")
            send_meta = {"reply_id": inbound[-1].get("reply_id"),
                         "to_name": lead.name, "to_email": lead.email}
    else:
        body_text = str(data.get("reply_text") or data.get("text") or data.get("body") or "")
        lead.reply_text = body_text
        thread = [{"direction": "in", "text": body_text}]
        send_meta = {"reply_to_uuid": data.get("reply_to_uuid") or data.get("email_id"),
                     "eaccount": data.get("eaccount"), "subject": lead.subject}
    lead.thread = thread
    lead.send_meta = send_meta

    # generate + decide
    ai = E.call_llm(*E.build_reply_prompt(rws, thread), E.build_ai_cfg(rws))
    lead.intent = str(ai.get("intent", ""))
    lead.confidence = str(ai.get("confidence", ""))
    lead.main_reply = str(ai.get("main_reply", ""))
    lead.followups = [ai.get(f"followup_{i}") for i in range(1, 7) if ai.get(f"followup_{i}")]
    lead.reply_added = bool(lead.main_reply) and not ai.get("_fallback")
    action = E.decide_reply_action(ai, rws.reply_format or {}, lead.reply_text)
    # detectable fallback is NEVER sent — but a stop (unsubscribe/OOO) still wins
    if ai.get("_fallback") and action == "send":
        action = "skip_enrich"

    if action == "send" and not E.auto_send_enabled():
        action = "would_send"   # kill-switch: review instead of sending
    lead.action = action

    sent = False
    if action == "send":
        try:
            message = E.add_signature(lead.main_reply, rws.sender_name, rws.website)
            if platform == "bison":
                E.send_bison_reply(rws, send_meta, message)
            else:
                E.send_instantly_reply(rws, send_meta, message, lead.subject)
            lead.replied = True
            lead.stage = "replied"
            sent = True
        except Exception as e:
            lead.action = "error"
            lead.lead_data = {**(lead.lead_data or {}), "_send_error": str(e)[:300]}

    # write follow-up variables back (Bison merge fix)
    if platform == "bison" and lead.followups and action in ("send", "would_send", "skip_enrich"):
        try:
            E.merge_bison_variables(rws, external_id, {
                "main_reply": lead.main_reply,
                **{f"followup_{i+1}": f for i, f in enumerate(lead.followups)},
                "reply_intent": lead.intent, "reply_confidence": lead.confidence})
            lead.fup_added = True
        except Exception:
            pass
    lead.updated_at = datetime.utcnow()
    db.commit()
    return {"recorded": lead.id, "intent": lead.intent, "action": lead.action, "sent": sent}


# Future handlers, one decorator each:
#   @register("same_day_nudge")     — handoff doc §12
#   @register("proposal_follow_up") — unopened-proposal reminder
