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


def _format_reply_date(raw) -> str:
    """Human 'Mon, Jul 13, 2026 at 5:31 PM' for the quoted-thread header. Accepts
    an ISO timestamp; falls back to now, or '' if formatting fails."""
    from datetime import datetime
    s = str(raw or "").strip()
    try:
        if s:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            dt = datetime.utcnow()
        return dt.strftime("%a, %b %-d, %Y at %-I:%M %p")
    except Exception:
        return ""


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

# ---------------------------------------------------------------- mailbox backfill
@register("mailbox_backfill")
def mailbox_backfill_job(db, job):
    """payload: {workspace_id, days?} — the 'wow on connect' import of recent mail."""
    from ..mailbox import service
    return service.backfill(db, job.workspace_id, days=int(job.payload.get("days", 60)))


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
    limit?: int, workers?: int}. Processes non-terminal leads only (resume
    semantics); checks for cancellation live; updates job progress live.

    process_lead is almost entirely network I/O (MX/DNS, Reoon, site crawl, AI),
    so with workers>1 we fan leads out across a thread pool — each thread gets
    its OWN DB session (Sessions aren't thread-safe). The main thread's session
    only tracks job progress/cancellation."""
    from ..models.enrich import TERMINAL_STATUSES, EnrichLead, EnrichList
    from ..models.jobs import Job as JobModel
    from ..enrichment.pipeline import _config, process_lead

    lst = db.get(EnrichList, int(job.payload.get("list_id", 0)))
    if lst is None or lst.workspace_id != job.workspace_id:
        raise RuntimeError("list not found in this job's workspace")
    q = db.query(EnrichLead.id).filter(EnrichLead.list_id == lst.id,
                                       EnrichLead.status.notin_(TERMINAL_STATUSES))
    ids = job.payload.get("lead_ids") or []
    if ids:
        q = q.filter(EnrichLead.id.in_([int(i) for i in ids]))
    limit = int(job.payload.get("limit") or 0)
    lead_ids = [r[0] for r in q.order_by(EnrichLead.id).limit(limit if limit > 0 else 100000).all()]
    steps = job.payload.get("steps", "pipeline")
    enrichments = job.payload.get("enrichments") or None
    workers = max(1, min(int(job.payload.get("workers") or 1), 25))
    counts = {"processed": 0, "done": 0, "invalid": 0, "unsafe": 0, "skipped": 0, "error": 0}
    total = len(lead_ids)

    def _cancelled():
        db.expire(job)
        return db.get(JobModel, job.id).status == "cancelled"

    def _tick(i, status, note):
        counts["processed"] += 1
        counts[status] = counts.get(status, 0) + 1
        job.progress = int((i / max(total, 1)) * 100)
        job.progress_note = f"{i}/{total} · {note}"[:250]
        db.commit()

    # Sequential path (workers=1) — unchanged behaviour, shared session.
    if workers <= 1:
        wid = job.workspace_id
        cfg = _config(db, wid)
        for i, lid in enumerate(lead_ids):
            if _cancelled():
                job.status = "cancelled"
                break
            lead = db.get(EnrichLead, lid)
            if lead is None:
                _tick(i + 1, "error", str(lid)); continue
            status = process_lead(db, lead, cfg, steps=steps, enrichments=enrichments)
            _tick(i + 1, status, lead.email or lead.company)
        return {"total_selected": total, "workers": 1, **counts}

    # Concurrent path — one session per thread, main thread aggregates results.
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from threading import Event
    from ..db import session as thread_session

    stop = Event()
    wid = job.workspace_id
    # Materialize the config row ONCE up front so worker threads only read it —
    # otherwise every thread races to INSERT the default config for a new
    # workspace (duplicate rows on Postgres, "database is locked" on SQLite).
    _config(db, wid)
    db.commit()

    def work(lid):
        if stop.is_set():
            return ("skipped", str(lid), True)  # skipped-because-cancelled → don't count
        with thread_session() as s:
            lead = s.get(EnrichLead, lid)
            if lead is None:
                return ("error", str(lid), False)
            cfg = _config(s, wid)
            status = process_lead(s, lead, cfg, steps=steps, enrichments=enrichments)
            return (status, lead.email or lead.company, False)

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(work, lid): lid for lid in lead_ids}
        for fut in as_completed(futures):
            status, note, cancelled_skip = fut.result()
            if cancelled_skip:
                continue
            done += 1
            _tick(done, status, note)
            if not stop.is_set() and _cancelled():
                stop.set()               # new leads bail out; in-flight ones finish
                job.status = "cancelled"
    return {"total_selected": total, "workers": workers, **counts}


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

    from ..reply.sync import _deep_get
    # Name can arrive as first_name, firstName (camelCase), name, or nested — dig
    # for it so greetings personalize reliably (the AI shouldn't have to guess).
    lead_name = (str(lead_obj.get("first_name") or lead_obj.get("firstName") or lead_obj.get("name") or "").strip()
                 or str(_deep_get(payload, {"first_name", "firstname"}) or "").strip())
    lead = ReplyLead(
        workspace_id=rws.workspace_id if rws else None,
        reply_workspace=p.get("reply_workspace") or "Unrouted",
        platform=platform, dedupe_key=dedupe, external_lead_id=external_id, reply_id=reply_id,
        name=lead_name,
        email=email, company=str(lead_obj.get("company") or lead_obj.get("company_name")
                                 or lead_obj.get("companyName") or _deep_get(payload, {"company", "companyname"}) or ""),
        campaign=str(data.get("campaign_name") or data.get("campaign_id") or ""),
        subject=str(data.get("subject") or data.get("reply_subject") or ""), lead_data=payload)
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

    from ..reply.sync import _deep_get
    # A human-readable date for the quoted thread ("On <date>, <name> wrote:").
    reply_date = _format_reply_date(_deep_get(payload, {"timestamp", "reply_timestamp", "date"}))
    # thread
    thread, send_meta = [], {}
    if platform == "bison" and rws.base_url:
        thread = E.fetch_bison_thread(external_id, decrypt(rws.api_key_enc), rws.base_url)
        inbound = [m for m in thread if m.get("direction") == "in"]
        if inbound:
            lead.reply_text = inbound[-1].get("text", "")
            send_meta = {"reply_id": inbound[-1].get("reply_id"),
                         "to_name": lead.name, "to_email": lead.email,
                         "reply_text_new": lead.reply_text, "reply_date": reply_date}
    else:
        body_text = str(data.get("reply_text") or data.get("text") or data.get("body") or "")
        campaign_id = str(data.get("campaign_id") or _deep_get(payload, {"campaign_id"}) or "")
        # Pull the FULL conversation from Instantly so the AI reads the whole
        # back-and-forth, not just the latest reply. Fall back to the single
        # webhook reply if the API can't return the thread.
        thread = E.fetch_instantly_thread(decrypt(rws.api_key_enc), email, campaign_id)
        if not thread:
            thread = [{"direction": "in", "text": body_text}]
        inbound = [m for m in thread if m.get("direction") == "in"]
        # latest inbound turn drives STOP-keyword detection + the quoted reply
        lead.reply_text = (inbound[-1]["text"] if inbound else body_text)
        # Instantly nests the reply target under different keys/levels depending on
        # the event — deep-search the whole payload so the reply-to UUID and the
        # sending mailbox (eaccount) are found wherever they live.
        reply_uuid = (data.get("reply_to_uuid") or data.get("email_id")
                      or _deep_get(payload, {"reply_to_uuid", "email_id", "message_id", "uuid", "id"}))
        eaccount = (data.get("eaccount")
                    or _deep_get(payload, {"eaccount", "email_account", "from_email", "sender_email"}))
        # Carry the lead email + campaign so we can look the reply target up later
        # if this webhook (e.g. lead_interested) didn't include reply_to_uuid/eaccount,
        # plus the fields needed to build the Gmail-style quoted thread.
        send_meta = {"reply_to_uuid": reply_uuid, "eaccount": eaccount, "subject": lead.subject,
                     "lead_email": email, "to_name": lead.name, "to_email": email,
                     "reply_text_new": lead.reply_text, "reply_date": reply_date,
                     "campaign_id": campaign_id}
    lead.thread = thread
    lead.send_meta = send_meta

    # blocklist: a reply from a blocked sender is never drafted or sent.
    try:
        from ..reply.sync import is_blocked
        if is_blocked(db, lead.workspace_id, email):
            lead.action = "stop"
            lead.stage = "stopped"
            lead.intent = lead.intent or "blocked"
            db.commit()
            return {"stopped": "blocked sender", "email": email}
    except Exception:
        pass

    # Calendly scheduling context (real open times, prospect TZ, reserved so no
    # two prospects get the same slot). Graceful "" when no token / error.
    sched = ""
    try:
        from ..reply.calendly import build_scheduling_context
        location = str((lead.lead_data or {}).get("location") or
                       (data.get("location") if isinstance(data, dict) else "") or "")
        sched = build_scheduling_context(db, rws, location, prospect_key=email, mode=flow)
    except Exception:
        sched = ""

    # generate + decide — via the ONE shared path the Test Thread screen also uses,
    # so a paste-in test always matches what production produces here.
    first = E.first_name_of(lead.name)
    gen = E.generate_reply(rws, thread, scheduling_context=sched,
                           prospect={"first_name": first, "company": lead.company})
    lead.intent = gen["intent"]
    lead.confidence = gen["confidence"]
    lead.main_reply = gen["main_reply"]
    lead.followups = gen["followups"]
    lead.reply_added = bool(lead.main_reply) and gen["model_ran"]
    action = gen["action"]

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
            lead.send_error = ""
            sent = True
        except Exception as e:
            # persist on the same column the manual path + drawer use, so the
            # failure reason is visible for auto-send failures too.
            lead.action = "error"
            lead.send_error = str(e)[:500]
            lead.lead_data = {**(lead.lead_data or {}), "_send_error": str(e)[:300]}

    # sync to CRM + enrichment: contact/company + enrich by email, and every
    # interested reply → an Opportunity deal (the pipeline card). The company/
    # contact are created but hidden from the Companies/Contacts LISTS until a
    # meeting is booked — those lists are for booked/active conversations only
    # (see the interested-only filter in routers/crm.py).
    try:
        from ..reply.sync import sync_reply_lead_to_crm, sync_interested_to_opportunity
        sync_reply_lead_to_crm(db, lead, queue_enrich=True)
        sync_interested_to_opportunity(db, lead)
    except Exception:
        pass  # CRM sync must never block the reply pipeline

    # write follow-up variables back so the platform's follow-up steps can send them.
    if lead.followups and action in ("send", "would_send", "skip_enrich"):
        if platform == "bison":
            try:
                E.merge_bison_variables(rws, external_id, {
                    "main_reply": lead.main_reply,
                    **{f"followup_{i+1}": f for i, f in enumerate(lead.followups)},
                    "reply_intent": lead.intent, "reply_confidence": lead.confidence})
                lead.fup_added = True
            except Exception:
                pass
        elif platform == "instantly":
            # push followup_1..N onto the Instantly lead as custom variables
            # (also auto-declares them on the campaign) so a follow-up
            # campaign/subsequence using {{followup_1}} can send them.
            try:
                res = E.push_instantly_followups(rws, lead.email, (send_meta or {}).get("campaign_id"),
                                                 lead.followups, lead.main_reply)
                lead.fup_added = bool(res.get("ok"))
                if not res.get("ok"):
                    lead.lead_data = {**(lead.lead_data or {}), "_fup_push_error": str(res.get("error", ""))[:300]}
            except Exception:
                pass
    lead.updated_at = datetime.utcnow()
    db.commit()
    return {"recorded": lead.id, "intent": lead.intent, "action": lead.action, "sent": sent}


# Future handlers, one decorator each:
#   @register("same_day_nudge")     — handoff doc §12
#   @register("proposal_follow_up") — unopened-proposal reminder


# ---------------------------------------------------------------- external API platform
@register("webhook_delivery")
def webhook_delivery(db, job):
    """Deliver one signed outbound webhook (retries are self-scheduled)."""
    from ..extapi import events
    return events.deliver(db, int(job.payload.get("delivery_id", 0)))


@register("crm_sync")
def crm_sync(db, job):
    """Run an outbound CRM sync for one connection (full or event-triggered)."""
    from ..extapi import sync
    return sync.run_sync(db, int(job.payload.get("connection_id", 0)),
                         entity_ids=job.payload.get("entity_ids") or None)
