"""Agreement + Invoice service: numbering, generation, the sign→countersign→
execute state machine (with checksum + frozen snapshot + locking), versioning,
and invoice creation from approved commercial terms.

All writes go through workspace-scoped callers; this layer assumes the caller
already authorized the workspace.
"""
import hashlib
import secrets
from datetime import date, datetime, timedelta

from ..enrichment.blueprint import slugify
from ..models.agreements import Agreement, Invoice
from ..models.crm import Activity, Company, Contact, Deal
from ..models.documents import Document
from . import content as content_mod
from . import render

# ---- state machine -----------------------------------------------------------
TRANSITIONS = {
    "draft": {"ready", "sent", "archived", "voided"},
    "ready": {"sent", "draft", "archived", "voided"},
    "sent": {"viewed", "client_signed", "voided", "archived"},
    "viewed": {"client_signed", "voided", "archived"},
    "client_signed": {"countersigned", "voided"},
    "countersigned": {"executed", "voided"},
    "executed": set(),          # terminal + locked
    "voided": set(),
    "archived": set(),
}


def can_transition(cur: str, nxt: str) -> bool:
    return nxt in TRANSITIONS.get(cur, set())


def _audit(db, ag, kind, title, actor_user_id=None, data=None):
    db.add(Activity(workspace_id=ag.workspace_id, company_id=ag.company_id,
                    contact_id=ag.contact_id, deal_id=ag.deal_id, kind=kind, title=title,
                    data={**(data or {}), "agreement_id": ag.id, "number": ag.number},
                    actor_user_id=actor_user_id))


def _inv_audit(db, inv, kind, title, actor_user_id=None, data=None):
    db.add(Activity(workspace_id=inv.workspace_id, company_id=inv.company_id,
                    contact_id=inv.contact_id, deal_id=inv.deal_id, kind=kind, title=title,
                    data={**(data or {}), "invoice_id": inv.id, "number": inv.number},
                    actor_user_id=actor_user_id))


# ---- numbering + slug --------------------------------------------------------
def _next_number(db, model, prefix, workspace_id) -> str:
    n = db.query(model).filter(model.workspace_id == workspace_id).count() + 1
    # keep unique even across races/deletes by bumping past any collision
    while db.query(model).filter(model.workspace_id == workspace_id,
                                 model.number == f"{prefix}-{n:06d}").first():
        n += 1
    return f"{prefix}-{n:06d}"


def _unique_slug(db, model, base) -> str:
    root = slugify(base) or model.__tablename__
    # add short random suffix so public URLs are not trivially enumerable
    slug = f"{root}-{secrets.token_hex(3)}"
    while db.query(model).filter(model.slug == slug).first():
        slug = f"{root}-{secrets.token_hex(3)}"
    return slug


# ---- agreement generation ----------------------------------------------------
def generate_agreement(db, workspace_id, company=None, contact=None, deal=None,
                       blueprint=None, profile=None, notes="", overrides=None,
                       actor_user_id=None) -> Agreement:
    """Create a new DRAFT agreement (version 1) from real CRM sources. Pricing,
    deliverables, dates and entities are sourced or flagged — never invented."""
    sections, fields, missing = content_mod.build_content(
        company=company, contact=contact, deal=deal, blueprint=blueprint,
        profile=profile, notes=notes, overrides=overrides)

    ag = Agreement(
        workspace_id=workspace_id,
        company_id=company.id if company else None,
        contact_id=contact.id if contact else (deal.contact_id if deal else None),
        deal_id=deal.id if deal else None,
        blueprint_doc_id=blueprint.id if blueprint else None,
        client_profile_id=profile.id if profile else None,
        number=_next_number(db, Agreement, "AGR", workspace_id),
        title=(overrides or {}).get("title") or f"Services Agreement — {company.name if company else 'Draft'}",
        status="draft", version=1, is_current=True,
        public_token=secrets.token_urlsafe(24),
        sections=sections, fields=fields, missing_flags=missing,
    )
    ag.slug = _unique_slug(db, Agreement, (company.name if company else "agreement"))
    db.add(ag)
    db.flush()
    ag.root_id = ag.id
    ag.html = render.render_agreement(ag, company, contact, signing=False)
    _audit(db, ag, "agreement_created", f"Agreement {ag.number} created", actor_user_id,
           {"version": 1, "missing": missing})
    db.commit()
    return ag


def rerender(db, ag):
    company = db.get(Company, ag.company_id) if ag.company_id else None
    contact = db.get(Contact, ag.contact_id) if ag.contact_id else None
    ag.html = render.render_agreement(ag, company, contact, signing=False)


def update_sections(db, ag, sections=None, fields=None, title=None, actor_user_id=None):
    """Edit a DRAFT/READY agreement. Signed/executed versions are immutable."""
    if ag.locked or ag.status not in content_mod_editable():
        raise PermissionError("This agreement version is locked; create a new version to change it.")
    if title is not None:
        ag.title = title
    if sections is not None:
        ag.sections = sections
    if fields is not None:
        ag.fields = {**(ag.fields or {}), **fields}
    # recompute missing flags on the structured fields we track
    _recompute_missing(ag)
    rerender(db, ag)
    _audit(db, ag, "agreement_edited", f"Agreement {ag.number} edited", actor_user_id)
    db.commit()
    return ag


def content_mod_editable():
    from ..models.agreements import EDITABLE_STATUSES
    return EDITABLE_STATUSES


def _recompute_missing(ag):
    f = ag.fields or {}
    missing = []
    if not f.get("effective_date"):
        missing.append("effective_date")
    fees = f.get("fees") or {}
    if fees.get("setup") is None and fees.get("recurring") is None and not (fees.get("summary") or "").strip():
        missing.append("fees")
    if not (f.get("governing_law") or "").strip():
        missing.append("governing_law")
    # deliverables/scope live in sections; flag if their bodies are placeholders/empty
    by_key = {s.get("key"): (s.get("body") or "") for s in (ag.sections or [])}
    if not by_key.get("deliverables", "").strip() or by_key.get("deliverables", "").startswith("["):
        missing.append("deliverables")
    if not by_key.get("scope_of_services", "").strip() or by_key.get("scope_of_services", "").startswith("["):
        missing.append("scope_of_services")
    ag.missing_flags = missing


def set_status(db, ag, new_status, actor_user_id=None):
    if new_status == ag.status:
        return ag
    if not can_transition(ag.status, new_status):
        raise ValueError(f"Illegal transition {ag.status} → {new_status}")
    ag.status = new_status
    _audit(db, ag, f"agreement_{new_status}", f"Agreement {ag.number} → {new_status}", actor_user_id)
    db.commit()
    return ag


def send(db, ag, actor_user_id=None):
    """Publish/send for signature. Requires a public slug + token."""
    if ag.status not in ("draft", "ready"):
        raise ValueError(f"Cannot send from status {ag.status}")
    if not ag.public_token:
        ag.public_token = secrets.token_urlsafe(24)
    ag.status = "sent"
    rerender(db, ag)
    _audit(db, ag, "agreement_sent", f"Agreement {ag.number} sent for signature", actor_user_id)
    db.commit()
    from .webhooks import fire_agreement
    fire_agreement("agreement.sent", ag)
    return ag


# ---- viewing -----------------------------------------------------------------
def track_view(db, ag):
    now = datetime.utcnow()
    first = ag.first_viewed_at is None
    if ag.last_viewed_at is None or (now - ag.last_viewed_at) > timedelta(hours=1):
        ag.view_count = (ag.view_count or 0) + 1
        ag.last_viewed_at = now
        if first:
            ag.first_viewed_at = now
        if ag.status == "sent":
            ag.status = "viewed"
        db.commit()
        if first:
            from .webhooks import fire_agreement
            fire_agreement("agreement.viewed", ag)


# ---- signing -----------------------------------------------------------------
def sign_client(db, ag, name, email, title="", consent_text="", ip="", user_agent=""):
    """Record the client's signature. Idempotent-safe against double submits."""
    if ag.status in ("voided", "archived"):
        raise ValueError("This agreement is no longer available for signature.")
    if ag.client_signed_at:
        raise ValueError("This agreement has already been signed.")
    if ag.status not in ("sent", "viewed"):
        raise ValueError("This agreement is not open for signature.")
    name = (name or "").strip()
    email = (email or "").strip()
    if not name or not email:
        raise ValueError("Name and email are required to sign.")
    ag.client_signer_name = name
    ag.client_signer_email = email
    ag.client_signer_title = (title or "").strip()
    ag.client_signature_repr = name          # styled by CSS; not a biometric capture
    ag.client_consent_text = consent_text or ""
    ag.client_consent_version = "v1"
    ag.client_signed_at = datetime.utcnow()
    ag.client_ip = (ip or "")[:64]
    ag.client_user_agent = (user_agent or "")[:512]
    ag.client_sig_doc_version = ag.version
    ag.status = "client_signed"
    rerender(db, ag)
    _audit(db, ag, "agreement_client_signed", f"{name} signed {ag.number}", None,
           {"email": email, "ip": ag.client_ip})
    db.commit()
    from .webhooks import fire_agreement
    fire_agreement("agreement.client_signed", ag)
    return ag


def countersign(db, ag, user, name, email, title="", ip="", user_agent="", allow_before_client=False):
    """Internal countersignature by an authorized (owner/admin) user. Auto-executes."""
    if ag.status in ("voided", "archived", "executed"):
        raise ValueError("This agreement cannot be countersigned.")
    if not ag.client_signed_at and not allow_before_client:
        raise ValueError("Client must sign before countersignature.")
    if ag.countersigned_at:
        raise ValueError("This agreement has already been countersigned.")
    ag.counter_signer_name = (name or "").strip()
    ag.counter_signer_email = (email or "").strip()
    ag.counter_signer_title = (title or "").strip()
    ag.counter_signature_repr = (name or "").strip()
    ag.counter_user_id = user.id if user else None
    ag.countersigned_at = datetime.utcnow()
    ag.counter_ip = (ip or "")[:64]
    ag.counter_user_agent = (user_agent or "")[:512]
    ag.status = "countersigned"
    rerender(db, ag)
    _audit(db, ag, "agreement_countersigned", f"{ag.counter_signer_name} countersigned {ag.number}",
           user.id if user else None, {"email": ag.counter_signer_email, "ip": ag.counter_ip})
    db.commit()
    from .webhooks import fire_agreement
    fire_agreement("agreement.countersigned", ag)
    # execution + downstream automation
    execute(db, ag, actor_user_id=user.id if user else None)
    return ag


def execute(db, ag, actor_user_id=None):
    """Freeze + lock the fully-signed agreement, then run Closed-Won automation.
    Idempotent: a second call is a no-op."""
    if ag.executed_at:
        return ag
    if not (ag.client_signed_at and ag.countersigned_at):
        raise ValueError("Both signatures are required before execution.")
    company = db.get(Company, ag.company_id) if ag.company_id else None
    contact = db.get(Contact, ag.contact_id) if ag.contact_id else None
    # frozen snapshot (with signatures, no form) — the executed PDF renders from this
    ag.executed_html = render.render_agreement(ag, company, contact, signing=False)
    ag.checksum = hashlib.sha256(ag.executed_html.encode("utf-8")).hexdigest()
    ag.executed_at = datetime.utcnow()
    ag.locked = True
    ag.status = "executed"
    _audit(db, ag, "agreement_executed", f"Agreement {ag.number} executed", actor_user_id,
           {"checksum": ag.checksum})
    db.commit()
    _closed_won_automation(db, ag, actor_user_id)
    from .webhooks import fire_agreement
    fire_agreement("agreement.executed", ag)
    return ag


def void(db, ag, actor_user_id=None, reason=""):
    if ag.status == "executed":
        raise ValueError("An executed agreement cannot be voided; issue an amendment instead.")
    ag.status = "voided"
    _audit(db, ag, "agreement_voided", f"Agreement {ag.number} voided", actor_user_id, {"reason": reason})
    db.commit()
    return ag


# ---- versioning / amendments -------------------------------------------------
def new_version(db, ag, actor_user_id=None):
    """Create a fresh editable version that supersedes `ag` (used when scope
    changes after send/sign). The old version is preserved and marked not-current."""
    company = db.get(Company, ag.company_id) if ag.company_id else None
    contact = db.get(Contact, ag.contact_id) if ag.contact_id else None
    ag.is_current = False
    nv = Agreement(
        workspace_id=ag.workspace_id, company_id=ag.company_id, contact_id=ag.contact_id,
        deal_id=ag.deal_id, blueprint_doc_id=ag.blueprint_doc_id, client_profile_id=ag.client_profile_id,
        number=_next_number(db, Agreement, "AGR", ag.workspace_id),
        title=ag.title, status="draft", version=(ag.version or 1) + 1,
        root_id=ag.root_id or ag.id, supersedes_id=ag.id, is_current=True,
        public_token=secrets.token_urlsafe(24),
        sections=list(ag.sections or []), fields=dict(ag.fields or {}),
        missing_flags=list(ag.missing_flags or []),
    )
    nv.slug = _unique_slug(db, Agreement, (company.name if company else "agreement"))
    db.add(nv)
    db.flush()
    nv.html = render.render_agreement(nv, company, contact, signing=False)
    _audit(db, nv, "agreement_versioned", f"Agreement {nv.number} v{nv.version} supersedes {ag.number}",
           actor_user_id, {"supersedes": ag.id})
    db.commit()
    return nv


# ---- Closed Won automation (idempotent) -------------------------------------
def _closed_won_automation(db, ag, actor_user_id=None):
    """Move the linked deal to Won, activate the client + build the profile,
    preserve scope, generate onboarding, create activities. Idempotent."""
    from ..models.crm import Stage
    deal = db.get(Deal, ag.deal_id) if ag.deal_id else None
    # move deal → Won
    if deal:
        won = (db.query(Stage).filter(Stage.workspace_id == deal.workspace_id, Stage.is_won == True)  # noqa: E712
               .order_by(Stage.sort_order).first())
        if won and deal.stage_id != won.id:
            deal.stage_changed_at = datetime.utcnow()
            deal.stage_id = won.id
            db.add(Activity(workspace_id=deal.workspace_id, deal_id=deal.id, contact_id=deal.contact_id,
                            kind="stage_change", title=f"Stage → {won.name} (agreement executed)",
                            data={"to": won.id, "agreement_id": ag.id}, actor_user_id=actor_user_id))
    # client profile (idempotent)
    if ag.company_id:
        try:
            from ..client.profiles import ensure_profile
            prof = ensure_profile(db, ag.company_id, ag.deal_id, actor_user_id)
            ag.client_profile_id = prof.id
            if not prof.agreement_doc_id:
                # link a Document mirror is optional; store the agreement id via profile field
                pass
        except Exception:
            pass
    db.commit()


# ---- invoices ----------------------------------------------------------------
def recompute_invoice(inv):
    subtotal = 0.0
    for li in (inv.line_items or []):
        # An empty/blank/invalid quantity bills as 1 (a line with a rate is one
        # unit unless someone explicitly types 0), so totals never come out 0.
        qraw = li.get("quantity", 1)
        try:
            qty = 1.0 if qraw in (None, "") else float(qraw)
        except (TypeError, ValueError):
            qty = 1.0
        try:
            rate = float(li.get("rate", 0) or 0)
        except (TypeError, ValueError):
            rate = 0.0
        # Recompute from qty*rate; only fall back to a stored amount when there is
        # no rate to compute from (e.g. a flat fee line carried from an agreement).
        amt_stored = li.get("amount")
        if rate == 0 and amt_stored not in (None, ""):
            try:
                amt = float(amt_stored)
            except (TypeError, ValueError):
                amt = 0.0
        else:
            amt = qty * rate
        li["amount"] = round(amt, 2)
        subtotal += amt
    inv.subtotal = round(subtotal, 2)
    disc = float(inv.discount_amount or 0)
    taxable = max(subtotal - disc, 0)
    inv.tax_amount = round(taxable * float(inv.tax_rate or 0) / 100.0, 2)
    inv.total = round(taxable + inv.tax_amount, 2)
    inv.balance_due = round(inv.total - float(inv.amount_paid or 0), 2)
    return inv


def create_invoice(db, workspace_id, company=None, contact=None, deal=None, agreement=None,
                   profile=None, line_items=None, overrides=None, actor_user_id=None) -> Invoice:
    overrides = overrides or {}
    today = date.today().isoformat()
    # Dates: issue defaults to today; due date is either given, or computed from a
    # 'terms_days' choice (Net 7/15/30 etc.), or defaults to 7 days out.
    _issue = overrides.get("issue_date") or today
    if overrides.get("due_date"):
        _due = overrides["due_date"]
    elif overrides.get("terms_days") is not None:
        try:
            _due = (date.fromisoformat(str(_issue)) + timedelta(days=int(overrides["terms_days"]))).isoformat()
        except Exception:
            _due = (date.today() + timedelta(days=7)).isoformat()
    else:
        _due = (date.today() + timedelta(days=7)).isoformat()
    inv = Invoice(
        workspace_id=workspace_id,
        company_id=company.id if company else (agreement.company_id if agreement else None),
        contact_id=contact.id if contact else (agreement.contact_id if agreement else None),
        deal_id=deal.id if deal else (agreement.deal_id if agreement else None),
        agreement_id=agreement.id if agreement else None,
        client_profile_id=profile.id if profile else (agreement.client_profile_id if agreement else None),
        number=_next_number(db, Invoice, "INV", workspace_id),
        status="draft",
        issue_date=_issue,
        due_date=_due,
        currency=overrides.get("currency", "USD"),
        bill_to_name=overrides.get("bill_to_name", (f"{contact.first_name} {contact.last_name}".strip() if contact else "")),
        bill_to_company=overrides.get("bill_to_company", (company.name if company else "")),
        bill_to_email=overrides.get("bill_to_email", (contact.email if contact else "")),
        bill_to_address=overrides.get("bill_to_address", ""),
        line_items=line_items or [],
        tax_rate=float(overrides.get("tax_rate", 0) or 0),
        discount_amount=float(overrides.get("discount_amount", 0) or 0),
        notes=overrides.get("notes", ""),
        payment_instructions=overrides.get("payment_instructions", ""),
    )
    inv.public_token = secrets.token_urlsafe(24)
    inv.slug = _unique_slug(db, Invoice, (company.name if company else "invoice"))
    recompute_invoice(inv)
    db.add(inv)
    db.flush()
    _inv_audit(db, inv, "invoice_created", f"Invoice {inv.number} created", actor_user_id)
    db.commit()
    return inv


def invoice_from_agreement(db, ag, overrides=None, actor_user_id=None) -> Invoice:
    """Build a DRAFT invoice from the agreement's APPROVED commercial terms only.
    Never invents a charge: line items come strictly from structured fee fields."""
    fees = (ag.fields or {}).get("fees") or {}
    currency = fees.get("currency", "USD")
    items = []
    if fees.get("setup") is not None:
        items.append({"description": "Setup fee (one-time)", "quantity": 1,
                      "rate": float(fees["setup"]), "amount": float(fees["setup"])})
    if fees.get("recurring") is not None:
        per = fees.get("recurring_period", "month")
        items.append({"description": f"Recurring fee (first {per})", "quantity": 1,
                      "rate": float(fees["recurring"]), "amount": float(fees["recurring"])})
    company = db.get(Company, ag.company_id) if ag.company_id else None
    contact = db.get(Contact, ag.contact_id) if ag.contact_id else None
    ov = {"currency": currency,
          "payment_instructions": (overrides or {}).get("payment_instructions", ""),
          "notes": f"For services under Agreement {ag.number}.", **(overrides or {})}
    inv = create_invoice(db, ag.workspace_id, company=company, contact=contact,
                         deal=db.get(Deal, ag.deal_id) if ag.deal_id else None,
                         agreement=ag, line_items=items, overrides=ov, actor_user_id=actor_user_id)
    return inv


def issue_invoice(db, inv, actor_user_id=None):
    if inv.status not in ("draft",):
        raise ValueError(f"Cannot issue invoice from status {inv.status}")
    recompute_invoice(inv)
    inv.status = "issued"
    if not inv.issue_date:
        inv.issue_date = date.today().isoformat()
    _inv_audit(db, inv, "invoice_issued", f"Invoice {inv.number} issued", actor_user_id,
               {"total": inv.total})
    db.commit()
    from .webhooks import fire_invoice
    fire_invoice("invoice.issued", inv)
    return inv


def track_invoice_view(db, inv):
    now = datetime.utcnow()
    first = inv.first_viewed_at is None
    if inv.last_viewed_at is None or (now - inv.last_viewed_at) > timedelta(hours=1):
        inv.view_count = (inv.view_count or 0) + 1
        inv.last_viewed_at = now
        if first:
            inv.first_viewed_at = now
        if inv.status == "issued":
            inv.status = "viewed"
        db.commit()
        if first:
            from .webhooks import fire_invoice
            fire_invoice("invoice.viewed", inv)


def set_payment(db, inv, amount_paid, actor_user_id=None):
    """Mark a payment amount (foundation only — no processor integration)."""
    inv.amount_paid = round(float(amount_paid or 0), 2)
    recompute_invoice(inv)
    if inv.amount_paid <= 0:
        pass
    elif inv.balance_due <= 0:
        inv.status = "paid"
        inv.paid_at = datetime.utcnow()
    else:
        inv.status = "partially_paid"
    _inv_audit(db, inv, "invoice_payment", f"Invoice {inv.number} payment recorded ({inv.currency} {inv.amount_paid:,.2f})",
               actor_user_id, {"amount_paid": inv.amount_paid, "status": inv.status})
    db.commit()
    from .webhooks import fire_invoice
    fire_invoice("invoice.paid" if inv.status == "paid" else "invoice.payment", inv)
    return inv


def void_invoice(db, inv, actor_user_id=None):
    inv.status = "void"
    _inv_audit(db, inv, "invoice_voided", f"Invoice {inv.number} voided", actor_user_id)
    db.commit()
    return inv
