"""Reply → CRM + Enrichment sync (legacy: booked leads flow to the CRM;
webhook leads get their platform lead_data parsed into contact/company).

extract_lead_enrichment: tolerant parser pulling company / location / website /
contact-LinkedIn / company-LinkedIn out of a raw Bison/Instantly payload
(legacy db.extract_lead_enrichment)."""
from datetime import datetime


def _deep_get(obj, keys):
    """First non-empty value for any of `keys` anywhere in a nested dict/list."""
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if str(k).lower() in keys and v not in (None, "", [], {}):
                    return v
                stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
    return ""


def extract_lead_enrichment(lead_data: dict) -> dict:
    ld = lead_data or {}
    return {
        "company": str(_deep_get(ld, {"company", "company_name", "organization"}) or ""),
        "website": str(_deep_get(ld, {"website", "company_website", "domain", "url"}) or ""),
        "location": str(_deep_get(ld, {"location", "city", "country"}) or ""),
        "contact_linkedin": str(_deep_get(ld, {"linkedin", "linkedin_url", "personal_linkedin"}) or ""),
        "company_linkedin": str(_deep_get(ld, {"company_linkedin", "company_linkedin_url"}) or ""),
        "title": str(_deep_get(ld, {"title", "job_title", "position"}) or ""),
    }


def sync_reply_lead_to_crm(db, lead, queue_enrich: bool = True) -> dict:
    """Create/link a Contact (+ Company) in the CRM from a ReplyLead, carrying
    the platform-provided data, and optionally queue enrichment by email.
    Idempotent by email per workspace. Returns ids."""
    from ..models.crm import Activity, Company, Contact
    from ..models.jobs import Job

    if not lead.workspace_id:
        return {"skipped": "unrouted lead has no workspace"}
    info = extract_lead_enrichment(lead.lead_data or {})
    email = (lead.email or "").lower().strip()

    company = None
    cname = (info["company"] or lead.company or "").strip()
    if cname:
        company = db.query(Company).filter(Company.workspace_id == lead.workspace_id,
                                           Company.name == cname).first()
        if company is None:
            company = Company(workspace_id=lead.workspace_id, name=cname,
                              website=info["website"], location=info["location"],
                              linkedin_url=info["company_linkedin"])
            db.add(company)
            db.flush()

    contact = None
    if email:
        contact = db.query(Contact).filter(Contact.workspace_id == lead.workspace_id,
                                            Contact.email == email).first()
    if contact is None and (email or lead.name):
        first, _, last = (lead.name or "").partition(" ")
        contact = Contact(workspace_id=lead.workspace_id, email=email, first_name=first,
                          last_name=last, title=info["title"], location=info["location"],
                          linkedin_url=info["contact_linkedin"],
                          company_id=company.id if company else None, source="reply")
        db.add(contact)
        db.flush()
        queued = False
        if queue_enrich and (company and (company.website or company.domain)):
            db.add(Job(kind="enrich_contact", workspace_id=lead.workspace_id,
                       payload={"contact_id": contact.id}))
            queued = True
        db.add(Activity(workspace_id=lead.workspace_id, contact_id=contact.id,
                        company_id=company.id if company else None, kind="email_in",
                        title=f"Reply · {lead.intent or 'inbound'}", body=(lead.reply_text or "")[:500],
                        data={"reply_lead_id": lead.id, "intent": lead.intent}))
        return {"contact_id": contact.id, "company_id": company.id if company else None,
                "enrich_queued": queued, "created": True}
    else:
        # existing contact: fill blanks from platform data
        if contact and company and not contact.company_id:
            contact.company_id = company.id
        if contact and info["contact_linkedin"] and not contact.linkedin_url:
            contact.linkedin_url = info["contact_linkedin"]
    return {"contact_id": contact.id if contact else None,
            "company_id": company.id if company else None, "created": False}


def is_interested(lead) -> bool:
    """Any engaged reply worth a pipeline opportunity: it reached a workspace and
    was NOT stopped (unsubscribe / OOO / wrong-person / auto-reply become
    action='stop' and are excluded). Everything else is a real inbound
    opportunity — that is exactly what the user wants synced."""
    if lead.action in ("stop", "error"):
        return False
    if (lead.intent or "").lower() in ("unrouted", "already_handled"):
        return False
    return True


def sync_interested_to_opportunity(db, lead) -> dict:
    """Every interested reply → a CRM deal in the 'Opportunity' stage (deduped by
    contact). Never downgrades a deal that's already further along."""
    from ..models.crm import Activity, Deal, Stage

    if not lead.workspace_id or not is_interested(lead):
        return {"skipped": "not interested"}
    synced = sync_reply_lead_to_crm(db, lead, queue_enrich=False)
    cid = synced.get("contact_id")
    if not cid:
        return {"skipped": "no contact"}
    existing = db.query(Deal).filter(Deal.workspace_id == lead.workspace_id,
                                     Deal.contact_id == cid).first()
    if existing:
        return {"deal_id": existing.id, "existed": True}
    opp = db.query(Stage).filter(Stage.workspace_id == lead.workspace_id,
                                 Stage.name == "Opportunity").order_by(Stage.sort_order).first()
    deal = Deal(workspace_id=lead.workspace_id,
                name=f"{lead.company or lead.name or lead.email} — opportunity",
                contact_id=cid, company_id=synced.get("company_id"),
                stage_id=opp.id if opp else None, lead_intent=lead.intent, source="reply")
    db.add(deal)
    db.flush()
    db.add(Activity(workspace_id=lead.workspace_id, deal_id=deal.id, contact_id=cid,
                    kind="deal_created", title="Opportunity from interested reply",
                    data={"reply_lead_id": lead.id, "intent": lead.intent}))
    return {"deal_id": deal.id, "created": True}


# ---- two-way status sync: CRM deal stage <-> ReplyLead.stage ----------------
# The reply inbox and the CRM pipeline are two views of the same conversation, so
# a status change in either place must show in the other.
CRM_TO_REPLY_STAGE = {
    "Opportunity": "interested", "Meeting Booked": "booked",
    "Meeting Completed": "meeting_completed", "No Show": "no_show",
    "Follow-up": "follow_up", "Won": "won", "Lost": "not_interested",
}
# reply-side label token → CRM stage name (the inbox label picker).
REPLY_TO_CRM_STAGE = {
    "interested": "Opportunity", "booked": "Meeting Booked", "meeting_booked": "Meeting Booked",
    "meeting_completed": "Meeting Completed", "no_show": "No Show", "follow_up": "Follow-up",
    "won": "Won", "lost": "Lost", "not_interested": "Lost",
}
# labels that are really "stop" outcomes — no pipeline move, mark the lead stopped.
STOP_LABELS = {"out_of_office", "wrong_person", "unsubscribe", "stopped"}


def is_blocked(db, workspace_id, email) -> bool:
    """True if the sender is on the workspace blocklist (auto-stop new replies)."""
    from ..models.reply import ReplyBlock
    email = (email or "").lower().strip()
    if not email or not workspace_id:
        return False
    return db.query(ReplyBlock).filter(ReplyBlock.workspace_id == workspace_id,
                                       ReplyBlock.email.ilike(email)).first() is not None


def sync_deal_stage_to_reply(db, deal, stage) -> dict:
    """CRM → Reply: when a deal moves stage (drag on the board or the drawer),
    reflect it on the matching ReplyLead(s) so the inbox shows the same status."""
    from ..models.crm import Contact
    from ..models.reply import ReplyLead
    if not deal or not stage:
        return {"skipped": "no deal/stage"}
    rstage = CRM_TO_REPLY_STAGE.get(stage.name)
    if not rstage:
        return {"skipped": f"no reply mapping for {stage.name}"}
    contact = db.get(Contact, deal.contact_id) if deal.contact_id else None
    email = (contact.email or "").lower().strip() if contact else ""
    if not email:
        return {"skipped": "no contact email"}
    leads = (db.query(ReplyLead)
             .filter(ReplyLead.workspace_id == deal.workspace_id,
                     ReplyLead.email.ilike(email)).all())
    n = 0
    for l in leads:
        if l.stage != rstage:
            l.stage = rstage
            l.updated_at = datetime.utcnow()
            n += 1
    return {"updated": n, "stage": rstage}


def sync_reply_stage_to_deal(db, lead) -> dict:
    """Reply → CRM: when a ReplyLead's stage changes (Mark booked, etc.), move the
    matching CRM deal to the mapped stage (creating contact/company/deal if
    needed). Never downgrades a deal already further along than the target."""
    from ..models.crm import Activity, Deal, Stage
    stage_name = REPLY_TO_CRM_STAGE.get(lead.stage or "")
    if not lead.workspace_id or not stage_name:
        return {"skipped": "no mapping"}
    synced = sync_reply_lead_to_crm(db, lead, queue_enrich=False)
    cid = synced.get("contact_id")
    stage = (db.query(Stage).filter(Stage.workspace_id == lead.workspace_id,
                                    Stage.name == stage_name).first())
    if not stage:
        return {"skipped": "stage missing"}
    deal = (db.query(Deal).filter(Deal.workspace_id == lead.workspace_id,
                                  Deal.contact_id == cid).first()) if cid else None
    if deal is None:
        deal = Deal(workspace_id=lead.workspace_id,
                    name=f"{lead.company or lead.name or lead.email} — {stage_name.lower()}",
                    contact_id=cid, company_id=synced.get("company_id"),
                    stage_id=stage.id, lead_intent=lead.intent, source="reply")
        db.add(deal)
        db.flush()
        db.add(Activity(workspace_id=lead.workspace_id, deal_id=deal.id, contact_id=cid,
                        kind="stage_change", title=f"{stage_name} (from reply inbox)",
                        data={"reply_lead_id": lead.id}))
        return {"deal_id": deal.id, "created": True}
    # don't downgrade a more-advanced stage
    cur = db.get(Stage, deal.stage_id) if deal.stage_id else None
    if cur and (cur.sort_order or 0) > (stage.sort_order or 0) and not stage.is_won and not stage.is_lost:
        return {"deal_id": deal.id, "kept": cur.name}
    if deal.stage_id != stage.id:
        deal.stage_id = stage.id
        deal.stage_changed_at = datetime.utcnow()
        db.add(Activity(workspace_id=lead.workspace_id, deal_id=deal.id, contact_id=cid,
                        kind="stage_change", title=f"Stage → {stage_name} (from reply inbox)",
                        data={"reply_lead_id": lead.id}))
    return {"deal_id": deal.id, "updated": True}


def sync_booked_to_deal(db, lead) -> dict:
    """When a reply lead is marked booked, create/update a CRM deal in the
    'Meeting Booked' stage, linked to the synced contact/company (legacy
    booked-hook)."""
    from ..models.crm import Activity, Deal, Stage

    if not lead.workspace_id:
        return {"skipped": "unrouted"}
    synced = sync_reply_lead_to_crm(db, lead, queue_enrich=False)
    stage = (db.query(Stage).filter(Stage.workspace_id == lead.workspace_id,
                                    Stage.name == "Meeting Booked").first())
    existing = db.query(Deal).filter(Deal.workspace_id == lead.workspace_id,
                                     Deal.contact_id == synced.get("contact_id")).first() \
        if synced.get("contact_id") else None
    if existing:
        if stage:
            existing.stage_id = stage.id
            existing.stage_changed_at = datetime.utcnow()
        return {"deal_id": existing.id, "updated": True}
    deal = Deal(workspace_id=lead.workspace_id,
                name=f"{lead.company or lead.name or lead.email} — meeting",
                contact_id=synced.get("contact_id"), company_id=synced.get("company_id"),
                stage_id=stage.id if stage else None, lead_intent=lead.intent, source="reply")
    db.add(deal)
    db.flush()
    db.add(Activity(workspace_id=lead.workspace_id, deal_id=deal.id,
                    contact_id=synced.get("contact_id"), kind="meeting_booked",
                    title="Meeting booked (from reply)", data={"reply_lead_id": lead.id}))
    return {"deal_id": deal.id, "created": True}
