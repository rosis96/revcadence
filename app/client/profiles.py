"""Client Profile service: idempotent Closed-Won activation, field writes with
provenance, and onboarding-submission ingestion (immutable original + conflict
flagging instead of silent overwrite)."""
import secrets
from datetime import datetime

from ..models.client_profile import ClientProfile
from ..models.crm import Activity, Company, Contact, Deal
from ..models.documents import Document
from . import schema


def _now():
    return datetime.utcnow().isoformat()


def get_field(profile: ClientProfile, section: str, field: str):
    return ((profile.data or {}).get(section, {}) or {}).get(field, {})


def set_field(profile, section, field, value, source="manual", by=None, visibility=None, overwrite=True):
    """Write one field with provenance. overwrite=False fills only when empty.
    Returns True if written."""
    data = dict(profile.data or {})
    sec = dict(data.get(section, {}) or {})
    cur = sec.get(field) or {}
    if not overwrite and str(cur.get("value") or "").strip():
        return False
    if visibility is None:
        m = schema.field_meta(f"{section}.{field}")
        visibility = m[2] if m else "internal"
    sec[field] = {"value": value, "source": source, "at": _now(),
                  "by": by, "visibility": cur.get("visibility") or visibility}
    data[section] = sec
    profile.data = data
    return True


def compute_completeness(profile: ClientProfile) -> int:
    targets = schema.completeness_fields(profile.scope_type or "full")
    if not targets:
        return 0
    filled = 0
    for t in targets:
        sec, fld = t.split(".", 1)
        if str(get_field(profile, sec, fld).get("value") or "").strip():
            filled += 1
    return int(round(100 * filled / len(targets)))


def _scope_from_deal(db, deal: Deal) -> str:
    tags = " ".join(str(t).lower() for t in (deal.tags or [])) if deal else ""
    text = f"{tags} {(deal.name or '') if deal else ''} {(deal.description or '') if deal else ''}".lower()
    has_out = any(k in text for k in ("outbound", "cold", "prospect"))
    has_in = any(k in text for k in ("inbound", "website", "form", "visitor"))
    if has_out and not has_in:
        return "outbound"
    if has_in and not has_out:
        return "inbound"
    return "full"


def ensure_profile(db, company_id: int, deal_id: int | None = None, actor_user_id: int | None = None) -> ClientProfile:
    """Idempotent Closed-Won activation: create-or-return THE profile for this
    company, mark it an active client, and seed known fields from company /
    contact / deal / blueprint / notes WITHOUT overwriting anything already set.
    Running twice never creates a duplicate."""
    company = db.get(Company, company_id)
    if company is None:
        raise ValueError("company not found")
    deal = db.get(Deal, deal_id) if deal_id else None
    contact = db.get(Contact, deal.contact_id) if (deal and deal.contact_id) else \
        db.query(Contact).filter(Contact.company_id == company_id).order_by(Contact.id).first()

    profile = db.query(ClientProfile).filter(ClientProfile.company_id == company_id).first()
    created = profile is None
    if created:
        profile = ClientProfile(workspace_id=company.workspace_id, company_id=company_id,
                                data={}, onboarding_submissions=[], review_flags=[])
        db.add(profile)

    profile.is_active_client = True
    if deal:
        profile.deal_id = deal.id
    if contact:
        profile.contact_id = contact.id
    if not profile.scope_type or profile.scope_type == "full":
        profile.scope_type = _scope_from_deal(db, deal) if deal else (profile.scope_type or "full")
    if not profile.onboarding_token:
        profile.onboarding_token = secrets.token_urlsafe(24)

    by = actor_user_id
    # ---- seed from company (fill-only) ----
    set_field(profile, "overview", "company_name", company.name, "company", by, overwrite=False)
    set_field(profile, "overview", "website", company.website or company.domain, "company", by, overwrite=False)
    set_field(profile, "overview", "industry", company.industry, "company", by, overwrite=False)
    ind_desc = ((company.enrichment or {}).get("description") or {}).get("value", "")
    if ind_desc:
        set_field(profile, "overview", "business_overview", ind_desc, "enrichment", by, overwrite=False)
    # ---- from contact ----
    if contact:
        set_field(profile, "onboarding_info", "approval_notes",
                  f"Primary contact: {contact.first_name} {contact.last_name} ({contact.title}) {contact.email}".strip(),
                  "contact", by, overwrite=False)
    # ---- from deal ----
    if deal:
        if deal.value:
            set_field(profile, "delivery_scope", "pricing", f"Deal value: {deal.value}", "deal", by, overwrite=False)
            set_field(profile, "overview", "avg_deal_value", str(deal.value), "deal", by, overwrite=False)
        if deal.description:
            set_field(profile, "delivery_scope", "services_purchased", deal.description, "deal", by, overwrite=False)
    # ---- from latest blueprint for this company ----
    bp = (db.query(Document)
          .filter(Document.company_id == company_id, Document.kind == "blueprint")
          .order_by(Document.updated_at.desc()).first())
    if bp:
        profile.blueprint_doc_id = bp.id
        content = (bp.fields or {}).get("content") or {}
        if content.get("exec_summary"):
            set_field(profile, "overview", "business_overview", content["exec_summary"], "blueprint", by, overwrite=False)
        if content.get("what_we_build"):
            set_field(profile, "delivery_scope", "deliverables",
                      "; ".join(content["what_we_build"]) if isinstance(content["what_we_build"], list) else content["what_we_build"],
                      "blueprint", by, overwrite=False)
        if content.get("commercial"):
            set_field(profile, "delivery_scope", "pricing", content["commercial"], "blueprint", by, overwrite=False)
        if content.get("target_outcome"):
            set_field(profile, "delivery_scope", "targets", content["target_outcome"], "blueprint", by, overwrite=False)
        tr = (bp.fields or {}).get("transcript")
        if tr:
            set_field(profile, "onboarding_info", "meeting_transcript", tr[:8000], "blueprint", by, overwrite=False)
    # ---- from notes (activities) ----
    note = (db.query(Activity)
            .filter(Activity.company_id == company_id, Activity.kind == "note")
            .order_by(Activity.occurred_at.desc()).first())
    if note and (note.body or note.title):
        set_field(profile, "onboarding_info", "kickoff_notes", (note.body or note.title)[:4000],
                  "note", by, overwrite=False)
    # link an agreement doc if one exists
    ag = (db.query(Document)
          .filter(Document.company_id == company_id, Document.kind == "agreement")
          .order_by(Document.updated_at.desc()).first())
    if ag:
        profile.agreement_doc_id = ag.id

    # onboarding form (scope-specific) — (re)generate only if empty or scope changed
    form = profile.onboarding_form or {}
    if form.get("scope_type") != profile.scope_type:
        profile.onboarding_form = schema.build_onboarding_form(profile.scope_type)
        if profile.onboarding_status in (None, "", "not_started"):
            profile.onboarding_status = "sent"

    profile.completeness = compute_completeness(profile)
    db.flush()

    # onboarding tasks for missing access/assets (only what's still empty) — no duplicates
    _sync_onboarding_tasks(db, profile, by)

    if created:
        db.add(Activity(workspace_id=profile.workspace_id, company_id=company_id, deal_id=deal_id,
                        kind="client_activated", title="Client activated (Closed Won)",
                        data={"profile_id": profile.id, "scope": profile.scope_type}, actor_user_id=by))
    db.commit()
    return profile


_TASK_TARGETS = [
    ("onboarding_info.domains_accounts", "Collect sending domains / accounts"),
    ("onboarding_info.calendars", "Get calendar / booking link"),
    ("onboarding_info.crm_access", "Get CRM access"),
    ("messaging.sender_identities", "Confirm sender identities"),
    ("delivery_scope.deliverables", "Confirm agreed deliverables"),
]


def _sync_onboarding_tasks(db, profile, by):
    """Create an onboarding task Activity for each still-missing access/asset,
    without duplicating tasks already open for this profile."""
    existing = {(a.data or {}).get("target") for a in
                db.query(Activity).filter(Activity.company_id == profile.company_id,
                                          Activity.kind == "onboarding_task").all()}
    for target, label in _TASK_TARGETS:
        sec, fld = target.split(".", 1)
        has_value = str(get_field(profile, sec, fld).get("value") or "").strip()
        if has_value or target in existing:
            continue
        db.add(Activity(workspace_id=profile.workspace_id, company_id=profile.company_id,
                        kind="onboarding_task", title=label,
                        data={"target": target, "done": False, "profile_id": profile.id}, actor_user_id=by))


def submit_onboarding(db, profile: ClientProfile, answers: dict, submitted_by: str = "client") -> dict:
    """Ingest an onboarding submission. The RAW submission is stored immutably;
    each answer fills its field ONLY if empty — a differing existing value is
    flagged for review instead of being overwritten."""
    raw = {"at": _now(), "by": submitted_by, "answers": dict(answers or {})}
    profile.onboarding_submissions = list(profile.onboarding_submissions or []) + [raw]  # append-only

    flags = list(profile.review_flags or [])
    applied, flagged = 0, 0
    for target, val in (answers or {}).items():
        if "." not in target or val in (None, ""):
            continue
        sec, fld = target.split(".", 1)
        if not schema.field_meta(target):
            continue
        cur = str(get_field(profile, sec, fld).get("value") or "").strip()
        if not cur:
            set_field(profile, sec, fld, val, "onboarding", overwrite=True)
            applied += 1
        elif cur != str(val).strip():
            flags.append({"field": target, "existing": cur, "submitted": val,
                          "note": "onboarding answer differs from existing value", "at": _now()})
            flagged += 1
    profile.review_flags = flags
    profile.onboarding_status = "in_review" if flagged else "submitted"
    profile.completeness = compute_completeness(profile)
    db.flush()
    _sync_onboarding_tasks(db, profile, None)
    db.add(Activity(workspace_id=profile.workspace_id, company_id=profile.company_id,
                    kind="onboarding_submitted", title="Onboarding form submitted",
                    data={"applied": applied, "flagged": flagged, "profile_id": profile.id}))
    db.commit()
    return {"applied": applied, "flagged": flagged}
