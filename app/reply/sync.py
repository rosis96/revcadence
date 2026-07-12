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
